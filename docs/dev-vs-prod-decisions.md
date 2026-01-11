# Dev vs Production Infrastructure Decisions

This document captures all infrastructure decisions made for this project, comparing production-grade configurations against dev-appropriate alternatives.

---

## Executive Summary

The current infrastructure was designed with **"Dev = Prod"** parity in mind. While this ensures consistency, it results in higher costs and complexity for a development environment. This document identifies where production-grade decisions were made and provides alternatives for cost optimization.

**Current State:** ~$603/month for dev environment
**Optimized Dev:** ~$253/month (42% reduction)

---

## Networking & Security

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **VPC CIDR Architecture** | Dual CIDR (10.0.0.0/16 + 100.64.0.0/16) | Single CIDR | Defense-in-depth, non-routable pods | SC-7 | +Complexity |
| **Availability Zones** | 3 AZs (us-east-1a/b/c) | 1 AZ | Survive AZ failure | CP-10 | +2 subnets per tier |
| **NAT Gateways** | 3 (one per AZ) | 1 (single AZ) | No single point of failure | SC-7 | +$65/mo |
| **Public Subnets** | 3 (ALB only) | 1 | ALB multi-AZ | SC-7 | Minimal |
| **Private Subnets** | 3 (bastion, NAT, RDS) | 1 | RDS multi-AZ, HA | CP-10 | Minimal |
| **Pod Subnets** | 3 (100.64.x.x non-routable) | Standard VPC subnets | Pods not internet-routable | SC-7 | +Complexity |
| **Istio mTLS** | Enabled (all traffic encrypted) | Disabled | Zero trust, encrypt in transit | SC-8 | +100MB RAM/pod |
| **Private EKS Endpoint** | Private only (no public) | Public (simpler access) | Control plane not internet-exposed | SC-7 | +SSM tunnel |
| **Bastion Host** | t3a.medium in private subnet | Not needed if public EKS | Emergency access, audit trail | AC-2, AU-2 | +$30/mo |
| **SSM Session Manager** | Enabled (no SSH keys) | SSH with keys | No key management, audit logs | IA-5, AU-2 | +IAM complexity |

---

## Compute

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Instance Type** | t3a.xlarge (4 vCPU, 16GB) | t3a.medium (2 vCPU, 4GB) | Handle prod workloads | - | +$150/mo |
| **Node Count** | 3 nodes | 1-2 nodes | HA, workload distribution | CP-10 | +$110/mo per node |
| **Node Min Size** | 2 | 0 | Always-available | - | Can't scale to zero |
| **Node Max Size** | 10 | 3 | Auto-scale for load | - | Same |
| **Disk Size** | 100GB gp3 per node | 50GB gp2 | IOPS consistency | - | +$15/mo per node |
| **Multi-AZ Nodes** | Spread across 3 AZs | Single AZ | Survive AZ failure | CP-10 | PV zone affinity issues |

---

## Observability - Metrics

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Prometheus** | Deployed (scraper) | Sufficient alone for dev | Real-time metrics | AU-2 | Base requirement |
| **Mimir** | Deployed (long-term storage) | Not needed for dev | Historical analysis (months) | AU-11 | +12 pods, S3 |
| **Mimir Mode** | Distributed with Kafka | Monolithic or no Kafka | Durability, horizontal scale | AU-9 | +Kafka, PVC issues |
| **Mimir Ingesters** | 3 zones (a, b, c) | 1 zone | Zone failure resilience | CP-10 | +2 StatefulSets |
| **Mimir Distributors** | 2 replicas | 1 replica | HA | CP-10 | +1 pod |
| **Mimir Queriers** | 2 replicas | 1 replica | Query HA | CP-10 | +1 pod |
| **Mimir Gateway** | 2 replicas | 1 replica | HA | CP-10 | +1 pod |
| **Mimir Cache** | Results + Chunks cache | Disabled | Query performance | - | +2 pods |
| **Prometheus Retention** | 15 days | 3 days | Balance storage/history | AU-11 | Storage cost |

---

## Observability - Logs

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Loki Mode** | SimpleScalable (read/write/backend) | SingleBinary | Horizontal scaling | AU-2 | +6 pods |
| **Loki Read Replicas** | 2 | 1 | Query HA | CP-10 | +1 pod |
| **Loki Write Replicas** | 2 | 1 | Ingest HA | CP-10 | +1 pod |
| **Loki Backend Replicas** | 2 | 1 | Compaction HA | CP-10 | +1 pod |
| **Loki Gateway** | 2 replicas | 1 replica | HA | CP-10 | +1 pod |
| **Loki Retention** | 90 days | 7 days | Audit compliance | AU-11 | S3 storage |
| **Loki Storage** | S3 | Local PVC | Durability, unlimited | SC-28 | S3 cost |

