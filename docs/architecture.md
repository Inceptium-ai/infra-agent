# AI Infrastructure Agent for AWS EKS - Architecture Document

## Executive Summary

This document defines the architecture for an AI-powered Infrastructure Agent system that manages AWS EKS clusters following NIST 800-53 Rev 5 security controls. The system employs a multi-agent architecture using LangGraph for orchestration and Claude (via AWS Bedrock) as the LLM backbone.

**Key Capabilities:**
- Automated infrastructure provisioning via CloudFormation
- NIST 800-53 R5 compliance validation and enforcement
- Zero Trust network architecture with non-routable pod subnets
- mTLS encryption via Istio service mesh
- Comprehensive observability with LGTM stack
- AI-driven drift detection and remediation
- Blue/Green deployment with automated rollback

**Target Environment:** AWS EKS in us-east-1, with three environments (DEV, TST, PRD)

---

## Assumptions

### Technical Assumptions
1. **AWS Account Access**: Operator has AWS account(s) with permissions to create VPCs, EKS clusters, IAM roles, and related resources
2. **Region Availability**: us-east-1 has capacity for requested resources (EKS, NAT Gateways, ALBs)
3. **Bedrock Access**: Claude model is available in the target AWS region via Bedrock
4. **Kubernetes Expertise**: Operators have basic Kubernetes and Helm knowledge
5. **Git Workflow**: Team uses GitHub for version control and GitHub Actions for CI/CD

### Operational Assumptions
1. **Single Operator Model**: Initially, one AI agent manages infrastructure (multi-operator support in future phases)
2. **DEV-First Deployment**: All changes deploy to DEV before promotion to TST/PRD
3. **OSS Preference**: Open-source solutions preferred over commercial alternatives where feasible
4. **RDS over Pods**: Databases run on RDS (not containerized) for managed reliability
5. **ALB over NLB**: Application Load Balancers used for HTTP/HTTPS traffic

### Security Assumptions
1. **MFA Required**: All operator access requires multi-factor authentication
2. **No Direct PRD Access**: AI agent uses JIT (Just-In-Time) access for production
3. **Zero Trust**: All network communication assumes hostile environment
4. **Encryption Everywhere**: Data encrypted at rest (KMS) and in transit (mTLS/TLS)

### Storage Assumptions
1. **No Node-Local Storage**: Pods are ephemeral; node local storage MUST NOT be used for persistence
2. **S3 for Object Storage**: Logs (Loki), traces (Tempo), backups (Velero) use S3 with IRSA authentication
3. **EBS for Block Storage**: Stateful apps (Grafana, Kubecost) use gp3 PVCs - EBS volumes persist independently of pods/nodes
4. **EBS is NOT Node-Local**: gp3 PVCs are AWS-managed block storage, not on node's disk; volumes survive node failures
5. **EFS for Shared Access**: If multiple pods need ReadWriteMany access, use EFS (not currently required)
6. **etcd for CRDs**: Lightweight data (Trivy reports) stored as Kubernetes CRDs in etcd

**Storage Decision Matrix:**

| Storage Type | Use Case | NIST Control | Addons Using |
|--------------|----------|--------------|--------------|
| **S3** | Object storage (logs, traces, backups) | SC-28, CP-9 | Loki, Tempo, Velero |
| **EBS (gp3)** | Block storage (databases, stateful apps) | SC-28 | Grafana, Kubecost |
| **etcd (CRDs)** | Kubernetes-native resources | CM-8 | Trivy Operator |
| **EFS** | Shared file access (ReadWriteMany) | - | Not currently used |
| **Node Local** | ❌ NEVER | - | ❌ Prohibited |

**Why EBS (gp3) is Safe:**
- Volumes are AWS-managed, NOT on node's ephemeral disk
- If node dies, EBS volume persists and reattaches to new node
- Data survives pod restarts, node failures, cluster upgrades
- Encryption at rest via AWS KMS (NIST SC-28 compliant)

---

## Constraints

### Technical Constraints
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| EKS managed node groups only | Cannot use custom AMIs with specialized configurations | Use EKS-optimized AMIs, configure via user data |
| CloudFormation (not Terraform) | Limited state management compared to Terraform | Use nested stacks, export/import values |
| 100.64.0.0/16 for pods | Secondary CIDR required on VPC | Configure VPC CNI custom networking |
| Istio sidecar overhead | ~100MB RAM per pod | Right-size node groups accordingly |

