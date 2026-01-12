#!/bin/bash
# Shutdown Environment - Stop all compute resources to save costs
# Usage: ./shutdown-environment.sh [environment]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env" 2>/dev/null || true

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${1:-${ENVIRONMENT:-dev}}"
REGION="${AWS_REGION:-us-east-1}"

echo "=============================================="
echo "Shutting Down Environment: ${ENVIRONMENT}"
echo "Project: ${PROJECT_NAME}"
echo "Region: ${REGION}"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
echo ""

# Confirm before proceeding
read -p "Are you sure you want to shut down the ${ENVIRONMENT} environment? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "--- Step 1: Scale down EKS Node Groups to 0 ---"

# Get all node groups for the cluster
CLUSTER_NAME="${PROJECT_NAME}-${ENVIRONMENT}-cluster"
NODE_GROUPS=$(aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --region "$REGION" --query 'nodegroups[]' --output text 2>/dev/null || echo "")

if [[ -n "$NODE_GROUPS" ]]; then
    for NG in $NODE_GROUPS; do
        echo "Scaling down node group: $NG to 0..."
        aws eks update-nodegroup-config \
            --cluster-name "$CLUSTER_NAME" \
            --nodegroup-name "$NG" \
            --scaling-config minSize=0,desiredSize=0 \
            --region "$REGION" || echo "Warning: Could not scale $NG"
    done
    echo "Node groups scaling initiated. Nodes will terminate shortly."
else
    echo "No node groups found for cluster $CLUSTER_NAME"
fi

echo ""
echo "--- Step 2: Stop Bastion Instance ---"

BASTION_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=${PROJECT_NAME}-${ENVIRONMENT}-bastion" \
              "Name=instance-state-name,Values=running,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --region "$REGION" \
    --output text 2>/dev/null)

if [[ -n "$BASTION_ID" && "$BASTION_ID" != "None" ]]; then
    echo "Stopping bastion instance: $BASTION_ID"
    aws ec2 stop-instances --instance-ids "$BASTION_ID" --region "$REGION" || echo "Warning: Could not stop bastion"
    echo "Bastion stop initiated."
else
    echo "No bastion instance found or already stopped."
fi

echo ""
echo "--- Step 3: Stop RDS Instances (if applicable) ---"

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

    if [[ "$RDS_STATUS" == "available" ]]; then
        echo "Stopping RDS instance: $RDS_IDENTIFIER"
        aws rds stop-db-instance --db-instance-identifier "$RDS_IDENTIFIER" --region "$REGION" || echo "Warning: Could not stop RDS $RDS_IDENTIFIER"
        echo "RDS stop initiated for $RDS_IDENTIFIER (will auto-start after 7 days)."
    elif [[ -n "$RDS_STATUS" ]]; then
        echo "RDS $RDS_IDENTIFIER is in status: $RDS_STATUS (skipping)"
    else
        echo "No RDS instance found for $RDS_IDENTIFIER (may not be deployed)"
    fi
done

echo ""
echo "--- Shutdown Summary ---"
echo ""
echo "Resources stopped/scaling down:"
echo "  - EKS Node Groups: Scaling to 0"
echo "  - Bastion: Stopped"
echo "  - RDS (postgres): Stopped (if exists)"
echo ""
echo "Resources still running (have ongoing costs):"
echo "  - EKS Control Plane: \$0.10/hour"
echo "  - NAT Gateway: \$0.045/hour + data transfer"
echo "  - VPC (no direct cost)"
echo "  - ALB (if deployed): \$0.0225/hour + LCU"
echo ""
echo "To completely eliminate costs, delete the CloudFormation stacks."
echo ""
echo "To restart: ./startup-environment.sh ${ENVIRONMENT}"
echo ""
echo "=============================================="
echo "Shutdown Complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
