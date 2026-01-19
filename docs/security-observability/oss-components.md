# OSS Components Resource Usage

This document tracks all OSS components deployed in the infra-agent cluster, their resource usage, and operational metrics.

## Summary

**Total Infrastructure:**
- EKS Worker Nodes: 3x t3a.xlarge (4 vCPU, 16GB RAM each = 12 vCPU, 48GB total)
- Total Resource Requests: ~8.5 vCPU, ~22GB RAM
- Utilization: ~70% CPU requested, ~46% RAM requested

## Component Inventory

### EKS Add-ons (AWS Managed)

| Add-on | Version | Purpose | NIST Control |
|--------|---------|---------|--------------|
| vpc-cni | v1.21.1-eksbuild.1 | Pod networking | SC-7 |
| coredns | v1.12.4-eksbuild.1 | DNS resolution | - |
| kube-proxy | v1.34.1-eksbuild.2 | Service networking | - |
| aws-ebs-csi-driver | v1.54.0-eksbuild.1 | Persistent volumes | SC-28 |
| metrics-server | v0.8.0-eksbuild.6 | Resource metrics | AU-2 |

### Observability Stack (LGTM)

| Component | Replicas | CPU Request | Memory Request | Actual Usage | Purpose |
|-----------|----------|-------------|----------------|--------------|---------|
| Grafana | 2 | 200m | 512Mi | ~20m, ~600Mi | Dashboards |
| Loki Backend | 2 | 200m | 512Mi | ~25m, ~340Mi | Log storage |
| Loki Read | 2 | 200m | 512Mi | ~40m, ~250Mi | Log queries |
| Loki Write | 2 | 200m | 512Mi | ~40m, ~200Mi | Log ingestion |
| Loki Gateway | 2 | - | - | minimal | Routing |
| Loki Chunks Cache | 1 | 500m | 9830Mi | - | Caching |
| Loki Results Cache | 1 | 500m | 1229Mi | - | Caching |
| Mimir Ingester | 2 | 200m | 512Mi | ~60m, ~1GB | Metrics storage |
| Mimir Distributor | 2 | 200m | 256Mi | ~40m, ~280Mi | Metrics routing |
| Mimir Querier | 2 | 200m | 256Mi | ~12m, ~66Mi | Metrics queries |
| Mimir Kafka | 1 | 250m | 512Mi | ~60m, ~630Mi | Write-ahead log |
| Prometheus Server | 1 | 200m | 512Mi | ~30m, ~680Mi | Metrics scraping |
| Tempo | 2 | 100m | 256Mi | ~8m, ~86Mi | Tracing |

**Loki Subtotal:** ~1.8 vCPU, ~12.5GB RAM (with caches)
**Mimir Subtotal:** ~0.9 vCPU, ~2GB RAM
**LGTM Total:** ~3 vCPU, ~15GB RAM

### Service Mesh (Istio)

| Component | Replicas | CPU Request | Memory Request | Actual Usage | Purpose |
|-----------|----------|-------------|----------------|--------------|---------|
| istiod | 2 | 400m | 1024Mi | ~6m, ~90Mi | Control plane |
| istio-ingress | 2 | 200m | 256Mi | minimal | Gateway |
| Kiali Server | 1 | 50m | 128Mi | ~10m, ~50Mi | Mesh visualization |
| Kiali Operator | 1 | 10m | 64Mi | ~3m, ~51Mi | CR management |

**Istio Total:** ~0.7 vCPU, ~1.5GB RAM

### Operations Tools

| Component | Replicas | CPU Request | Memory Request | Actual Usage | Purpose |
|-----------|----------|-------------|----------------|--------------|---------|
| Headlamp | 1 | 50m | 64Mi | ~4m, ~59Mi | K8s dashboard |
| Kubecost Analyzer | 1 | 150m | 320Mi | ~4m, ~350Mi | Cost tracking |
| Kubecost Controller | 1 | 50m | 64Mi | minimal | Recommendations |
| Kubecost Forecasting | 1 | 200m | 300Mi | ~1m, ~144Mi | Predictions |
| Kubecost Network | 2 | 100m | 128Mi | minimal | Network costs |
| Velero | 1 | 100m | 128Mi | minimal | Backups |
| Trivy Operator | 1 | 100m | 200Mi | ~5m, ~109Mi | Security scanning |