### Compliance Constraints
| Constraint | NIST Control | Implementation |
|------------|--------------|----------------|
| All changes via IaC | CM-3 | CloudFormation only, no console changes |
| Mandatory resource tagging | CM-8 | cfn-guard enforces tags before deployment |
| Audit all actions | AU-2 | VPC Flow Logs, CloudWatch, Loki |
| No wildcard IAM permissions | AC-6 | cfn-guard validates IAM policies |
| Encryption at rest | SC-28 | KMS for EKS secrets, RDS, S3 |
| Encryption in transit | SC-8 | Istio mTLS, ALB TLS termination |

### Operational Constraints
| Constraint | Reason | Mitigation |
|------------|--------|------------|
| 72hr idle resource reaping (DEV only) | Cost control | Kubecost monitoring, alerts before deletion |
| Blue/Green deployments to PRD | Zero downtime requirement | ALB target group switching |
| 4-hour RTO for DR | Business continuity | Velero backups, CloudFormation re-provisioning |

### CloudFormation Constraints (Lessons Learned)
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| Export value max 1024 chars | Cannot export EKS CertificateAuthorityData | Store in SSM Parameter Store or retrieve via API |
| No commas in tag values | NIST_Control tags like `AC-2,AC-6` fail validation | Use underscores: `AC-2_AC-6` |
| SSM parameters must exist | `{{resolve:ssm:...}}` fails if parameter missing | Use static values until bootstrap stack creates params |
| Export names must be unique | Duplicate exports across stacks cause failures | Use descriptive prefixes (e.g., `eks-cluster-created-sg-id`) |
| EKS creates log groups | Defining same log group causes conflict | Add `DependsOn` to create log group BEFORE EKS cluster |
| EKS upgrade path | Can only upgrade one minor version at a time | Plan sequential upgrades (1.32 → 1.33 → 1.34) |

### AMI and Instance Constraints
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| AMI IDs are region-specific | Hardcoded AMIs break cross-region | Use SSM public parameters for dynamic lookup |
| AL2023 has curl-minimal | Installing curl causes package conflict | Skip curl install or use `--allowerasing` |
| User data must match OS | AL2023 uses dnf, Ubuntu uses apt | Verify AMI matches expected OS before deployment |

---

## Dependencies

### AWS Services
| Service | Purpose | Version/Config |
|---------|---------|----------------|
| Amazon EKS | Kubernetes control plane | 1.34 |
| EC2 | Worker nodes, bastion | t3a.medium (bastion), m5.large (nodes) |
| VPC | Networking | Primary + Secondary CIDR |
| ALB | Load balancing | Via AWS Load Balancer Controller |
| RDS | PostgreSQL databases | Aurora PostgreSQL 15+ |
| S3 | Backups, artifacts | Cross-region replication enabled |
| KMS | Encryption keys | Customer-managed keys |
| IAM | Identity management | IRSA for service accounts |
| CloudWatch | Logging, metrics | VPC Flow Logs destination |
| SQS/SNS | Event messaging | Async agent communication |
| Bedrock | LLM access | Claude model |

### Open Source Components
| Component | Version | Purpose |
|-----------|---------|---------|
| Istio | 1.24+ | Service mesh, mTLS |
| Loki | 3.x | Log aggregation |
| Grafana | 11.x | Visualization |
| Prometheus | 2.x | Metrics scraping |
| Mimir | 2.x | Metrics long-term storage (S3-backed) |
| Kiali | 2.x | Service mesh traffic visualization |
| Trivy | 0.58+ | Vulnerability scanning |
| Trivy Operator | 0.24+ | In-cluster scanning |
| Velero | 1.15+ | Backup/restore |
| Kubecost | 2.x | Cost management |
| Headlamp | 0.26+ | Admin console |
| LangGraph | Latest | Agent orchestration |

### Python Dependencies
| Package | Purpose |
|---------|---------|
| langgraph | Agent state machine |
| langchain-aws | Bedrock integration |
| boto3 | AWS SDK |
| cfn-lint | CloudFormation linting |
| kubernetes | K8s Python client |
| click | CLI framework |
| pydantic | Data validation |
| pytest | Testing |

---

## Kubernetes Add-ons Detailed Specifications

