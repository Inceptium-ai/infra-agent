# Dev vs Prod vs AWS Infrastructure Comparison

This document provides a three-way comparison of infrastructure options:
- **Self-Managed PROD**: Full production-grade, NIST-compliant stack
- **Self-Managed DEV**: Optimized for cost while maintaining architecture parity
- **AWS Managed**: Using AWS native services where comparable alternatives exist

---

## Executive Summary

| Option | Monthly Cost | Pods | Setup Complexity | Vendor Lock-in | Agent-Ready |
|--------|-------------|------|------------------|----------------|-------------|
| **Self-Managed PROD** | ~$593/mo | ~42 | High | None (OSS) | ✅ Full |
| **Self-Managed DEV** | ~$249/mo | ~11 | High | None (OSS) | ✅ Full |
| **Agent-Optimized Hybrid** | ~$380-520/mo | ~14 | Medium | Medium | ✅ Full |
| **AWS Managed** | ~$362-581/mo | ~9 | Low | High | ⚠️ Basic |

**Stack Descriptions:**
- **AWS Managed**: CloudWatch Observability add-on only (9 DaemonSet pods)
- **Agent-Optimized Hybrid**: CloudWatch + Istio + Mini Prometheus (no UIs, full API access)

**Key Trade-offs:**
- **PROD**: Full control, NIST compliance, predictable costs, operational overhead
- **DEV**: Same architecture at 42% cost reduction, reduced HA
- **Agent-Optimized**: AI-first design, no UIs, full observability APIs, Istio mTLS
- **AWS**: Lowest ops burden, variable costs, limited agent capabilities (no request metrics)

---

## Unified Observability Platform Comparison (Free/OSS Only)

This section compares all FREE observability platform options. **No enterprise/paid tiers included.**

### Platform Options

| Platform | License | Components | Storage Backend |
|----------|---------|------------|-----------------|
| **LGTM + Istio** | Apache 2.0 | Loki, Grafana, Tempo, Mimir, Prometheus, Istio, Keycloak | S3 |
| **SigNoz + Istio** | MIT/Apache | SigNoz, ClickHouse, OTEL Collector, Istio, Cognito | ClickHouse + S3 |
| **OpenSearch + Istio** | Apache 2.0 | OpenSearch, Data Prepper, Fluent Bit, Istio, Cognito | OpenSearch + S3 |
| **AWS CW + Istio + Mini Prom** | N/A | CloudWatch, Fluent Bit, ADOT, Mini Prometheus, Istio | CloudWatch + S3 |
| **Splunk Free + Istio** | Proprietary | Splunk Free, Istio | Local disk |

### Architecture Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED OBSERVABILITY PLATFORMS                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LGTM + Istio (Current)           SigNoz + Istio                            │
│  ─────────────────────            ──────────────                            │
│  ┌─────┐┌─────┐┌─────┐           ┌─────────────────┐                       │
│  │Loki ││Tempo││Mimir│           │    ClickHouse   │                       │
│  └──┬──┘└──┬──┘└──┬──┘           │(Logs+Metrics+   │                       │
│     └──────┼──────┘              │    Traces)      │                       │
│            ▼                      └────────┬────────┘                       │
│     ┌──────────┐                          ▼                                 │
│     │ Grafana  │                   ┌──────────┐                             │
│     └──────────┘                   │ SigNoz UI│                             │
│  Pods: 38-43                       └──────────┘                             │
│  Separate UIs                      Pods: 16-18                              │
│                                    Unified UI                               │
│                                                                              │
│  OpenSearch + Istio               AWS CW + Istio + Mini Prom                │
│  ──────────────────               ──────────────────────────                │
│  ┌─────────────────┐              ┌─────────┐ ┌─────────┐                  │
│  │   OpenSearch    │              │CloudWatch│ │Mini Prom│                  │
│  │(Logs+Metrics+   │              │(Logs+Met)│ │(Istio)  │                  │
│  │    Traces)      │              └────┬─────┘ └────┬────┘                  │
│  └────────┬────────┘                   │            │                       │
│           ▼                            └─────┬──────┘                       │
│  ┌─────────────────┐                        ▼                               │
│  │   OS Dashboards │               ┌──────────────┐                         │
│  └─────────────────┘               │   AI Agent   │                         │
│  Pods: 18-20                       │  (API only)  │                         │
│  Unified UI                        └──────────────┘                         │
│                                    Pods: 14-16                              │
│                                    No human UI                              │
│                                                                              │
│  Splunk Free + Istio                                                        │
│  ───────────────────                                                        │
│  ┌─────────────────┐                                                        │
│  │  Splunk Free    │  ⚠️ 500 MB/day limit                                   │
│  │  (Single node)  │  ⚠️ No authentication                                  │
│  └────────┬────────┘  ⚠️ No alerting                                        │
│           ▼           ⚠️ No HA/clustering                                   │
│  ┌─────────────────┐                                                        │
│  │   Splunk UI     │  ❌ NOT VIABLE for production                          │
│  └─────────────────┘                                                        │
│  Pods: 3-5                                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Feature Comparison

| Feature | LGTM + Istio | SigNoz + Istio | OpenSearch + Istio | AWS CW Hybrid | Splunk Free |
|---------|--------------|----------------|--------------------| --------------|-------------|
| **License** | Apache 2.0 | MIT/Apache | Apache 2.0 | Proprietary | Proprietary |
| **Data Limit** | ✅ Unlimited | ✅ Unlimited | ✅ Unlimited | ✅ Unlimited | ❌ 500MB/day |
| **Logs** | ✅ Loki | ✅ ClickHouse | ✅ OpenSearch | ✅ CloudWatch | ✅ Yes |
| **Metrics** | ✅ Mimir | ✅ ClickHouse | ✅ OpenSearch | ✅ CW + Prom | ✅ Yes |
| **Traces** | ✅ Tempo | ✅ ClickHouse | ✅ OpenSearch | ⚠️ X-Ray (sampled) | ❌ No |
| **Unified UI** | ❌ Separate | ✅ Single | ✅ Single | ❌ No UI | ✅ Single |
| **Service Map** | ✅ Kiali | ✅ Built-in | ✅ Built-in | ❌ No | ❌ No |
| **Alerting** | ✅ Grafana | ✅ Built-in | ✅ Built-in | ✅ CW Alarms | ❌ No |
| **Authentication** | ✅ Keycloak | ✅ Cognito | ✅ Cognito | ✅ Cognito | ❌ None |
| **MFA** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |
| **RBAC** | ✅ Full | ⚠️ Basic | ✅ Full | ✅ IAM | ❌ No |
| **HA/Clustering** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |
| **mTLS (Istio)** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |

