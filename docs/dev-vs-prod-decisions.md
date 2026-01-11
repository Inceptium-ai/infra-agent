# Dev vs Prod vs AWS Infrastructure Comparison

This document provides a three-way comparison of infrastructure options:
- **Self-Managed PROD**: Full production-grade, NIST-compliant stack
- **Self-Managed DEV**: Optimized for cost while maintaining architecture parity
- **AWS Managed**: Using AWS native services where comparable alternatives exist

---

## Executive Summary

| Option | Monthly Cost | Pods | Setup Complexity | Vendor Lock-in |
|--------|-------------|------|------------------|----------------|
| **Self-Managed PROD** | ~$593/mo | ~42 | High | None (OSS) |
| **Self-Managed DEV** | ~$249/mo | ~11 | High | None (OSS) |
| **AWS Managed** | ~$362-581/mo | ~5 | Low | High |

**Key Trade-offs:**
- **PROD**: Full control, NIST compliance, predictable costs, operational overhead
- **DEV**: Same architecture at 42% cost reduction, reduced HA
- **AWS**: Lower ops burden, variable costs, limited customization, no Kiali equivalent

---

## Networking & Security

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **VPC CIDR** | Dual (10.0.0.0/16 + 100.64.x.x) | Single CIDR | Same (required) | $0 | $0 | $0 |
| **Availability Zones** | 3 AZs | 1 AZ | 3 AZs (required) | $0 | $0 | $0 |
| **NAT Gateways** | 3 (one per AZ) | 1 | 1-3 | $100 | $35 | $35-100 |
| **Bastion Host** | t3a.medium (SSM) | Skip (public EKS) | SSM-only | $30 | $0 | $0 |
| **Service Mesh** | Istio (mTLS) | Istio (optional) | App Mesh | $0 | $0 | $0 |
| **Private EKS Endpoint** | Private only | Public OK | Private | $0 | $0 | $0 |

**NIST Mapping:**
- SC-7 (Boundary Protection): Non-routable pod subnets, NACLs
- SC-8 (Transmission Confidentiality): Istio mTLS
- AC-2/AU-2 (Audit): SSM Session Manager logs

---

## Compute

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **EKS Control Plane** | Managed | Managed | Managed (required) | $73 | $73 | $73 |
| **Instance Type** | t3a.xlarge (4 vCPU, 16GB) | t3a.medium (2 vCPU, 4GB) | t3a.medium | $110/node | $37/node | $37/node |
| **Node Count** | 3 nodes | 2 nodes | 2 nodes | $330 | $74 | $74 |
| **Node Disk** | 100GB gp3 | 50GB gp2 | 50GB gp2 | $24 | $10 | $10 |
| **Multi-AZ Nodes** | 3 AZs | 1 AZ | 2 AZs | $0 | $0 | $0 |

**NIST Mapping:**
- CP-10 (Recovery): Multi-AZ for AZ failure resilience

---

## Observability - Metrics

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Metrics Scraper** | Prometheus | Prometheus | CloudWatch Agent | $0 | $0 | $0 |
| **Metrics Storage** | Mimir (S3) | Prometheus only | CloudWatch Metrics | $5 | $0 | $50-150 |
| **Mimir Mode** | Distributed + Kafka | Skip Mimir | N/A | +Kafka | $0 | N/A |
| **Mimir Pods** | 15 pods (HA) | 0 | 0 | CPU/RAM | $0 | $0 |
| **Retention** | 15 days local, unlimited S3 | 3 days | 15 months | S3 | Minimal | Per metric |

**AWS Pricing Note:** CloudWatch charges $0.30/metric/month. At scale (1000+ metrics), this can exceed $300/mo.

**NIST Mapping:**
- AU-2 (Audit Events): Prometheus scraping
- AU-11 (Retention): Mimir S3 long-term storage
- AU-9 (Audit Protection): Kafka WAL durability

---

