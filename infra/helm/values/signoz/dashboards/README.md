# SigNoz Dashboards (IaC)

Pre-built SigNoz dashboard JSON files sourced from the official [SigNoz dashboards repository](https://github.com/SigNoz/dashboards).

## Dashboard Files

### Kubernetes Infrastructure
| File | Description |
|------|-------------|
| `kubernetes-cluster-metrics.json` | Deployments, DaemonSets, StatefulSets, Jobs, HPAs, Pods by phase |
| `kubernetes-pod-metrics.json` | Pod CPU, Memory, Network, Restarts |
| `kubernetes-node-metrics.json` | Node CPU, Memory, Disk, Network |
| `kubernetes-pvc-metrics.json` | PVC capacity and usage |
| `host-metrics.json` | Host CPU, Memory, Disk, Network, Filesystem |

### APM & Traces
| File | Description |
|------|-------------|
| `apm-metrics.json` | Application performance metrics (latency, throughput, errors) |
| `http-api-monitoring.json` | HTTP API metrics (request rate, latency, status codes) |
| `db-calls-monitoring.json` | Database call metrics (query latency, connection pools) |
| `key-operations.json` | Key operation tracking across services |

## Deploy Dashboards

```bash
# Deploy all dashboards (keeps existing)
./scripts/deploy-signoz-dashboards.sh

# Deploy all dashboards (delete existing first)
./scripts/deploy-signoz-dashboards.sh --delete-existing
```

**Prerequisites:**
- SSM tunnel running (`./scripts/tunnel.sh`)
- `SIGNOZ_API_KEY` in `.env` file
- `jq` installed (`brew install jq`)

## Update to Latest Official Dashboards

```bash
# K8s Infrastructure
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-cluster-metrics.json" -o kubernetes-cluster-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-pod-metrics-overall.json" -o kubernetes-pod-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-node-metrics-overall.json" -o kubernetes-node-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-pvc-metrics.json" -o kubernetes-pvc-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/host-metrics.json" -o host-metrics.json

# APM & Traces
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/apm/apm-metrics.json" -o apm-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/apm/http-api-monitoring.json" -o http-api-monitoring.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/apm/db-calls-monitoring.json" -o db-calls-monitoring.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/key-operations/key-operations.json" -o key-operations.json
```

## SigNoz Built-in Features (No Dashboard Needed)

SigNoz has built-in explorers that don't require custom dashboards:

| Feature | Access | Description |
|---------|--------|-------------|
| **Traces** | Services → Select Service → Traces | Distributed tracing with flame graphs |
| **Logs** | Logs Explorer | Full-text search, filters, aggregations |
| **Metrics** | Metrics Explorer | Ad-hoc metric queries and graphs |
| **Alerts** | Alerts | Metric and log-based alerting |
| **Service Map** | Services | Auto-generated service dependency map |
| **Exceptions** | Exceptions | Error tracking across services |

## Required Data Sources

| Dashboard Type | Requires |
|----------------|----------|
| K8s Infrastructure | k8sclusterreceiver, kubeletstatsreceiver, hostmetricsreceiver |
| APM/Traces | OpenTelemetry SDK in applications |
| DB Calls | OpenTelemetry auto-instrumentation for DB libraries |
| HTTP API | OpenTelemetry auto-instrumentation for HTTP clients |

## Troubleshooting

**K8s dashboards show "No data":**
- Check k8s-infra collector: `kubectl logs -n signoz deploy/k8s-infra-otel-deployment`
- Wait 2-3 minutes for metrics to populate

**APM dashboards show "No data":**
- Applications must be instrumented with OpenTelemetry SDK
- Verify traces in: Services → your-service → Traces

**Logs not appearing:**
- Configure log collection in OTel collector
- Check: `kubectl logs -n signoz deploy/k8s-infra-otel-deployment`