### Query Language Comparison

| Platform | Logs | Metrics | Traces | Power |
|----------|------|---------|--------|-------|
| **LGTM** | LogQL | PromQL | TraceQL | ✅ Excellent |
| **SigNoz** | SQL | SQL | SQL | ✅ Excellent |
| **OpenSearch** | DSL/SQL | PPL/DSL | DSL | ✅ Good |
| **AWS CW Hybrid** | CW Insights | PromQL + CW | X-Ray filter | ⚠️ Mixed |
| **Splunk Free** | SPL | SPL | N/A | ⚠️ Limited (no alerting) |

### Resource Requirements

| Platform | Pods | CPU Request | Memory Request | Storage |
|----------|------|-------------|----------------|---------|
| **LGTM + Istio** | 38-43 | ~5.5 vCPU | ~19 GB | ~50 GB PVC + S3 |
| **SigNoz + Istio** | 16-18 | ~2.5 vCPU | ~8 GB | ~100 GB PVC |
| **OpenSearch + Istio** | 18-20 | ~3 vCPU | ~12 GB | ~100 GB PVC |
| **AWS CW Hybrid** | 14-16 | ~1.5 vCPU | ~4 GB | ~10 GB PVC |
| **Splunk Free + Istio** | 8-10 | ~1 vCPU | ~4 GB | ~50 GB PVC |

### Cost Comparison (Monthly)

| Cost Factor | LGTM + Istio | SigNoz + Istio | OpenSearch + Istio | AWS CW Hybrid | Splunk Free |
|-------------|--------------|----------------|--------------------| --------------|-------------|
| Compute (pods) | ~$100 | ~$40 | ~$50 | ~$30 | ~$20 |
| Storage (PVC) | ~$10 | ~$20 | ~$20 | ~$5 | ~$10 |
| S3/Backend | ~$15 | ~$10 | ~$15 | ~$0 | ~$0 |
| Auth (Keycloak/Cognito) | ~$15 | ~$5 | ~$5 | ~$5 | ~$0 |
| CloudWatch costs | ~$0 | ~$0 | ~$0 | ~$100-200 | ~$0 |
| **TOTAL** | **~$140/mo** | **~$75/mo** | **~$90/mo** | **~$140-240/mo** | **~$30/mo** |

*Note: Costs exclude Istio overhead (~$20/mo) which is common to all options.*

### NIST 800-53 Compliance (Free Versions Only)

| Control | LGTM | SigNoz | OpenSearch | AWS CW Hybrid | Splunk Free |
|---------|------|--------|------------|---------------|-------------|
| **AC-2** (Account Mgmt) | ✅ | ✅ | ✅ | ✅ | ❌ No users |
| **AC-3** (RBAC) | ✅ | ⚠️ Basic | ✅ | ✅ | ❌ No RBAC |
| **AC-6** (Least Privilege) | ✅ | ✅ | ✅ | ✅ | ❌ |
| **AU-2** (Audit Events) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **AU-6** (Audit Review) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **AU-9** (Audit Protection) | ✅ | ⚠️ | ✅ | ✅ | ❌ |
| **AU-11** (Retention) | ✅ | ✅ | ✅ | ✅ | ⚠️ Limited |
| **CP-9** (Backup) | ✅ | ⚠️ Manual | ✅ | ✅ | ❌ No |
| **CP-10** (HA/Recovery) | ✅ | ✅ | ✅ | ✅ | ❌ No HA |
| **IA-2** (Authentication) | ✅ | ✅ | ✅ | ✅ | ❌ None |
| **IA-2(1)** (MFA) | ✅ | ✅ | ✅ | ✅ | ❌ None |
| **SC-7** (Boundary) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **SC-8** (mTLS) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **SC-28** (Encrypt Rest) | ✅ | ⚠️ Config | ✅ | ✅ | ⚠️ |
| **SI-2** (Vuln Scan) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **SI-4** (Monitoring) | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| **PM-3** (Cost Tracking) | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| | | | | | |
| **FULL (✅)** | **33** | **28** | **31** | **31** | **8** |
| **PARTIAL (⚠️)** | **0** | **4** | **0** | **2** | **3** |
| **GAP (❌)** | **0** | **1** | **2** | **0** | **22** |
| **TOTAL SCORE** | **33/33** | **28/33** | **31/33** | **31/33** | **8/33** |

### Weighted Score Analysis

| Category (Weight) | LGTM | SigNoz | OpenSearch | AWS CW Hybrid | Splunk Free |
|-------------------|------|--------|------------|---------------|-------------|
| **Compliance (25%)** | 25 | 21 | 23 | 23 | 6 |
| **Unified UI (15%)** | 8 | 15 | 15 | 0 | 10 |
| **Query Power (10%)** | 10 | 10 | 8 | 6 | 5 |
| **Agent-Ready (15%)** | 12 | 15 | 12 | 15 | 5 |
| **Resource Efficiency (10%)** | 4 | 8 | 7 | 9 | 10 |
| **Operational Simplicity (10%)** | 4 | 7 | 6 | 9 | 8 |
| **Performance (5%)** | 4 | 5 | 4 | 4 | 3 |
| **Cost (5%)** | 3 | 5 | 4 | 3 | 5 |
| **Features (5%)** | 5 | 4 | 4 | 3 | 1 |
| | | | | | |
| **TOTAL SCORE** | **75/100** | **90/100** | **83/100** | **72/100** | **53/100** |