This section provides complete specifications for all Kubernetes add-ons deployed in the cluster.

### EKS Managed Add-ons (via CloudFormation)

| Add-on | Version | Description | NIST Controls |
|--------|---------|-------------|---------------|
| **VPC CNI** | v1.21.1 | AWS VPC networking for pods | SC-7 (Network isolation) |
| **CoreDNS** | v1.12.4 | Kubernetes DNS service | SC-7 (Service discovery) |
| **kube-proxy** | v1.34.1 | Network proxy for services | SC-7 (Network routing) |
| **EBS CSI Driver** | v1.54.0 | Persistent volume provisioning | SC-28 (Storage encryption) |

### Helm Chart Add-ons (Phase 3)

#### 1. Istio Service Mesh

| Property | Value |
|----------|-------|
| **Chart** | `istio/base`, `istio/istiod`, `istio/gateway` |
| **Namespace** | `istio-system` |
| **Purpose** | mTLS encryption, traffic management, observability |
| **NIST Controls** | SC-8 (Transmission confidentiality), AU-2 (Access logging) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| istiod | 1-2 | 200m | 512Mi | 15010 (gRPC), 15012 (Webhook), 15014 (Metrics) |
| istio-ingress | 1-2 | 100m | 128Mi | 80, 443, 15021 (Health) |
| Sidecar (per pod) | 1 | 100m | 128Mi | 15001 (Envoy), 15006 (Inbound), 15090 (Prometheus) |

**Health Checks:**
- Istiod: `GET /ready` on port 15021
- Gateway: `GET /healthz/ready` on port 15021

**Dependencies:** None (deploys first)

---

#### 2. Loki (Log Aggregation)

| Property | Value |
|----------|-------|
| **Chart** | `grafana/loki` |
| **Namespace** | `observability` |
| **Purpose** | Centralized log storage and querying |
| **NIST Controls** | AU-2 (Audit events), AU-9 (Audit protection), AU-11 (Retention) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| loki (SingleBinary) | 1 | 500m | 1Gi | 3100 (HTTP), 9095 (gRPC), 7946 (Memberlist) |

**Storage:**
| Type | Backend | Bucket/Path | Retention |
|------|---------|-------------|-----------|
| Chunks | S3 | `{project}-{env}-loki-{account}/chunks` | 30 days → IA |
| Index | S3 | `{project}-{env}-loki-{account}/index` | 30 days → IA |

**Health Checks:**
- Readiness: `GET /ready` on port 3100
- Liveness: `GET /loki/api/v1/status/buildinfo` on port 3100

**Dependencies:** S3 bucket (CloudFormation), IRSA role

---

#### 3. Prometheus (Metrics Scraping)

| Property | Value |
|----------|-------|
| **Chart** | `prometheus-community/prometheus` |
| **Namespace** | `observability` |
| **Purpose** | Scrape Kubernetes/Istio metrics and push to Mimir |
| **NIST Controls** | AU-2 (Audit events), SI-4 (System monitoring) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| prometheus-server | 1 | 100m | 512Mi | 80 (HTTP) |
| node-exporter | 1 per node | 10m | 32Mi | 9100 (Metrics) |
| kube-state-metrics | 1 | 10m | 64Mi | 8080 (Metrics) |

**Data Flow:**
```
[Kubernetes Pods/Nodes] → [Prometheus SCRAPES] → [Remote Write] → [Mimir STORES]
```

**Health Checks:**
- Readiness: `GET /-/ready` on port 9090
- Liveness: `GET /-/healthy` on port 9090

**Dependencies:** Mimir (remote write target)

---

#### 3b. Kiali (Service Mesh Visualization)

| Property | Value |
|----------|-------|
| **Chart** | `kiali/kiali-operator` |
| **Namespace** | `istio-system` |
| **Purpose** | Real-time traffic flow visualization for Istio service mesh |
| **NIST Controls** | AU-6 (Audit review), SI-4 (System monitoring) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| kiali | 1 | 50m | 128Mi | 20001 (HTTP) |

**Features:**
- Real-time traffic flow graph between services
- Request rates, error rates, latency visualization
- Service dependency topology
- Istio configuration validation
- Traffic animation

**Health Checks:**
- Readiness: `GET /healthz` on port 20001

**Dependencies:** Istio, Prometheus

---

