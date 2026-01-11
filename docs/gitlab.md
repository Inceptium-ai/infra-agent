# GitLab Self-Hosted Deployment

This document describes the GitLab self-hosted deployment on EKS using the minimal configuration with Istio service mesh integration.

---

## Overview

| Property | Value |
|----------|-------|
| **Deployment Type** | Minimal (non-production) |
| **Namespace** | `gitlab` |
| **Helm Chart** | `gitlab/gitlab` |
| **Service Mesh** | Istio sidecar enabled |
| **Storage Backend** | S3 (IRSA) |

---

## Resource Requirements

### GitLab Reference Architectures

| Architecture | Users | RPS | vCPU | RAM | Production Ready |
|--------------|-------|-----|------|-----|------------------|
| **Minimal** (current) | ~5-20 | Low | 3 | 12 GB | No - dev/test only |
| 1K Users | 1,000 | 20 | 8 | 16 GB | Yes |
| 2K Users | 2,000 | 40 | 16 | 32 GB | Yes |
| 3K Users | 3,000 | 60 | 24 | 48 GB | Yes |

### Current Deployment (Minimal)

| Component | Replicas | CPU Request | Memory Request |
|-----------|----------|-------------|----------------|
| Webservice | 1 | 300m | 1.5Gi |
| Sidekiq | 1 | 500m | 1Gi |
| Gitaly | 1 | 400m | 600Mi |
| Registry | 1 | 50m | 32Mi |
| Shell | 1 | 0m | 6Mi |
| Toolbox | 1 | 50m | 350Mi |
| Migrations | 1 | 100m | 200Mi |
| PostgreSQL | 1 | 250m | 256Mi |
| Redis | 1 | 100m | 128Mi |
| MinIO (disabled) | 0 | - | - |
| **TOTAL** | ~9 | **~1.75 vCPU** | **~4 Gi** |

*Note: Actual usage will be higher due to Istio sidecar overhead (~100m CPU, ~128Mi per pod).*

### With Istio Sidecar Overhead

| Resource | GitLab | Istio Sidecars (~9 pods) | Total |
|----------|--------|--------------------------|-------|
| CPU | 1.75 vCPU | 0.9 vCPU | **~2.65 vCPU** |
| Memory | 4 Gi | 1.15 Gi | **~5.15 Gi** |

---

## Cluster Capacity Analysis

### Before GitLab (Current State)

| Resource | Total Capacity | Used | Available |
|----------|----------------|------|-----------|
| vCPU | 12 (3x t3a.xlarge) | ~9.1 | ~2.9 |
| RAM | 48 GB | ~22.8 GB | ~25.2 GB |

### After Adding 1 Node (Recommended)

| Resource | Total Capacity | Used (incl. GitLab) | Available |
|----------|----------------|---------------------|-----------|
| vCPU | 16 (4x t3a.xlarge) | ~11.75 | ~4.25 |
| RAM | 64 GB | ~28 GB | ~36 GB |

### Cost Impact

| Configuration | Nodes | Monthly Cost | Delta |
|---------------|-------|--------------|-------|
| Current | 3x t3a.xlarge | $330/mo | - |
| With GitLab | 4x t3a.xlarge | $440/mo | +$110/mo |

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GITLAB DATA FLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Developer                                                                  │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────────┐                                                        │
│   │   ALB (HTTPS)   │                                                        │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│   │  Istio Ingress  │────▶│   GitLab Web    │────▶│    Sidekiq      │       │
│   │    Gateway      │     │   (+ sidecar)   │     │   (+ sidecar)   │       │
│   └─────────────────┘     └────────┬────────┘     └────────┬────────┘       │
│                                    │                       │                 │
│                    ┌───────────────┼───────────────┐       │                 │
│                    ▼               ▼               ▼       ▼                 │
│            ┌───────────┐   ┌───────────┐   ┌───────────────────┐            │
│            │PostgreSQL │   │   Redis   │   │      Gitaly       │            │
│            │(+ sidecar)│   │(+ sidecar)│   │    (+ sidecar)    │            │
│            └───────────┘   └───────────┘   └─────────┬─────────┘            │
│                                                      │                       │
│                                                      ▼                       │
│                                              ┌───────────────┐               │
│                                              │   S3 Bucket   │               │
│                                              │ (Git LFS, CI) │               │
│                                              └───────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Istio Integration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ISTIO SERVICE MESH                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   gitlab namespace (istio-injection=enabled)                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │   │
│   │  │ gitlab-webservice│  │ gitlab-sidekiq │  │  gitlab-gitaly  │     │   │
│   │  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │ ┌─────────────┐ │     │   │
│   │  │ │    App      │ │  │ │    App      │ │  │ │    App      │ │     │   │
│   │  │ └─────────────┘ │  │ └─────────────┘ │  │ └─────────────┘ │     │   │
│   │  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │ ┌─────────────┐ │     │   │
│   │  │ │Envoy Sidecar│ │  │ │Envoy Sidecar│ │  │ │Envoy Sidecar│ │     │   │
│   │  │ └─────────────┘ │  │ └─────────────┘ │  │ └─────────────┘ │     │   │
│   │  └─────────────────┘  └─────────────────┘  └─────────────────┘     │   │
│   │           │                    │                    │               │   │
│   │           └────────────────────┼────────────────────┘               │   │
│   │                                │                                    │   │
│   │                         mTLS (automatic)                            │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    Observability Stack                               │   │
│   │   Prometheus ◄─── scrape metrics ───► Grafana                       │   │
│   │   Tempo      ◄─── traces (OTLP)                                     │   │
│   │   Kiali      ◄─── traffic visualization                             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## IaC Components

