#!/bin/bash
# API Test Coverage Script for Observability Stack
# Tests actual API functionality, not just pod status
# NIST AU-2: Audit Events verification

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="observability"
GRAFANA_PORT=3000
LOKI_PORT=3100
PROMETHEUS_PORT=9090
MIMIR_PORT=9080  # Local port for mimir-gateway (gateway listens on 80)
KUBECOST_PORT=9091
KIALI_PORT=20001

# Get Grafana credentials
GRAFANA_USER="admin"
GRAFANA_PASS=$(kubectl get secret grafana -n observability -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d || echo "admin")

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Observability Stack API Test Suite   ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to test an API endpoint
test_api() {
    local name=$1
    local url=$2
    local expected=$3
    local method=${4:-GET}
    local data=${5:-}

    echo -n "Testing $name... "

    if [ -n "$data" ]; then
        response=$(curl -s -w "\n%{http_code}" -X "$method" -H "Content-Type: application/json" -d "$data" "$url" 2>/dev/null || echo "000")
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" 2>/dev/null || echo "000")
    fi

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "$expected" ]; then
        echo -e "${GREEN}PASS${NC} (HTTP $http_code)"
        return 0
    else
        echo -e "${RED}FAIL${NC} (HTTP $http_code, expected $expected)"
        if [ -n "$body" ]; then
            echo "  Response: $(echo "$body" | head -c 200)"
        fi
        return 1
    fi
}

# Function to check if port-forward is active
check_port_forward() {
    local port=$1
    local service=$2

    if ! nc -z localhost $port 2>/dev/null; then
        echo -e "${YELLOW}WARNING: Port $port not forwarded. Run: kubectl port-forward svc/$service $port:$port -n $NAMESPACE &${NC}"
        return 1
    fi
    return 0
}

# Results tracking
PASSED=0
FAILED=0
WARNINGS=0

run_test() {
    if "$@"; then
        ((PASSED++))
    else
        ((FAILED++))
    fi
}

echo -e "${BLUE}=== 1. Grafana API Tests ===${NC}"
echo ""

if check_port_forward $GRAFANA_PORT "grafana"; then
    # Grafana Health
    run_test test_api "Grafana Health" "http://localhost:$GRAFANA_PORT/api/health" "200"

    # Grafana Datasources
    echo -n "Testing Grafana Datasources List... "
    datasources=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASS" "http://localhost:$GRAFANA_PORT/api/datasources" 2>/dev/null)
    ds_count=$(echo "$datasources" | jq '. | length' 2>/dev/null || echo "0")
    if [ "$ds_count" -gt 0 ]; then
        echo -e "${GREEN}PASS${NC} ($ds_count datasources configured)"
        ((PASSED++))

        # List datasources
        echo "  Configured datasources:"
        echo "$datasources" | jq -r '.[] | "    - \(.name) (\(.type)): \(.url)"' 2>/dev/null || true
    else
        echo -e "${RED}FAIL${NC} (No datasources configured)"
        ((FAILED++))
    fi

    # Test each datasource health
    echo ""
    echo "Testing datasource connectivity:"
    for ds_uid in $(echo "$datasources" | jq -r '.[].uid' 2>/dev/null); do
        ds_name=$(echo "$datasources" | jq -r ".[] | select(.uid==\"$ds_uid\") | .name" 2>/dev/null)
        echo -n "  $ds_name health check... "
        health=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASS" "http://localhost:$GRAFANA_PORT/api/datasources/uid/$ds_uid/health" 2>/dev/null)
        status=$(echo "$health" | jq -r '.status' 2>/dev/null || echo "unknown")
        if [ "$status" = "OK" ]; then
            echo -e "${GREEN}OK${NC}"
            ((PASSED++))
        else
            message=$(echo "$health" | jq -r '.message' 2>/dev/null || echo "unknown error")
            echo -e "${RED}FAIL${NC} - $message"
            ((FAILED++))
        fi
    done
else
    echo -e "${YELLOW}Skipping Grafana tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 2. Loki API Tests ===${NC}"
echo ""

