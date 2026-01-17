#!/bin/bash
# Graceful Shutdown Script for EKS Cluster
# NIST CP-9: System Backup, CP-10: System Recovery
#
# PURPOSE: Safely shut down the cluster to prevent StatefulSet PV AZ-binding issues
# CRITICAL: Always use this script instead of direct node scaling
#
# See: docs/lessons-learned.md #53 - StatefulSet PV AZ-Binding Incident
#
# Usage: ./graceful-shutdown.sh
#        ./graceful-shutdown.sh --skip-backup  # Skip Velero backup (faster, less safe)

set -euo pipefail

# Configuration
CLUSTER_NAME="${CLUSTER_NAME:-infra-agent-dev-cluster}"
NODEGROUP_NAME="${NODEGROUP_NAME:-infra-agent-dev-general-nodes}"
BASTION_INSTANCE_ID="${BASTION_INSTANCE_ID:-i-02c424847cd5f557e}"
REGION="${AWS_REGION:-us-east-1}"
BACKUP_NAME="pre-shutdown-$(date +%Y%m%d-%H%M%S)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
SKIP_BACKUP=false
for arg in "$@"; do
    case $arg in
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
    esac
done

echo "=============================================="
echo "   EKS Cluster Graceful Shutdown"
echo "=============================================="
echo ""
echo "Cluster:   $CLUSTER_NAME"
echo "NodeGroup: $NODEGROUP_NAME"
echo "Bastion:   $BASTION_INSTANCE_ID"
echo "Region:    $REGION"
echo ""

# Step 1: Check kubectl connectivity
log_info "Step 1/6: Checking kubectl connectivity..."
if ! kubectl get nodes &>/dev/null; then
    log_error "Cannot connect to cluster. Is SSM tunnel running?"
    log_info "Start tunnel with: /Users/ymuwakki/infra-agent/scripts/tunnel.sh"
    exit 1
fi
log_info "Cluster connectivity: OK"

# Step 2: Create Velero backup (unless skipped)
if [ "$SKIP_BACKUP" = false ]; then
    log_info "Step 2/6: Creating Velero backup '$BACKUP_NAME'..."

    if kubectl get namespace velero &>/dev/null; then
        # Check if Velero is installed
        if kubectl get pods -n velero -l app.kubernetes.io/name=velero --no-headers 2>/dev/null | grep -q Running; then
            velero backup create "$BACKUP_NAME" \
                --include-namespaces signoz,headlamp,kubecost \
                --wait \
                --ttl 720h || {
                log_warn "Velero backup failed - continuing anyway"
            }
            log_info "Backup created: $BACKUP_NAME"
        else
            log_warn "Velero not running - skipping backup"
        fi
    else
        log_warn "Velero namespace not found - skipping backup"
    fi
else
    log_warn "Step 2/6: Skipping Velero backup (--skip-backup flag)"
fi

# Step 3: Scale down Deployments first (they're flexible)
log_info "Step 3/6: Scaling down Deployments..."
NAMESPACES="signoz headlamp kubecost"
for ns in $NAMESPACES; do
    if kubectl get namespace "$ns" &>/dev/null; then
        log_info "  Scaling deployments in $ns to 0..."
        kubectl scale deployment --all --replicas=0 -n "$ns" 2>/dev/null || true
    fi
done
sleep 5

# Step 4: Scale down StatefulSets gracefully
log_info "Step 4/6: Scaling down StatefulSets gracefully..."
for ns in $NAMESPACES; do
    if kubectl get namespace "$ns" &>/dev/null; then
        STATEFULSETS=$(kubectl get statefulset -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
        for sts in $STATEFULSETS; do
            log_info "  Scaling StatefulSet $ns/$sts to 0..."
            kubectl scale statefulset "$sts" --replicas=0 -n "$ns" 2>/dev/null || true
        done
    fi
done

# Wait for pods to terminate gracefully
log_info "  Waiting for pods to terminate (60s max)..."
sleep 10
for ns in $NAMESPACES; do
    kubectl wait --for=delete pod --all -n "$ns" --timeout=60s 2>/dev/null || true
done

# Step 5: Scale down node group
log_info "Step 5/6: Scaling node group to 0..."
aws eks update-nodegroup-config \
    --cluster-name "$CLUSTER_NAME" \
    --nodegroup-name "$NODEGROUP_NAME" \
    --scaling-config minSize=0,maxSize=10,desiredSize=0 \
    --region "$REGION"

log_info "  Waiting for nodes to drain..."
TIMEOUT=300
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$NODE_COUNT" -eq 0 ]; then
        log_info "  All nodes terminated"
        break
    fi
    log_info "  Nodes remaining: $NODE_COUNT (waiting...)"
    sleep 30
    ELAPSED=$((ELAPSED + 30))
done

# Step 6: Stop bastion
log_info "Step 6/6: Stopping bastion instance..."
aws ec2 stop-instances \
    --instance-ids "$BASTION_INSTANCE_ID" \
    --region "$REGION" >/dev/null

echo ""
echo "=============================================="
log_info "Graceful shutdown complete!"
echo "=============================================="
echo ""
echo "To restart the cluster, run:"
echo "  /Users/ymuwakki/infra-agent/scripts/graceful-startup.sh"
echo ""
echo "Backup name (for recovery): $BACKUP_NAME"
echo ""
