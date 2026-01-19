# GitLab Self-Hosted Deployment

This document describes the GitLab self-hosted deployment on EKS using the minimal configuration with Istio service mesh integration.

---

## Overview

| Property | Value |
|----------|-------|
| **Deployment Type** | Minimal (non-production) |
| **Namespace** | `gitlab` |
| **Helm Chart** | `gitlab/gitlab` |
| **Chart Version** | Latest |
| **Service Mesh** | Istio sidecar enabled |
| **Storage Backend** | S3 (IRSA) |
| **Database** | Bundled PostgreSQL |
| **Cache** | Bundled Redis |

---

## Pod Inventory

### Complete Pod List

| Pod Name | Component | Purpose | Replicas | Stateful |
|----------|-----------|---------|----------|----------|
| `gitlab-webservice-default-*` | Webservice | Rails app serving UI and API | 1 | No |
| `gitlab-sidekiq-all-in-1-v2-*` | Sidekiq | Background job processor | 1 | No |
| `gitlab-gitaly-0` | Gitaly | Git repository storage and operations | 1 | Yes |
| `gitlab-gitlab-shell-*` | Shell | SSH access for Git operations | 1 | No |
| `gitlab-registry-*` | Registry | Container image registry | 1 | No |
| `gitlab-toolbox-*` | Toolbox | Admin tasks, backups, rails console | 1 | No |
| `gitlab-migrations-*` | Migrations | Database migrations (Job) | 1 | No |
| `gitlab-postgresql-0` | PostgreSQL | Primary database | 1 | Yes |
| `gitlab-redis-master-0` | Redis | Cache and session storage | 1 | Yes |
| `gitlab-gitlab-runner-*` | Runner | CI/CD job executor | 1 | No |
| `gitlab-gitlab-exporter-*` | Exporter | Prometheus metrics exporter | 1 | No |

**Total: ~11 pods** (each with Istio sidecar = 22 containers)

### Pod Descriptions

#### Webservice (gitlab-webservice)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee` |
| **Purpose** | Main Rails application serving web UI and REST/GraphQL APIs |
| **Containers** | webservice, workhorse, istio-proxy |
| **Ports** | 8080 (Puma), 8181 (Workhorse) |
| **Dependencies** | PostgreSQL, Redis, Gitaly |
| **Scaling** | Horizontal (increase replicas for more users) |

#### Sidekiq (gitlab-sidekiq)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitlab-sidekiq-ee` |
| **Purpose** | Processes background jobs (emails, CI pipelines, webhooks) |
| **Containers** | sidekiq, istio-proxy |
| **Ports** | 3807 (metrics) |
| **Dependencies** | PostgreSQL, Redis, Gitaly, S3 |
| **Scaling** | Horizontal (increase for faster job processing) |

#### Gitaly (gitlab-gitaly)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitaly` |
| **Purpose** | Git RPC service - all Git operations go through Gitaly |
| **Containers** | gitaly, istio-proxy |
| **Ports** | 8075 (gRPC), 9236 (metrics) |
| **Dependencies** | None (standalone) |
| **Storage** | PVC (50Gi) for Git repositories |
| **Scaling** | Vertical only (stateful) |

#### GitLab Shell (gitlab-gitlab-shell)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitlab-shell` |
| **Purpose** | Handles SSH connections for Git push/pull |
| **Containers** | gitlab-shell, istio-proxy |
| **Ports** | 2222 (SSH) |
| **Dependencies** | Gitaly, Redis |
| **Scaling** | Horizontal |

#### Registry (gitlab-registry)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitlab-container-registry` |
| **Purpose** | Docker/OCI container image registry |
| **Containers** | registry, istio-proxy |
| **Ports** | 5000 (HTTP) |
| **Dependencies** | S3 (storage backend) |
| **Scaling** | Horizontal |

#### Toolbox (gitlab-toolbox)
| Property | Value |
|----------|-------|
| **Image** | `registry.gitlab.com/gitlab-org/build/cng/gitlab-toolbox-ee` |
| **Purpose** | Administrative tasks, backup/restore, rails console |
| **Containers** | toolbox, istio-proxy |
| **Ports** | None |
| **Dependencies** | PostgreSQL, Redis, Gitaly, S3 |
| **Scaling** | Not needed (admin only) |

#### PostgreSQL (gitlab-postgresql)
| Property | Value |
|----------|-------|
| **Image** | `bitnami/postgresql` |
| **Purpose** | Primary relational database for GitLab metadata |
| **Containers** | postgresql, istio-proxy |
| **Ports** | 5432 |
| **Dependencies** | None |
| **Storage** | PVC (20Gi) |
| **Scaling** | Vertical only (stateful) |

