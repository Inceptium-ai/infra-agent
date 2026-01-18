#!/bin/bash
# Deploy SigNoz Dashboards from IaC
# This script deploys all dashboard JSON files to SigNoz via API
#
# Usage:
#   ./scripts/deploy-signoz-dashboards.sh [--delete-existing]
#
# Prerequisites:
#   - kubectl access to the cluster (SSM tunnel must be running)
#   - SIGNOZ_API_KEY in .env file
#   - jq installed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="$PROJECT_ROOT/infra/helm/values/signoz/dashboards"
ENV_FILE="$PROJECT_ROOT/.env"

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
        log_error "kubectl not found. Please install kubectl."
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        log_error "jq not found. Please install jq: brew install jq"
        exit 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env file not found at $ENV_FILE"
        exit 1
    fi

    # Load API key from .env
    SIGNOZ_API_KEY=$(grep "^SIGNOZ_API_KEY=" "$ENV_FILE" | cut -d= -f2-)
    if [ -z "$SIGNOZ_API_KEY" ]; then
        log_error "SIGNOZ_API_KEY not found in .env file"
        log_info "Create an API key in SigNoz: Settings → API Keys → Create"
        log_info "Then add to .env: SIGNOZ_API_KEY=<your-key>"
        exit 1
    fi

    log_info "Prerequisites OK"
}

# Start port-forward
start_port_forward() {
    log_info "Starting port-forward to SigNoz..."

    # Kill any existing port-forward on 3301
    pkill -f "port-forward.*3301" 2>/dev/null || true
    sleep 1

    kubectl port-forward svc/signoz 3301:8080 -n signoz &
    PF_PID=$!
    sleep 3

    # Verify port-forward is working
    if ! kill -0 $PF_PID 2>/dev/null; then
        log_error "Failed to start port-forward. Is the SSM tunnel running?"
        exit 1
    fi

    log_info "Port-forward started (PID: $PF_PID)"
}

# Stop port-forward
stop_port_forward() {
    log_info "Stopping port-forward..."
    pkill -f "port-forward.*3301" 2>/dev/null || true
}

# List existing dashboards
list_dashboards() {
    curl -s -H "SIGNOZ-API-KEY: $SIGNOZ_API_KEY" \
        "http://localhost:3301/api/v1/dashboards" | jq -r '.data[] | "\(.id) - \(.data.title)"'
}

# Delete all existing dashboards
delete_existing_dashboards() {
    log_warn "Deleting all existing dashboards..."

    DASHBOARD_IDS=$(curl -s -H "SIGNOZ-API-KEY: $SIGNOZ_API_KEY" \
        "http://localhost:3301/api/v1/dashboards" | jq -r '.data[].id')

    for id in $DASHBOARD_IDS; do
        log_info "Deleting dashboard: $id"
        curl -s -X DELETE -H "SIGNOZ-API-KEY: $SIGNOZ_API_KEY" \
            "http://localhost:3301/api/v1/dashboards/$id" > /dev/null
    done

    log_info "All existing dashboards deleted"
}

# Deploy a single dashboard
deploy_dashboard() {
    local json_file="$1"
    local filename=$(basename "$json_file")
    local title=$(jq -r '.title' "$json_file")

    log_info "Deploying: $title ($filename)"

    response=$(curl -s -X POST \
        -H "SIGNOZ-API-KEY: $SIGNOZ_API_KEY" \
        -H "Content-Type: application/json" \
        -d @"$json_file" \
        "http://localhost:3301/api/v1/dashboards")

    status=$(echo "$response" | jq -r '.status')

    if [ "$status" == "success" ]; then
        dash_id=$(echo "$response" | jq -r '.data.id')
        log_info "✓ Deployed: $title (ID: $dash_id)"
    else
        error=$(echo "$response" | jq -r '.error.message // .error // "Unknown error"')
        log_error "✗ Failed to deploy $title: $error"
    fi
}

# Deploy all dashboards
deploy_all_dashboards() {
    log_info "Deploying dashboards from: $DASHBOARD_DIR"

    # Find all JSON files (exclude README)
    for json_file in "$DASHBOARD_DIR"/*.json; do
        if [ -f "$json_file" ]; then
            deploy_dashboard "$json_file"
        fi
    done

    log_info "Dashboard deployment complete"
}

# Main
main() {
    local delete_existing=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --delete-existing)
                delete_existing=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [--delete-existing]"
                echo ""
                echo "Options:"
                echo "  --delete-existing  Delete all existing dashboards before deploying"
                echo ""
                echo "Dashboard JSON files are read from:"
                echo "  $DASHBOARD_DIR"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    check_prerequisites
    start_port_forward

    # Trap to ensure cleanup
    trap stop_port_forward EXIT

    echo ""
    log_info "Current dashboards:"
    list_dashboards || echo "  (none)"
    echo ""

    if [ "$delete_existing" = true ]; then
        delete_existing_dashboards
        echo ""
    fi

    deploy_all_dashboards

    echo ""
    log_info "Deployed dashboards:"
    list_dashboards

    echo ""
    log_info "Access SigNoz: http://localhost:3301 or via ALB"
}

main "$@"
