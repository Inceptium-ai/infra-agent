#!/bin/bash
# API Functional Test Suite for Observability Stack
# Tests actual API functionality, not just health endpoints
# NIST AU-2: Audit Events verification
#
# Usage: ./test-apis.sh
# Requires: Port forwarding via ./services.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Port Configuration
GRAFANA_PORT=3000
LOKI_PORT=3100
TEMPO_PORT=3200
PROMETHEUS_PORT=9090
MIMIR_PORT=9080
KIALI_PORT=20001
HEADLAMP_PORT=8080
KUBECOST_PORT=9091
KEYCLOAK_PORT=8180

# Get Grafana credentials
GRAFANA_USER="admin"
GRAFANA_PASS=$(kubectl get secret grafana -n observability -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d || echo "admin")

# Results tracking
PASSED=0
FAILED=0
WARNINGS=0

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Infrastructure API Functional Test Suite ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Helper function to check port
check_port() {
    local port=$1
    local service=$2
    if ! nc -z localhost $port 2>/dev/null; then
        echo -e "${YELLOW}WARNING: Port $port ($service) not forwarded${NC}"
        return 1
    fi
    return 0
}

# Helper function for API test
test_api() {
    local name=$1
    local url=$2
    local expected_code=$3
    local auth=${4:-}

    echo -n "  $name... "

    if [ -n "$auth" ]; then
        response=$(curl -s -w "\n%{http_code}" -u "$auth" "$url" 2>/dev/null || echo -e "\n000")
    else
        response=$(curl -s -w "\n%{http_code}" "$url" 2>/dev/null || echo -e "\n000")
    fi

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "$expected_code" ]; then
        echo -e "${GREEN}PASS${NC} (HTTP $http_code)"
        ((PASSED++))
        echo "$body"
        return 0
    else
        echo -e "${RED}FAIL${NC} (HTTP $http_code, expected $expected_code)"
        ((FAILED++))
        return 1
    fi
}

#############################################
# 1. GRAFANA TESTS
#############################################
echo -e "${BLUE}=== 1. Grafana (Dashboards & Visualization) ===${NC}"
echo ""

if check_port $GRAFANA_PORT "Grafana"; then
    # Health check
    echo -n "  Health Check... "
    health=$(curl -s "http://localhost:$GRAFANA_PORT/api/health" 2>/dev/null)
    if echo "$health" | jq -e '.database == "ok"' >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC} (database: ok)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # List datasources
    echo -n "  Datasources Configured... "
    datasources=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASS" "http://localhost:$GRAFANA_PORT/api/datasources" 2>/dev/null)
    ds_count=$(echo "$datasources" | jq '. | length' 2>/dev/null || echo "0")
    if [ "$ds_count" -gt 0 ]; then
        echo -e "${GREEN}PASS${NC} ($ds_count datasources)"
        ((PASSED++))
        echo "$datasources" | jq -r '.[] | "    - \(.name) (\(.type))"' 2>/dev/null || true
    else
        echo -e "${RED}FAIL${NC} (no datasources)"
        ((FAILED++))
    fi

    # Test datasource connectivity
    echo "  Testing datasource connectivity:"
    for ds_id in $(echo "$datasources" | jq -r '.[].id' 2>/dev/null); do
        ds_name=$(echo "$datasources" | jq -r ".[] | select(.id==$ds_id) | .name" 2>/dev/null)
        echo -n "    $ds_name... "
        health_resp=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASS" "http://localhost:$GRAFANA_PORT/api/datasources/$ds_id/health" 2>/dev/null)
        status=$(echo "$health_resp" | jq -r '.status' 2>/dev/null || echo "unknown")
        if [ "$status" = "OK" ]; then
            echo -e "${GREEN}OK${NC}"
            ((PASSED++))
        else
            message=$(echo "$health_resp" | jq -r '.message' 2>/dev/null || echo "connection failed")
            echo -e "${RED}FAIL${NC} ($message)"
            ((FAILED++))
        fi
    done

    # List dashboards
    echo -n "  Dashboards Available... "
    dashboards=$(curl -s -u "$GRAFANA_USER:$GRAFANA_PASS" "http://localhost:$GRAFANA_PORT/api/search?type=dash-db" 2>/dev/null)
    dash_count=$(echo "$dashboards" | jq '. | length' 2>/dev/null || echo "0")
    echo -e "${GREEN}INFO${NC} ($dash_count dashboards)"
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 2. LOKI TESTS
#############################################
echo -e "${BLUE}=== 2. Loki (Log Aggregation) ===${NC}"
echo ""

