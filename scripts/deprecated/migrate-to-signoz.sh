#!/bin/bash
# Migration Script: LGTM Stack -> SigNoz with ALB + Cognito
# This script migrates from Grafana/Loki/Tempo/Mimir/Prometheus to SigNoz
#
# Prerequisites:
# - kubectl configured and connected to cluster (via SSM tunnel)
# - helm 3.x installed
# - aws cli configured with appropriate permissions
# - cfn-lint and cfn-guard installed (for CloudFormation validation)
#
# What gets removed:
# - Grafana, Loki, Tempo, Prometheus, Mimir (observability namespace)
# - Kiali (istio-system namespace)
#
# What stays:
# - Istio (istiod, ingress gateway)
# - Headlamp (K8s admin)
# - Kubecost (cost analysis)
# - Velero (backups)
# - Trivy (security scanning)
#
# What gets installed:
# - SigNoz (new signoz namespace)
# - Updated ALB configuration (CloudFormation)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SIGNOZ_VALUES="$PROJECT_ROOT/infra/helm/values/signoz/values.yaml"
ALB_CFN_TEMPLATE="$PROJECT_ROOT/infra/cloudformation/stacks/01-networking/alb-observability.yaml"
NODEPORT_SERVICES="$PROJECT_ROOT/infra/helm/values/alb-nodeport-services.yaml"
TGB_FILE="$PROJECT_ROOT/infra/helm/values/alb-target-group-bindings.yaml"

# AWS/Stack configuration
AWS_REGION="us-east-1"
STACK_NAME="infra-agent-dev-alb-observability"
EKS_CLUSTER="infra-agent-dev-cluster"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log_step "Checking prerequisites..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found"
        exit 1
    fi

    if ! command -v helm &> /dev/null; then
        log_error "helm not found"
        exit 1
    fi

    if ! command -v aws &> /dev/null; then
        log_error "aws cli not found"
        exit 1
    fi

    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Is the SSM tunnel running?"
        log_info "Start tunnel with: $PROJECT_ROOT/scripts/tunnel.sh"
        exit 1
    fi

    log_info "Prerequisites OK"
}

# Phase 1: Validate CloudFormation template
validate_cloudformation() {
    log_step "Phase 1: Validating CloudFormation template..."

    if [ ! -f "$ALB_CFN_TEMPLATE" ]; then
        log_error "CloudFormation template not found: $ALB_CFN_TEMPLATE"
        exit 1
    fi

    # Activate virtual environment if available
    if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
        source "$PROJECT_ROOT/.venv/bin/activate"
    fi

    # Run cfn-lint
    if command -v cfn-lint &> /dev/null; then
        log_info "Running cfn-lint..."
        cfn-lint "$ALB_CFN_TEMPLATE" || {
            log_error "cfn-lint validation failed"
            exit 1
        }
    else
        log_warn "cfn-lint not found, skipping syntax validation"
    fi

    # Run cfn-guard
    if command -v cfn-guard &> /dev/null; then
        log_info "Running cfn-guard..."
        cfn-guard validate \
            -d "$ALB_CFN_TEMPLATE" \
            -r "$PROJECT_ROOT/infra/cloudformation/cfn-guard-rules/nist-800-53/" 2>/dev/null || {
            log_warn "cfn-guard validation had warnings (non-blocking)"
        }
    else
        log_warn "cfn-guard not found, skipping compliance validation"
    fi

    log_info "CloudFormation validation complete"
}