---

## Observability - Tracing

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Tempo** | Deployed (distributed tracing) | Optional for dev | Debug request latency | AU-2, AU-6 | +2 pods, S3 |
| **Tempo Replicas** | 2 | 1 | HA | CP-10 | +1 pod |
| **Tempo Storage** | S3 | Local PVC | Durability, unlimited | SC-28 | S3 cost |
| **Tempo Retention** | 30 days | 7 days | Trace history | AU-11 | S3 storage |
| **Trace Protocols** | OTLP, Jaeger, Zipkin | OTLP only | Legacy compatibility | - | Minimal |

**Tracing vs Traffic Visualization:**
| Tool | Purpose | When to Use |
|------|---------|-------------|
| **Tempo** | Debug ONE request across services | "Why was this request slow?" |
| **Kiali** | See ALL traffic flows (aggregate) | "How does traffic flow between services?" |

---

## Observability - Visualization

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Grafana Replicas** | 2 | 1 | Zero-downtime | CP-10 | +1 pod |
| **Grafana Storage** | 10GB gp3 PVC | 5GB gp2 | Dashboard persistence | - | +$1/mo |
| **Kiali** | Deployed (traffic visualization) | On-demand or skip | Service mesh visibility | AU-6 | +2 pods |
| **Pre-built Dashboards** | 5 dashboards | Create as needed | Immediate visibility | SI-4 | Minimal |

---

## Security & Compliance

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Trivy Operator** | Always running, continuous | On-demand CLI scan | Catch vulns immediately | SI-2, RA-5 | +1 pod |
| **Trivy Scan Scope** | Images, configs, RBAC, secrets | Images only | Comprehensive security | CM-8 | CPU overhead |
| **IRSA for All Services** | Loki, Mimir, Velero | Static credentials | No long-lived credentials | AC-6, IA-5 | +IAM roles |
| **KMS Encryption** | EKS secrets, S3, EBS | Default encryption | Customer-managed keys | SC-28 | +$1/mo per key |
| **Mandatory Tagging** | 4 required tags | Optional | Asset inventory | CM-8 | Enforcement |

---

## Backup & DR

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Velero** | Deployed with schedules | Not deployed | Disaster recovery | CP-9 | +4 pods |
| **Daily Backups** | 2 AM UTC, 7-day retention | Disabled | RPO < 24 hours | CP-9 | S3 storage |
| **Weekly Backups** | Sunday 3 AM, 30-day retention | Disabled | Monthly recovery point | CP-9 | S3 storage |
| **Cross-Region Backup** | Configured (disabled) | Not needed | Regional DR | CP-6 | +S3 replication |
| **Node Agent (fsbackup)** | Deployed on all nodes | Disabled | PVC backup | CP-9 | +3 daemonset pods |

---

## Operations & Cost Management

| Decision | Current Config | Dev Alternative | Prod Requirement | NIST Control | Impact |
|----------|---------------|-----------------|------------------|--------------|--------|
| **Kubecost** | Always running | Not deployed | Cost visibility | PM-3 | +4 pods |
| **Headlamp** | Always running | kubectl only | Web UI for operators | AC-2 | +1 pod |
| **EKS Control Plane** | Always on | Always on (required) | Managed K8s | - | $73/mo fixed |

---

## Kafka in Mimir: Decision (KEPT for Prod Parity)

### What is Kafka's Role in Mimir 3.0?

Mimir 3.0 introduced Kafka as an **ingest write-ahead log (WAL)** between distributors and ingesters:

```
Mimir 2.x (Classic):
  Prometheus → Distributor → Ingester → S3

Mimir 3.0 (With Kafka - Current Config):
  Prometheus → Distributor → Kafka (WAL) → Ingester → S3
```

### Why We Kept Kafka (Prod Parity Decision)

| Benefit | Explanation |
|---------|-------------|
| **Durability** | If an ingester crashes, metrics in Kafka survive and can be replayed |
| **Decoupling** | Distributors don't block waiting for slow ingesters |
| **Horizontal Scaling** | Add/remove ingesters without data loss during rebalancing |
| **Backpressure Handling** | Kafka buffers during load spikes |
| **Exactly-Once Semantics** | Prevents duplicate metrics |
| **NIST AU-9** | Protection of audit information through WAL durability |

