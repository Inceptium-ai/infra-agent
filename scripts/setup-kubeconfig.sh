#!/bin/bash
# One-time kubeconfig setup for SSM tunnel access
# Usage: ./setup-kubeconfig.sh
#
# Run this once to configure kubectl to use the SSM tunnel

set -e

CLUSTER_NAME="infra-agent-dev-cluster"
REGION="us-east-1"
EKS_ENDPOINT="C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"
CLUSTER_ARN="arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster"

echo "Configuring kubeconfig for SSM tunnel access..."

# Get EKS kubeconfig
aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}"

# Backup and modify to use localhost
cp ~/.kube/config ~/.kube/config.bak
sed -i.tmp "s|https://${EKS_ENDPOINT}|https://localhost:6443|" ~/.kube/config
rm -f ~/.kube/config.tmp

# Skip TLS verification (cert doesn't include localhost)
kubectl config set-cluster "${CLUSTER_ARN}" --insecure-skip-tls-verify=true

echo ""
echo "Kubeconfig configured for SSM tunnel access."
echo "Original config backed up to ~/.kube/config.bak"
echo ""
echo "Usage:"
echo "  1. Run ./tunnel.sh in one terminal (keep it running)"
echo "  2. Run ./services.sh in another terminal"
echo "  3. Access services at localhost ports"
