#!/bin/bash
# Startup Environment - Start all compute resources
# Usage: ./startup-environment.sh [environment]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env" 2>/dev/null || true

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${1:-${ENVIRONMENT:-dev}}"
REGION="${AWS_REGION:-us-east-1}"

# Default node group sizes
DEFAULT_MIN_SIZE="${DEFAULT_MIN_SIZE:-2}"
DEFAULT_DESIRED_SIZE="${DEFAULT_DESIRED_SIZE:-3}"
DEFAULT_MAX_SIZE="${DEFAULT_MAX_SIZE:-5}"

echo "=============================================="
echo "Starting Up Environment: ${ENVIRONMENT}"
echo "Project: ${PROJECT_NAME}"
echo "Region: ${REGION}"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
echo ""

echo "--- Step 1: Start Bastion Instance ---"

BASTION_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=${PROJECT_NAME}-${ENVIRONMENT}-bastion" \
              "Name=instance-state-name,Values=stopped,running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --region "$REGION" \
    --output text 2>/dev/null)

if [[ -n "$BASTION_ID" && "$BASTION_ID" != "None" ]]; then
    BASTION_STATE=$(aws ec2 describe-instances \
        --instance-ids "$BASTION_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --region "$REGION" \
        --output text)

    if [[ "$BASTION_STATE" == "stopped" ]]; then
        echo "Starting bastion instance: $BASTION_ID"
        aws ec2 start-instances --instance-ids "$BASTION_ID" --region "$REGION"
        echo "Bastion start initiated."
    else
        echo "Bastion is already in state: $BASTION_STATE"
    fi
else
    echo "No bastion instance found."
fi

echo ""
echo "--- Step 2: Scale up EKS Node Groups ---"

CLUSTER_NAME="${PROJECT_NAME}-${ENVIRONMENT}-cluster"
NODE_GROUPS=$(aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --region "$REGION" --query 'nodegroups[]' --output text 2>/dev/null || echo "")

if [[ -n "$NODE_GROUPS" ]]; then
    for NG in $NODE_GROUPS; do
        echo "Scaling up node group: $NG to min=$DEFAULT_MIN_SIZE, desired=$DEFAULT_DESIRED_SIZE..."
        aws eks update-nodegroup-config \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name "$NG" \
            --scaling-config minSize=$DEFAULT_MIN_SIZE,desiredSize=$DEFAULT_DESIRED_SIZE,maxSize=$DEFAULT_MAX_SIZE \
            --region "$REGION" || echo "Warning: Could not scale $NG"
    done
    echo "Node groups scaling initiated. Nodes will start shortly."
else
    echo "No node groups found for cluster $CLUSTER_NAME"
fi

echo ""
echo "--- Step 3: Start RDS Instances (if stopped) ---"

# List of RDS instances to manage
RDS_INSTANCES=(
    "${PROJECT_NAME}-${ENVIRONMENT}-postgres"
    # Keycloak removed - using AWS Cognito for authentication
)

for RDS_IDENTIFIER in "${RDS_INSTANCES[@]}"; do
    RDS_STATUS=$(aws rds describe-db-instances \
        --db-instance-identifier "$RDS_IDENTIFIER" \
        --region "$REGION" \
        --query 'DBInstances[0].DBInstanceStatus' \
        --output text 2>/dev/null || echo "")

    if [[ "$RDS_STATUS" == "stopped" ]]; then
        echo "Starting RDS instance: $RDS_IDENTIFIER"
        aws rds start-db-instance --db-instance-identifier "$RDS_IDENTIFIER" --region "$REGION" || echo "Warning: Could not start RDS $RDS_IDENTIFIER"
        echo "RDS start initiated for $RDS_IDENTIFIER"
    elif [[ -n "$RDS_STATUS" ]]; then
        echo "RDS $RDS_IDENTIFIER is already in status: $RDS_STATUS"
    else
        echo "No RDS instance found for $RDS_IDENTIFIER (may not be deployed)"
    fi
done

echo ""
echo "--- Step 4: Wait for Bastion to be Ready ---"

if [[ -n "$BASTION_ID" && "$BASTION_ID" != "None" ]]; then
    echo "Waiting for bastion instance to be running..."
    aws ec2 wait instance-running --instance-ids "$BASTION_ID" --region "$REGION" 2>/dev/null || true

    echo "Waiting for SSM to be available (may take 2-3 minutes)..."
    for i in {1..30}; do
        SSM_STATUS=$(aws ssm describe-instance-information \
            --filters Key=InstanceIds,Values=$BASTION_ID \
            --query 'InstanceInformationList[0].PingStatus' \
            --region "$REGION" \
            --output text 2>/dev/null || echo "")

        if [[ "$SSM_STATUS" == "Online" ]]; then
            echo "Bastion SSM is Online!"
            break
        fi
        echo "  Waiting for SSM... ($i/30)"
        sleep 10
    done
fi

echo ""
echo "--- Step 5: Wait for Nodes to be Ready ---"

if [[ -n "$NODE_GROUPS" ]]; then
    echo "Waiting for nodes to join cluster (may take 3-5 minutes)..."
    for i in {1..30}; do
        READY_NODES=$(aws eks describe-nodegroup \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name $(echo $NODE_GROUPS | awk '{print $1}') \
            --region "$REGION" \
            --query 'nodegroup.scalingConfig.desiredSize' \
            --output text 2>/dev/null || echo "0")

        CURRENT_NODES=$(aws eks describe-nodegroup \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name $(echo $NODE_GROUPS | awk '{print $1}') \
            --region "$REGION" \
            --query 'nodegroup.resources.autoScalingGroups[0]' \
            --output text 2>/dev/null || echo "")

        if [[ -n "$CURRENT_NODES" ]]; then
            ASG_NAME=$(aws eks describe-nodegroup \
                --cluster-name "$CLUSTER_NAME" \
                --nodegroup-name $(echo $NODE_GROUPS | awk '{print $1}') \
                --region "$REGION" \
                --query 'nodegroup.resources.autoScalingGroups[0].name' \
                --output text)

            RUNNING_COUNT=$(aws autoscaling describe-auto-scaling-groups \
                --auto-scaling-group-names "$ASG_NAME" \
                --region "$REGION" \
                --query 'AutoScalingGroups[0].Instances[?LifecycleState==`InService`] | length(@)' \
                --output text 2>/dev/null || echo "0")

            if [[ "$RUNNING_COUNT" -ge "$DEFAULT_DESIRED_SIZE" ]]; then
                echo "Nodes are ready! ($RUNNING_COUNT/$DEFAULT_DESIRED_SIZE)"
                break
            fi
            echo "  Nodes starting... ($RUNNING_COUNT/$DEFAULT_DESIRED_SIZE) - ($i/30)"
        fi
        sleep 10
    done
fi

echo ""
echo "--- Startup Summary ---"
echo ""
echo "Resources started:"

# Show bastion status
if [[ -n "$BASTION_ID" && "$BASTION_ID" != "None" ]]; then
    BASTION_STATE=$(aws ec2 describe-instances \
        --instance-ids "$BASTION_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --region "$REGION" \
        --output text)
    echo "  - Bastion: $BASTION_STATE (ID: $BASTION_ID)"
fi

# Show node group status
if [[ -n "$NODE_GROUPS" ]]; then
    for NG in $NODE_GROUPS; do
        NG_STATUS=$(aws eks describe-nodegroup \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name "$NG" \
            --region "$REGION" \
            --query 'nodegroup.status' \
            --output text 2>/dev/null || echo "UNKNOWN")
        DESIRED=$(aws eks describe-nodegroup \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name "$NG" \
            --region "$REGION" \
            --query 'nodegroup.scalingConfig.desiredSize' \
            --output text 2>/dev/null || echo "?")
        echo "  - Node Group $NG: $NG_STATUS (desired: $DESIRED)"
    done
fi

# Show RDS status for all instances
for RDS_ID in "${RDS_INSTANCES[@]}"; do
    RDS_CURRENT=$(aws rds describe-db-instances \
        --db-instance-identifier "$RDS_ID" \
        --region "$REGION" \
        --query 'DBInstances[0].DBInstanceStatus' \
        --output text 2>/dev/null || echo "not deployed")
    echo "  - RDS ($RDS_ID): $RDS_CURRENT"
done

echo ""
echo "Connect to bastion:"
echo "  aws ssm start-session --target $BASTION_ID --region $REGION"
echo ""
echo "=============================================="
echo "Startup Complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