if check_port $LOKI_PORT "Loki"; then
    # Gateway ready check (via labels API since /ready is not exposed on gateway)
    echo -n "  Gateway Check... "
    labels=$(curl -s -m 5 "http://localhost:$LOKI_PORT/loki/api/v1/labels" 2>/dev/null || echo "{}")
    label_status=$(echo "$labels" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$label_status" = "success" ]; then
        label_count=$(echo "$labels" | jq '.data | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # List labels
    echo -n "  Labels API... "
    if [ "$label_status" = "success" ]; then
        echo -e "${GREEN}PASS${NC} ($label_count labels)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # Query recent logs
    echo -n "  Log Query (last 1h)... "
    end_time=$(date +%s)000000000
    start_time=$(($(date +%s) - 3600))000000000
    query_result=$(curl -s -m 10 "http://localhost:$LOKI_PORT/loki/api/v1/query_range?query=%7Bnamespace%3D%22observability%22%7D&limit=10&start=$start_time&end=$end_time" 2>/dev/null || echo "{}")
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        if [ "$result_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($result_count streams)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} (no logs found - deploy Promtail)"
            ((WARNINGS++))
        fi
    else
        echo -e "${YELLOW}WARN${NC} (query failed)"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 3. MIMIR TESTS
#############################################
echo -e "${BLUE}=== 3. Mimir (Long-term Metrics Storage) ===${NC}"
echo ""

if check_port $MIMIR_PORT "Mimir"; then
    # Ready check
    echo -n "  Ready Check... "
    ready=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$MIMIR_PORT/ready" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    # Query 'up' metric
    echo -n "  Prometheus Query API... "
    query_result=$(curl -s "http://localhost:$MIMIR_PORT/prometheus/api/v1/query?query=up" 2>/dev/null)
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($result_count time series)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # List label names
    echo -n "  Label Names API... "
    labels=$(curl -s "http://localhost:$MIMIR_PORT/prometheus/api/v1/labels" 2>/dev/null)
    label_status=$(echo "$labels" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$label_status" = "success" ]; then
        label_count=$(echo "$labels" | jq '.data | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($label_count labels)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # Query container memory
    echo -n "  Container Metrics Query... "
    mem_query=$(curl -s "http://localhost:$MIMIR_PORT/prometheus/api/v1/query?query=container_memory_usage_bytes" 2>/dev/null)
    mem_status=$(echo "$mem_query" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$mem_status" = "success" ]; then
        mem_count=$(echo "$mem_query" | jq '.data.result | length' 2>/dev/null || echo "0")
        if [ "$mem_count" -gt 0 ]; then
            echo -e "${GREEN}PASS${NC} ($mem_count containers)"
            ((PASSED++))
        else
            echo -e "${YELLOW}WARN${NC} (no container metrics)"
            ((WARNINGS++))
        fi
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 4. PROMETHEUS TESTS
#############################################
echo -e "${BLUE}=== 4. Prometheus (Metrics Scraping) ===${NC}"
echo ""

if check_port $PROMETHEUS_PORT "Prometheus"; then
    # Ready check
    echo -n "  Ready Check... "
    ready=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PROMETHEUS_PORT/-/ready" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    # Targets
    echo -n "  Scrape Targets... "
    targets=$(curl -s "http://localhost:$PROMETHEUS_PORT/api/v1/targets" 2>/dev/null)
    targets_status=$(echo "$targets" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$targets_status" = "success" ]; then
        active=$(echo "$targets" | jq '.data.activeTargets | length' 2>/dev/null || echo "0")
        up_count=$(echo "$targets" | jq '[.data.activeTargets[] | select(.health=="up")] | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($up_count/$active targets up)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # Query up metric
    echo -n "  Query API (up metric)... "
    query_result=$(curl -s "http://localhost:$PROMETHEUS_PORT/api/v1/query?query=up" 2>/dev/null)
    query_status=$(echo "$query_result" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$query_status" = "success" ]; then
        result_count=$(echo "$query_result" | jq '.data.result | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($result_count time series)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # TSDB status
    echo -n "  TSDB Status... "
    tsdb=$(curl -s "http://localhost:$PROMETHEUS_PORT/api/v1/status/tsdb" 2>/dev/null)
    tsdb_status=$(echo "$tsdb" | jq -r '.status' 2>/dev/null || echo "error")
    if [ "$tsdb_status" = "success" ]; then
        series=$(echo "$tsdb" | jq -r '.data.headStats.numSeries' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($series active series)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 5. TEMPO TESTS
#############################################
echo -e "${BLUE}=== 5. Tempo (Distributed Tracing) ===${NC}"
echo ""

if check_port $TEMPO_PORT "Tempo"; then
    # Ready check
    echo -n "  Ready Check... "
    ready=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://localhost:$TEMPO_PORT/ready" 2>/dev/null || echo "000")
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    # Metrics endpoint (more reliable than buildinfo)
    echo -n "  Metrics Endpoint... "
    metrics=$(curl -s -m 5 "http://localhost:$TEMPO_PORT/metrics" 2>/dev/null | grep -c "tempo_" || echo "0")
    if [ "$metrics" -gt 0 ]; then
        echo -e "${GREEN}PASS${NC} ($metrics tempo metrics)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC} (no metrics)"
        ((WARNINGS++))
    fi

    # Services endpoint
    echo -n "  Services API... "
    services=$(curl -s -m 5 "http://localhost:$TEMPO_PORT/api/search/tags" 2>/dev/null)
    if [ -n "$services" ]; then
        echo -e "${GREEN}PASS${NC} (API available)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC} (no tags yet)"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 6. KIALI TESTS
#############################################
echo -e "${BLUE}=== 6. Kiali (Service Mesh Visualization) ===${NC}"
echo ""

if check_port $KIALI_PORT "Kiali"; then
    # Health check
    echo -n "  Health Check... "
    ready=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$KIALI_PORT/kiali/healthz" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    # Status API
    echo -n "  Status API... "
    status=$(curl -s "http://localhost:$KIALI_PORT/kiali/api/status" 2>/dev/null)
    istio_env=$(echo "$status" | jq -r '.status.istio_environment.istio_certs_generated' 2>/dev/null || echo "null")
    if [ "$istio_env" != "null" ]; then
        echo -e "${GREEN}PASS${NC} (Istio integration working)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC} (no Istio integration)"
        ((WARNINGS++))
    fi

    # Namespaces
    echo -n "  Namespaces API... "
    namespaces=$(curl -s "http://localhost:$KIALI_PORT/kiali/api/namespaces" 2>/dev/null)
    ns_count=$(echo "$namespaces" | jq '. | length' 2>/dev/null || echo "0")
    if [ "$ns_count" -gt 0 ]; then
        echo -e "${GREEN}PASS${NC} ($ns_count namespaces visible)"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # Mesh status
    echo -n "  Mesh TLS Status... "
    mesh=$(curl -s "http://localhost:$KIALI_PORT/kiali/api/mesh/tls" 2>/dev/null)
    mtls=$(echo "$mesh" | jq -r '.status' 2>/dev/null || echo "unknown")
    if [ -n "$mtls" ] && [ "$mtls" != "null" ]; then
        echo -e "${GREEN}PASS${NC} (mTLS: $mtls)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC} (mTLS status unknown)"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 7. KUBECOST TESTS
#############################################
echo -e "${BLUE}=== 7. Kubecost (Cost Management) ===${NC}"
echo ""

if check_port $KUBECOST_PORT "Kubecost"; then
    # Health check
    echo -n "  Health Check... "
    ready=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$KUBECOST_PORT/healthz" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    # Allocation by namespace
    echo -n "  Namespace Allocation... "
    alloc=$(curl -s "http://localhost:$KUBECOST_PORT/model/allocation?window=1d&aggregate=namespace" 2>/dev/null)
    if echo "$alloc" | jq -e '.data' >/dev/null 2>&1; then
        ns_count=$(echo "$alloc" | jq '[.data[].[] | keys[]] | unique | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}PASS${NC} ($ns_count namespaces tracked)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC} (no allocation data yet)"
        ((WARNINGS++))
    fi

    # Assets
    echo -n "  Assets API... "
    assets=$(curl -s "http://localhost:$KUBECOST_PORT/model/assets?window=1d&aggregate=type" 2>/dev/null)
    if echo "$assets" | jq -e '.data' >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi

    # Cluster info
    echo -n "  Cluster Info... "
    cluster=$(curl -s "http://localhost:$KUBECOST_PORT/model/clusterInfo" 2>/dev/null)
    cluster_id=$(echo "$cluster" | jq -r '.id' 2>/dev/null || echo "unknown")
    if [ "$cluster_id" != "unknown" ] && [ -n "$cluster_id" ]; then
        echo -e "${GREEN}PASS${NC} (cluster: $cluster_id)"
        ((PASSED++))
    else
        echo -e "${YELLOW}WARN${NC}"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 8. VELERO TESTS (via kubectl)
#############################################
echo -e "${BLUE}=== 8. Velero (Backup & Recovery) ===${NC}"
echo ""

echo -n "  Server Status... "
velero_ready=$(kubectl get deployment velero -n velero -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$velero_ready" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($velero_ready replicas)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC}"
    ((FAILED++))
fi

echo -n "  Backup Storage Location... "
bsl_phase=$(kubectl get backupstoragelocation -n velero -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")
if [ "$bsl_phase" = "Available" ]; then
    echo -e "${GREEN}PASS${NC} (Available)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC} ($bsl_phase)"
    ((FAILED++))
fi

echo -n "  Backup Count... "
backup_count=$(kubectl get backups -n velero --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo -e "${GREEN}INFO${NC} ($backup_count backups)"

echo -n "  Schedule Count... "
schedule_count=$(kubectl get schedules -n velero --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo -e "${GREEN}INFO${NC} ($schedule_count schedules)"

echo ""

#############################################
# 9. TRIVY OPERATOR TESTS (via kubectl)
#############################################
echo -e "${BLUE}=== 9. Trivy Operator (Security Scanning) ===${NC}"
echo ""

echo -n "  Operator Status... "
trivy_ready=$(kubectl get deployment trivy-operator -n trivy-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$trivy_ready" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($trivy_ready replicas)"
    ((PASSED++))
else
    echo -e "${RED}FAIL${NC}"
    ((FAILED++))
fi

echo -n "  Vulnerability Reports... "
vuln_count=$(kubectl get vulnerabilityreports -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$vuln_count" -gt 0 ]; then
    echo -e "${GREEN}PASS${NC} ($vuln_count reports)"
    ((PASSED++))
else
    echo -e "${YELLOW}WARN${NC} (scanning in progress)"
    ((WARNINGS++))
fi

echo -n "  Critical Vulnerabilities... "
critical=$(kubectl get vulnerabilityreports -A -o json 2>/dev/null | jq '[.items[].report.summary.criticalCount] | add' 2>/dev/null || echo "0")
if [ "$critical" = "null" ]; then critical=0; fi
if [ "$critical" -eq 0 ]; then
    echo -e "${GREEN}PASS${NC} (0 critical)"
    ((PASSED++))
else
    echo -e "${RED}WARN${NC} ($critical critical vulnerabilities)"
    ((WARNINGS++))
fi

echo ""

#############################################
# 10. HEADLAMP TESTS
#############################################
echo -e "${BLUE}=== 10. Headlamp (K8s Dashboard) ===${NC}"
echo ""

if check_port $HEADLAMP_PORT "Headlamp"; then
    echo -n "  Frontend Available... "
    ready=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$HEADLAMP_PORT/" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    echo -n "  Config API... "
    config=$(curl -s "http://localhost:$HEADLAMP_PORT/config" 2>/dev/null)
    if [ -n "$config" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}SKIPPED - port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# 11. KEYCLOAK TESTS
#############################################
echo -e "${BLUE}=== 11. Keycloak (Identity Provider) ===${NC}"
echo ""

if check_port $KEYCLOAK_PORT "Keycloak"; then
    echo -n "  Health Check... "
    ready=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://localhost:$KEYCLOAK_PORT/health/ready" 2>/dev/null)
    if [ "$ready" = "200" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $ready)"
        ((FAILED++))
    fi

    echo -n "  Admin Console... "
    admin=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://localhost:$KEYCLOAK_PORT/admin/master/console/" 2>/dev/null)
    if [ "$admin" = "200" ] || [ "$admin" = "302" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC} (HTTP $admin)"
        ((FAILED++))
    fi

    echo -n "  OIDC Discovery... "
    oidc=$(curl -s -m 5 "http://localhost:$KEYCLOAK_PORT/realms/master/.well-known/openid-configuration" 2>/dev/null)
    issuer=$(echo "$oidc" | jq -r '.issuer' 2>/dev/null || echo "")
    if [ -n "$issuer" ] && [ "$issuer" != "null" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}SKIPPED - Keycloak not deployed or port not forwarded${NC}"
    ((WARNINGS++))
fi

echo ""

#############################################
# SUMMARY
#############################################
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}              TEST SUMMARY                  ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "  ${GREEN}PASSED:${NC}   $PASSED"
echo -e "  ${RED}FAILED:${NC}   $FAILED"
echo -e "  ${YELLOW}WARNINGS:${NC} $WARNINGS"
echo ""

# Calculate pass rate
TOTAL=$((PASSED + FAILED))
if [ $TOTAL -gt 0 ]; then
    PASS_RATE=$((PASSED * 100 / TOTAL))
    echo -e "  Pass Rate: ${PASS_RATE}%"
fi

echo ""

# Exit code based on results
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Some tests failed. Check component status.${NC}"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}All critical tests passed with warnings.${NC}"
    exit 0
else
    echo -e "${GREEN}All tests passed successfully.${NC}"
    exit 0
fi