### Dev Alternative (If Prod Parity Not Required)

To disable Kafka for simpler dev environment:

```yaml
# mimir-values.yaml
kafka:
  enabled: false

mimir:
  structuredConfig:
    ingest_storage:
      enabled: false
```

---

## AWS Managed Services vs Self-Managed: Full Comparison

This section compares our current self-managed observability stack against using AWS managed services.

### Option A: Current Stack (Self-Managed OSS)

```
┌─────────────────────────────────────────────────────────────────┐
│                    SELF-MANAGED (Current)                        │
├─────────────────────────────────────────────────────────────────┤
│  METRICS:   Prometheus → Mimir → Kafka → S3                     │
│  LOGS:      Promtail → Loki → S3                                │
│  TRACES:    Istio → Tempo → S3                                  │
│  DASHBOARDS: Grafana                                             │
│  TRAFFIC:   Kiali (Istio visualization)                         │
│  COST:      Kubecost                                             │
│  SECURITY:  Trivy Operator                                       │
├─────────────────────────────────────────────────────────────────┤
│  Pods: ~42        Storage: S3 + EBS        Cost: ~$115/mo*      │
│  * Infrastructure cost only, not including compute              │
└─────────────────────────────────────────────────────────────────┘
```

### Option B: AWS CloudWatch + Container Insights

```
┌─────────────────────────────────────────────────────────────────┐
│                    AWS MANAGED ALTERNATIVE                       │
├─────────────────────────────────────────────────────────────────┤
│  METRICS:   CloudWatch Container Insights                        │
│  LOGS:      CloudWatch Logs (Fluent Bit → CW)                   │
│  TRACES:    AWS X-Ray                                            │
│  DASHBOARDS: CloudWatch Dashboards                               │
│  TRAFFIC:   (None - no Istio visualization)                     │
│  COST:      AWS Cost Explorer                                    │
│  SECURITY:  Amazon Inspector + ECR Scanning                      │
├─────────────────────────────────────────────────────────────────┤
│  Pods: ~5         Storage: CloudWatch       Cost: ~$150-300/mo* │
│  * Varies significantly with log/metric volume                  │
└─────────────────────────────────────────────────────────────────┘
```

### Detailed Comparison Table

| Capability | Current (Self-Managed) | AWS Managed | Dev Alternative |
|------------|----------------------|-------------|-----------------|
| **Metrics Collection** | Prometheus (scrape) | CloudWatch Agent + Container Insights | CloudWatch (simpler) |
| **Metrics Storage** | Mimir (S3-backed, unlimited) | CloudWatch Metrics (15mo retention) | CloudWatch (managed) |
| **Metrics Cost** | S3 storage (~$5/mo) | $0.30/metric/month (can explode) | CloudWatch basic |
| **Log Collection** | Loki + Promtail | CloudWatch Logs + Fluent Bit | CloudWatch (managed) |
| **Log Storage** | S3 (~$5/mo for 90 days) | $0.50/GB ingestion + $0.03/GB storage | CloudWatch |
| **Log Retention** | 90 days (configurable) | Configurable (costs scale) | 7 days (cheaper) |
| **Log Query** | LogQL (powerful) | CloudWatch Insights ($0.005/GB scanned) | Basic |
| **Dashboards** | Grafana (powerful, customizable) | CloudWatch Dashboards (limited) | CloudWatch |
| **Alerting** | Grafana Alerting | CloudWatch Alarms | CloudWatch |
| **Traffic Visualization** | Kiali (real-time Istio mesh) | None (no equivalent) | Skip |
| **Distributed Tracing** | Tempo (S3-backed) | X-Ray ($5/million traces) | X-Ray or skip |
| **Cost Analysis** | Kubecost (K8s-native) | AWS Cost Explorer (account-level) | Cost Explorer |
| **Security Scanning** | Trivy Operator (continuous) | ECR scanning + Inspector | ECR basic |
| **Setup Complexity** | High (many Helm charts) | Low (enable features) | Low |
| **Operational Overhead** | High (manage pods, PVCs) | Low (AWS managed) | Low |
| **Customization** | Full control | Limited to AWS features | Limited |
| **Vendor Lock-in** | None (OSS) | High (AWS-specific) | High |
| **Multi-Cloud** | Yes (portable) | No (AWS only) | No |

### Three-Way Cost Comparison

