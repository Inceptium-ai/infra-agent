#!/bin/bash
# Graceful Startup Script for EKS Cluster
# NIST CP-10: System Recovery
#
# PURPOSE: Safely restart the cluster with StatefulSets scheduled correctly
# CRITICAL: Ensures PriorityClass 'stateful-critical' is applied before workloads start
#
# See: docs/lessons-learned.md #53 - StatefulSet PV AZ-Binding Incident
#
# Usage: ./graceful-startup.sh
#        ./graceful-startup.sh --nodes 2  # Start with specific node count (default: 3)

set -euo pipefail

# Configuration
CLUSTER_NAME="${CLUSTER_NAME:-infra-agent-dev-cluster}"
NODEGROUP_NAME="${NODEGROUP_NAME:-infra-agent-dev-general-nodes}"
BASTION_INSTANCE_ID="${BASTION_INSTANCE_ID:-i-02c424847cd5f557e}"
REGION="${AWS_REGION:-us-east-1}"
DEFAULT_NODE_COUNT=3

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
NODE_COUNT=$DEFAULT_NODE_COUNT
for arg in "$@"; do
    case $arg in
        --nodes)
            shift
            NODE_COUNT=$1
            shift
            ;;
        --nodes=*)
            NODE_COUNT="${arg#*=}"
            shift
            ;;
    esac
done

# Ensure minimum 3 nodes for multi-AZ
if [ "$NODE_COUNT" -lt 3 ]; then
    log_warn "Requested $NODE_COUNT nodes, but minimum 3 required for multi-AZ. Using 3."
    NODE_COUNT=3
fi

echo "=============================================="
echo "   EKS Cluster Graceful Startup"
echo "=============================================="
echo ""
echo "Cluster:    $CLUSTER_NAME"
echo "NodeGroup:  $NODEGROUP_NAME"
echo "Bastion:    $BASTION_INSTANCE_ID"
echo "Region:     $REGION"
echo "Node Count: $NODE_COUNT"
echo ""

# Step 1: Start bastion
log_info "Step 1/6: Starting bastion instance..."
aws ec2 start-instances \
    --instance-ids "$BASTION_INSTANCE_ID" \
    --region "$REGION" >/dev/null

log_info "  Waiting for bastion to be running..."
aws ec2 wait instance-running \
    --instance-ids "$BASTION_INSTANCE_ID" \
    --region "$REGION"
log_info "  Bastion is running"

# Step 2: Wait for SSM to be available
log_info "Step 2/6: Waiting for SSM agent (60s)..."
sleep 60

# Step 3: Scale up node group
log_info "Step 3/6: Scaling node group to $NODE_COUNT nodes..."
aws eks update-nodegroup-config \
    --cluster-name "$CLUSTER_NAME" \
    --nodegroup-name "$NODEGROUP_NAME" \
    --scaling-config minSize=3,maxSize=10,desiredSize="$NODE_COUNT" \
    --region "$REGION"

echo ""
echo "=============================================="
log_info "Startup initiated!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start SSM tunnel (in a separate terminal):"
echo "   /Users/ymuwakki/infra-agent/scripts/tunnel.sh"
echo ""
echo "2. Wait for nodes to be Ready (2-3 minutes):"
echo "   kubectl get nodes -w"
echo ""
echo "3. Apply PriorityClass (if not already applied):"
echo "   kubectl apply -f /Users/ymuwakki/infra-agent/infra/helm/values/signoz/priority-class.yaml"
echo ""
echo "4. StatefulSets will auto-recover. Check status:"
echo "   kubectl get pods -n signoz"
echo "   kubectl get pods -n headlamp"
echo "   kubectl get pods -n kubecost"
echo ""
echo "5. If StatefulSets fail to schedule, check PV AZ bindings:"
echo "   kubectl get pv -o custom-columns='NAME:.metadata.name,AZ:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0],CLAIM:.spec.claimRef.name'"
echo ""
echo "6. If recovery is needed, restore from Velero backup:"
echo "   velero backup get  # List available backups"
echo "   velero restore create --from-backup <backup-name>"
echo ""
