#!/bin/bash
# Shutdown compute (nodes + bastion)
set -e

CLUSTER_NAME="infra-agent-dev-cluster"
NODEGROUP_NAME="infra-agent-dev-general-nodes"
BASTION_ID="i-02c424847cd5f557e"
REGION="us-east-1"

echo "=== SHUTDOWN ==="
echo "Start: $(date)"
START=$(date +%s)

echo "Scaling nodes to 0..."
aws eks update-nodegroup-config \
  --cluster-name $CLUSTER_NAME \
  --nodegroup-name $NODEGROUP_NAME \
  --scaling-config minSize=0,maxSize=3,desiredSize=0 \
  --region $REGION > /dev/null

echo "Stopping bastion..."
aws ec2 stop-instances --instance-ids $BASTION_ID --region $REGION > /dev/null

END=$(date +%s)
echo "=== SHUTDOWN COMPLETE in $((END - START))s ==="