## Observability - Logs

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Log Collector** | Promtail | Promtail | Fluent Bit → CW | $0 | $0 | $0 |
| **Log Storage** | Loki (S3) | Loki (S3) | CloudWatch Logs | $5 | $2 | $50-100 |
| **Loki Mode** | SimpleScalable (10 pods) | SingleBinary (2 pods) | N/A | CPU/RAM | Minimal | $0 |
| **Retention** | 90 days | 7 days | Configurable | S3 | S3 | $0.03/GB |
| **Query Language** | LogQL | LogQL | CW Insights | $0 | $0 | $0.005/GB |

**AWS Pricing Note:** CloudWatch Logs charges $0.50/GB ingested + $0.03/GB storage. At 10GB/day, this is ~$150/mo + query costs.

**NIST Mapping:**
- AU-2 (Audit Events): Centralized log collection
- AU-11 (Retention): 90-day retention for compliance
- SC-28 (Encryption at Rest): S3 server-side encryption

---

## Observability - Tracing

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Tracing Backend** | Tempo (S3) | Tempo (S3) | AWS X-Ray | $5 | $2 | $5-20 |
| **Tempo Replicas** | 2 pods | 1 pod | N/A | CPU/RAM | Minimal | $0 |
| **Retention** | 30 days | 7 days | 30 days | S3 | S3 | Included |
| **Protocols** | OTLP, Jaeger, Zipkin | OTLP | X-Ray SDK | $0 | $0 | $0 |

**AWS Pricing Note:** X-Ray charges $5/million traces recorded + $0.50/million traces scanned.

**Tempo vs Kiali (both deployed):**
| Tool | Purpose | Question it Answers |
|------|---------|---------------------|
| **Tempo** | Distributed tracing | "Why was this ONE request slow?" |
| **Kiali** | Traffic visualization | "How does ALL traffic flow between services?" |

**NIST Mapping:**
- AU-2/AU-6 (Audit Events/Review): Request tracing for debugging
- AU-11 (Retention): 30-day trace history

---

## Observability - Visualization

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Dashboards** | Grafana (2 pods) | Grafana (1 pod) | CloudWatch Dashboards | $0 | $0 | $9 |
| **Traffic Viz** | Kiali (2 pods) | Kiali (1 pod) | **None** | $0 | $0 | N/A |
| **Dashboard Storage** | 10GB PVC | 5GB PVC | Managed | $1 | $0.50 | $0 |

**AWS Pricing Note:** CloudWatch charges $3/dashboard/month. No AWS equivalent for Kiali's Istio traffic visualization.

**NIST Mapping:**
- AU-6 (Audit Review): Grafana dashboards for log/metric review
- SI-4 (System Monitoring): Pre-built observability dashboards

---

## Security & Compliance

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Vuln Scanning** | Trivy Operator (continuous) | Trivy CLI (on-demand) | ECR + Inspector | $0 | $0 | $0* |
| **Image Scanning** | In-cluster + CI/CD | CI/CD only | ECR scan on push | $0 | $0 | $0 |
| **IAM for Pods** | IRSA (all services) | IRSA | IRSA (required) | $0 | $0 | $0 |
| **Encryption Keys** | KMS (customer-managed) | AWS-managed | KMS | $3 | $1 | $1 |
| **Mandatory Tags** | 4 tags enforced | Optional | Same | $0 | $0 | $0 |

**AWS Pricing Note:** *Amazon Inspector has a free tier (90 days). After that, ~$1.25/instance/month for EC2 scanning.

**NIST Mapping:**
- SI-2 (Flaw Remediation): Trivy continuous scanning
- RA-5 (Vulnerability Scanning): Image + config scanning
- AC-6/IA-5 (Least Privilege): IRSA, no long-lived credentials
- SC-28 (Encryption at Rest): KMS encryption
- CM-8 (System Inventory): Mandatory tagging

---