### Executive Recommendation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PLATFORM RECOMMENDATION SUMMARY                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  OVERALL SCORES:                                                            │
│  ───────────────                                                            │
│                                                                              │
│  1. SigNoz + Istio         ████████████████████████████████████  90/100    │
│     Best overall: unified UI, low cost, good compliance                     │
│                                                                              │
│  2. OpenSearch + Istio     █████████████████████████████████     83/100    │
│     Best for: AWS integration option, full compliance                       │
│                                                                              │
│  3. LGTM + Istio           ██████████████████████████████        75/100    │
│     Best for: maximum compliance (33/33), full features                     │
│                                                                              │
│  4. AWS CW + Mini Prom     ████████████████████████████          72/100    │
│     Best for: AI agent-only (no human UI needed)                            │
│                                                                              │
│  5. Splunk Free            █████████████████                     53/100    │
│     NOT RECOMMENDED: 500MB/day limit, no auth, no HA                        │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  RECOMMENDATION BY USE CASE:                                                │
│  ───────────────────────────                                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ "We need 100% NIST compliance"                                       │   │
│  │  → LGTM + Istio (33/33 controls)                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ "We want unified UI + best value"                                    │   │
│  │  → SigNoz + Istio (90/100 score, ~$75/mo)                           │   │
│  │    Accept: Basic RBAC (AC-3), no access audit log (AU-9)            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ "We want unified UI + better compliance"                             │   │
│  │  → OpenSearch + Istio (83/100 score, 31/33 controls)                │   │
│  │    Option: Use Amazon OpenSearch Service for managed                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ "AI agent is primary operator, humans rarely need UI"                │   │
│  │  → AWS CW + Istio + Mini Prometheus (72/100 score)                  │   │
│  │    Best for: API-first, AWS-native, minimal pods                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ "We want to use Splunk"                                              │   │
│  │  → ❌ NOT RECOMMENDED (Splunk Free has critical limitations)        │   │
│  │    500MB/day limit, no auth, no alerting, no HA = NOT VIABLE        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  FINAL RECOMMENDATION:                                                      │
│  ─────────────────────                                                      │
│                                                                              │
│  For most use cases: SigNoz + Istio + Cognito                              │
│                                                                              │
│  • Highest overall score (90/100)                                          │
│  • Unified UI for logs, metrics, traces                                    │
│  • Lowest pod count (16-18 vs 38-43)                                       │
│  • Lowest cost (~$75/mo vs $140/mo)                                        │
│  • 28/33 NIST controls (acceptable for most non-FedRAMP workloads)        │
│  • ClickHouse provides excellent query performance                         │
│  • Single SQL API for AI agent integration                                 │
│                                                                              │
│  Gaps to accept or mitigate:                                               │
│  • AC-3: Basic RBAC (Admin/Viewer) - usually sufficient                   │
│  • AU-9: No access audit trail - document as accepted risk                │
│  • Add Velero for backup (CP-9)                                           │
│  • Configure ClickHouse encryption (SC-28)                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Splunk Free Limitations (Why NOT Recommended)

| Limitation | Impact | Severity |
|------------|--------|----------|
| **500 MB/day data limit** | Stops indexing after ~2 hours with typical cluster | 🔴 Critical |
| **No authentication** | Anyone can access all data | 🔴 Critical |
| **No alerting** | Cannot detect or notify on issues | 🔴 Critical |
| **No clustering/HA** | Single point of failure | 🔴 Critical |
| **No RBAC** | No access control | 🔴 Critical |
| **No distributed search** | Cannot scale | 🟡 High |
| **No SSO/OIDC** | Cannot integrate with Cognito/Keycloak | 🟡 High |

**Verdict:** Splunk Free is suitable only for local development/testing, NOT for any production or compliance-required environment.

---

## AWS CloudWatch Observability EKS Add-on

The **Amazon CloudWatch Observability EKS Add-on** is the AWS-managed observability solution. It's a hybrid approach that deploys lightweight agents in your cluster that forward data to fully managed AWS services.

### Add-on Components (Deployed in EKS)

| Component | Deployment Type | Pods (3-node cluster) | CPU Request | Memory Request |
|-----------|----------------|----------------------|-------------|----------------|
| **CloudWatch Agent** | DaemonSet | 3 (1 per node) | 50m/pod | 200Mi/pod |
| **Fluent Bit** | DaemonSet | 3 (1 per node) | 50m/pod | 100Mi/pod |
| **ADOT Collector** | DaemonSet | 3 (1 per node) | 100m/pod | 256Mi/pod |
| **TOTAL** | | **6-9 pods** | **~600m** | **~1.7Gi** |

**Note:** ADOT (AWS Distro for OpenTelemetry) Collector is optional - only needed if using X-Ray tracing.

### Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CLOUDWATCH OBSERVABILITY ADD-ON                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  IN-CLUSTER (EKS Pods)                    AWS MANAGED (No Pods)             │
│  ─────────────────────                    ─────────────────────             │
│                                                                              │
│  ┌─────────────────┐                      ┌─────────────────┐               │
│  │ CloudWatch Agent│ ────────────────────►│ CloudWatch      │               │
│  │   (DaemonSet)   │      Metrics         │ Metrics         │               │
│  └─────────────────┘                      │ Container       │               │
│         │                                 │ Insights        │               │
│         │ Scrapes kubelet,                └─────────────────┘               │
│         │ cAdvisor, kube-state                                              │
│                                                                              │
│  ┌─────────────────┐                      ┌─────────────────┐               │
│  │   Fluent Bit    │ ────────────────────►│ CloudWatch Logs │               │
│  │   (DaemonSet)   │      Logs            │                 │               │
│  └─────────────────┘                      └─────────────────┘               │
│         │                                                                    │
│         │ Tails /var/log/pods                                               │
│                                                                              │
│  ┌─────────────────┐                      ┌─────────────────┐               │
│  │ ADOT Collector  │ ────────────────────►│    AWS X-Ray    │               │
│  │   (DaemonSet)   │      Traces          │                 │               │
│  └─────────────────┘                      └─────────────────┘               │
│         │                                         │                         │
│         │ OTLP receiver                           │                         │
│                                           ┌───────▼─────────┐               │
│                                           │   CloudWatch    │               │
│                                           │   Dashboards    │               │
│                                           └─────────────────┘               │
│                                                                              │
│  MISSING IN AWS:                                                            │
│  • Kiali (Istio traffic visualization) - NO EQUIVALENT                      │
│  • Kubecost (pod-level cost allocation) - Cost Explorer is account-level   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Installation (EKS Add-on)

```bash
# Enable via eksctl
eksctl create addon \
  --cluster infra-agent-dev-cluster \
  --name amazon-cloudwatch-observability \
  --region us-east-1

# Or via AWS CLI
aws eks create-addon \
  --cluster-name infra-agent-dev-cluster \
  --addon-name amazon-cloudwatch-observability \
  --region us-east-1

# Or via CloudFormation
AWS::EKS::Addon:
  Type: AWS::EKS::Addon
  Properties:
    ClusterName: !Ref EKSCluster
    AddonName: amazon-cloudwatch-observability
```

### CloudWatch Observability vs Self-Managed Stack

| Feature | CloudWatch Observability | Self-Managed (LGTM) |
|---------|------------------------|---------------------|
| **In-cluster pods** | 6-9 (DaemonSets only) | 35-44 pods |
| **CPU overhead** | ~600m total | ~5.5 vCPU total |
| **Memory overhead** | ~1.7Gi total | ~19 GB total |
| **Metrics query** | CloudWatch Insights | PromQL (powerful) |
| **Log query** | CloudWatch Insights | LogQL (powerful) |
| **Trace query** | X-Ray console | TraceQL |
| **Istio traffic viz** | **Not available** | Kiali |
| **Pod-level costs** | **Not available** | Kubecost |
| **Data retention** | 15 months (metrics) | Unlimited (S3) |
| **Vendor lock-in** | High | None |
| **Setup complexity** | Low (1 add-on) | High (multiple Helm charts) |