if check_port_forward $LOKI_PORT "loki-gateway"; then
    # Loki Ready
    run_test test_api "Loki Ready" "http://localhost:$LOKI_PORT/ready" "200"

    # Loki Labels (shows what labels exist)
    echo -n "Testing Loki Labels API... "
    labels=$(curl -s "http://localhost:$LOKI_PORT/loki/api/v1/labels" 2>/dev/null)
    label_status=$(echo "$labels" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$label_status" = "success" ]; then
        label_count=$(echo "$labels" | jq '.data | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($label_count labels found)"
        ((PASSED++))
        if [ "$label_count" -gt 0 ]; then
            echo "  Labels: $(echo "$labels" | jq -r '.data | join(", ")' 2>/dev/null | head -c 100)"
        fi
    else
        echo -e "${RED}FAIL${NC} - No labels found (Loki may have no data)"
        ((FAILED++))
    fi

    # Loki Query - Try to get recent logs
    echo -n "Testing Loki Query API... "
    query_result=$(curl -s "http://localhost:$LOKI_PORT/loki/api/v1/query_range?query=%7Bnamespace%3D%22observability%22%7D&limit=10&start=$(date -v-1H +%s)000000000&end=$(date +%s)000000000" 2>/dev/null)
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        if [ "$result_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($result_count streams returned)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} - Query succeeded but no logs found"
            ((WARNINGS++))
            echo -e "  ${YELLOW}DIAGNOSIS: Loki is working but no logs are being ingested${NC}"
            echo -e "  ${YELLOW}SOLUTION: Deploy Promtail or Grafana Agent to collect logs${NC}"
        fi
    else
        echo -e "${RED}FAIL${NC} - Query failed"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}Skipping Loki tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 3. Mimir API Tests ===${NC}"
echo ""

if check_port_forward $MIMIR_PORT "mimir-gateway"; then
    # Mimir Ready (through gateway, needs different path)
    run_test test_api "Mimir Gateway Ready" "http://localhost:$MIMIR_PORT/ready" "200"

    # Mimir Prometheus-compatible query
    echo -n "Testing Mimir Query API... "
    query_result=$(curl -s "http://localhost:$MIMIR_PORT/prometheus/api/v1/query?query=up" 2>/dev/null)
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        if [ "$result_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($result_count time series found)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} - Query succeeded but no metrics found"
            ((WARNINGS++))
            echo -e "  ${YELLOW}DIAGNOSIS: Mimir is working but no metrics are being scraped${NC}"
            echo -e "  ${YELLOW}SOLUTION: Deploy Prometheus or Grafana Agent to scrape and push metrics${NC}"
        fi
    else
        echo -e "${RED}FAIL${NC} - Query failed"
        ((FAILED++))
    fi

    # List available metrics
    echo -n "Testing Mimir Label Names API... "
    labels=$(curl -s "http://localhost:$MIMIR_PORT/prometheus/api/v1/labels" 2>/dev/null)
    label_status=$(echo "$labels" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$label_status" = "success" ]; then
        label_count=$(echo "$labels" | jq '.data | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($label_count label names)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}Skipping Mimir tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 4. Prometheus API Tests ===${NC}"
echo ""

if check_port_forward $PROMETHEUS_PORT "prometheus-server"; then
    # Prometheus Ready
    run_test test_api "Prometheus Ready" "http://localhost:$PROMETHEUS_PORT/-/ready" "200"

    # Prometheus Healthy
    run_test test_api "Prometheus Healthy" "http://localhost:$PROMETHEUS_PORT/-/healthy" "200"

    # Prometheus Targets
    echo -n "Testing Prometheus Targets API... "
    targets_result=$(curl -s "http://localhost:$PROMETHEUS_PORT/api/v1/targets" 2>/dev/null)
    targets_status=$(echo "$targets_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$targets_status" = "success" ]; then
        active_targets=$(echo "$targets_result" | jq '.data.activeTargets | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($active_targets active targets)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} - Could not get targets"
        ((FAILED++))
    fi

    # Prometheus Query (up metric)
    echo -n "Testing Prometheus Query API (up metric)... "
    query_result=$(curl -s "http://localhost:$PROMETHEUS_PORT/api/v1/query?query=up" 2>/dev/null)
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        if [ "$result_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($result_count time series)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} - Query succeeded but no data yet"
            ((WARNINGS++))
        fi
    else
        echo -e "${RED}FAIL${NC} - Query failed"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}Skipping Prometheus tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 5. Kiali API Tests ===${NC}"
echo ""

if check_port_forward $KIALI_PORT "kiali"; then
    # Kiali Health
    run_test test_api "Kiali Healthz" "http://localhost:$KIALI_PORT/kiali/healthz" "200"

    # Kiali Status
    run_test test_api "Kiali Status" "http://localhost:$KIALI_PORT/kiali/api/status" "200"

    # Kiali Namespaces
    echo -n "Testing Kiali Namespaces API... "
    ns_result=$(curl -s "http://localhost:$KIALI_PORT/kiali/api/namespaces" 2>/dev/null)
    if echo "$ns_result" | jq -e '.[0].name' >/dev/null 2>&1; then
        ns_count=$(echo "$ns_result" | jq '. | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($ns_count namespaces visible)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} - Could not get namespaces"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}Skipping Kiali tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 6. Kubecost API Tests ===${NC}"
echo ""

if check_port_forward $KUBECOST_PORT "kubecost-cost-analyzer"; then
    # Kubecost Health
    run_test test_api "Kubecost Health" "http://localhost:$KUBECOST_PORT/healthz" "200"

    # Kubecost Allocation API
    echo -n "Testing Kubecost Allocation API... "
    alloc=$(curl -s "http://localhost:$KUBECOST_PORT/model/allocation?window=1d&aggregate=namespace" 2>/dev/null)
    if echo "$alloc" | jq -e '.data' >/dev/null 2>&1; then
        ns_count=$(echo "$alloc" | jq '.data | length' 2>/dev/null || echo "0")
        if [ "$ns_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($ns_count namespaces tracked)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} - API working but no allocation data yet"
            ((WARNINGS++))
        fi
    else
        echo -e "${RED}FAIL${NC} - Invalid response"
        ((FAILED++))
    fi

    # Kubecost Assets API
    echo -n "Testing Kubecost Assets API... "
    assets=$(curl -s "http://localhost:$KUBECOST_PORT/model/assets?window=1d" 2>/dev/null)
    if echo "$assets" | jq -e '.data' >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}Skipping Kubecost tests - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}=== 7. Velero API Tests ===${NC}"
echo ""

# Velero doesn't have HTTP API, test via kubectl
echo -n "Testing Velero Server Status... "
velero_status=$(kubectl get deployment velero -n velero -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$velero_status" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($velero_status replicas ready)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC} - Velero not ready"
    ((FAILED++))
fi

echo -n "Testing Velero Backup Location... "
backup_location=$(kubectl get backupstoragelocation -n velero -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")
if [ "$backup_location" = "Available" ]; then
    echo -e "${GREEN}PASS${NC} (Backup location: Available)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC} (Backup location: $backup_location)"
    ((FAILED++))
fi

echo -n "Testing Velero Backups... "
backup_count=$(kubectl get backups -n velero --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo -e "${GREEN}INFO${NC} ($backup_count backups exist)"

echo ""
echo -e "${BLUE}=== 8. Trivy Operator Tests ===${NC}"
echo ""

echo -n "Testing Trivy Operator Status... "
trivy_status=$(kubectl get deployment trivy-operator -n trivy-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$trivy_status" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($trivy_status replicas ready)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC} - Trivy Operator not ready"
    ((FAILED++))
fi

echo -n "Testing VulnerabilityReports... "
vuln_count=$(kubectl get vulnerabilityreports -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$vuln_count" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($vuln_count vulnerability reports generated)"
    ((PASSED++))
else
    echo -e "${YELLOW}WARN${NC} - No vulnerability reports yet (scanning may be in progress)"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}              TEST SUMMARY              ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "  ${GREEN}PASSED:${NC}   $PASSED"
echo -e "  ${RED}FAILED:${NC}   $FAILED"
echo -e "  ${YELLOW}WARNINGS:${NC} $WARNINGS"
echo ""

# Diagnosis section
if [ $WARNINGS -gt 0 ] || [ $FAILED -gt 0 ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}           DIAGNOSIS & FIXES            ${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Potential issues detected:${NC}"
    echo ""
    echo "1. ${YELLOW}LOGS (Loki)${NC}: If no logs found"
    echo "   - Loki-canary generates test logs automatically"
    echo "   - For application logs, deploy Promtail or Grafana Agent"
    echo ""
    echo "2. ${YELLOW}METRICS (Mimir)${NC}: If no metrics found"
    echo "   - Prometheus should be scraping and pushing to Mimir"
    echo "   - Check: kubectl logs -n observability -l app.kubernetes.io/name=prometheus"
    echo ""
    echo "3. ${YELLOW}TRAFFIC (Kiali)${NC}: If Kiali shows no data"
    echo "   - Kiali needs traffic between Istio-enabled services"
    echo "   - Deploy a test application with Istio sidecar injection"
    echo ""
fi

# Exit with appropriate code
if [ $FAILED -gt 0 ]; then
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    exit 2
else
    exit 0
fi