## Backup & DR

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **K8s Backup** | Velero (4 pods) | Skip | AWS Backup | $5 | $0 | $5-10 |
| **Daily Backups** | 7-day retention | Skip | AWS Backup | S3 | $0 | S3 |
| **Weekly Backups** | 30-day retention | Skip | AWS Backup | S3 | $0 | S3 |
| **Cross-Region** | S3 replication | Skip | S3 Cross-Region | $5 | $0 | $5 |
| **PVC Backup** | Node Agent (DaemonSet) | Skip | EBS Snapshots | $0 | $0 | Snapshot cost |

**AWS Pricing Note:** AWS Backup charges based on storage used. EBS snapshots: $0.05/GB/month.

**NIST Mapping:**
- CP-9 (System Backup): Daily/weekly backups
- CP-6 (Alternate Processing Site): Cross-region backup capability

---

## Operations & Cost Management

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Cost Analysis** | Kubecost (4 pods) | Skip | AWS Cost Explorer | $0 | $0 | $0 |
| **Admin Console** | Headlamp (1 pod) | kubectl only | EKS Console | $0 | $0 | $0 |
| **Alerting** | Grafana Alerting | Grafana | CloudWatch Alarms | $0 | $0 | $5 |

**AWS Pricing Note:** CloudWatch Alarms: $0.10/alarm/month. 50 alarms = $5/mo.

**Kubecost vs Cost Explorer:**
| Feature | Kubecost | AWS Cost Explorer |
|---------|----------|-------------------|
| **Granularity** | Pod/namespace level | Account/service level |
| **K8s Native** | Yes | No |
| **Idle Resource Detection** | Yes | No |
| **Cost Allocation** | Label-based | Tag-based |

**NIST Mapping:**
- PM-3 (Cost Management): Kubecost for resource cost visibility

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

## Full Cost Summary

### Architecture Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARCHITECTURE COMPARISON                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SELF-MANAGED PROD (Current)                                                │
│  ────────────────────────────                                               │
│  METRICS:   Prometheus → Mimir → Kafka → S3                                 │
│  LOGS:      Promtail → Loki → S3                                            │
│  TRACES:    Istio → Tempo → S3                                              │
│  DASHBOARDS: Grafana           TRAFFIC: Kiali                               │
│  COST:      Kubecost           SECURITY: Trivy Operator                     │
│  Pods: ~42    |    Cost: ~$593/mo    |    Vendor Lock-in: None              │
│                                                                              │
│  SELF-MANAGED DEV (Optimized)                                               │
│  ───────────────────────────                                                │
│  METRICS:   Prometheus (no Mimir)                                           │
│  LOGS:      Promtail → Loki (SingleBinary) → S3                             │
│  TRACES:    Istio → Tempo → S3                                              │
│  DASHBOARDS: Grafana           TRAFFIC: Kiali                               │
│  COST:      Skip               SECURITY: CI/CD only                         │
│  Pods: ~11    |    Cost: ~$249/mo    |    Vendor Lock-in: None              │
│                                                                              │
│  AWS MANAGED                                                                 │
│  ───────────                                                                │
│  METRICS:   CloudWatch Container Insights                                    │
│  LOGS:      Fluent Bit → CloudWatch Logs                                    │
│  TRACES:    AWS X-Ray                                                        │
│  DASHBOARDS: CloudWatch Dashboards    TRAFFIC: **None**                     │
│  COST:      Cost Explorer             SECURITY: ECR + Inspector             │
│  Pods: ~5     |    Cost: ~$362-581/mo |    Vendor Lock-in: High             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Monthly Cost Breakdown

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MONTHLY COST COMPARISON                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SELF-MANAGED PROD    ████████████████████████████████████  $593/mo         │
│  (42 pods)                    Fixed, predictable costs                      │
│                                                                              │
│  AWS MANAGED          ████████████████████████████████░░░░  $362-581/mo     │
│  (5 pods)                     Variable based on volume                      │
│                                                                              │
│  SELF-MANAGED DEV     ████████████░░░░░░░░░░░░░░░░░░░░░░░░  $249/mo         │
│  (11 pods)                    58% savings vs Prod                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Decision Matrix

