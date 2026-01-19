# Security & Observability Platform Architecture

This document describes the AWS EKS infrastructure platform, including the observability stack, security controls, and NIST 800-53 compliance.

---

## Overview

The platform provides a secure, compliant Kubernetes environment with unified observability.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SECURITY & OBSERVABILITY PLATFORM                       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                         AWS ACCOUNT (340752837296)                            │   │
│  │                                                                               │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐   │   │
│  │  │                    VPC (10.0.0.0/16)                                   │   │   │
│  │  │                                                                        │   │   │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                       │   │   │
│  │  │  │ us-east-1a │  │ us-east-1b │  │ us-east-1c │  (3 AZs)              │   │   │
│  │  │  │            │  │            │  │            │                       │   │   │
│  │  │  │  Private   │  │  Private   │  │  Private   │                       │   │   │
│  │  │  │  Subnet    │  │  Subnet    │  │  Subnet    │                       │   │   │
│  │  │  └────────────┘  └────────────┘  └────────────┘                       │   │   │
│  │  │         │               │               │                              │   │   │
│  │  │         └───────────────┼───────────────┘                              │   │   │
│  │  │                         │                                              │   │   │
│  │  │                 ┌───────▼───────┐                                      │   │   │
│  │  │                 │   EKS Cluster │                                      │   │   │
│  │  │                 │   (Private)   │                                      │   │   │
│  │  │                 └───────────────┘                                      │   │   │
│  │  └────────────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                               │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                           │   │
│  │  │   Cognito   │  │     S3      │  │   Bastion   │                           │   │
│  │  │   (Auth)    │  │  (Backups)  │  │   (SSM)     │                           │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                           │   │
│  └───────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### EKS Cluster

| Property | Value |
|----------|-------|
| Name | `infra-agent-dev-cluster` |
| Version | 1.34 |
| Endpoint | Private only |
| Access | Via SSM tunnel through bastion |

### Node Groups

| Node Group | Instance Type | Min | Max | Purpose |
|------------|---------------|-----|-----|---------|
| general-nodes | t3.medium | 3 | 10 | General workloads |

**Critical**: Minimum 3 nodes required for multi-AZ coverage (see [Lessons Learned](lessons-learned.md#statefulset-pv-az-binding-incident)).

### Observability Stack (SigNoz)

SigNoz provides unified observability with metrics, logs, and traces in a single platform.

| Component | Purpose | Storage |
|-----------|---------|---------|
| SigNoz Frontend | Web UI | - |
| SigNoz Query Service | Query engine | - |
| SigNoz OTEL Collector | Telemetry ingestion | - |
| ClickHouse | Time-series DB | EBS PVs (3 replicas) |
| Zookeeper | ClickHouse coordination | EBS PV |

**Why SigNoz over LGTM**: See [decisions.md](decisions.md) for full comparison.

### Service Mesh (Istio)

Provides mTLS encryption and traffic management.

| Component | Purpose |
|-----------|---------|
| Istiod | Control plane |
| Envoy sidecars | Data plane (per-pod) |
| Kiali | Traffic visualization |

**Namespaces with Istio enabled**: signoz, headlamp, demo
**Namespaces with Istio disabled**: velero, trivy-system, kiali-operator

### Security Components

| Component | Purpose | NIST Control |
|-----------|---------|--------------|
| Trivy | Vulnerability scanning | RA-5 |
| Velero | Backup/restore | CP-9 |
| Cognito | Authentication | AC-2, IA-2 |
| KMS | Encryption keys | SC-28 |

---

## Access Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Operator   │────►│  SSM Tunnel  │────►│   Bastion    │────►│  EKS API     │
│   Laptop     │     │  (Port 6443) │     │   (Private)  │     │  (Private)   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Browser    │────►│     ALB      │────►│   Services   │
│              │     │  + Cognito   │     │   (K8s)      │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Service URLs

| Service | URL | Auth |
|---------|-----|------|
| SigNoz | `https://<alb>/` | Cognito |
| Headlamp | `https://<alb>/headlamp/` | OIDC → EKS |
| Kubecost | `https://<alb>/kubecost/` | Cognito |
| Kiali | `https://<alb>/kiali/` | Cognito |

See [access-guide.md](access-guide.md) for full URLs and setup instructions.

---

## NIST 800-53 R5 Compliance

| Control | Status | Implementation |
|---------|--------|----------------|
| SC-8 (Transmission Confidentiality) | Partial | Istio mTLS for user-facing services |
| SC-28 (Protection at Rest) | Pass | EBS encryption, S3 SSE |
| AC-2 (Account Management) | Pass | Cognito with groups |
| AC-6 (Least Privilege) | Partial | IRSA for pods |
| AU-2 (Audit Events) | Pass | CloudTrail, VPC Flow Logs, K8s audit |
| CP-9 (Backup) | Pass | Velero with S3 + EBS snapshots |
| RA-5 (Vulnerability Scanning) | Pass | Trivy |

See [security.md](security.md) for detailed compliance documentation.

---

## IaC Structure

All infrastructure is managed as code:

```
infra/
├── cloudformation/
│   ├── stacks/
│   │   ├── 01-networking/    # VPC, subnets, bastion
│   │   ├── 02-eks/           # EKS cluster, node groups
│   │   ├── 03-security/      # IAM, KMS, security groups
│   │   └── 04-data/          # S3 buckets
│   └── cfn-guard-rules/      # NIST compliance rules
├── helm/
│   └── values/
│       ├── signoz/           # SigNoz configuration
│       ├── istio/            # Istio configuration
│       ├── velero/           # Backup configuration
│       ├── trivy/            # Security scanning
│       └── ...
```

---

## Related Documents

- [decisions.md](decisions.md) - Architecture decision records
- [security.md](security.md) - Security controls and compliance
- [access-guide.md](access-guide.md) - Access URLs and instructions
- [lessons-learned.md](lessons-learned.md) - Infrastructure lessons
- [dev-vs-prod-decisions.md](dev-vs-prod-decisions.md) - Dev vs Prod comparison

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-19 | AI Agent | Initial platform architecture document |
