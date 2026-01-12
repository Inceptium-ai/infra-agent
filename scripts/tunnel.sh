#!/bin/bash
# SSM Tunnel to EKS API
# Usage: ./tunnel.sh
#
# This script creates an SSM port-forwarding tunnel through the bastion
# to the private EKS API endpoint. Keep this running while using kubectl.

set -e

BASTION_ID="i-02c424847cd5f557e"
EKS_ENDPOINT="C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"
LOCAL_PORT="6443"

echo "Starting SSM tunnel to EKS API..."
echo "  Bastion: ${BASTION_ID}"
echo "  EKS API: ${EKS_ENDPOINT}"
echo "  Local:   localhost:${LOCAL_PORT}"
echo ""
echo "Keep this terminal open while working with kubectl."
echo "Press Ctrl+C to stop the tunnel."
echo ""

aws ssm start-session \
  --target "${BASTION_ID}" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"${EKS_ENDPOINT}\"],\"portNumber\":[\"443\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