| Component | AWS Managed | Self-Managed PROD | Self-Managed DEV | Notes |
|-----------|-------------|-------------------|------------------|-------|
| **EKS Control Plane** | $73 | $73 | $73 | Fixed cost, all options |
| **Compute Nodes** | $110 (2x t3a.medium) | $330 (3x t3a.xlarge) | $110 (2x t3a.medium) | Fewer pods = smaller nodes |
| **NAT Gateways** | $35 (1 AZ) | $100 (3 AZ) | $35 (1 AZ) | HA requires multi-AZ |
| **EBS Storage** | $10 | $50 | $20 | PVCs for stateful workloads |
| **S3 Storage** | $0 | $25 | $7 | Loki/Mimir/Tempo/Velero buckets |
| | | | | |
| **--- Observability ---** | | | | |
| **Metrics Storage** | $50-150 (CW Metrics) | $5 (Mimir→S3) | $0 (Prometheus only) | CW: $0.30/metric/mo |
| **Metrics Collection** | $0 (CW Agent) | $0 (Prometheus) | $0 (Prometheus) | Agent vs scraper |
| **Log Ingestion** | $50-100 (CW Logs) | $0 (Loki) | $0 (Loki) | CW: $0.50/GB ingested |
| **Log Storage** | $10-30 (CW Logs) | $5 (S3) | $2 (S3, 7 days) | CW: $0.03/GB/mo |
| **Log Queries** | $5-20 (CW Insights) | $0 (LogQL) | $0 (LogQL) | CW: $0.005/GB scanned |
| **Dashboards** | $9 (3 dashboards) | $0 (Grafana) | $0 (Grafana) | CW: $3/dashboard/mo |
| **Alerts** | $5 (50 alarms) | $0 (Grafana) | $0 (Grafana) | CW: $0.10/alarm/mo |
| **Tracing** | $5-20 (X-Ray) | $5 (Tempo→S3) | $2 (Tempo→S3) | X-Ray: $5/million traces |
| | | | | |
| **--- Optional Tools ---** | | | | |
| **Traffic Viz (Kiali)** | N/A | $0 (included) | $0 or skip | No AWS equivalent |
| **Cost Analysis** | $0 (Cost Explorer) | $0 (Kubecost) | $0 (Cost Explorer) | Kubecost = K8s-native |
| **Security Scanning** | $0 (ECR + Inspector) | $0 (Trivy) | $0 (ECR basic) | Inspector: free tier |
| **Backup (Velero)** | $0 (not needed) | $5 (S3) | $0 (skip) | AWS Backup alternative |
| | | | | |
| **--- TOTALS ---** | | | | |
| **Infrastructure** | **$228** | **$578** | **$245** | Nodes + NAT + Storage |
| **Observability** | **$134-353** | **$15** | **$4** | Variable vs fixed |
| **GRAND TOTAL** | **$362-581/mo** | **$593/mo** | **$249/mo** | |

### Cost Comparison Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MONTHLY COST COMPARISON                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  AWS MANAGED          ████████████████████████████████░░░░  $362-581/mo     │
│  (CW + Container Insights)    Variable based on log/metric volume           │
│                                                                              │
│  SELF-MANAGED PROD    ████████████████████████████████████  $593/mo         │
│  (Current Config)             Fixed, predictable costs                      │
│                                                                              │
│  SELF-MANAGED DEV     ████████████░░░░░░░░░░░░░░░░░░░░░░░░  $245/mo         │
│  (Optimized)                  42% savings vs Prod                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### AWS Managed Prometheus (AMP) + Managed Grafana (AMG) Option

For teams wanting OSS compatibility with AWS management:

| Component | AMP + AMG | Self-Managed | Notes |
|-----------|-----------|--------------|-------|
| **Amazon Managed Prometheus** | $0.10/million samples ingested + $0.03/GB storage | $5/mo (Mimir→S3) | AMP can get expensive at scale |
| **Amazon Managed Grafana** | $9/editor/mo + $5/viewer/mo | $0 (self-hosted) | Per-user pricing |
| **Example: 3 users, 10M samples/mo** | $27 + $1 + $1 = **$29/mo** | **$5/mo** | AMP cheaper at low volume |
| **Example: 10 users, 100M samples/mo** | $90 + $10 + $5 = **$105/mo** | **$5/mo** | Self-managed wins at scale |

**AMP/AMG Best For:**
- Small teams (<5 users)
- Low metric volume (<50M samples/month)
- Teams wanting Grafana without managing pods
- Hybrid: AMP for storage, self-hosted Grafana for dashboards

### Decision Matrix

