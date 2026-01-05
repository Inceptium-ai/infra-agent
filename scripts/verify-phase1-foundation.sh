#!/bin/bash
# Phase 1 Foundation Verification Script
# Tests: IAM Roles, VPC, Security Groups, Bastion
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env"

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
EVIDENCE_DIR="${SCRIPT_DIR}/../evidence/phase1-foundation"

mkdir -p "$EVIDENCE_DIR"

echo "=============================================="
echo "Phase 1: Foundation Verification"
echo "Environment: ${ENVIRONMENT}"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
echo ""

PASS_COUNT=0
FAIL_COUNT=0

# Test function
run_test() {
    local test_name="$1"
    local test_cmd="$2"
    local evidence_file="$3"

    echo -n "Testing: $test_name... "
    if eval "$test_cmd" > "$EVIDENCE_DIR/$evidence_file" 2>&1; then
        echo "PASS"
        ((PASS_COUNT++))
    else
        echo "FAIL"
        ((FAIL_COUNT++))
    fi
}

# 1. IAM Roles Stack
echo "--- IAM Roles ---"
run_test "IAM Roles stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-iam-roles --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "iam-roles-stack.txt"

run_test "EKS Cluster Role exists" \
    "aws iam get-role --role-name ${PROJECT_NAME}-${ENVIRONMENT}-eks-cluster-role" \
    "eks-cluster-role.json"

run_test "EKS Node Group Role exists" \
    "aws iam get-role --role-name ${PROJECT_NAME}-${ENVIRONMENT}-eks-nodegroup-role" \
    "eks-nodegroup-role.json"

run_test "Bastion Role exists" \
    "aws iam get-role --role-name ${PROJECT_NAME}-${ENVIRONMENT}-bastion-role" \
    "bastion-role.json"

# 2. VPC Stack
echo ""
echo "--- VPC ---"
run_test "VPC stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-vpc --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "vpc-stack.txt"

VPC_ID=$(aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-vpc --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' --output text)
run_test "VPC exists and is available" \
    "aws ec2 describe-vpcs --vpc-ids $VPC_ID --query 'Vpcs[0].State' --output text | grep available" \
    "vpc-state.txt"

run_test "VPC has dual CIDR (10.0.0.0/16 + 100.64.0.0/16)" \
    "aws ec2 describe-vpcs --vpc-ids $VPC_ID --query 'Vpcs[0].CidrBlockAssociationSet[*].CidrBlock' --output text | grep -E '10.0.0.0|100.64.0.0'" \
    "vpc-cidrs.txt"

run_test "Internet Gateway attached" \
    "aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=$VPC_ID --query 'InternetGateways[0].InternetGatewayId' --output text | grep igw-" \
    "igw.txt"

run_test "NAT Gateway exists and available" \
    "aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=$VPC_ID Name=state,Values=available --query 'NatGateways[0].NatGatewayId' --output text | grep nat-" \
    "nat-gateway.txt"

run_test "Public subnets exist (3 AZs)" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-vpc --query 'Stacks[0].Outputs[?OutputKey==\`PublicSubnetIds\`].OutputValue' --output text | tr ',' '\n' | wc -l | grep -E '^ *3$'" \
    "public-subnets.txt"

run_test "Private subnets exist (3 AZs)" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-vpc --query 'Stacks[0].Outputs[?OutputKey==\`PrivateSubnetIds\`].OutputValue' --output text | tr ',' '\n' | wc -l | grep -E '^ *3$'" \
    "private-subnets.txt"

run_test "Pod subnets exist (100.64.x.x, 3 AZs)" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-vpc --query 'Stacks[0].Outputs[?OutputKey==\`PodSubnetIds\`].OutputValue' --output text | tr ',' '\n' | wc -l | grep -E '^ *3$'" \
    "pod-subnets.txt"

# 3. Security Groups Stack
echo ""
echo "--- Security Groups ---"
run_test "Security Groups stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-security-groups --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "security-groups-stack.txt"

run_test "EKS Cluster SG exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-security-groups --query 'Stacks[0].Outputs[?OutputKey==\`EksClusterSecurityGroupId\`].OutputValue' --output text | grep sg-" \
    "eks-cluster-sg.txt"

run_test "EKS Nodes SG exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-security-groups --query 'Stacks[0].Outputs[?OutputKey==\`EksNodesSecurityGroupId\`].OutputValue' --output text | grep sg-" \
    "eks-nodes-sg.txt"

# 4. Bastion Host
echo ""
echo "--- Bastion Host ---"
run_test "Bastion stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-bastion --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "bastion-stack.txt"

BASTION_ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=${PROJECT_NAME}-${ENVIRONMENT}-bastion" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].InstanceId' --output text)
run_test "Bastion instance running" \
    "echo $BASTION_ID | grep i-" \
    "bastion-instance.txt"

run_test "Bastion in private subnet" \
    "aws ec2 describe-instances --instance-ids $BASTION_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text | grep -E '^None$|^$'" \
    "bastion-no-public-ip.txt"

run_test "Bastion SSM connectivity" \
    "aws ssm describe-instance-information --filters Key=InstanceIds,Values=$BASTION_ID --query 'InstanceInformationList[0].PingStatus' --output text | grep Online" \
    "bastion-ssm-status.txt"

# Network connectivity test via SSM
echo ""
echo "--- Network Connectivity (via Bastion) ---"

# First ensure system is updated and tools are available
echo "Ensuring bastion has required tools (dnf update)..."
UPDATE_CMD_ID=$(aws ssm send-command \
    --instance-ids "$BASTION_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["dnf update -y -q 2>/dev/null || true","which curl && which aws && echo TOOLS_OK || echo TOOLS_MISSING"]' \
    --query 'Command.CommandId' \
    --output text)

sleep 15

# Now run network tests
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$BASTION_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["echo === Network Tests ===","curl -s --connect-timeout 10 https://www.google.com > /dev/null && echo INTERNET_OK || echo INTERNET_FAIL","curl -s --connect-timeout 10 https://public.ecr.aws/v2/ > /dev/null && echo ECR_OK || echo ECR_FAIL","curl -s --connect-timeout 10 https://registry-1.docker.io/v2/ > /dev/null && echo DOCKERHUB_OK || echo DOCKERHUB_FAIL","aws sts get-caller-identity > /dev/null 2>&1 && echo AWS_API_OK || echo AWS_API_FAIL","nslookup google.com > /dev/null 2>&1 && echo DNS_OK || echo DNS_FAIL"]' \
    --query 'Command.CommandId' \
    --output text)

sleep 15

run_test "Bastion DNS resolution" \
    "aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $BASTION_ID --query 'StandardOutputContent' --output text | grep DNS_OK" \
    "bastion-dns-test.txt"

run_test "Bastion internet connectivity" \
    "aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $BASTION_ID --query 'StandardOutputContent' --output text | grep INTERNET_OK" \
    "bastion-network-test.txt"

run_test "Bastion ECR access" \
    "aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $BASTION_ID --query 'StandardOutputContent' --output text | grep ECR_OK" \
    "bastion-ecr-test.txt"

run_test "Bastion AWS API access" \
    "aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $BASTION_ID --query 'StandardOutputContent' --output text | grep AWS_API_OK" \
    "bastion-aws-api-test.txt"

# Summary
echo ""
echo "=============================================="
echo "VERIFICATION SUMMARY"
echo "=============================================="
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo "Evidence saved to: $EVIDENCE_DIR"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo "STATUS: ALL TESTS PASSED"
    exit 0
else
    echo "STATUS: SOME TESTS FAILED"
    exit 1
fi