# Phase 2: Uninstall LGTM Stack
uninstall_lgtm() {
    log_step "Phase 2: Uninstalling LGTM Stack..."

    # Delete old NodePort services first
    log_info "Deleting old ALB NodePort services..."
    kubectl delete svc grafana-alb -n observability --ignore-not-found
    kubectl delete svc kiali-alb -n istio-system --ignore-not-found

    # Delete old TargetGroupBindings
    log_info "Deleting old TargetGroupBindings..."
    kubectl delete targetgroupbinding grafana-tgb -n observability --ignore-not-found
    kubectl delete targetgroupbinding kiali-tgb -n istio-system --ignore-not-found

    # Uninstall Grafana
    if helm status grafana -n observability &> /dev/null; then
        log_info "Uninstalling Grafana..."
        helm uninstall grafana -n observability
    else
        log_warn "Grafana not found, skipping"
    fi

    # Uninstall Loki
    if helm status loki -n observability &> /dev/null; then
        log_info "Uninstalling Loki..."
        helm uninstall loki -n observability
    else
        log_warn "Loki not found, skipping"
    fi

    # Uninstall Tempo
    if helm status tempo -n observability &> /dev/null; then
        log_info "Uninstalling Tempo..."
        helm uninstall tempo -n observability
    else
        log_warn "Tempo not found, skipping"
    fi

    # Uninstall Prometheus
    if helm status prometheus -n observability &> /dev/null; then
        log_info "Uninstalling Prometheus..."
        helm uninstall prometheus -n observability
    else
        log_warn "Prometheus not found, skipping"
    fi

    # Uninstall Mimir
    if helm status mimir -n observability &> /dev/null; then
        log_info "Uninstalling Mimir..."
        helm uninstall mimir -n observability
    else
        log_warn "Mimir not found, skipping"
    fi

    log_info "LGTM Stack uninstalled"
}

# Phase 3: Uninstall Kiali
uninstall_kiali() {
    log_step "Phase 3: Uninstalling Kiali..."

    # Delete Kiali CR first
    if kubectl get kiali kiali -n istio-system &> /dev/null; then
        log_info "Deleting Kiali CR..."
        kubectl delete kiali kiali -n istio-system --ignore-not-found
    fi

    # Uninstall Kiali operator
    if helm status kiali-operator -n istio-system &> /dev/null; then
        log_info "Uninstalling Kiali operator..."
        helm uninstall kiali-operator -n istio-system
    else
        log_warn "Kiali operator not found, skipping"
    fi

    log_info "Kiali uninstalled"
}

# Phase 4: Deploy updated CloudFormation stack
deploy_cloudformation() {
    log_step "Phase 4: Deploying updated CloudFormation stack..."

    # Get existing stack parameters
    log_info "Retrieving existing stack parameters..."

    EXISTING_PARAMS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Parameters' \
        --output json 2>/dev/null || echo "[]")

    if [ "$EXISTING_PARAMS" == "[]" ]; then
        log_error "Could not retrieve existing stack parameters. Stack may not exist."
        log_info "Manual deployment required. See docs/observability-platform-comparison.md"
        return 1
    fi

    # Deploy with existing parameters
    log_info "Deploying CloudFormation stack..."
    aws cloudformation deploy \
        --template-file "$ALB_CFN_TEMPLATE" \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --capabilities CAPABILITY_IAM \
        --no-fail-on-empty-changeset \
        --parameter-overrides $(echo "$EXISTING_PARAMS" | jq -r '.[] | "\(.ParameterKey)=\(.ParameterValue)"' | tr '\n' ' ')

    log_info "CloudFormation stack deployed"
}

# Phase 5: Get new Target Group ARN and update binding
update_target_group_binding() {
    log_step "Phase 5: Updating Target Group Binding..."

    # Get SigNoz Target Group ARN from CloudFormation outputs
    SIGNOZ_TG_ARN=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`SigNozTargetGroupArn`].OutputValue' \
        --output text)

    if [ -z "$SIGNOZ_TG_ARN" ] || [ "$SIGNOZ_TG_ARN" == "None" ]; then
        log_error "Could not retrieve SigNoz Target Group ARN"
        exit 1
    fi

    log_info "SigNoz Target Group ARN: $SIGNOZ_TG_ARN"

    # Update the TGB file with actual ARN
    log_info "Updating target group binding file..."
    sed -i.bak "s|targetgroup/infra-agent-dev-signoz-tg/PLACEHOLDER|${SIGNOZ_TG_ARN#*targetgroup/}|" "$TGB_FILE"
    rm -f "${TGB_FILE}.bak"

    log_info "Target Group Binding file updated"
}