**Operations Total:** ~0.8 vCPU, ~1.2GB RAM

### System Components (kube-system)

| Component | Replicas | CPU Request | Memory Request | Purpose |
|-----------|----------|-------------|----------------|---------|
| aws-node | 3 (DaemonSet) | 75m | - | VPC CNI |
| kube-proxy | 3 (DaemonSet) | 300m | - | Service routing |
| ebs-csi-controller | 2 | 120m | 480Mi | Volume management |
| ebs-csi-node | 3 (DaemonSet) | 90m | 360Mi | Volume mounts |
| coredns | 2 | 200m | 140Mi | DNS |
| metrics-server | 2 | 200m | 400Mi | Resource metrics |

**System Total:** ~1 vCPU, ~1.4GB RAM

## Total Resource Requirements

| Category | CPU Request | Memory Request |
|----------|-------------|----------------|
| LGTM Stack | ~3.0 vCPU | ~15GB |
| Istio | ~0.7 vCPU | ~1.5GB |
| Operations | ~0.8 vCPU | ~1.2GB |
| System | ~1.0 vCPU | ~1.4GB |
| **TOTAL** | **~5.5 vCPU** | **~19GB** |

**Infrastructure Capacity:** 3x t3a.xlarge = 12 vCPU, 48GB RAM
**Headroom:** ~6.5 vCPU (54%), ~29GB RAM (60%)

## Cost Considerations

### Monthly Estimates (us-east-1)

| Resource | Qty | Unit Cost | Monthly |
|----------|-----|-----------|---------|
| t3a.xlarge nodes | 3 | $0.1504/hr | ~$327 |
| EBS gp3 (100GB/node) | 3 | $0.08/GB | ~$24 |
| EBS gp3 (PVCs ~200GB) | 1 | $0.08/GB | ~$16 |
| NAT Gateway | 3 | $0.045/hr | ~$97 |
| S3 (Velero, Loki) | ~50GB | $0.023/GB | ~$1 |
| **TOTAL** | | | **~$465/mo** |

## Scaling Recommendations

### For Development
- Current: 3x t3a.xlarge ($327/mo compute)
- Minimum viable: 2x t3a.xlarge ($218/mo compute)
- Warning: 2 nodes may cause evictions during updates

### For Production
- Recommended: 5x t3a.xlarge + 3x t3a.xlarge system pool
- With HA: Multi-AZ with 3+ nodes per pool
- Estimated: ~$700-1000/mo compute

## Optimization Opportunities

1. **Loki Caches** - chunks-cache uses 10GB RAM. Consider reducing for dev.
2. **Mimir Kafka** - Using significant resources. Consider disabling WAL in dev.
3. **Grafana HA** - Running 2 replicas. 1 is sufficient for dev.
4. **istiod** - Running 2 replicas with high memory. Reduce to 1 for dev.

## Component Versions (Jan 2025)

| Component | Current | Latest | Status |
|-----------|---------|--------|--------|
| EKS | 1.34 | 1.34 | Current |
| Istio | 1.24+ | 1.24 | Current |
| Loki | 3.x | 3.x | Current |
| Grafana | 11.x | 11.x | Current |
| Mimir | 2.x | 2.x | Current |
| Tempo | 2.x | 2.x | Current |
| Trivy Operator | 0.24+ | 0.24+ | Current |
| Velero | 1.15+ | 1.15+ | Current |
| Kubecost | 2.8.5 | 2.8.5 | Current |
| Headlamp | 0.26+ | 0.26+ | Current |

## Health Check Commands

```bash
# Node resource usage
kubectl top nodes

# Pod resource usage
kubectl top pods -A --sort-by=memory | head -30

# Check all add-ons
aws eks list-addons --cluster-name infra-agent-dev-cluster

# Run API tests
./scripts/test-apis.sh

# Check drift
./scripts/drift-check.sh
```
