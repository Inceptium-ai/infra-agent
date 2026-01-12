#!/bin/bash
# Drift Detection Script
# Checks for configuration drift in CloudFormation and Helm releases

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VALUES_DIR="$PROJECT_ROOT/infra/helm/values"

echo "=============================================="
echo "  INFRASTRUCTURE DRIFT DETECTION"
echo "=============================================="
echo ""

REGION="us-east-1"

# =============================================================================
# 1. CloudFormation Drift Detection
# =============================================================================
echo "=== CloudFormation Stacks ==="
STACKS=$(aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?contains(StackName, `infra-agent`)].StackName' \
  --output text --region $REGION 2>/dev/null || echo "")

if [ -z "$STACKS" ]; then
  echo "  No stacks found or AWS CLI error"
else
  for stack in $STACKS; do
    echo -n "  $stack... "
    DETECTION_ID=$(aws cloudformation detect-stack-drift --stack-name $stack --region $REGION --query 'StackDriftDetectionId' --output text 2>/dev/null || echo "SKIP")

    if [ "$DETECTION_ID" != "SKIP" ]; then
      # Wait for drift detection to complete (max 30 seconds)
      for i in {1..6}; do
        sleep 5
        DETECTION_STATUS=$(aws cloudformation describe-stack-drift-detection-status \
          --stack-drift-detection-id $DETECTION_ID \
          --region $REGION \
          --query 'DetectionStatus' --output text 2>/dev/null || echo "UNKNOWN")

        if [ "$DETECTION_STATUS" = "DETECTION_COMPLETE" ] || [ "$DETECTION_STATUS" = "DETECTION_FAILED" ]; then
          break
        fi
      done

      STATUS=$(aws cloudformation describe-stack-drift-detection-status \
        --stack-drift-detection-id $DETECTION_ID \
        --region $REGION \
        --query 'StackDriftStatus' --output text 2>/dev/null || echo "UNKNOWN")

      if [ "$STATUS" = "DRIFTED" ]; then
        echo "⚠️  DRIFTED"
      elif [ "$STATUS" = "IN_SYNC" ]; then
        echo "✅ IN_SYNC"
      elif [ "$STATUS" = "NOT_CHECKED" ]; then
        echo "⏳ PENDING"
      else
        echo "❓ $STATUS"
      fi
    else
      echo "⏭️  SKIPPED"
    fi
  done
fi

echo ""

# =============================================================================
# 2. Helm Release Drift Detection
# =============================================================================
echo "=== Helm Release Drift ==="

# Check if helm-diff plugin is installed
if ! helm plugin list | grep -q diff; then
  echo "⚠️  helm-diff plugin not installed"
  echo "   Install with: helm plugin install https://github.com/databus23/helm-diff"
  echo ""
  echo "Listing Helm releases (manual check needed):"
  helm list -A 2>/dev/null || echo "  kubectl not configured"