### When to Use CloudWatch Observability

**Good fit:**
- Teams without Istio service mesh
- Small clusters (<10 nodes)
- Low operational capacity (no dedicated platform team)
- AWS-only deployments (no multi-cloud plans)
- Low log/metric volume (<5GB logs/day, <1000 metrics)

**Poor fit (use self-managed instead):**
- Istio users who need Kiali traffic visualization
- Teams needing pod-level cost allocation
- High volume workloads (CloudWatch costs escalate quickly)
- Multi-cloud or hybrid environments
- Teams requiring PromQL/LogQL query power

---

## Agent-Optimized Hybrid Stack

This configuration is optimized for **AI agent-based infrastructure management**. It combines AWS managed services with minimal self-managed components to give an agent full query capabilities with low operational overhead.

### Design Principles

1. **Agents use APIs, not UIs** - No Kiali, Headlamp, or Grafana needed
2. **Request-level metrics are essential** - Mini Prometheus for Istio metrics
3. **CloudWatch for logs** - Good enough, agent can query via API
4. **Istio for mTLS** - Security compliance (SC-8)
5. **Minimal pods** - Only what the agent needs

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AGENT-OPTIMIZED HYBRID STACK                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      AI INFRASTRUCTURE AGENT                         │   │
│   │                                                                      │   │
│   │  Capabilities:                                                       │   │
│   │  • Query pod CPU/memory (CloudWatch API)                            │   │
│   │  • Query logs with filters (CloudWatch Logs Insights)               │   │
│   │  • Query request latency/rate/errors (Prometheus API)               │   │
│   │  • Query traces (X-Ray API)                                         │   │
│   │  • Manage deployments (Kubernetes API)                              │   │
│   │  • Check infrastructure drift (CloudFormation API)                  │   │
│   │  • Manage Istio traffic policies (Istio API)                        │   │
│   │                                                                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│            ┌───────────────────────┼───────────────────────┐                │
│            │                       │                       │                │
│            ▼                       ▼                       ▼                │
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐      │
│   │   CLOUDWATCH    │     │ MINI PROMETHEUS │     │   KUBERNETES    │      │
│   │                 │     │                 │     │      API        │      │
│   │ • Container     │     │ • Istio metrics │     │                 │      │
│   │   Insights      │     │   only          │     │ • Pods/Deploys  │      │
│   │ • Logs          │     │ • 24h retention │     │ • ConfigMaps    │      │
│   │ • X-Ray traces  │     │ • PromQL        │     │ • Istio CRDs    │      │
│   └─────────────────┘     └─────────────────┘     └─────────────────┘      │
│            │                       │                       │                │
│            │                       │                       │                │
│   ┌────────┴────────┐     ┌───────┴───────┐       ┌──────┴──────┐         │
│   │  CW AGENT (3)   │     │  PROMETHEUS   │       │   ISTIOD    │         │
│   │  FLUENT BIT (3) │     │  SERVER (1)   │       │    (2)      │         │
│   │  ADOT (3)       │     │               │       │  INGRESS(2) │         │
│   └─────────────────┘     └───────────────┘       │  SIDECARS   │         │
│                                                    └─────────────┘         │
│                                                                              │
│   TOTAL IN-CLUSTER: 14 pods + sidecars                                      │
│   NO UIs DEPLOYED: Kiali ❌  Headlamp ❌  Grafana ❌                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Breakdown

| Component | Pods | Purpose | Agent Uses |
|-----------|------|---------|------------|
| **CloudWatch Agent** | 3 (DaemonSet) | Node/pod metrics | CloudWatch API |
| **Fluent Bit** | 3 (DaemonSet) | Log forwarding | CloudWatch Logs Insights |
| **ADOT Collector** | 3 (DaemonSet) | Traces to X-Ray | X-Ray API |
| **Mini Prometheus** | 1 | Istio service metrics | Prometheus API (PromQL) |
| **istiod** | 2 | Service mesh control plane | Istio API |
| **istio-ingress** | 2 | Gateway | - |
| **Istio sidecars** | 1 per app pod | mTLS encryption | - |
| **TOTAL** | **14 + sidecars** | | |

### What the Agent Can Query

#### CloudWatch API (Container Insights)
```python
# Pod resource utilization
cloudwatch.get_metric_data(
    MetricDataQueries=[{
        'MetricStat': {
            'Metric': {
                'Namespace': 'ContainerInsights',
                'MetricName': 'pod_cpu_utilization',
            }
        }
    }]
)
```

#### CloudWatch Logs Insights
```sql
-- Find error logs in last hour
fields @timestamp, @message, kubernetes.pod_name
| filter @message like /error|exception|fatal/i
| filter kubernetes.namespace_name = "production"
| sort @timestamp desc
| limit 100
```

#### Prometheus API (Istio Metrics) - THE KEY ADDITION
```promql
# Request latency P99 by service
histogram_quantile(0.99,
  sum(rate(istio_request_duration_milliseconds_bucket[5m]))
  by (le, destination_service))

# Request rate per service
sum(rate(istio_requests_total[5m])) by (destination_service)

# Error rate per service
sum(rate(istio_requests_total{response_code=~"5.*"}[5m]))
  / sum(rate(istio_requests_total[5m])) by (destination_service)

# mTLS coverage
sum(istio_requests_total{connection_security_policy="mutual_tls"})
  / sum(istio_requests_total)
```

#### X-Ray API
```python
# Get slow traces
xray.get_trace_summaries(
    StartTime=datetime.now() - timedelta(hours=1),
    EndTime=datetime.now(),
    FilterExpression='service("payment") AND responseTime > 2'
)
```

#### Kubernetes API
```bash
# Agent can execute any kubectl command
kubectl get pods -n production -o json
kubectl describe deployment api -n production
kubectl get events --field-selector type=Warning
kubectl get virtualservices -n production  # Istio traffic rules
```

### Mini Prometheus Configuration