#### Redis (gitlab-redis)
| Property | Value |
|----------|-------|
| **Image** | `bitnami/redis` |
| **Purpose** | Cache, session storage, Sidekiq job queue |
| **Containers** | redis, istio-proxy |
| **Ports** | 6379 |
| **Dependencies** | None |
| **Storage** | PVC (5Gi) |
| **Scaling** | Vertical only (stateful) |

#### GitLab Runner (gitlab-gitlab-runner)
| Property | Value |
|----------|-------|
| **Image** | `gitlab/gitlab-runner` |
| **Purpose** | Executes CI/CD jobs |
| **Containers** | gitlab-runner, istio-proxy |
| **Ports** | 9252 (metrics) |
| **Dependencies** | GitLab API |
| **Scaling** | Horizontal (more runners = more concurrent jobs) |

---

## Resource Requirements

### Per-Pod Resource Allocation

| Pod | CPU Request | CPU Limit | Memory Request | Memory Limit | Storage |
|-----|-------------|-----------|----------------|--------------|---------|
| webservice | 300m | 1500m | 1.5Gi | 3Gi | - |
| workhorse (in webservice) | 100m | 500m | 100Mi | 500Mi | - |
| sidekiq | 500m | 1500m | 1Gi | 2Gi | - |
| gitaly | 400m | 1000m | 600Mi | 1Gi | 50Gi PVC |
| gitlab-shell | 0m | 100m | 6Mi | 64Mi | - |
| registry | 50m | 200m | 32Mi | 256Mi | - |
| toolbox | 50m | 500m | 350Mi | 1Gi | - |
| migrations | 100m | 500m | 200Mi | 1Gi | - |
| postgresql | 250m | 1000m | 256Mi | 1Gi | 20Gi PVC |
| redis | 100m | 500m | 128Mi | 512Mi | 5Gi PVC |
| runner | 100m | 500m | 128Mi | 512Mi | - |
| exporter | 50m | 100m | 64Mi | 128Mi | - |
| **Subtotal (GitLab)** | **2000m** | - | **4.4Gi** | - | **75Gi** |

### Istio Sidecar Overhead

| Resource | Per Sidecar | x11 Pods | Total |
|----------|-------------|----------|-------|
| CPU Request | 100m | 1100m | **1.1 vCPU** |
| Memory Request | 128Mi | 1408Mi | **1.4 Gi** |

### Total Resource Requirements

| Resource | GitLab | Istio Sidecars | **TOTAL** |
|----------|--------|----------------|-----------|
| **CPU Request** | 2.0 vCPU | 1.1 vCPU | **3.1 vCPU** |
| **Memory Request** | 4.4 Gi | 1.4 Gi | **5.8 Gi** |
| **Storage (PVC)** | 75 Gi | - | **75 Gi** |

---

## Dependencies

### Component Dependency Matrix

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GITLAB COMPONENT DEPENDENCIES                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                            ┌──────────────┐                                  │
│                            │  PostgreSQL  │                                  │
│                            │   (5432)     │                                  │
│                            └──────┬───────┘                                  │
│                                   │                                          │
│          ┌────────────────────────┼────────────────────────┐                │
│          │                        │                        │                │
│          ▼                        ▼                        ▼                │
│   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐        │
│   │ Webservice  │          │   Sidekiq   │          │   Toolbox   │        │
│   │  (8080)     │          │   (3807)    │          │             │        │
│   └──────┬──────┘          └──────┬──────┘          └─────────────┘        │
│          │                        │                                          │
│          │         ┌──────────────┼──────────────┐                          │
│          │         │              │              │                          │
│          ▼         ▼              ▼              ▼                          │
│   ┌─────────────────────┐  ┌─────────────┐  ┌─────────────┐                │
│   │       Redis         │  │   Gitaly    │  │     S3      │                │
│   │      (6379)         │  │   (8075)    │  │  (Buckets)  │                │
│   └─────────────────────┘  └──────┬──────┘  └─────────────┘                │
│          ▲                        │                                          │
│          │                        │                                          │
│   ┌──────┴──────┐                 │                                          │
│   │ GitLab Shell│◄────────────────┘                                          │
│   │   (2222)    │                                                            │
│   └─────────────┘                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Dependency Table

