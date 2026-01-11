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

## Kafka in Mimir: Analysis & Recommendation

### What is Kafka's Role in Mimir 3.0?

Mimir 3.0 introduced Kafka as an **ingest write-ahead log (WAL)** between distributors and ingesters:

```
Mimir 2.x (Classic):
  Prometheus → Distributor → Ingester → S3

Mimir 3.0 (With Kafka):
  Prometheus → Distributor → Kafka → Ingester → S3
```

### Why Grafana Added Kafka

| Benefit | Explanation |
|---------|-------------|
| **Durability** | If an ingester crashes, metrics in Kafka survive and can be replayed |
| **Decoupling** | Distributors don't block waiting for slow ingesters |
| **Horizontal Scaling** | Add/remove ingesters without data loss during rebalancing |
| **Backpressure Handling** | Kafka buffers during load spikes |
| **Exactly-Once Semantics** | Prevents duplicate metrics |

### Why Kafka is Problematic for Dev

| Issue | Impact |
|-------|--------|
| **StatefulSet with PVC** | EBS volumes are AZ-bound; when nodes scale to 0 and back, PVs can't reattach to nodes in different AZs |
| **Memory Requirements** | Kafka needs ~1GB+ RAM minimum |
| **Additional Complexity** | One more component to monitor and troubleshoot |
| **Overkill for Dev** | Durability during ingester crashes is a prod concern, not dev |
| **Current Status** | `mimir-kafka-0` is Pending due to PV node affinity mismatch |

### Current Failure Cascade

```
mimir-kafka-0: Pending (PV stuck on old node AZ)
    ↓
mimir-distributor: CrashLoopBackOff (can't connect to Kafka)
    ↓
mimir-ingester: CrashLoopBackOff (can't connect to Kafka)
    ↓
mimir-querier: CrashLoopBackOff (no ingesters available)
    ↓
Mimir: Non-functional
```

### Recommendation: Disable Kafka for Dev

**Action:** Reconfigure Mimir to use classic ingestion path (no Kafka)

**Helm Values Change:**
```yaml
mimir:
  structuredConfig:
    # Disable Kafka-based ingestion
    ingest_storage:
      enabled: false

    # Use classic ingester configuration
    ingester:
      ring:
        replication_factor: 1  # Dev doesn't need 3-way replication
```

**Benefits:**
- Eliminates Kafka pod and its PVC issues
- Reduces memory footprint by ~1GB
- Simpler architecture for dev
- Still maintains prod-like architecture (just without WAL durability)

**Trade-offs:**
- If ingester crashes during write, those metrics are lost (acceptable for dev)
- No backpressure buffering (dev workloads are light)

### Alternative Options

| Option | Effort | Result |
|--------|--------|--------|
| **1. Disable Kafka (Recommended)** | Low | Classic ingestion, fixes immediately |
| **2. Delete stuck PVCs** | Medium | Kafka restarts, may recur on next scale-to-zero |
| **3. Use single-AZ for dev** | High | Prevents PV affinity issues but limits HA |
| **4. Remove Mimir entirely** | Low | Use Prometheus only (15-day retention) |

### Implementation Steps

To disable Kafka:

```bash
# 1. Update mimir-values.yaml
# Add ingest_storage.enabled: false

# 2. Upgrade Helm release
helm upgrade mimir grafana/mimir-distributed \
  -n observability \
  -f infra/helm/values/lgtm/mimir-values.yaml

# 3. Delete stuck Kafka resources
kubectl delete statefulset mimir-kafka -n observability
kubectl delete pvc kafka-data-mimir-kafka-0 -n observability
```

---

## Pod Count Summary

| Category | Prod-Grade | Dev-Optimized | Reduction |
|----------|-----------|---------------|-----------|
| **Mimir** | 15+ pods | 0 or 5 (no Kafka) | 10-15 pods |
| **Loki** | 10+ pods | 2 (SingleBinary) | 8 pods |
| **Grafana** | 2 pods | 1 pod | 1 pod |
| **Velero** | 4 pods | 0 | 4 pods |
| **Kiali** | 2 pods | 1 pod | 1 pod |
| **Kubecost** | 4 pods | 0 | 4 pods |
| **Trivy** | 1 pod | 0 | 1 pod |
| **Total** | ~40 pods | ~10 pods | ~30 pods |

---

## Cost Summary

| Item | Prod-Grade | Dev-Optimized | Savings |
|------|-----------|---------------|---------|
| EKS Control Plane | $73 | $73 | $0 |
| Nodes (3x t3a.xlarge) | $330 | $110 (2x t3a.medium) | $220 |
| NAT Gateways (3) | $100 | $35 (1) | $65 |
| EBS Storage | $50 | $20 | $30 |
| S3 (Loki/Mimir/Velero) | $20 | $5 | $15 |
| Data Transfer | $30 | $10 | $20 |
| **Total** | **~$603/mo** | **~$253/mo** | **~$350/mo** |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial dev vs prod analysis with Kafka recommendation |