```yaml
# infra/helm/values/prometheus-mini/values.yaml
# Minimal Prometheus for Istio metrics only - optimized for agent queries

prometheus:
  server:
    retention: "24h"  # Short retention, agent queries recent data

    resources:
      requests:
        cpu: 100m
        memory: 512Mi
      limits:
        cpu: 500m
        memory: 1Gi

    # Only store Istio metrics
    global:
      scrape_interval: 30s
      evaluation_interval: 30s

  # Disable all unnecessary components
  alertmanager:
    enabled: false
  pushgateway:
    enabled: false
  nodeExporter:
    enabled: false  # CloudWatch handles node metrics
  kubeStateMetrics:
    enabled: false  # CloudWatch handles this

  # Only scrape Istio
  serverFiles:
    prometheus.yml:
      scrape_configs:
        # Istio control plane
        - job_name: 'istiod'
          kubernetes_sd_configs:
            - role: pod
              namespaces:
                names: ['istio-system']
          relabel_configs:
            - source_labels: [__meta_kubernetes_pod_label_app]
              regex: istiod
              action: keep

        # Istio sidecar proxies (Envoy)
        - job_name: 'envoy-stats'
          metrics_path: /stats/prometheus
          kubernetes_sd_configs:
            - role: pod
          relabel_configs:
            - source_labels: [__meta_kubernetes_pod_container_name]
              regex: istio-proxy
              action: keep
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
              regex: "true"
              action: keep
```

### Installation

```bash
# 1. Enable CloudWatch Observability add-on
aws eks create-addon \
  --cluster-name infra-agent-dev-cluster \
  --addon-name amazon-cloudwatch-observability \
  --region us-east-1

# 2. Install Istio (if not already installed)
istioctl install --set profile=minimal -y
kubectl label namespace default istio-injection=enabled

# 3. Install Mini Prometheus for Istio metrics
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install prometheus-mini prometheus-community/prometheus \
  --namespace observability \
  --create-namespace \
  -f infra/helm/values/prometheus-mini/values.yaml

# 4. Verify agent can query all APIs
# CloudWatch
aws cloudwatch get-metric-data --metric-data-queries '[...]'

# Prometheus
curl http://prometheus-mini.observability:9090/api/v1/query?query=istio_requests_total

# Kubernetes
kubectl auth can-i --list
```

### Agent Query Capabilities Matrix

| Query Type | API | Example Question Agent Can Answer |
|------------|-----|-----------------------------------|
| **Pod resources** | CloudWatch | "Which pods are using >80% CPU?" |
| **Logs** | CW Logs Insights | "Show errors from payment service" |
| **Traces** | X-Ray | "Find slow requests to /checkout" |
| **Request latency** | Prometheus | "What's P99 latency for each service?" |
| **Request rate** | Prometheus | "Which service has highest traffic?" |
| **Error rate** | Prometheus | "Which service has >1% error rate?" |
| **mTLS status** | Prometheus | "Is all traffic encrypted?" |
| **Deployments** | Kubernetes | "What version is deployed?" |
| **Events** | Kubernetes | "Any pod crashes in last hour?" |
| **Traffic rules** | Istio API | "What's the canary split for API?" |
| **Infra drift** | CloudFormation | "Any resources out of sync?" |

### Cost Comparison

| Stack | Pods | Monthly Cost | Agent Capability |
|-------|------|--------------|------------------|
| CloudWatch only | 9 | $362-500 | Basic (no request metrics) |
| **Agent-Optimized Hybrid** | **14** | **$380-520** | **Full** |
| Self-Managed DEV | 11 | $249 | Full |
| Self-Managed PROD | 42 | $593 | Full + HA |

### NIST Compliance

| Control | Status | Implementation |
|---------|--------|----------------|
| **SC-8** (mTLS) | ✅ | Istio sidecar injection |
| **AU-2** (Audit) | ✅ | CloudWatch Logs |
| **AU-6** (Review) | ✅ | Agent queries APIs directly |
| **SI-4** (Monitoring) | ✅ | Prometheus + CloudWatch |
| **AC-2** (Accounts) | ✅ | Cognito (no Keycloak needed for agent) |
| **PM-3** (Costs) | ⚠️ | Account-level only (add Kubecost for pod-level) |

### When to Use Agent-Optimized Hybrid

**Ideal for:**
- AI-first infrastructure management
- Teams building agentic DevOps workflows
- Minimizing human UI dependencies
- AWS-centric environments with Istio

**Not ideal for:**
- Teams needing visual dashboards for humans
- Environments where humans are primary operators
- Multi-cloud deployments

### Optional Add-ons for Full Agent Capability

| Add-on | Pods | Enables |
|--------|------|---------|
| **Kubecost** | +4 | Pod-level cost optimization |
| **Tempo** | +2 | 100% trace capture (vs X-Ray sampling) |

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
| **Identity Provider** | Keycloak (HA) | Keycloak (single) | Amazon Cognito | ~$25 | ~$15 | $5-50* |

**Identity Provider Notes:**
- **Keycloak**: Open-source OIDC provider with full control over configuration
- **Cognito**: AWS-managed, $0.0055 per MAU (Monthly Active User)
- DEV uses single Keycloak instance with RDS db.t4g.micro (~$15/mo)
- PROD uses HA Keycloak with RDS Multi-AZ db.r6g.large (~$25/mo + $200/mo RDS)

**AWS Pricing Note:** *Amazon Inspector has a free tier (90 days). After that, ~$1.25/instance/month for EC2 scanning.

**NIST Mapping:**
- SI-2 (Flaw Remediation): Trivy continuous scanning
- RA-5 (Vulnerability Scanning): Image + config scanning
- AC-6/IA-5 (Least Privilege): IRSA, no long-lived credentials
- SC-28 (Encryption at Rest): KMS encryption
- CM-8 (System Inventory): Mandatory tagging
- IA-2 (Identification): Keycloak OIDC authentication
- AC-2 (Account Management): Centralized user management in Keycloak

---

## NIST 800-53 Rev 5 Compliance Matrix

This table shows compliance status for each NIST 800-53 control across all three architecture options.

**Legend:**
- ✅ **FULL** - Control fully satisfied
- ⚠️ **PARTIAL** - Control partially satisfied (see notes)
- ❌ **GAP** - Control not satisfied
- ➖ **N/A** - Control not applicable to this component

### Access Control (AC)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **AC-2** | Account Management | ✅ | ✅ | ✅ | PROD/DEV: Keycloak SSO with user lifecycle. AWS: Cognito user pools |
| **AC-3** | Access Enforcement | ✅ | ✅ | ✅ | PROD/DEV: Keycloak RBAC + K8s RBAC. AWS: IAM + Cognito groups |
| **AC-6** | Least Privilege | ✅ | ✅ | ✅ | All: IRSA for pod IAM (no static credentials) |
| **AC-17** | Remote Access | ✅ | ⚠️ | ✅ | PROD: Private EKS + SSM bastion. DEV: Public endpoint OK. AWS: Private + SSM |