| Component | Depends On | Required | Purpose |
|-----------|------------|----------|---------|
| **Webservice** | PostgreSQL | Yes | User data, projects, issues |
| | Redis | Yes | Session cache, rate limiting |
| | Gitaly | Yes | Repository operations |
| | S3 | Yes | Uploads, LFS, artifacts |
| **Sidekiq** | PostgreSQL | Yes | Job metadata |
| | Redis | Yes | Job queue |
| | Gitaly | Yes | Repository operations in jobs |
| | S3 | Yes | Artifacts, uploads |
| **GitLab Shell** | Redis | Yes | Session validation |
| | Gitaly | Yes | Git operations |
| **Registry** | S3 | Yes | Image layer storage |
| | Redis | No | Optional caching |
| **Runner** | Webservice API | Yes | Job fetching |
| **Gitaly** | (none) | - | Standalone |
| **PostgreSQL** | (none) | - | Standalone |
| **Redis** | (none) | - | Standalone |

### Startup Order

```
1. PostgreSQL     ─┐
2. Redis          ─┼─► 3. Gitaly ─► 4. Migrations ─► 5. Webservice ─► 6. Sidekiq
                   │                                                      │
                   │                                                      ▼
                   └─────────────────────────────────────────────► 7. Shell, Registry, Runner
```

---

## Data Flow Diagrams

### User Request Flow (Web UI)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST FLOW (WEB UI)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Browser                                                                    │
│      │                                                                       │
│      │ HTTPS (443)                                                           │
│      ▼                                                                       │
│   ┌─────────────────┐                                                        │
│   │       ALB       │  SSL termination                                       │
│   └────────┬────────┘                                                        │
│            │ HTTP (80)                                                       │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │  Istio Ingress  │  Route by host header                                  │
│   │    Gateway      │                                                        │
│   └────────┬────────┘                                                        │
│            │ HTTP (8181)                                                     │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │   Workhorse     │  Static files, Git HTTP, upload handling               │
│   │ (in webservice) │                                                        │
│   └────────┬────────┘                                                        │
│            │ HTTP (8080)                                                     │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────┐     ┌─────────────┐               │
│   │   Puma/Rails    │────▶│ PostgreSQL  │     │    Redis    │               │
│   │  (webservice)   │     │  (5432)     │     │   (6379)    │               │
│   └────────┬────────┘     └─────────────┘     └─────────────┘               │
│            │                                                                 │
│            │ gRPC (8075)                                                     │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │     Gitaly      │  Repository operations                                 │
│   └─────────────────┘                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Git SSH Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GIT SSH FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Developer                                                                  │
│      │                                                                       │
│      │ git push origin main (SSH)                                           │
│      ▼                                                                       │
│   ┌─────────────────┐                                                        │
│   │  NLB / NodePort │  TCP passthrough (port 22 → 2222)                     │
│   └────────┬────────┘                                                        │
│            │ TCP (2222)                                                      │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │  GitLab Shell   │────▶│    Redis    │  Validate SSH key                 │
│   │    (2222)       │     │   (6379)    │                                   │
│   └────────┬────────┘     └─────────────┘                                   │
│            │                                                                 │
│            │ gRPC (8075)                                                     │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │     Gitaly      │────▶│  Local Disk │  Write Git objects                │
│   │    (8075)       │     │   (PVC)     │                                   │
│   └─────────────────┘     └─────────────┘                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CI/CD Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CI/CD PIPELINE FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. Push triggers pipeline                                                  │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │   Webservice    │────▶│    Redis    │  Queue pipeline job               │
│   └─────────────────┘     └──────┬──────┘                                   │
│                                  │                                           │
│   2. Sidekiq processes job       │                                           │
│      ┌───────────────────────────┘                                           │
│      ▼                                                                       │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │    Sidekiq      │────▶│ PostgreSQL  │  Update job status                │
│   └─────────────────┘     └─────────────┘                                   │
│                                                                              │
│   3. Runner picks up job                                                     │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │  GitLab Runner  │────▶│ Webservice  │  Fetch job via API                │
│   └────────┬────────┘     │    API      │                                   │
│            │              └─────────────┘                                   │
│            │                                                                 │
│   4. Runner executes job                                                     │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │   Job Pod       │────▶│     S3      │  Upload artifacts                 │
│   │ (ephemeral)     │     │  (Bucket)   │                                   │
│   └─────────────────┘     └─────────────┘                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Container Registry Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTAINER REGISTRY FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   docker push registry.example.com/project/image:tag                        │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────────┐                                                        │
│   │  Istio Ingress  │  Route to registry service                            │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐     ┌─────────────┐                                   │
│   │    Registry     │────▶│ Webservice  │  Authenticate via JWT             │
│   │    (5000)       │     │    API      │                                   │
│   └────────┬────────┘     └─────────────┘                                   │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │       S3        │  Store image layers                                   │
│   │ (registry bucket)│                                                       │
│   └─────────────────┘                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Network & Ports

