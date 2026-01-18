#!/bin/bash
# Startup compute (bastion + nodes)
# ENFORCES MINIMUM 3 NODES - see CLAUDE.md PRINCIPLE #2
set -e

CLUSTER_NAME="infra-agent-dev-cluster"
NODEGROUP_NAME="infra-agent-dev-general-nodes"
BASTION_ID="i-02c424847cd5f557e"
REGION="us-east-1"
MIN_NODES=3

# Parse requested node count (default 3)
REQUESTED_NODES="${1:-3}"

# ENFORCE MINIMUM 3 NODES
if [ "$REQUESTED_NODES" -lt "$MIN_NODES" ]; then
    echo "WARNING: Requested $REQUESTED_NODES nodes, but minimum $MIN_NODES required for multi-AZ."
    echo "         EBS volumes are AZ-bound. Fewer nodes causes StatefulSet failures."
    echo "         Using $MIN_NODES nodes."
    REQUESTED_NODES=$MIN_NODES
fi

echo "=== STARTUP ==="
echo "Start: $(date)"
START=$(date +%s)

# Start bastion and verify it's running
echo "Starting bastion..."
BASTION_STATE=$(aws ec2 describe-instances --instance-ids $BASTION_ID --region $REGION --query 'Reservations[0].Instances[0].State.Name' --output text)
if [ "$BASTION_STATE" = "stopped" ]; then
    aws ec2 start-instances --instance-ids $BASTION_ID --region $REGION > /dev/null
    echo "  Waiting for bastion to start..."
    aws ec2 wait instance-running --instance-ids $BASTION_ID --region $REGION
    echo "  Bastion running."
elif [ "$BASTION_STATE" = "running" ]; then
    echo "  Bastion already running."
else
    echo "  Bastion state: $BASTION_STATE - waiting..."
    aws ec2 wait instance-running --instance-ids $BASTION_ID --region $REGION
fi

# Wait for SSM agent
echo "Waiting for SSM agent..."
for i in {1..30}; do
    SSM_STATUS=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$BASTION_ID" --region $REGION --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "None")
    if [ "$SSM_STATUS" = "Online" ]; then
        echo "  SSM agent online."
        break
    fi
    sleep 5
done

echo "Scaling nodes to $REQUESTED_NODES..."
aws eks update-nodegroup-config \
  --cluster-name $CLUSTER_NAME \
  --nodegroup-name $NODEGROUP_NAME \
  --scaling-config minSize=1,maxSize=3,desiredSize=$REQUESTED_NODES \
  --region $REGION > /dev/null

END=$(date +%s)
echo "=== STARTUP COMPLETE in $((END - START))s ==="
echo ""
echo "Next steps:"
echo "  1. ./scripts/tunnel.sh"
echo "  2. Wait for nodes (kubectl get nodes)"
echo "  3. ./scripts/cleanup-orphaned-pods.sh"