### Audit & Accountability (AU)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **AU-2** | Audit Events | ✅ | ✅ | ✅ | PROD/DEV: Loki + Prometheus. AWS: CloudWatch Logs + Metrics |
| **AU-3** | Content of Audit Records | ✅ | ✅ | ✅ | PROD/DEV: Structured JSON logs with trace IDs. AWS: CW Logs format |
| **AU-6** | Audit Review | ✅ | ✅ | ⚠️ | PROD/DEV: Grafana dashboards + Kiali. AWS: CW Dashboards (no Kiali) |
| **AU-7** | Audit Reduction | ✅ | ✅ | ✅ | PROD/DEV: LogQL/PromQL queries. AWS: CW Insights queries |
| **AU-9** | Audit Protection | ✅ | ⚠️ | ✅ | PROD: Kafka WAL durability. DEV: No Kafka (risk accepted). AWS: CW managed |
| **AU-11** | Audit Retention | ✅ | ⚠️ | ✅ | PROD: 90 days logs, unlimited S3. DEV: 7 days. AWS: Configurable |
| **AU-12** | Audit Generation | ✅ | ✅ | ✅ | All: Automatic via Promtail/Fluent Bit |

### Configuration Management (CM)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **CM-2** | Baseline Configuration | ✅ | ✅ | ✅ | All: IaC (CloudFormation + Helm) defines baseline |
| **CM-3** | Configuration Change Control | ✅ | ✅ | ✅ | All: Git + CloudFormation change sets |
| **CM-6** | Configuration Settings | ✅ | ✅ | ✅ | All: cfn-guard validates NIST settings before deploy |
| **CM-8** | System Inventory | ✅ | ⚠️ | ⚠️ | PROD: Mandatory 4 tags enforced. DEV/AWS: Tags optional |

### Contingency Planning (CP)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **CP-6** | Alternate Storage | ✅ | ❌ | ✅ | PROD: S3 cross-region replication. DEV: Skipped. AWS: S3 CRR available |
| **CP-9** | System Backup | ✅ | ❌ | ✅ | PROD: Velero daily/weekly. DEV: Skipped. AWS: AWS Backup |
| **CP-10** | Recovery | ✅ | ⚠️ | ✅ | PROD: Multi-AZ (3 AZs). DEV: Single AZ. AWS: Multi-AZ |

### Identification & Authentication (IA)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **IA-2** | Identification | ✅ | ✅ | ✅ | PROD/DEV: Keycloak OIDC. AWS: Cognito OIDC |
| **IA-2(1)** | MFA for Privileged | ✅ | ⚠️ | ✅ | PROD: MFA required. DEV: Optional. AWS: Cognito MFA |
| **IA-5** | Authenticator Management | ✅ | ✅ | ✅ | PROD/DEV: Keycloak password policies. AWS: Cognito policies |
| **IA-8** | Non-Org User ID | ✅ | ✅ | ✅ | PROD/DEV: Keycloak federation. AWS: Cognito social login |

### Risk Assessment (RA)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **RA-5** | Vulnerability Scanning | ✅ | ⚠️ | ✅ | PROD: Trivy Operator continuous. DEV: CI/CD only. AWS: ECR + Inspector |

### System & Communications Protection (SC)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **SC-7** | Boundary Protection | ✅ | ✅ | ✅ | All: Non-routable pod subnets (100.64.x.x), NACLs, SGs |
| **SC-8** | Transmission Confidentiality | ✅ | ⚠️ | ⚠️ | PROD: Full Istio mTLS. DEV: Partial (resource gap). AWS: No Istio |
| **SC-8(1)** | Cryptographic Protection | ✅ | ⚠️ | ⚠️ | PROD: mTLS all pods. DEV: mTLS user-facing only. AWS: TLS to services |
| **SC-12** | Crypto Key Management | ✅ | ✅ | ✅ | All: AWS KMS (customer-managed in PROD) |
| **SC-13** | Cryptographic Protection | ✅ | ✅ | ✅ | All: TLS 1.3 for ALB, AES-256 at rest |
| **SC-28** | Encryption at Rest | ✅ | ✅ | ✅ | All: KMS encryption for EBS, S3, RDS, EKS secrets |

### System & Information Integrity (SI)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **SI-2** | Flaw Remediation | ✅ | ⚠️ | ✅ | PROD: Trivy continuous scanning. DEV: CI/CD only. AWS: Inspector |
| **SI-4** | System Monitoring | ✅ | ✅ | ⚠️ | PROD/DEV: Grafana + Kiali traffic viz. AWS: CW (no traffic viz) |
| **SI-5** | Security Alerts | ✅ | ✅ | ✅ | All: Alerting via Grafana/CloudWatch Alarms |

### Program Management (PM)

| Control | Control Name | PROD | DEV | AWS Managed | Implementation Notes |
|---------|-------------|------|-----|-------------|---------------------|
| **PM-3** | Resource Management | ✅ | ❌ | ⚠️ | PROD: Kubecost pod-level costs. DEV: Skipped. AWS: Cost Explorer (account-level only) |

---

### Compliance Summary

| Category | PROD | DEV | AWS Managed |
|----------|------|-----|-------------|
| **Access Control (AC)** | 4/4 ✅ | 3/4 ✅, 1/4 ⚠️ | 4/4 ✅ |
| **Audit (AU)** | 7/7 ✅ | 5/7 ✅, 2/7 ⚠️ | 6/7 ✅, 1/7 ⚠️ |
| **Config Management (CM)** | 4/4 ✅ | 3/4 ✅, 1/4 ⚠️ | 3/4 ✅, 1/4 ⚠️ |
| **Contingtic Planning (CP)** | 3/3 ✅ | 0/3 ✅, 1/3 ⚠️, 2/3 ❌ | 3/3 ✅ |
| **Identification (IA)** | 4/4 ✅ | 3/4 ✅, 1/4 ⚠️ | 4/4 ✅ |
| **Risk Assessment (RA)** | 1/1 ✅ | 0/1 ✅, 1/1 ⚠️ | 1/1 ✅ |
| **System Protection (SC)** | 6/6 ✅ | 4/6 ✅, 2/6 ⚠️ | 4/6 ✅, 2/6 ⚠️ |
| **System Integrity (SI)** | 3/3 ✅ | 2/3 ✅, 1/3 ⚠️ | 2/3 ✅, 1/3 ⚠️ |
| **Program Mgmt (PM)** | 1/1 ✅ | 0/1 ✅, 0/1 ⚠️, 1/1 ❌ | 0/1 ✅, 1/1 ⚠️ |
| | | | |
| **TOTAL** | **33/33 ✅** | **20/33 ✅, 10/33 ⚠️, 3/33 ❌** | **27/33 ✅, 6/33 ⚠️** |

### Key Compliance Gaps by Environment

#### DEV Environment Gaps (Accepted for Cost Savings)