### Internal Service Ports

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| webservice (Puma) | 8080 | HTTP | Rails API |
| webservice (Workhorse) | 8181 | HTTP | Proxy, uploads |
| gitaly | 8075 | gRPC | Git operations |
| gitlab-shell | 2222 | TCP | SSH |
| registry | 5000 | HTTP | Container registry |
| postgresql | 5432 | TCP | Database |
| redis | 6379 | TCP | Cache |
| sidekiq metrics | 3807 | HTTP | Prometheus metrics |
| gitaly metrics | 9236 | HTTP | Prometheus metrics |
| runner metrics | 9252 | HTTP | Prometheus metrics |

### External Access

| Endpoint | Port | Service | Notes |
|----------|------|---------|-------|
| `gitlab.example.com` | 443 | Webservice | Web UI and API |
| `registry.example.com` | 443 | Registry | Container images |
| `gitlab.example.com` | 22 | GitLab Shell | SSH Git access |

---

## Storage

### S3 Buckets (Created by CloudFormation)

| Bucket | Purpose | Lifecycle |
|--------|---------|-----------|
| `*-gitlab-lfs` | Large File Storage | Versioned, retained |
| `*-gitlab-artifacts` | CI/CD artifacts | 30-day expiry |
| `*-gitlab-uploads` | User uploads, avatars | Retained |
| `*-gitlab-packages` | Package registry | Retained |
| `*-gitlab-registry` | Container images | Retained |
| `*-gitlab-terraform-state` | Terraform state backend | Versioned, retained |
| `*-gitlab-ci-secure-files` | CI secure files | Retained |
| `*-gitlab-backups` | Database backups | 90-day expiry, IA after 30d |
| `*-gitlab-tmp` | Temporary files | 1-day expiry |

### Persistent Volume Claims

| PVC | Size | Storage Class | Component |
|-----|------|---------------|-----------|
| `repo-data-gitlab-gitaly-0` | 50Gi | gp3 | Git repositories |
| `data-gitlab-postgresql-0` | 20Gi | gp3 | Database |
| `redis-data-gitlab-redis-master-0` | 5Gi | gp3 | Redis persistence |
| **Total** | **75Gi** | | |

---

## Istio Integration

### Sidecar Configuration

All GitLab pods have Istio sidecar injection enabled via:

1. **Namespace label**: `istio-injection=enabled`
2. **Pod annotations**: `sidecar.istio.io/inject: "true"`
3. **Startup ordering**: `proxy.istio.io/config: '{"holdApplicationUntilProxyStarts": true}'`

### mTLS Policy

```yaml
# Strict mTLS enforced for all GitLab traffic
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: gitlab-mtls
  namespace: gitlab
spec:
  mtls:
    mode: STRICT
```

### Observability via Istio

| Tool | What It Shows |
|------|---------------|
| **Kiali** | Service graph, traffic flow between GitLab components |
| **Prometheus** | Request rate, latency, error rate per service |
| **Tempo** | Distributed traces through GitLab request lifecycle |
| **Grafana** | Dashboards combining all metrics |

---

## Cluster Capacity Analysis

### Before GitLab (Current State)

| Resource | Total Capacity | Used | Available |
|----------|----------------|------|-----------|
| vCPU | 12 (3x t3a.xlarge) | ~9.1 | ~2.9 |
| RAM | 48 GB | ~22.8 GB | ~25.2 GB |

### After Adding 1 Node (Required)

| Resource | Total Capacity | Used (incl. GitLab) | Available |
|----------|----------------|---------------------|-----------|
| vCPU | 16 (4x t3a.xlarge) | ~12.2 | ~3.8 |
| RAM | 64 GB | ~28.6 GB | ~35.4 GB |

### Cost Impact

| Configuration | Nodes | Monthly Cost | Delta |
|---------------|-------|--------------|-------|
| Current | 3x t3a.xlarge | $330/mo | - |
| With GitLab | 4x t3a.xlarge | $440/mo | +$110/mo |

---

## IaC Components

### Helm Values

| File | Purpose |
|------|---------|
| `infra/helm/values/gitlab/values.yaml` | Main GitLab configuration with Istio sidecars |
| `infra/helm/values/gitlab/istio/gateway.yaml` | Istio Gateway, VirtualService, DestinationRules |

