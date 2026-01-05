#!/bin/bash
# Bastion Connection Script
# Connects to the bastion host via AWS SSM Session Manager

set -e

# Load environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# Set defaults
PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "=== Bastion Connection Script ==="
echo "Project: ${PROJECT_NAME}"
echo "Environment: ${ENVIRONMENT}"
echo "Region: ${AWS_REGION}"
echo ""

# Get bastion instance ID
echo "Looking up bastion instance..."
INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=${PROJECT_NAME}-${ENVIRONMENT}-bastion" \
              "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text \
    --region "${AWS_REGION}")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
    echo "ERROR: Bastion instance not found or not running"
    exit 1
fi

echo "Found bastion: ${INSTANCE_ID}"
echo ""
echo "Connecting... (type 'exit' to disconnect)"
echo "==========================================="
echo ""

# Start SSM session
aws ssm start-session \
    --target "${INSTANCE_ID}" \
    --region "${AWS_REGION}"
