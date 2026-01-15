#!/bin/bash
# Migration Script: LGTM Stack -> SigNoz
# This script migrates from Grafana/Loki/Tempo/Mimir/Prometheus to SigNoz
#
# Prerequisites:
# - kubectl configured and connected to cluster
# - helm 3.x installed
# - SSM tunnel running (scripts/tunnel.sh)
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

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SIGNOZ_VALUES="$PROJECT_ROOT/infra/helm/values/signoz/values.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found"
        exit 1
    fi

    if ! command -v helm &> /dev/null; then
        log_error "helm not found"
        exit 1
    fi

    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Is the SSM tunnel running?"
        exit 1
    fi

    log_info "Prerequisites OK"
}

# Phase 1: Uninstall LGTM Stack
uninstall_lgtm() {
    log_info "Phase 1: Uninstalling LGTM Stack..."

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

# Phase 2: Uninstall Kiali
uninstall_kiali() {
    log_info "Phase 2: Uninstalling Kiali..."

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

# Phase 3: Create SigNoz namespace with Istio injection
create_signoz_namespace() {
    log_info "Phase 3: Creating SigNoz namespace..."

    # Create namespace if not exists
    kubectl create namespace signoz --dry-run=client -o yaml | kubectl apply -f -

    # Label for Istio injection
    kubectl label namespace signoz istio-injection=enabled --overwrite

    log_info "SigNoz namespace created with Istio injection enabled"
}

# Phase 4: Add SigNoz Helm repo
add_signoz_repo() {
    log_info "Phase 4: Adding SigNoz Helm repository..."

    helm repo add signoz https://charts.signoz.io
    helm repo update

    log_info "SigNoz Helm repo added"
}

# Phase 5: Install SigNoz
install_signoz() {
    log_info "Phase 5: Installing SigNoz..."

    if [ ! -f "$SIGNOZ_VALUES" ]; then
        log_error "SigNoz values file not found: $SIGNOZ_VALUES"
        exit 1
    fi

    helm upgrade --install signoz signoz/signoz \
        --namespace signoz \
        --values "$SIGNOZ_VALUES" \
        --wait \
        --timeout 10m

    log_info "SigNoz installed"
}

# Phase 6: Update Istio tracing config
update_istio_tracing() {
    log_info "Phase 6: Updating Istio tracing configuration..."

    # Check if istiod exists
    if ! kubectl get deployment istiod -n istio-system &> /dev/null; then
        log_warn "Istiod not found, skipping tracing configuration"
        return
    fi

    log_info "Istio tracing should be configured via Helm values (istiod-values.yaml)"
    log_info "Update meshConfig.defaultConfig.tracing to point to SigNoz OTel collector"

    cat << 'EOF'

Add to infra/helm/values/istio/istiod-values.yaml:

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

# Phase 7: Verify installation
verify_installation() {
    log_info "Phase 7: Verifying SigNoz installation..."

    echo ""
    log_info "SigNoz pods:"
    kubectl get pods -n signoz

    echo ""
    log_info "SigNoz services:"
    kubectl get svc -n signoz

    echo ""
    log_info "To access SigNoz UI:"
    echo "  kubectl port-forward svc/signoz-frontend 3301:3301 -n signoz"
    echo "  Open: http://localhost:3301"

    echo ""
    log_info "Remaining observability namespace pods:"
    kubectl get pods -n observability 2>/dev/null || echo "  (namespace may be empty or deleted)"
}

# Phase 8: Cleanup old PVCs (optional)
cleanup_pvcs() {
    log_info "Phase 8: PVC Cleanup (manual step)..."

    echo ""
    log_warn "Old PVCs may still exist in observability namespace:"
    kubectl get pvc -n observability 2>/dev/null || echo "  (no PVCs found)"

    echo ""
    log_info "To delete old PVCs (data will be lost):"
    echo "  kubectl delete pvc --all -n observability"
    echo ""
    log_info "To delete observability namespace entirely:"
    echo "  kubectl delete namespace observability"
}

# Main execution
main() {
    echo "========================================"
    echo "  LGTM -> SigNoz Migration Script"
    echo "========================================"
    echo ""

    check_prerequisites

    echo ""
    read -p "This will uninstall Grafana, Loki, Tempo, Prometheus, Mimir, and Kiali. Continue? (y/N) " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "Migration cancelled"
        exit 0
    fi

    echo ""
    uninstall_lgtm
    echo ""
    uninstall_kiali
    echo ""
    create_signoz_namespace
    echo ""
    add_signoz_repo
    echo ""
    install_signoz
    echo ""
    update_istio_tracing
    echo ""
    verify_installation
    echo ""
    cleanup_pvcs

    echo ""
    echo "========================================"
    log_info "Migration complete!"
    echo "========================================"
}

# Run main function
main "$@"