| Control | Gap | Risk | Compensating Control |
|---------|-----|------|---------------------|
| **CP-6** (Alternate Storage) | No cross-region backup | Data loss if region fails | DEV is ephemeral, can recreate |
| **CP-9** (Backup) | No Velero backups | Data loss if cluster fails | IaC can recreate; no prod data |
| **PM-3** (Cost Management) | No Kubecost | Can't track pod-level costs | AWS Cost Explorer for account-level |
| **SC-8** (mTLS) | Partial Istio sidecars | Internal traffic unencrypted | VPC isolation (100.64.x.x) |
| **AU-9** (Audit Protection) | No Kafka WAL | Metrics could be lost | Prometheus local buffer |
| **AU-11** (Retention) | 7-day logs only | Limited forensic history | Sufficient for dev debugging |

#### AWS Managed Gaps

| Control | Gap | Risk | Compensating Control |
|---------|-----|------|---------------------|
| **AU-6** (Audit Review) | No Kiali | Cannot visualize Istio traffic | Not using Istio in AWS option |
| **SC-8** (mTLS) | No Istio | No service mesh encryption | VPC isolation + TLS to AWS services |
| **SI-4** (Monitoring) | No traffic visualization | Limited service debugging | X-Ray traces for request flow |
| **PM-3** (Cost Management) | Account-level only | Cannot track pod costs | Limited Kubernetes visibility |

---

## Identity & Authentication (Keycloak)

| Component | PROD Config | DEV Config | AWS Alternative | PROD $/mo | DEV $/mo | AWS $/mo |
|-----------|-------------|------------|-----------------|-----------|----------|----------|
| **Keycloak Pods** | 2 (HA) | 1 | N/A | $0 | $0 | N/A |
| **Database** | RDS Multi-AZ | RDS Single-AZ | N/A | ~$200 | ~$15 | N/A |
| **PostgreSQL Version** | 17.7 | 17.7 | N/A | - | - | N/A |
| **Instance Class** | db.r6g.large | db.t4g.micro | N/A | - | - | N/A |

**Why Keycloak Over Cognito:**
| Feature | Keycloak | Amazon Cognito |
|---------|----------|----------------|
| **Full OIDC/SAML** | Yes | Limited SAML |
| **Custom Authentication Flows** | Full control | Limited |
| **Identity Brokering** | Yes (LDAP, AD, Social) | Yes (Social only) |
| **Fine-grained Authorization** | Yes | No |
| **Open Source** | Yes | No |
| **Vendor Lock-in** | None | High |
| **Self-hosted** | Yes | No |

**Services Integrated with Keycloak SSO:**
| Service | Authentication Method | Namespace |
|---------|----------------------|-----------|
| Grafana | OIDC | observability |
| Headlamp | OIDC | headlamp |
| Kiali | OIDC | istio-system |
| Kubecost | OIDC | kubecost |

**NIST Mapping:**
- IA-2 (Identification and Authentication): Centralized OIDC authentication
- IA-5 (Authenticator Management): Password policies, MFA support
- AC-2 (Account Management): User lifecycle management
- AC-3 (Access Enforcement): Role-based access control

### Known Compliance Gap: SC-8 (Transmission Confidentiality)

| Environment | Istio mTLS Status | Notes |
|-------------|-------------------|-------|
| **DEV** | PARTIAL | Only Grafana + Headlamp have sidecars (resource constraint) |
| **TST** | FULL | All namespaces will have sidecars |
| **PRD** | FULL | All namespaces will have sidecars |

**DEV Gap Details:**
- 53 pods in observability/velero/kubecost namespaces lack Istio sidecars
- Enabling all sidecars requires +5.3 vCPU (only 1.8 vCPU free)
- Compensating control: All traffic within private VPC (100.64.x.x)
- Remediation: Add 1 node (+$110/mo) when budget allows

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
│  AWS MANAGED (CloudWatch Observability EKS Add-on)                          │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  IN-CLUSTER AGENTS (DaemonSets):                                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ CloudWatch Agent│  │   Fluent Bit    │  │ ADOT Collector  │             │
│  │  (3 pods)       │  │   (3 pods)      │  │  (3 pods)       │             │
│  │  Metrics scrape │  │   Log forward   │  │  Trace forward  │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           ▼                    ▼                    ▼                       │
│  AWS MANAGED SERVICES (No Pods):                                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   CloudWatch    │  │   CloudWatch    │  │    AWS X-Ray    │             │
│  │    Metrics      │  │     Logs        │  │                 │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  DASHBOARDS: CloudWatch Dashboards    TRAFFIC: **NONE (No Kiali)**         │
│  COST:      Cost Explorer (no pod $)  SECURITY: ECR + Inspector            │
│  Pods: ~9 (agents only) | Cost: ~$362-581/mo | Vendor Lock-in: High        │
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
│  (9 DaemonSet pods)           Variable based on volume                      │
│  + CW Observability           (logs/metrics/traces ingestion)               │
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

| Component | PROD | DEV | AWS Managed (CW Observability Add-on) |
|-----------|------|-----|---------------------------------------|
| **Mimir** | 15 pods | 0 | 0 → CloudWatch Metrics (managed) |
| **Loki** | 10 pods | 2 | 0 → CloudWatch Logs (managed) |
| **Tempo** | 2 pods | 1 | 0 → X-Ray (managed) |
| **Prometheus** | 2 pods | 2 | 0 → CloudWatch Agent scrapes |
| **Grafana** | 2 pods | 1 | 0 → CloudWatch Dashboards (managed) |
| **Kiali** | 2 pods | 1 | 0 → **NO EQUIVALENT** |
| **Keycloak** | 2 pods | 1 | 0 → Cognito (managed) |
| **Velero** | 4 pods | 0 | 0 → AWS Backup (managed) |
| **Kubecost** | 4 pods | 0 | 0 → Cost Explorer (**account-level only**) |
| **Trivy** | 1 pod | 0 | 0 → ECR + Inspector (managed) |
| **CloudWatch Agent** | 0 | 0 | 3 (DaemonSet) - metrics collection |
| **Fluent Bit** | 0 | 0 | 3 (DaemonSet) - log forwarding |
| **ADOT Collector** | 0 | 0 | 3 (DaemonSet) - trace collection |
| **TOTAL** | **~44 pods** | **~8 pods** | **~9 pods** (DaemonSets only) |

**AWS Managed Note:** The CloudWatch Observability EKS add-on deploys only DaemonSet agents in your cluster. All storage, querying, and dashboarding happens in fully managed AWS services (no pods).

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

## Actual Resource Metrics (DEV Environment - Jan 2025)

### Cluster Infrastructure

| Metric | Value |
|--------|-------|
| **EKS Version** | 1.34 |
| **Worker Nodes** | 3x t3a.xlarge |
| **Total Capacity** | 12 vCPU, 48 GB RAM |
| **Available for Workloads** | ~10.5 vCPU, ~42 GB RAM |

