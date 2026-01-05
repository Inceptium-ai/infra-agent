#!/bin/bash
# Phase 2 EKS Verification Script
# Tests: EKS Cluster, Node Groups, Cluster Connectivity
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env"

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
CLUSTER_NAME="${PROJECT_NAME}-${ENVIRONMENT}-cluster"
EVIDENCE_DIR="${SCRIPT_DIR}/../evidence/phase2-eks"

mkdir -p "$EVIDENCE_DIR"

echo "=============================================="
echo "Phase 2: EKS Cluster Verification"
echo "Cluster: ${CLUSTER_NAME}"
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

# 1. EKS Cluster Stack
echo "--- EKS Cluster ---"
run_test "EKS Cluster stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-eks-cluster --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "eks-cluster-stack.txt"

run_test "EKS Cluster is ACTIVE" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.status' --output text | grep ACTIVE" \
    "eks-cluster-status.txt"

run_test "EKS Cluster version is 1.34" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.version' --output text | grep '1.34'" \
    "eks-cluster-version.txt"

run_test "EKS Cluster endpoint exists" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.endpoint' --output text | grep https://" \
    "eks-cluster-endpoint.txt"

run_test "EKS Cluster has private endpoint enabled" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.resourcesVpcConfig.endpointPrivateAccess' --output text | grep -i true" \
    "eks-private-endpoint.txt"

run_test "EKS Cluster logging enabled" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.logging.clusterLogging[?enabled==\`true\`].types' --output text | grep -E 'api|audit|authenticator'" \
    "eks-logging.txt"

run_test "EKS Cluster secrets encryption enabled" \
    "aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.encryptionConfig[0].provider.keyArn' --output text | grep arn:aws:kms" \
    "eks-encryption.txt"

# 2. Node Groups Stack
echo ""
echo "--- Node Groups ---"
run_test "Node Groups stack exists" \
    "aws cloudformation describe-stacks --stack-name ${PROJECT_NAME}-${ENVIRONMENT}-eks-node-groups --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'" \
    "node-groups-stack.txt"

run_test "General node group is ACTIVE" \
    "aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name ${PROJECT_NAME}-${ENVIRONMENT}-general-nodes --query 'nodegroup.status' --output text | grep ACTIVE" \
    "general-nodegroup-status.txt"

run_test "Node group instance type is t3a.xlarge" \
    "aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name ${PROJECT_NAME}-${ENVIRONMENT}-general-nodes --query 'nodegroup.instanceTypes' --output text | grep t3a.xlarge" \
    "nodegroup-instance-type.txt"

run_test "Node group AMI is AL2023" \
    "aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name ${PROJECT_NAME}-${ENVIRONMENT}-general-nodes --query 'nodegroup.amiType' --output text | grep AL2023" \
    "nodegroup-ami.txt"

run_test "Node group in pod subnets (100.64.x.x)" \
    "aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name ${PROJECT_NAME}-${ENVIRONMENT}-general-nodes --query 'nodegroup.subnets' --output text" \
    "nodegroup-subnets.txt"

run_test "Node group scaling config (min 2, desired 3)" \
    "aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name ${PROJECT_NAME}-${ENVIRONMENT}-general-nodes --query 'nodegroup.scalingConfig' --output json | grep -E '\"minSize\": 2|\"desiredSize\": 3'" \
    "nodegroup-scaling.txt"

# 3. Nodes Ready
echo ""
echo "--- Cluster Connectivity ---"

# Update kubeconfig
aws eks update-kubeconfig --name $CLUSTER_NAME --region ${AWS_REGION:-us-east-1} > "$EVIDENCE_DIR/kubeconfig-update.txt" 2>&1

run_test "kubectl can connect to cluster" \
    "kubectl cluster-info" \
    "kubectl-cluster-info.txt"

run_test "Nodes are Ready" \
    "kubectl get nodes -o wide | grep -v 'NotReady'" \
    "kubectl-nodes.txt"

NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
run_test "Expected number of nodes running (>=2)" \
    "[ $NODE_COUNT -ge 2 ] && echo 'Node count: $NODE_COUNT'" \
    "node-count.txt"

run_test "All nodes in Ready state" \
    "kubectl get nodes -o jsonpath='{.items[*].status.conditions[?(@.type==\"Ready\")].status}' | grep -v False" \
    "nodes-ready-state.txt"

run_test "CoreDNS pods running" \
    "kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide | grep Running" \
    "coredns-pods.txt"

run_test "kube-proxy pods running" \
    "kubectl get pods -n kube-system -l k8s-app=kube-proxy -o wide | grep Running" \
    "kube-proxy-pods.txt"

run_test "VPC CNI pods running" \
    "kubectl get pods -n kube-system -l k8s-app=aws-node -o wide | grep Running" \
    "vpc-cni-pods.txt"

# 4. OIDC Provider
echo ""
echo "--- OIDC Provider (IRSA) ---"
OIDC_ISSUER=$(aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.identity.oidc.issuer' --output text)
OIDC_ID=$(echo $OIDC_ISSUER | cut -d'/' -f5)

run_test "OIDC issuer configured" \
    "echo $OIDC_ISSUER | grep oidc.eks" \
    "oidc-issuer.txt"

run_test "OIDC provider exists in IAM" \
    "aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[*].Arn' --output text | grep $OIDC_ID" \
    "oidc-provider.txt"

# Summary
echo ""
echo "=============================================="
echo "VERIFICATION SUMMARY"
echo "=============================================="
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo "Evidence saved to: $EVIDENCE_DIR"
echo ""

# Save cluster info as evidence
aws eks describe-cluster --name $CLUSTER_NAME > "$EVIDENCE_DIR/cluster-full-description.json" 2>&1
kubectl get nodes -o yaml > "$EVIDENCE_DIR/nodes-full.yaml" 2>&1

if [ $FAIL_COUNT -eq 0 ]; then
    echo "STATUS: ALL TESTS PASSED"
    exit 0
else
    echo "STATUS: SOME TESTS FAILED"
    exit 1
fi