### CloudFormation

| File | Purpose |
|------|---------|
| `infra/cloudformation/stacks/02-data/gitlab-storage.yaml` | 9 S3 buckets + IRSA role |

---

## Installation

### Prerequisites

1. EKS cluster running with 4x t3a.xlarge nodes
2. Istio service mesh installed
3. S3 buckets created via CloudFormation
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
    OIDCProviderArn=<OIDC_PROVIDER_ARN> \
    EKSClusterName=<CLUSTER_NAME>
```

### Step 3: Create S3 Connection Secret

```bash
kubectl create secret generic gitlab-rails-storage -n gitlab \
  --from-literal=connection="provider: AWS
region: us-east-1
use_iam_profile: true"
```

### Step 4: Apply Istio Configuration

```bash
kubectl apply -f infra/helm/values/gitlab/istio/gateway.yaml
```

### Step 5: Install GitLab via Helm

```bash
helm repo add gitlab https://charts.gitlab.io/
helm repo update

helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 15m \
  -f infra/helm/values/gitlab/values.yaml
```

### Step 6: Get Initial Root Password

```bash
kubectl get secret -n gitlab gitlab-gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

### Step 7: Access GitLab

```
URL: https://gitlab.<your-domain>
Username: root
Password: <from step 6>
```

---

## Monitoring

### Grafana Dashboards

| Dashboard | Metrics |
|-----------|---------|
| GitLab Overview | Request rate, latency, errors |
| Sidekiq | Job queue depth, processing time |
| Gitaly | Repository operations, RPC latency |
| PostgreSQL | Connections, query time |
| Redis | Memory, commands/sec |

### Kiali Traffic Graph

View GitLab traffic in Kiali:
1. Open Kiali UI
2. Select `gitlab` namespace
3. View service graph showing traffic between components

### Tempo Traces

Distributed traces available for:
- HTTP requests through web UI
- Git operations (clone, push, pull)
- CI/CD pipeline execution
- Background job processing

---

## Backup & Restore

### Automated Backups (via Velero)

GitLab namespace is included in Velero backup schedules:

```yaml
includedNamespaces:
  - gitlab
```

### Manual Backup

```bash
velero backup create gitlab-backup-$(date +%Y%m%d) \
  --include-namespaces gitlab \
  --wait
```

### GitLab Native Backup

```bash
kubectl exec -it -n gitlab $(kubectl get pod -n gitlab -l app=toolbox -o name) \
  -- backup-utility --skip artifacts,registry
```

---

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n gitlab -o wide
```

### Check Istio Sidecar Injection

```bash
kubectl get pods -n gitlab -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.containers[*].name}{"\n"}{end}'
```

### View Logs

```bash
# Webservice logs
kubectl logs -n gitlab -l app=webservice -c webservice

# Sidekiq logs
kubectl logs -n gitlab -l app=sidekiq -c sidekiq

# Gitaly logs
kubectl logs -n gitlab -l app=gitaly -c gitaly

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
| Database connection errors | PostgreSQL not ready | Check postgresql pod status |
| Job queue backing up | Sidekiq overloaded | Increase Sidekiq replicas |

---

## NIST 800-53 Compliance

| Control | Implementation |
|---------|----------------|
| **AC-2** (Account Management) | GitLab built-in user management, LDAP/SAML support |
| **AC-6** (Least Privilege) | IRSA for S3 access, no static credentials |
| **AU-2** (Audit Events) | GitLab audit logs + Istio access logs |
| **AU-11** (Audit Retention) | Logs shipped to Loki (90-day retention) |
| **SC-8** (Transmission Confidentiality) | Istio mTLS between all pods |
| **SC-28** (Encryption at Rest) | S3 SSE, EBS encryption, PostgreSQL encryption |
| **CP-9** (Backup) | Velero daily backups, GitLab native backups |
| **SI-2** (Flaw Remediation) | Container scanning via Trivy |

---

## Cost Summary

| Component | Monthly Cost |
|-----------|--------------|
| Additional node (t3a.xlarge) | $110 |
| EBS PVCs (75Gi gp3) | $6 |
| S3 storage (est. 10GB) | $0.23 |
| Data transfer | ~$5 |
| **Total GitLab Addition** | **~$121/mo** |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-10 | AI Agent | Initial GitLab minimal deployment documentation |
| 1.1 | 2025-01-10 | AI Agent | Added complete pod inventory, dependencies, data flows, ports |