#### 4. Grafana (Dashboards)

| Property | Value |
|----------|-------|
| **Chart** | `grafana/grafana` |
| **Namespace** | `observability` |
| **Purpose** | Unified visualization for logs, metrics, traces |
| **NIST Controls** | AU-7 (Audit reduction), SI-4 (System monitoring) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| grafana | 1-2 | 250m | 512Mi | 3000 (HTTP) |

**Data Sources (auto-configured):**
| Source | URL | Type |
|--------|-----|------|
| Loki | `http://loki-gateway.observability:3100` | Logs |
| Mimir | `http://mimir-gateway.observability:80/prometheus` | Metrics (long-term) |
| Prometheus | `http://prometheus-server.observability:80` | Metrics (real-time) |

**Health Checks:**
- Readiness: `GET /api/health` on port 3000
- Liveness: `GET /api/health` on port 3000

**Dependencies:** Loki, Mimir, Prometheus (for data sources)

---

#### 5. Trivy Operator (Security Scanning)

| Property | Value |
|----------|-------|
| **Chart** | `aqua/trivy-operator` |
| **Namespace** | `trivy-system` |
| **Purpose** | Continuous vulnerability scanning of container images |
| **NIST Controls** | SI-2 (Flaw remediation), RA-5 (Vulnerability scanning), CM-8 (Inventory) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| trivy-operator | 1 | 100m | 256Mi | 8080 (Metrics), 9443 (Webhook) |

**Scan Types:**
| Type | CRD | Frequency |
|------|-----|-----------|
| Vulnerabilities | `VulnerabilityReport` | On image change |
| ConfigAudit | `ConfigAuditReport` | On resource change |
| RBAC | `RbacAssessmentReport` | Periodic |
| Secrets | `ExposedSecretReport` | On image change |

**Health Checks:**
- Readiness: `GET /readyz` on port 9090
- Liveness: `GET /healthz` on port 9090

**Dependencies:** None

---

#### 6. Velero (Backup & Restore)

| Property | Value |
|----------|-------|
| **Chart** | `vmware-tanzu/velero` |
| **Namespace** | `velero` |
| **Purpose** | Kubernetes backup, restore, and disaster recovery |
| **NIST Controls** | CP-9 (Backup), CP-10 (Recovery), CP-6 (Alternate storage) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| velero | 1 | 100m | 256Mi | 8085 (Metrics) |
| node-agent (per node) | 1 | 100m | 256Mi | N/A |

**Storage:**
| Type | Backend | Bucket |
|------|---------|--------|
| Backups | S3 | `{project}-{env}-velero-backups` |
| Volume Snapshots | EBS Snapshots | AWS-managed |

**Backup Schedule:**
| Schedule | Retention | Scope |
|----------|-----------|-------|
| Daily (2am UTC) | 7 days | All namespaces |
| Weekly (Sunday) | 30 days | All namespaces |

**Health Checks:**
- Readiness: `GET /metrics` on port 8085

**Dependencies:** S3 bucket (CloudFormation), IRSA role

---

#### 7. Kubecost (Cost Management)

| Property | Value |
|----------|-------|
| **Chart** | `kubecost/cost-analyzer` |
| **Namespace** | `kubecost` |
| **Purpose** | Kubernetes cost monitoring and optimization |
| **NIST Controls** | PM-3 (Resource management) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| cost-model | 1 | 200m | 512Mi | 9003 (API), 9090 (Prometheus) |
| frontend | 1 | 50m | 128Mi | 9090 (UI) |

**Features:**
- Real-time cost allocation by namespace, deployment, pod
- Cost anomaly detection
- Right-sizing recommendations
- Idle resource detection (72hr threshold)

**Health Checks:**
- Readiness: `GET /healthz` on port 9003

**Dependencies:** Prometheus metrics

---

#### 8. Headlamp (Admin Console)

| Property | Value |
|----------|-------|
| **Chart** | `headlamp/headlamp` |
| **Namespace** | `headlamp` |
| **Purpose** | Kubernetes web UI for cluster management |
| **NIST Controls** | AC-2 (Account management UI), AU-6 (Audit review) |

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| headlamp | 1 | 100m | 128Mi | 4466 (HTTP) |

**Features:**
- Cluster overview and health
- Pod/Deployment management
- Log viewing
- RBAC visualization
- Plugin support

