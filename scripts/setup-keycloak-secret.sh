#!/bin/bash
# Setup Keycloak Database Secret from AWS Secrets Manager
# This script fetches RDS credentials and creates a Kubernetes secret
#
# Prerequisites:
#   - AWS CLI configured
#   - kubectl configured for EKS cluster
#   - CloudFormation stack infra-agent-dev-keycloak-rds deployed
#
# Usage: ./setup-keycloak-secret.sh [environment]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.env" 2>/dev/null || true

PROJECT_NAME="${PROJECT_NAME:-infra-agent}"
ENVIRONMENT="${1:-${ENVIRONMENT:-dev}}"
REGION="${AWS_REGION:-us-east-1}"
NAMESPACE="identity"

echo "=============================================="
echo "Setting up Keycloak Database Secret"
echo "Project: ${PROJECT_NAME}"
echo "Environment: ${ENVIRONMENT}"
echo "Region: ${REGION}"
echo "=============================================="
echo ""

# Check if CloudFormation stack exists
STACK_NAME="${PROJECT_NAME}-${ENVIRONMENT}-keycloak-rds"
echo "Checking CloudFormation stack: $STACK_NAME..."

STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [[ "$STACK_STATUS" != "CREATE_COMPLETE" && "$STACK_STATUS" != "UPDATE_COMPLETE" ]]; then
    echo "Error: Stack $STACK_NAME is not ready. Status: $STACK_STATUS"
    echo "Please wait for the stack to complete or check for errors."
    exit 1
fi

echo "Stack status: $STACK_STATUS"
echo ""

# Get RDS endpoint from CloudFormation outputs
echo "Fetching RDS endpoint..."
RDS_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`KeycloakDBEndpoint`].OutputValue' \
    --output text)

RDS_PORT=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`KeycloakDBPort`].OutputValue' \
    --output text)

DB_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`KeycloakDBName`].OutputValue' \
    --output text)

SECRET_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`KeycloakDBSecretArn`].OutputValue' \
    --output text)

echo "RDS Endpoint: $RDS_ENDPOINT"
echo "RDS Port: $RDS_PORT"
echo "Database Name: $DB_NAME"
echo ""

# Get credentials from Secrets Manager
echo "Fetching credentials from Secrets Manager..."
SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ARN" \
    --region "$REGION" \
    --query 'SecretString' \
    --output text)

DB_USERNAME=$(echo "$SECRET_JSON" | jq -r '.username')
DB_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.password')

if [[ -z "$DB_USERNAME" || -z "$DB_PASSWORD" ]]; then
    echo "Error: Could not retrieve database credentials"
    exit 1
fi

echo "Credentials retrieved successfully"
echo ""

# Create namespace if it doesn't exist
echo "Ensuring namespace $NAMESPACE exists..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Create/update Kubernetes secret
echo "Creating Kubernetes secret keycloak-db..."
KC_DB_URL="jdbc:postgresql://${RDS_ENDPOINT}:${RDS_PORT}/${DB_NAME}"

kubectl create secret generic keycloak-db \
    --namespace "$NAMESPACE" \
    --from-literal=KC_DB_URL="$KC_DB_URL" \
    --from-literal=KC_DB_USERNAME="$DB_USERNAME" \
    --from-literal=KC_DB_PASSWORD="$DB_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "=============================================="
echo "Keycloak Database Secret Created"
echo "=============================================="
echo ""
echo "Secret: keycloak-db"
echo "Namespace: $NAMESPACE"
echo "JDBC URL: $KC_DB_URL"
echo "Username: $DB_USERNAME"
echo ""
echo "Next steps:"
echo "  1. Deploy Keycloak: kubectl apply -f infra/helm/values/keycloak/keycloak-deployment.yaml"
echo "  2. Wait for pod to be ready: kubectl get pods -n identity -w"
echo "  3. Port forward: kubectl port-forward svc/keycloak 8180:8080 -n identity"
echo "  4. Access: http://localhost:8180"
echo ""