| Factor | Self-Managed Wins | AWS Managed Wins |
|--------|------------------|------------------|
| **Cost at Scale** | ✓ (predictable S3 costs) | |
| **Setup Speed** | | ✓ (enable and go) |
| **Operational Overhead** | | ✓ (no pods to manage) |
| **Query Power** | ✓ (LogQL, PromQL) | |
| **Customization** | ✓ (full control) | |
| **Dashboard Flexibility** | ✓ (Grafana) | |
| **Multi-Cloud/Portability** | ✓ (OSS) | |
| **Istio Traffic Visualization** | ✓ (Kiali) | (no equivalent) |
| **K8s-Native Cost Analysis** | ✓ (Kubecost) | |
| **Low Volume Dev** | | ✓ (simpler) |
| **Compliance Familiarity** | | ✓ (AWS artifacts) |

### Why We Chose Self-Managed

1. **Production Parity**: Dev matches prod architecture
2. **Cost Control**: Predictable S3 costs vs variable CloudWatch
3. **Query Power**: LogQL and PromQL are more powerful than CloudWatch Insights
4. **Grafana Flexibility**: Custom dashboards, multiple data sources
5. **Kiali**: Real-time Istio traffic visualization (no AWS equivalent)
6. **Kubecost**: Kubernetes-native cost analysis (namespace/pod level)
7. **No Vendor Lock-in**: Portable to any cloud
8. **NIST Compliance**: Full control over audit log retention and protection

### When to Consider AWS Managed (Dev Simplification)

| Scenario | Recommendation |
|----------|----------------|
| Quick prototype, <1 week | CloudWatch + Container Insights |
| Cost-sensitive, low volume | CloudWatch (fewer pods) |
| Team unfamiliar with Grafana | CloudWatch Dashboards |
| No Istio/service mesh | CloudWatch (Kiali not needed) |
| Single AWS account | CloudWatch (simpler) |
| Multi-cloud or hybrid | Self-managed (portability) |
| High log volume (>100GB/day) | Self-managed (cost) |
| Advanced queries needed | Self-managed (LogQL/PromQL) |

### Hybrid Option (Best of Both)

```
┌─────────────────────────────────────────────────────────────────┐
│                    HYBRID APPROACH                               │
├─────────────────────────────────────────────────────────────────┤
│  METRICS:   Prometheus → CloudWatch (via remote_write)          │
│  LOGS:      CloudWatch Logs (simple) + Loki (advanced)          │
│  DASHBOARDS: Grafana (queries both CW and Loki/Prometheus)      │
│  TRAFFIC:   Kiali (keep for Istio)                              │
│  COST:      AWS Cost Explorer + Kubecost                        │
├─────────────────────────────────────────────────────────────────┤
│  Benefit: AWS managed storage + Grafana flexibility             │
│  Drawback: More complex, two systems to manage                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pod Count Summary

| Category | Prod-Grade | Dev-Optimized | Reduction |
|----------|-----------|---------------|-----------|
| **Mimir** | 15+ pods | 0 or 5 (no Kafka) | 10-15 pods |
| **Loki** | 10+ pods | 2 (SingleBinary) | 8 pods |
| **Tempo** | 2 pods | 1 pod | 1 pod |
| **Grafana** | 2 pods | 1 pod | 1 pod |
| **Velero** | 4 pods | 0 | 4 pods |
| **Kiali** | 2 pods | 1 pod | 1 pod |
| **Kubecost** | 4 pods | 0 | 4 pods |
| **Trivy** | 1 pod | 0 | 1 pod |
| **Total** | ~42 pods | ~11 pods | ~31 pods |

---

## Cost Summary

| Item | Prod-Grade | Dev-Optimized | Savings |
|------|-----------|---------------|---------|
| EKS Control Plane | $73 | $73 | $0 |
| Nodes (3x t3a.xlarge) | $330 | $110 (2x t3a.medium) | $220 |
| NAT Gateways (3) | $100 | $35 (1) | $65 |
| EBS Storage | $50 | $20 | $30 |
| S3 (Loki/Mimir/Tempo/Velero) | $25 | $7 | $18 |
| Data Transfer | $30 | $10 | $20 |
| **Total** | **~$608/mo** | **~$255/mo** | **~$353/mo** |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial dev vs prod analysis with Kafka recommendation |
| 1.1 | 2025-01-10 | AI Agent | Added three-way cost comparison (AWS vs Prod vs Dev), AMP/AMG pricing |
| 1.2 | 2025-01-10 | AI Agent | Moved Kafka details to architecture.md, removed trade-offs from this doc |
| 1.3 | 2025-01-10 | AI Agent | Added Tempo back for distributed tracing, updated pod/cost counts |