**Health Checks:**
- Readiness: `GET /` on port 4466

**Dependencies:** None

---

### Add-on Port Summary

| Service | Namespace | Service Port | Target Port | Protocol |
|---------|-----------|--------------|-------------|----------|
| istiod | istio-system | 15010, 15012, 443 | 15010, 15012, 15017 | gRPC, HTTPS |
| istio-ingress | istio-system | 80, 443 | 8080, 8443 | HTTP, HTTPS |
| kiali | istio-system | 20001 | 20001 | HTTP |
| loki-gateway | observability | 3100 | 3100 | HTTP |
| mimir-gateway | observability | 80 | 80 | HTTP |
| prometheus-server | observability | 80 | 9090 | HTTP |
| grafana | observability | 3000 | 3000 | HTTP |
| trivy-operator | trivy-system | 8080 | 8080 | HTTP |
| velero | velero | 8085 | 8085 | HTTP |
| kubecost | kubecost | 9090 | 9090 | HTTP |
| headlamp | headlamp | 4466 | 4466 | HTTP |

---

## Compute Requirements

### EKS Add-on Resource Requirements

| Component | CPU Request | Memory Request | Replicas | Total CPU | Total Memory |
|-----------|-------------|----------------|----------|-----------|--------------|
| **Istio Control Plane** |
| istiod | 500m | 2Gi | 2 | 1000m | 4Gi |
| istio-ingressgateway | 100m | 128Mi | 2 | 200m | 256Mi |
| istio sidecars (per pod) | 100m | 128Mi | ~20 | 2000m | 2.5Gi |
| **Observability (LGMP + Kiali)** |
| Loki | 500m | 1Gi | 3 | 1500m | 3Gi |
| Grafana | 250m | 512Mi | 2 | 500m | 1Gi |
| Prometheus | 100m | 512Mi | 1 | 100m | 512Mi |
| Mimir | 500m | 1Gi | 2 | 1000m | 2Gi |
| Kiali | 50m | 128Mi | 1 | 50m | 128Mi |
| **Security & Operations** |
| Trivy Operator | 100m | 256Mi | 1 | 100m | 256Mi |
| Velero | 100m | 256Mi | 1 | 100m | 256Mi |
| Kubecost | 200m | 512Mi | 1 | 200m | 512Mi |
| Headlamp | 100m | 128Mi | 1 | 100m | 128Mi |
| **AWS Controllers** |
| AWS LB Controller | 100m | 128Mi | 2 | 200m | 256Mi |
| EBS CSI Driver | 100m | 128Mi | 2 | 200m | 256Mi |
| **Kubernetes Core** |
| CoreDNS | 100m | 70Mi | 2 | 200m | 140Mi |
| kube-proxy | 100m | 128Mi | per node | 300m | 384Mi |
| VPC CNI (aws-node) | 25m | 64Mi | per node | 75m | 192Mi |

### Total Resource Summary

| Resource | Base Estimate | With 30% Buffer |
|----------|---------------|-----------------|
| **Total CPU** | ~8.3 vCPU | ~11 vCPU |
| **Total Memory** | ~16.5 Gi | ~22 Gi |

### Worker Node Sizing

Based on compute requirements, the recommended instance type is **t3a.xlarge**:

| Instance Type | vCPU | Memory | Network | Hourly Cost | Monthly (3 nodes) |
|---------------|------|--------|---------|-------------|-------------------|
| t3a.large | 2 | 8 Gi | Up to 5 Gbps | $0.0752 | ~$165 |
| **t3a.xlarge** ✓ | 4 | 16 Gi | Up to 5 Gbps | $0.1504 | ~$330 |
| m5a.xlarge | 4 | 16 Gi | Up to 10 Gbps | $0.172 | ~$375 |

**Selected Configuration:**
- Instance Type: `t3a.xlarge` (4 vCPU, 16 Gi RAM)
- Min Nodes: 2
- Desired Nodes: 3
- Max Nodes: 10
- Disk: 100 GB gp3 (3,000 IOPS, 125 MB/s)
- AMI: AL2023_x86_64_STANDARD (EKS Optimized)