# Phase 6: Create SigNoz namespace with Istio injection
create_signoz_namespace() {
    log_step "Phase 6: Creating SigNoz namespace..."

    # Apply namespace from IaC file (includes Istio injection label)
    # Note: Istio injection is currently DISABLED due to Istio 1.24 NativeSidecars bug
    NAMESPACE_FILE="$PROJECT_ROOT/infra/helm/values/signoz/namespace.yaml"
    if [ -f "$NAMESPACE_FILE" ]; then
        kubectl apply -f "$NAMESPACE_FILE"
        log_info "SigNoz namespace created from IaC file"
    else
        log_warn "Namespace IaC file not found, creating manually"
        kubectl create namespace signoz --dry-run=client -o yaml | kubectl apply -f -
        kubectl label namespace signoz istio-injection=disabled --overwrite
    fi

    log_info "SigNoz namespace created (Istio injection disabled - see namespace.yaml)"
}

# Phase 7: Add SigNoz Helm repo and install
install_signoz() {
    log_step "Phase 7: Installing SigNoz..."

    if [ ! -f "$SIGNOZ_VALUES" ]; then
        log_error "SigNoz values file not found: $SIGNOZ_VALUES"
        exit 1
    fi

    # Add Helm repo
    log_info "Adding SigNoz Helm repository..."
    helm repo add signoz https://charts.signoz.io
    helm repo update

    # Install SigNoz
    log_info "Installing SigNoz (this may take several minutes)..."
    helm upgrade --install signoz signoz/signoz \
        --namespace signoz \
        --values "$SIGNOZ_VALUES" \
        --wait \
        --timeout 10m

    log_info "SigNoz installed"
}

# Phase 8: Apply NodePort services and TargetGroupBindings
apply_k8s_resources() {
    log_step "Phase 8: Applying K8s resources..."

    # Apply NodePort services
    log_info "Applying NodePort services..."
    kubectl apply -f "$NODEPORT_SERVICES"

    # Apply TargetGroupBindings
    log_info "Applying TargetGroupBindings..."
    kubectl apply -f "$TGB_FILE"

    log_info "K8s resources applied"
}

# Phase 9: Update Istio tracing config
update_istio_tracing() {
    log_step "Phase 9: Istio tracing configuration..."

    # Check if istiod exists
    if ! kubectl get deployment istiod -n istio-system &> /dev/null; then
        log_warn "Istiod not found, skipping tracing configuration"
        return
    fi

    log_info "Istio tracing should be configured via Helm values (istiod-values.yaml)"
    log_info "Add to infra/helm/values/istio/istiod-values.yaml:"

    cat << 'EOF'

meshConfig:
  enableTracing: true
  defaultConfig:
    tracing:
      sampling: 100.0
      zipkin:
        address: signoz-otel-collector.signoz.svc.cluster.local:9411

Then run: helm upgrade istiod istio/istiod -n istio-system -f infra/helm/values/istio/istiod-values.yaml

EOF
}

# Phase 10: Verify installation
verify_installation() {
    log_step "Phase 10: Verifying installation..."

    echo ""
    log_info "SigNoz pods:"
    kubectl get pods -n signoz

    echo ""
    log_info "SigNoz services:"
    kubectl get svc -n signoz

    echo ""
    log_info "NodePort services:"
    kubectl get svc -l access=alb -A

    echo ""
    log_info "TargetGroupBindings:"
    kubectl get targetgroupbinding -A

    # Get ALB URL
    ALB_DNS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`ALBDNSName`].OutputValue' \
        --output text 2>/dev/null || echo "")

    echo ""
    log_info "Access URLs (via ALB + Cognito):"
    if [ -n "$ALB_DNS" ]; then
        echo "  SigNoz:   https://$ALB_DNS/"
        echo "  Headlamp: https://$ALB_DNS/headlamp"
    else
        log_warn "Could not retrieve ALB DNS name"
    fi

    echo ""
    log_info "Note: DEV uses self-signed cert - accept browser warning"
}

