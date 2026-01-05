#!/bin/bash
# Destroy Environment - Delete all CloudFormation stacks
# WARNING: This will permanently delete all resources!
# Usage: ./destroy-environment.sh [environment]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env" 2>/dev/null || true

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${1:-${ENVIRONMENT:-dev}}"
REGION="${AWS_REGION:-us-east-1}"

echo "=============================================="
echo "DESTROY Environment: ${ENVIRONMENT}"
echo "Project: ${PROJECT_NAME}"
echo "Region: ${REGION}"
echo "=============================================="
echo ""
echo "WARNING: This will PERMANENTLY DELETE all resources!"
echo ""

# List stacks to be deleted
STACKS=(
    "${PROJECT_NAME}-${ENVIRONMENT}-eks-addons"
    "${PROJECT_NAME}-${ENVIRONMENT}-eks-node-groups"
    "${PROJECT_NAME}-${ENVIRONMENT}-eks-cluster"
    "${PROJECT_NAME}-${ENVIRONMENT}-bastion"
    "${PROJECT_NAME}-${ENVIRONMENT}-security-groups"
    "${PROJECT_NAME}-${ENVIRONMENT}-vpc"
    "${PROJECT_NAME}-${ENVIRONMENT}-iam-roles"
)

echo "Stacks to be deleted (in order):"
for stack in "${STACKS[@]}"; do
    EXISTS=$(aws cloudformation describe-stacks --stack-name "$stack" --region "$REGION" 2>/dev/null && echo "EXISTS" || echo "")
    if [[ -n "$EXISTS" ]]; then
        echo "  - $stack (EXISTS)"
    else
        echo "  - $stack (not found)"
    fi
done

echo ""
read -p "Type 'DELETE ${ENVIRONMENT}' to confirm destruction: " confirm
if [[ "$confirm" != "DELETE ${ENVIRONMENT}" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Starting deletion..."
echo ""

for stack in "${STACKS[@]}"; do
    EXISTS=$(aws cloudformation describe-stacks --stack-name "$stack" --region "$REGION" 2>/dev/null && echo "EXISTS" || echo "")
    if [[ -n "$EXISTS" ]]; then
        echo "Deleting: $stack"
        aws cloudformation delete-stack --stack-name "$stack" --region "$REGION"

        echo "  Waiting for deletion..."
        aws cloudformation wait stack-delete-complete --stack-name "$stack" --region "$REGION" 2>/dev/null || {
            echo "  Warning: Stack deletion may have issues. Continuing..."
        }
        echo "  Deleted: $stack"
    else
        echo "Skipping (not found): $stack"
    fi
    echo ""
done

echo "=============================================="
echo "Destruction Complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