### Current Resource Utilization

| Node | CPU Usage | CPU % | Memory Usage | Memory % |
|------|-----------|-------|--------------|----------|
| Node 1 | ~500m | ~12% | ~5 GB | ~33% |
| Node 2 | ~400m | ~10% | ~3.4 GB | ~22% |
| Node 3 | ~300m | ~8% | ~1.5 GB | ~10% |
| **Total** | **~1.2 vCPU** | **~10%** | **~10 GB** | **~21%** |

### Resource Usage by Component

| Component | Pods | CPU Request | Memory Request | Actual CPU | Actual Memory |
|-----------|------|-------------|----------------|------------|---------------|
| **LGTM Stack** | | | | | |
| Grafana | 2 | 200m | 512 Mi | ~20m | ~600 Mi |
| Loki (backend) | 2 | 200m | 512 Mi | ~25m | ~340 Mi |
| Loki (read) | 2 | 200m | 512 Mi | ~40m | ~250 Mi |
| Loki (write) | 2 | 200m | 512 Mi | ~40m | ~200 Mi |
| Loki (caches) | 2 | 1000m | 11 GB | ~10m | ~11 GB |
| Mimir (ingesters) | 2 | 400m | 1 GB | ~60m | ~1 GB |
| Mimir (distributors) | 2 | 400m | 512 Mi | ~40m | ~280 Mi |
| Mimir (kafka) | 1 | 250m | 512 Mi | ~60m | ~630 Mi |
| Prometheus | 1 | 200m | 512 Mi | ~30m | ~680 Mi |
| Tempo | 2 | 200m | 512 Mi | ~8m | ~86 Mi |
| **Istio** | | | | | |
| istiod | 2 | 400m | 1 GB | ~6m | ~90 Mi |
| istio-ingress | 2 | 200m | 256 Mi | ~5m | ~50 Mi |
| Kiali | 1 | 50m | 128 Mi | ~10m | ~50 Mi |
| Kiali Operator | 1 | 10m | 64 Mi | ~3m | ~51 Mi |
| **Operations** | | | | | |
| Headlamp | 1 | 50m | 64 Mi | ~4m | ~59 Mi |
| Kubecost | 4 | 500m | 750 Mi | ~6m | ~640 Mi |
| Velero | 1 | 100m | 128 Mi | ~2m | ~50 Mi |
| Trivy Operator | 1 | 100m | 200 Mi | ~5m | ~109 Mi |
| **System** | | | | | |
| metrics-server | 2 | 200m | 400 Mi | ~10m | ~60 Mi |
| coredns | 2 | 200m | 140 Mi | ~5m | ~40 Mi |
| aws-node (CNI) | 3 | 75m | - | ~15m | ~180 Mi |
| kube-proxy | 3 | 300m | - | ~5m | ~50 Mi |
| ebs-csi | 5 | 210m | 600 Mi | ~20m | ~200 Mi |

### Resource Summary

| Category | CPU Request | Memory Request | CPU Actual | Memory Actual |
|----------|-------------|----------------|------------|---------------|
| LGTM Stack | ~3.0 vCPU | ~15 GB | ~0.3 vCPU | ~14 GB |
| Istio | ~0.7 vCPU | ~1.5 GB | ~0.02 vCPU | ~240 Mi |
| Operations | ~0.8 vCPU | ~1.2 GB | ~0.02 vCPU | ~860 Mi |
| System | ~1.0 vCPU | ~1.2 GB | ~0.05 vCPU | ~530 Mi |
| **TOTAL** | **~5.5 vCPU** | **~19 GB** | **~0.4 vCPU** | **~16 GB** |

### Headroom Analysis

| Resource | Capacity | Requested | Actual | Headroom |
|----------|----------|-----------|--------|----------|
| CPU | 12 vCPU | 5.5 vCPU (46%) | 0.4 vCPU (3%) | 6.5 vCPU (54%) |
| Memory | 48 GB | 19 GB (40%) | 16 GB (33%) | 29 GB (60%) |

**Observations:**
- Actual CPU usage is much lower than requested (over-provisioned)
- Loki caches consume ~11 GB RAM (could be reduced in dev)
- Mimir Kafka WAL uses significant resources (could be disabled in dev)
- Grafana HA (2 replicas) could be reduced to 1 in dev

### EKS Add-ons Status

| Add-on | Version | Status |
|--------|---------|--------|
| vpc-cni | v1.21.1 | Active |
| coredns | v1.12.4 | Active |
| kube-proxy | v1.34.1 | Active |
| aws-ebs-csi-driver | v1.54.0 | Active |
| metrics-server | v0.8.0 | Active |

### Security Posture

| Metric | Value |
|--------|-------|
| Vulnerability Reports | 50+ |
| Critical Vulnerabilities | 0 |
| High Vulnerabilities | 5 |
| Medium Vulnerabilities | 25 |
| Trivy Scanning | Continuous |

### Backup Status

| Metric | Value |
|--------|-------|
| Storage Location | Available (S3) |
| Scheduled Backups | 0 |
| Total Backups | 0 |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial dev vs prod analysis with Kafka recommendation |
| 1.1 | 2025-01-10 | AI Agent | Added three-way cost comparison (AWS vs Prod vs Dev), AMP/AMG pricing |
| 1.2 | 2025-01-10 | AI Agent | Moved Kafka details to architecture.md, removed trade-offs from this doc |
| 1.3 | 2025-01-10 | AI Agent | Added Tempo back for distributed tracing, updated pod/cost counts |
| 2.0 | 2025-01-10 | AI Agent | Major restructure: Dev vs Prod vs AWS three-way comparison with cost columns in all tables |
| 2.1 | 2025-01-11 | AI Agent | Added actual resource metrics section with real cluster data |
| 2.2 | 2025-01-11 | AI Agent | Added Keycloak identity provider section with OIDC integration details |
| 2.3 | 2026-01-14 | AI Agent | Added AWS CloudWatch Observability EKS Add-on section with pod breakdown, data flow diagram, installation commands, and comparison table |
| 2.4 | 2026-01-14 | AI Agent | Added NIST 800-53 Rev 5 Compliance Matrix with 33 controls across PROD/DEV/AWS, compliance summary, and gap analysis |
| 2.5 | 2026-01-14 | AI Agent | Added Agent-Optimized Hybrid Stack for AI-first infrastructure management with CloudWatch + Istio + Mini Prometheus |
| 2.6 | 2026-01-14 | AI Agent | Added Unified Observability Platform Comparison (Free/OSS Only) with 5-way analysis, NIST compliance matrix, weighted scoring, and executive recommendations |