### Helm Values

| File | Purpose |
|------|---------|
| `infra/helm/values/gitlab/values.yaml` | Main GitLab configuration |

### CloudFormation

| File | Purpose |
|------|---------|
| `infra/cloudformation/stacks/02-data/gitlab-storage.yaml` | S3 bucket + IRSA role |

---

## Capabilities

### Included (Minimal Deployment)

| Feature | Status | Notes |
|---------|--------|-------|
| Git repositories | Yes | Push/pull/clone |
| Web UI | Yes | Single replica |
| CI/CD pipelines | Yes | Limited concurrency |
| Container registry | Yes | S3-backed |
| Issue tracking | Yes | |
| Merge requests | Yes | |
| Wiki | Yes | |

### Limitations (Minimal Deployment)

| Limitation | Impact |
|------------|--------|
| No HA | Downtime during updates/restarts |
| Single replicas | Slow under concurrent load |
| Limited CI runners | Queue delays for pipelines |
| No Geo replication | Single region only |
| No advanced monitoring | Basic metrics only |

---

## Installation

### Prerequisites

1. EKS cluster running with 4x t3a.xlarge nodes
2. Istio service mesh installed
3. S3 bucket created via CloudFormation
4. IRSA role for GitLab service account

### Step 1: Create Namespace with Istio Injection

```bash
kubectl create namespace gitlab
kubectl label namespace gitlab istio-injection=enabled
```

### Step 2: Deploy CloudFormation (S3 + IRSA)

```bash
aws cloudformation deploy \
  --template-file infra/cloudformation/stacks/02-data/gitlab-storage.yaml \
  --stack-name infra-agent-dev-gitlab-storage \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    Environment=dev \
    ProjectName=infra-agent \
    OIDCProviderArn=<OIDC_PROVIDER_ARN>
```

### Step 3: Install GitLab via Helm

```bash
helm repo add gitlab https://charts.gitlab.io/
helm repo update

helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 10m \
  -f infra/helm/values/gitlab/values.yaml
```

### Step 4: Get Initial Root Password

```bash
kubectl get secret -n gitlab gitlab-gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

### Step 5: Access GitLab

```
URL: https://gitlab.<your-domain>
Username: root
Password: <from step 4>
```

---

## Monitoring

### Grafana Dashboards

GitLab metrics are automatically scraped by Prometheus via Istio sidecar. Available dashboards:

| Dashboard | Metrics |
|-----------|---------|
| GitLab Overview | Request rate, latency, errors |
| Sidekiq | Job queue depth, processing time |
| Gitaly | Repository operations, RPC latency |
| PostgreSQL | Connections, query time |

### Kiali

View GitLab traffic in Kiali:
1. Open Kiali UI
2. Select `gitlab` namespace
3. View service graph for traffic flow between components

### Tempo

Distributed traces available for:
- HTTP requests through web UI
- Git operations (clone, push, pull)
- CI/CD pipeline execution

---

## Backup & Restore

### Automated Backups (via Velero)

GitLab namespace is included in Velero backup schedules:

```yaml
# Already configured in Velero
includedNamespaces:
  - gitlab
```

### Manual Backup

```bash
# Create on-demand backup
velero backup create gitlab-backup-$(date +%Y%m%d) \
  --include-namespaces gitlab \
  --wait
```

### Restore

```bash
velero restore create --from-backup gitlab-backup-20250110
```

---

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n gitlab
```

### Check Istio Sidecar Injection

```bash
kubectl get pods -n gitlab -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}'
```

Expected output should show `istio-proxy` container in each pod.

### View Logs

```bash
# Webservice logs
kubectl logs -n gitlab -l app=webservice -c webservice

# Sidekiq logs
kubectl logs -n gitlab -l app=sidekiq -c sidekiq

# Istio proxy logs
kubectl logs -n gitlab -l app=webservice -c istio-proxy
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Pods pending | Insufficient resources | Add node or reduce requests |
| Sidecar not injected | Namespace not labeled | `kubectl label ns gitlab istio-injection=enabled` |
| S3 access denied | IRSA misconfigured | Check service account annotation |
| Slow Git operations | Resource contention | Scale up or add nodes |

---

## NIST 800-53 Compliance

| Control | Implementation |
|---------|----------------|
| **AC-2** (Account Management) | GitLab built-in user management |
| **AU-2** (Audit Events) | GitLab audit logs + Istio access logs |
| **SC-8** (Transmission Confidentiality) | Istio mTLS between all pods |
| **SC-28** (Encryption at Rest) | S3 SSE, PostgreSQL encryption |
| **CP-9** (Backup) | Velero daily backups |

---

## Cost Summary

| Component | Monthly Cost |
|-----------|--------------|
| Additional node (t3a.xlarge) | $110 |
| S3 storage (est. 10GB) | $0.23 |
| Data transfer | ~$5 |
| **Total GitLab Addition** | **~$115/mo** |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial GitLab minimal deployment documentation |