| Factor | PROD Wins | DEV Wins | AWS Wins |
|--------|-----------|----------|----------|
| **HA/Resilience** | ✓ | | |
| **NIST Compliance** | ✓ | | |
| **Cost** | | ✓ | |
| **Setup Speed** | | | ✓ |
| **Ops Overhead** | | | ✓ |
| **Query Power (LogQL/PromQL)** | ✓ | ✓ | |
| **Kiali Traffic Viz** | ✓ | ✓ | ✗ |
| **Kubecost (Pod-level)** | ✓ | | |
| **Vendor Lock-in** | None | None | High |
| **Multi-Cloud** | ✓ | ✓ | |

### AWS Managed Prometheus (AMP) + Grafana (AMG)

For teams wanting OSS compatibility with managed infrastructure:

| Volume | AMP + AMG Cost | Self-Managed Cost | Winner |
|--------|---------------|-------------------|--------|
| 3 users, 10M samples/mo | ~$29/mo | ~$5/mo | Self-managed |
| 10 users, 100M samples/mo | ~$105/mo | ~$5/mo | Self-managed |

**AMP/AMG Best For:** Small teams (<5 users), low metric volume (<50M samples/month)

---

## Pod Count Summary

| Component | PROD | DEV | AWS Managed |
|-----------|------|-----|-------------|
| **Mimir** | 15 pods | 0 | 0 (CloudWatch) |
| **Loki** | 10 pods | 2 | 0 (CloudWatch) |
| **Tempo** | 2 pods | 1 | 0 (X-Ray) |
| **Prometheus** | 2 pods | 2 | 0 (CW Agent) |
| **Grafana** | 2 pods | 1 | 0 (CW Dashboards) |
| **Kiali** | 2 pods | 1 | 0 (**No equivalent**) |
| **Velero** | 4 pods | 0 | 0 (AWS Backup) |
| **Kubecost** | 4 pods | 0 | 0 (Cost Explorer) |
| **Trivy** | 1 pod | 0 | 0 (ECR+Inspector) |
| **Fluent Bit** | 0 | 0 | 3 (DaemonSet) |
| **CW Agent** | 0 | 0 | 3 (DaemonSet) |
| **TOTAL** | **~42 pods** | **~7 pods** | **~6 pods** |

---

## Cost Summary

| Category | PROD | DEV | AWS Managed | Notes |
|----------|------|-----|-------------|-------|
| **Infrastructure** | | | | |
| EKS Control Plane | $73 | $73 | $73 | Fixed |
| Compute Nodes | $330 | $74 | $74 | PROD: 3x t3a.xlarge |
| NAT Gateways | $100 | $35 | $35 | PROD: 3 AZs |
| EBS Storage | $50 | $20 | $10 | PVCs |
| S3 Storage | $25 | $7 | $0 | Loki/Mimir/Tempo/Velero |
| | | | | |
| **Observability** | | | | |
| Metrics | $5 | $0 | $50-150 | CW: $0.30/metric |
| Logs | $5 | $2 | $50-100 | CW: $0.50/GB ingest |
| Tracing | $5 | $2 | $5-20 | X-Ray: $5/million |
| Dashboards | $0 | $0 | $9 | CW: $3/dashboard |
| Alerts | $0 | $0 | $5 | CW: $0.10/alarm |
| | | | | |
| **TOTAL** | **~$593/mo** | **~$249/mo** | **~$362-581/mo** | |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial dev vs prod analysis with Kafka recommendation |
| 1.1 | 2025-01-10 | AI Agent | Added three-way cost comparison (AWS vs Prod vs Dev), AMP/AMG pricing |
| 1.2 | 2025-01-10 | AI Agent | Moved Kafka details to architecture.md, removed trade-offs from this doc |
| 1.3 | 2025-01-10 | AI Agent | Added Tempo back for distributed tracing, updated pod/cost counts |
| 2.0 | 2025-01-10 | AI Agent | Major restructure: Dev vs Prod vs AWS three-way comparison with cost columns in all tables |