# Phase 11: Delete old CloudFormation stacks
delete_lgtm_stacks() {
    log_step "Phase 11: Deleting LGTM CloudFormation stacks..."

    LGTM_STACKS=(
        "infra-agent-dev-loki-storage"
        "infra-agent-dev-tempo-storage"
        "infra-agent-dev-mimir-storage"
    )

    for stack in "${LGTM_STACKS[@]}"; do
        if aws cloudformation describe-stacks --stack-name "$stack" --region "$AWS_REGION" &> /dev/null; then
            log_info "Deleting CloudFormation stack: $stack"
            aws cloudformation delete-stack --stack-name "$stack" --region "$AWS_REGION"
            log_info "Stack deletion initiated: $stack"
        else
            log_warn "Stack not found: $stack (skipping)"
        fi
    done

    log_info "Note: S3 buckets have DeletionPolicy=Retain and will NOT be deleted"
    log_info "To delete buckets manually, see cleanup info below"
}

# Phase 12: Cleanup info (PVCs, S3 buckets)
cleanup_info() {
    log_step "Phase 12: Cleanup information..."

    echo ""
    log_warn "Old PVCs may still exist in observability namespace:"
    kubectl get pvc -n observability 2>/dev/null || echo "  (no PVCs found)"

    echo ""
    log_info "To delete old PVCs (data will be lost):"
    echo "  kubectl delete pvc --all -n observability"
    echo ""
    log_info "To delete observability namespace entirely:"
    echo "  kubectl delete namespace observability"

    echo ""
    log_warn "S3 buckets were retained (DeletionPolicy=Retain):"
    echo "  - infra-agent-dev-loki-340752837296"
    echo "  - infra-agent-dev-tempo-340752837296"
    echo "  - infra-agent-dev-mimir-340752837296"
    echo ""
    log_info "To delete S3 buckets (after confirming data is not needed):"
    echo "  # Empty and delete each bucket:"
    echo "  aws s3 rm s3://infra-agent-dev-loki-340752837296 --recursive"
    echo "  aws s3 rb s3://infra-agent-dev-loki-340752837296"
    echo "  aws s3 rm s3://infra-agent-dev-tempo-340752837296 --recursive"
    echo "  aws s3 rb s3://infra-agent-dev-tempo-340752837296"
    echo "  aws s3 rm s3://infra-agent-dev-mimir-340752837296 --recursive"
    echo "  aws s3 rb s3://infra-agent-dev-mimir-340752837296"
}

# Main execution
main() {
    echo "========================================"
    echo "  LGTM -> SigNoz Migration Script"
    echo "  With ALB + Cognito Authentication"
    echo "========================================"
    echo ""
    echo "This script will:"
    echo "  1. Validate CloudFormation template"
    echo "  2. Uninstall Grafana, Loki, Tempo, Prometheus, Mimir (Helm)"
    echo "  3. Uninstall Kiali (Helm)"
    echo "  4. Deploy updated ALB CloudFormation stack"
    echo "  5. Create SigNoz namespace with Istio injection"
    echo "  6. Install SigNoz (Helm)"
    echo "  7. Configure ALB routing to SigNoz"
    echo "  8. Delete LGTM S3 storage CloudFormation stacks"
    echo ""

    check_prerequisites

    echo ""
    read -p "Continue with migration? (y/N) " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "Migration cancelled"
        exit 0
    fi

    echo ""
    validate_cloudformation
    echo ""
    uninstall_lgtm
    echo ""
    uninstall_kiali
    echo ""
    deploy_cloudformation
    echo ""
    update_target_group_binding
    echo ""
    create_signoz_namespace
    echo ""
    install_signoz
    echo ""
    apply_k8s_resources
    echo ""
    update_istio_tracing
    echo ""
    delete_lgtm_stacks
    echo ""
    verify_installation
    echo ""
    cleanup_info

    echo ""
    echo "========================================"
    log_info "Migration complete!"
    echo "========================================"
}

# Run main function
main "$@"