**Cost Estimate (DEV environment):**
| Resource | Monthly Cost |
|----------|--------------|
| EKS Control Plane | $73 |
| Worker Nodes (3x t3a.xlarge) | ~$330 |
| NAT Gateways (3x) | ~$100 |
| EBS Storage (3x 100GB gp3) | ~$24 |
| Data Transfer | ~$20-50 |
| **Total DEV** | **~$550-580/month** |

---

## Workflow Diagrams

### Deployment Workflow
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Commit    │────►│   CI Build  │────►│  DEV Deploy │────►│  DEV Test   │
│  to Git     │     │  & Scan     │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                    │
                                                              Pass? │
                                                                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PRD Live   │◄────│  PRD Deploy │◄────│  TST Test   │◄────│  TST Deploy │
│             │     │ Blue/Green  │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Agent Communication Workflow
```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Chat Agent (Supervisor)                        │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐            │
│  │  Parse    │─►│  Route    │─►│  MFA      │─►│ Aggregate │            │
│  │  Command  │  │  Intent   │  │  Gate     │  │ Response  │            │
│  └───────────┘  └─────┬─────┘  └─────┬─────┘  └───────────┘            │
└───────────────────────┼──────────────┼──────────────────────────────────┘
                        │              │
        ┌───────────────┼──────────────┼───────────────┐
        │               │              │               │
   ┌────▼────┐    ┌────▼────┐   ┌─────▼────┐   ┌─────▼────┐
   │   IaC   │    │   K8s   │   │ Security │   │  Cost    │
   │  Agent  │    │  Agent  │   │  Agent   │   │  Agent   │
   └────┬────┘    └────┬────┘   └────┬─────┘   └────┬─────┘
        │              │             │              │
   ┌────▼────┐    ┌────▼────┐   ┌────▼─────┐   ┌────▼─────┐
   │ cfn-lint│    │ kubectl │   │  Trivy   │   │ Kubecost │
   │cfn-guard│    │  helm   │   │ Scanning │   │ Metrics  │
   └─────────┘    └─────────┘   └──────────┘   └──────────┘
```

### Infrastructure Build Workflow
```
Phase 1: Foundation              Phase 2: EKS                Phase 3: Services
┌─────────────────┐             ┌─────────────────┐         ┌─────────────────┐
│ VPC + Subnets   │────────────►│ EKS Cluster     │────────►│ Istio Mesh      │
│ NACLs + SGs     │             │ Node Groups     │         │ LGTM Stack      │
│ NAT + IGW       │             │ OIDC Provider   │         │ Trivy Operator  │
│ IAM Roles       │             │ EKS Add-ons     │         │ Headlamp        │
└─────────────────┘             └─────────────────┘         └─────────────────┘
```

---

## Component Diagrams

### Network Architecture
```
                              ┌─────────────────────────────────────────────────┐
                              │                    Internet                      │
                              └─────────────────────────┬───────────────────────┘
                                                        │
                              ┌─────────────────────────▼───────────────────────┐
                              │              Internet Gateway                    │
                              └─────────────────────────┬───────────────────────┘
                                                        │
┌───────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┐
│                                                  VPC (10.0.0.0/16 + 100.64.0.0/16)                            │
│                                                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                    PUBLIC SUBNETS (10.0.0.0/20 - 10.0.32.0/20)                           │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │    ALB    │  │    │  │    ALB    │  │    │  │    ALB    │  │    Route: 0.0.0.0/0 → IGW            │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │                                      │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                        │                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                   PRIVATE SUBNETS (10.0.48.0/20 - 10.0.80.0/20)                          │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │  Bastion  │  │    │  │    NAT    │  │    │  │    RDS    │  │    Route: 0.0.0.0/0 → NAT            │  │
│  │  │  │ t3a.medium│  │    │  │  Gateway  │  │    │  │  Primary  │  │                                      │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │                                      │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                        │                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                 POD SUBNETS (100.64.0.0/16) - NON-ROUTABLE                               │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    Route: 0.0.0.0/0 → NAT (outbound) │  │
│  │  │  │   Pods    │  │    │  │   Pods    │  │    │  │   Pods    │  │    NOT directly addressable from     │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │    internet                          │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Bastion Access Architecture (SSM Session Manager)

The bastion host uses **AWS Systems Manager Session Manager** instead of traditional SSH. This is a Zero Trust approach that eliminates SSH key management and exposed ports.

```
┌─────────────────┐                    ┌─────────────────┐                    ┌─────────────────┐
│   Operator      │                    │   AWS SSM       │                    │    Bastion      │
│   Workstation   │                    │   Service       │                    │    (Private)    │
│                 │                    │                 │                    │                 │
│  ┌───────────┐  │   HTTPS (443)      │  ┌───────────┐  │   SSM Agent        │  ┌───────────┐  │
│  │ AWS CLI + │  │ ─────────────────► │  │ Session   │  │ ◄───────────────── │  │ SSM Agent │  │
│  │ SSM Plugin│  │   WebSocket        │  │ Manager   │  │   Outbound HTTPS   │  │           │  │
│  └───────────┘  │                    │  └───────────┘  │                    │  └───────────┘  │
└─────────────────┘                    └─────────────────┘                    └─────────────────┘
        │                                      │                                      │
        │                                      │                                      │
   IAM Auth +                            TLS 1.2/1.3                           No inbound
   MFA (optional)                        Encryption                            ports open