else
  # Define all releases with their chart, namespace, values file, and optional version
  # Format: "release|chart|namespace|values_file|version"
  RELEASES=(
    # LGTM Stack
    "grafana|grafana/grafana|observability|lgtm/grafana-values.yaml|"
    "loki|grafana/loki|observability|lgtm/loki-values.yaml|"
    "mimir|grafana/mimir-distributed|observability|lgtm/mimir-values.yaml|"
    "prometheus|prometheus-community/prometheus|observability|lgtm/prometheus-values.yaml|"
    "tempo|grafana/tempo|observability|lgtm/tempo-values.yaml|"
    # Istio
    "istio-base|istio/base|istio-system|istio/base-values.yaml|"
    "istiod|istio/istiod|istio-system|istio/istiod-values.yaml|"
    "istio-ingress|istio/gateway|istio-system|istio/gateway-values.yaml|"
    # Kiali
    "kiali-operator|kiali/kiali-operator|kiali-operator|kiali/values.yaml|"
    # Operations
    "headlamp|headlamp/headlamp|headlamp|headlamp/values.yaml|"
    "kubecost|kubecost/cost-analyzer|kubecost|kubecost/values.yaml|2.8.5"
    "velero|vmware-tanzu/velero|velero|velero/values.yaml|"
    "trivy-operator|aqua/trivy-operator|trivy-system|trivy-operator/values.yaml|"
  )

  # Note: Keycloak uses official quay.io image as Kubernetes deployment (not Helm chart)
  # Check separately below

  for entry in "${RELEASES[@]}"; do
    IFS='|' read -r release chart namespace values_file version <<< "$entry"
    values_path="$VALUES_DIR/$values_file"

    # Check if release is deployed
    if ! helm status "$release" -n "$namespace" &>/dev/null; then
      echo "  $release ($namespace)... ❌ NOT DEPLOYED"
      continue
    fi

    # Check if values file exists
    if [ ! -f "$values_path" ]; then
      echo "  $release ($namespace)... ⚠️  NO VALUES FILE"
      continue
    fi

    echo -n "  $release ($namespace)... "

    # Build helm diff command
    DIFF_CMD="helm diff upgrade $release $chart -n $namespace -f $values_path"
    if [ -n "$version" ]; then
      DIFF_CMD="$DIFF_CMD --version $version"
    fi

    # Run diff and capture output
    DIFF_OUTPUT=$($DIFF_CMD 2>&1) || true

    # Check for errors
    if echo "$DIFF_OUTPUT" | grep -q "Error:"; then
      echo "⚠️  ERROR"
      # echo "     $DIFF_OUTPUT" | head -1
    elif [ -z "$DIFF_OUTPUT" ]; then
      echo "✅ IN_SYNC"
    else
      # Count actual changes (lines starting with + or -)
      CHANGES=$(echo "$DIFF_OUTPUT" | grep -c "^[+-]" || echo "0")
      if [ "$CHANGES" -eq 0 ]; then
        echo "✅ IN_SYNC"
      else
        echo "⚠️  DRIFT ($CHANGES changes)"
      fi
    fi
  done

  # Check Keycloak deployment (not a Helm chart)
  echo -n "  keycloak (identity)... "
  if kubectl get deployment keycloak -n identity &>/dev/null; then
    REPLICAS=$(kubectl get deployment keycloak -n identity -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    DESIRED=$(kubectl get deployment keycloak -n identity -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
    if [ "$REPLICAS" = "$DESIRED" ]; then
      echo "✅ DEPLOYED ($REPLICAS/$DESIRED ready)"
    else
      echo "⚠️  DEGRADED ($REPLICAS/$DESIRED ready)"
    fi
  else
    echo "❌ NOT DEPLOYED"
  fi
fi

echo ""

# =============================================================================
# 3. Helm Release Status Check
# =============================================================================
echo "=== Helm Release Status ==="
helm list -A --output json 2>/dev/null | jq -r '.[] | "\(.name)|\(.namespace)|\(.status)"' | while IFS='|' read -r name ns status; do
  if [ "$status" != "deployed" ]; then
    echo "  ⚠️  $name ($ns): $status"
  fi
done || echo "  All releases deployed"

# Check for any non-deployed status
FAILED=$(helm list -A --output json 2>/dev/null | jq -r '.[] | select(.status != "deployed") | .name' | wc -l | tr -d ' ')
if [ "$FAILED" -eq 0 ]; then
  echo "  ✅ All releases in 'deployed' status"
fi

echo ""

# =============================================================================
# 4. Namespace Labels (Istio Injection)
# =============================================================================
echo "=== Istio Injection Status ==="
kubectl get namespaces -L istio-injection --no-headers 2>/dev/null | while read line; do
  ns=$(echo $line | awk '{print $1}')
  label=$(echo $line | awk '{print $4}')
  if [ "$label" = "enabled" ]; then
    echo "  $ns: ✅ istio-injection=enabled"
  fi
done || echo "  kubectl not configured"

# Count pods with sidecars
echo ""
echo "=== Istio Sidecar Coverage ==="
TOTAL_PODS=$(kubectl get pods -A -o json 2>/dev/null | jq '[.items[] | select(.metadata.namespace != "kube-system" and .metadata.namespace != "kube-node-lease" and .metadata.namespace != "kube-public")] | length')
SIDECAR_PODS=$(kubectl get pods -A -o json 2>/dev/null | jq '[.items[] | select(.spec.initContainers[]?.name == "istio-proxy" or .spec.containers[]?.name == "istio-proxy")] | length')
echo "  Pods with Istio sidecar: $SIDECAR_PODS / $TOTAL_PODS"

echo ""

# =============================================================================
# 5. Cluster Resource Metrics
# =============================================================================
echo "=== Cluster Resource Metrics ==="

# Check if metrics-server is available
if kubectl top nodes &>/dev/null; then
  echo ""
  echo "  Node Resources:"
  kubectl top nodes 2>/dev/null | while read line; do
    if echo "$line" | grep -q "NAME"; then
      printf "    %-40s %10s %10s %15s %10s\n" "NODE" "CPU" "CPU%" "MEMORY" "MEM%"
    else
      node=$(echo $line | awk '{print $1}')
      cpu=$(echo $line | awk '{print $2}')
      cpu_pct=$(echo $line | awk '{print $3}')
      mem=$(echo $line | awk '{print $4}')
      mem_pct=$(echo $line | awk '{print $5}')
      printf "    %-40s %10s %10s %15s %10s\n" "$node" "$cpu" "$cpu_pct" "$mem" "$mem_pct"
    fi
  done

  # Calculate cluster totals
  TOTAL_CPU=$(kubectl top nodes --no-headers 2>/dev/null | awk '{gsub(/m/,"",$2); sum+=$2} END {printf "%.1f", sum/1000}')
  TOTAL_MEM=$(kubectl top nodes --no-headers 2>/dev/null | awk '{gsub(/Mi/,"",$4); sum+=$4} END {printf "%.1f", sum/1024}')
  NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')

  echo ""
  echo "  Cluster Totals ($NODE_COUNT nodes):"
  echo "    CPU Used:    ${TOTAL_CPU} vCPU"
  echo "    Memory Used: ${TOTAL_MEM} GB"
else
  echo "  ⚠️  metrics-server not available (kubectl top not working)"
fi

echo ""

# =============================================================================
# 6. Pod Resource Summary by Namespace
# =============================================================================
echo "=== Pod Resource Usage by Namespace ==="

if kubectl top pods -A &>/dev/null; then
  # Get top namespaces by resource usage
  echo ""
  echo "  Top Namespaces by Memory:"
  kubectl top pods -A --no-headers 2>/dev/null | \
    awk '{ns[$1]+=$4} END {for(n in ns) print ns[n], n}' | \
    sed 's/Mi//g' | sort -rn | head -5 | \
    while read mem ns; do
      printf "    %-25s %10s Mi\n" "$ns" "$mem"
    done

  echo ""
  echo "  Top Namespaces by CPU:"
  kubectl top pods -A --no-headers 2>/dev/null | \
    awk '{gsub(/m/,"",$3); ns[$1]+=$3} END {for(n in ns) print ns[n], n}' | \
    sort -rn | head -5 | \
    while read cpu ns; do
      printf "    %-25s %10s m\n" "$ns" "$cpu"
    done
fi

echo ""

# =============================================================================
# 7. EKS Add-ons Status
# =============================================================================
echo "=== EKS Add-ons ==="

CLUSTER_NAME="infra-agent-dev-cluster"
ADDONS=$(aws eks list-addons --cluster-name $CLUSTER_NAME --region $REGION --query 'addons[]' --output text 2>/dev/null || echo "")

if [ -n "$ADDONS" ]; then
  for addon in $ADDONS; do
    STATUS=$(aws eks describe-addon --cluster-name $CLUSTER_NAME --addon-name $addon --region $REGION --query 'addon.status' --output text 2>/dev/null || echo "UNKNOWN")
    VERSION=$(aws eks describe-addon --cluster-name $CLUSTER_NAME --addon-name $addon --region $REGION --query 'addon.addonVersion' --output text 2>/dev/null || echo "?")

    if [ "$STATUS" = "ACTIVE" ]; then
      echo "  $addon ($VERSION): ✅ ACTIVE"
    else
      echo "  $addon ($VERSION): ⚠️  $STATUS"
    fi
  done
else
  echo "  No add-ons found or unable to query"
fi

echo ""

# =============================================================================
# 8. Security Summary (Trivy)
# =============================================================================
echo "=== Security Scan Summary ==="

VULN_REPORTS=$(kubectl get vulnerabilityreports -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$VULN_REPORTS" -gt 0 ]; then
  CRITICAL=$(kubectl get vulnerabilityreports -A -o json 2>/dev/null | jq '[.items[].report.summary.criticalCount // 0] | add' 2>/dev/null || echo "0")
  HIGH=$(kubectl get vulnerabilityreports -A -o json 2>/dev/null | jq '[.items[].report.summary.highCount // 0] | add' 2>/dev/null || echo "0")
  MEDIUM=$(kubectl get vulnerabilityreports -A -o json 2>/dev/null | jq '[.items[].report.summary.mediumCount // 0] | add' 2>/dev/null || echo "0")

  if [ "$CRITICAL" = "null" ]; then CRITICAL=0; fi
  if [ "$HIGH" = "null" ]; then HIGH=0; fi
  if [ "$MEDIUM" = "null" ]; then MEDIUM=0; fi

  echo "  Vulnerability Reports: $VULN_REPORTS"
  if [ "$CRITICAL" -gt 0 ]; then
    echo "  Critical: ⚠️  $CRITICAL"
  else
    echo "  Critical: ✅ $CRITICAL"
  fi
  echo "  High:     $HIGH"
  echo "  Medium:   $MEDIUM"
else
  echo "  No vulnerability reports available (Trivy scanning in progress)"
fi

echo ""

# =============================================================================
# 9. Backup Status (Velero)
# =============================================================================
echo "=== Backup Status ==="

BSL_PHASE=$(kubectl get backupstoragelocation -n velero -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")
BACKUP_COUNT=$(kubectl get backups -n velero --no-headers 2>/dev/null | wc -l | tr -d ' ')
SCHEDULE_COUNT=$(kubectl get schedules -n velero --no-headers 2>/dev/null | wc -l | tr -d ' ')
LAST_BACKUP=$(kubectl get backups -n velero --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "none")

if [ "$BSL_PHASE" = "Available" ]; then
  echo "  Storage Location: ✅ Available"
else
  echo "  Storage Location: ⚠️  $BSL_PHASE"
fi
echo "  Total Backups:    $BACKUP_COUNT"
echo "  Schedules:        $SCHEDULE_COUNT"
echo "  Last Backup:      $LAST_BACKUP"

echo ""
echo "=============================================="
echo "  DRIFT CHECK COMPLETE"
echo "=============================================="