```

**Security Features:**

| Feature | Traditional SSH | SSM Session Manager |
|---------|-----------------|---------------------|
| **Inbound Ports** | Port 22 open | No inbound ports |
| **Key Management** | SSH key pairs | IAM credentials |
| **Authentication** | Key-based | IAM + optional MFA |
| **Audit Trail** | Manual logging | CloudTrail automatic |
| **Session Logging** | Optional | S3/CloudWatch Logs |
| **Network Path** | Direct to instance | Via AWS control plane |

**Protocol Flow:**
1. Operator runs `aws ssm start-session --target <instance-id>`
2. AWS CLI authenticates via IAM credentials (supports MFA)
3. SSM service validates IAM permissions (`ssm:StartSession`)
4. WebSocket connection established over HTTPS (port 443)
5. SSM Agent on bastion (outbound only) connects to SSM service
6. Bidirectional encrypted tunnel created
7. All commands logged to CloudTrail

**NIST 800-53 R5 Controls Satisfied:**

| Control | Implementation |
|---------|---------------|
| AC-2 (Account Management) | IAM-based access, no shared SSH keys |
| AC-6 (Least Privilege) | Fine-grained IAM policies per user/role |
| AU-2 (Audit Events) | All sessions logged to CloudTrail |
| AU-3 (Audit Content) | Session recordings to S3 (optional) |
| SC-7 (Boundary Protection) | No inbound ports, outbound-only agent |
| SC-8 (Transmission Confidentiality) | TLS 1.2+ encryption end-to-end |
| IA-2 (Identification) | IAM identity, optional MFA |

**Connection Script:** `scripts/bastion-connect.sh`
```bash
./scripts/bastion-connect.sh  # Interactive shell on bastion
```

### Agent Architecture
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    LANGGRAPH STATE MACHINE                                   │
│                                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              InfraAgentState                                         │   │
│  │  • messages: List[BaseMessage]     • current_agent: str                             │   │
│  │  • environment: DEV|TST|PRD        • cloudformation_templates: dict                 │   │
│  │  • validation_results: dict        • eks_cluster_status: dict                       │   │
│  │  • nist_compliance_status: dict    • audit_log: List[dict]                          │   │
│  │  • mfa_verified: bool              • session_expiry: datetime                       │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                                  │
│                                           ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                  Chat Agent                                         │    │
│  │                               (Supervisor Node)                                     │    │
│  │  • Operator authentication        • Command parsing                                 │    │
│  │  • Intent routing                 • Response aggregation                            │    │
│  └────────────────────────────────────────┬───────────────────────────────────────────┘    │
│                                           │                                                  │
│           ┌───────────┬───────────┬───────┴───────┬───────────┬───────────┐                │
│           ▼           ▼           ▼               ▼           ▼           ▼                │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │  IaC Agent   │ │K8s Agent │ │ Deploy   │ │ Verify   │ │ Security │ │  Cost    │        │
│  │              │ │          │ │  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │        │
│  │ • cfn-lint   │ │• kubectl │ │• GitHub  │ │• Drift   │ │• Trivy   │ │• Kubecost│        │
│  │ • cfn-guard  │ │• helm    │ │  Actions │ │  detect  │ │• NIST    │ │• Reaper  │        │
│  │ • ChangeSets │ │• Istio   │ │• B/G     │ │• Tests   │ │  checks  │ │          │        │
│  └──────────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       DATA FLOWS                                             │
│                                                                                              │
│  ┌────────────┐                                                                              │
│  │  Operator  │──── CLI Command ────►┌───────────────┐                                      │
│  │            │                      │  Chat Agent   │                                      │
│  │            │◄─── Response ────────│               │                                      │
│  └────────────┘                      └───────┬───────┘                                      │
│                                              │                                               │
│                          ┌───────────────────┼───────────────────┐                          │
│                          │                   │                   │                          │
│                          ▼                   ▼                   ▼                          │
│                   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                  │
│                   │ CloudForm.  │     │    EKS      │     │  Bedrock    │                  │
│                   │   Stacks    │     │   Cluster   │     │   Claude    │                  │
│                   └──────┬──────┘     └──────┬──────┘     └─────────────┘                  │
│                          │                   │                                               │
│                          ▼                   ▼                                               │
│                   ┌─────────────┐     ┌─────────────┐                                       │
│                   │    AWS      │     │ Kubernetes  │                                       │
│                   │  Resources  │     │   Pods      │                                       │
│                   └─────────────┘     └──────┬──────┘                                       │
│                                              │                                               │
│                          ┌───────────────────┼───────────────────┐                          │
│                          ▼                   ▼                   ▼                          │
│                   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                  │
│                   │    Loki     │     │ Prometheus  │     │   Kiali     │                  │
│                   │   (Logs)    │     │  (Scraper)  │     │(Traffic UI) │                  │
│                   └──────┬──────┘     └──────┬──────┘     └─────────────┘                  │
│                          │                   │                                               │
│                          │            ┌──────▼──────┐                                       │
│                          │            │   Mimir     │                                       │
│                          │            │ (Storage)   │                                       │
│                          │            └──────┬──────┘                                       │
│                          │                   │                                               │
│                          └───────────────────┼───────────────────┘                          │
│                                              ▼                                               │
│                                       ┌─────────────┐                                       │
│                                       │   Grafana   │                                       │
│                                       │ (Dashboard) │                                       │
│                                       └─────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Architecture

### Zero Trust Implementation
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ZERO TRUST LAYERS                                         │
│                                                                                              │
│  Layer 1: Network Isolation                                                                  │
│  ├── NACLs deny by default                                                                   │
│  ├── Security Groups allow specific traffic only                                             │
│  └── Pod subnets (100.64.x.x) not internet-routable                                         │
│                                                                                              │
│  Layer 2: Service Mesh (Istio)                                                               │
│  ├── mTLS between all pods (automatic)                                                       │
│  ├── SPIFFE identity certificates                                                            │
│  └── Authorization policies for service-to-service                                           │
│                                                                                              │
│  Layer 3: Identity & Access                                                                  │
│  ├── IRSA for pod-level AWS permissions                                                      │
│  ├── JIT access for production (STS AssumeRole)                                             │
│  └── MFA required for operator actions                                                       │
│                                                                                              │
│  Layer 4: Data Protection                                                                    │
│  ├── KMS encryption at rest (EKS secrets, RDS, S3)                                          │
│  ├── TLS 1.3 for ALB termination                                                            │
│  └── Secrets in AWS Secrets Manager                                                          │
│                                                                                              │
│  Layer 5: Continuous Validation                                                              │
│  ├── Trivy scans in CI/CD pipeline                                                          │
│  ├── cfn-guard NIST compliance checks                                                        │
│  └── Drift detection and auto-remediation                                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Version Information

| Component | Version | Notes |
|-----------|---------|-------|
| EKS | 1.34 | Latest standard support |
| Istio | 1.24+ | mTLS enabled |
| Loki | 3.x | Scalable mode |
| Grafana | 11.x | Unified observability |
| Trivy | 0.58+ | Latest scanning rules |
| Python | 3.11+ | LangGraph compatible |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-04 | AI Agent | Initial architecture document |
| 1.1 | 2025-01-04 | AI Agent | Added CloudFormation and AMI constraints from lessons learned |
| 1.2 | 2025-01-04 | AI Agent | Added Bastion Access Architecture (SSM Session Manager) section |
| 1.3 | 2025-01-04 | AI Agent | Added Compute Requirements section with EKS add-on resource estimates |
| 1.4 | 2026-01-06 | AI Agent | Replaced Tempo with Prometheus+Kiali for metrics scraping and traffic visualization |
