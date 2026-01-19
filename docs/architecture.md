# AI Infrastructure Agent for AWS EKS - Architecture Document

## Executive Summary

This document defines the architecture for an AI-powered Infrastructure Agent system that manages AWS EKS clusters following NIST 800-53 Rev 5 security controls. The system employs a multi-agent architecture using LangGraph for orchestration and Claude (via AWS Bedrock) as the LLM backbone.

**Key Capabilities:**
- Automated infrastructure provisioning via CloudFormation
- NIST 800-53 R5 compliance validation and enforcement
- Zero Trust network architecture with non-routable pod subnets
- mTLS encryption via Istio service mesh
- Centralized SSO authentication via AWS Cognito (OIDC)
- Unified observability via SigNoz (metrics, logs, traces in single platform)
- AI-driven drift detection and remediation
- Blue/Green deployment with automated rollback
- IaC validation via cfn-lint and cfn-guard (NIST policy-as-code)

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
2. **S3 for Object Storage**: Backups (Velero) use S3 with IRSA authentication
3. **EBS for Block Storage**: Stateful apps (SigNoz ClickHouse, Kubecost) use gp3 PVCs - EBS volumes persist independently of pods/nodes
4. **EBS is NOT Node-Local**: gp3 PVCs are AWS-managed block storage, not on node's disk; volumes survive node failures
5. **EFS for Shared Access**: If multiple pods need ReadWriteMany access, use EFS (not currently required)
6. **etcd for CRDs**: Lightweight data (Trivy reports) stored as Kubernetes CRDs in etcd

**Storage Decision Matrix:**

| Storage Type | Use Case | NIST Control | Addons Using |
|--------------|----------|--------------|--------------|
| **S3** | Object storage (backups) | SC-28, CP-9 | Velero |
| **EBS (gp3)** | Block storage (databases, stateful apps) | SC-28 | SigNoz (ClickHouse, ZooKeeper), Kubecost |
| **etcd (CRDs)** | Kubernetes-native resources | CM-8 | Trivy Operator |
| **EFS** | Shared file access (ReadWriteMany) | - | Not currently used |
| **Node Local** | NEVER | - | Prohibited |

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
| 100.64.0.0/16 for pods/nodes | Secondary CIDR required on VPC | Nodes deployed in 100.64.x.x subnets (no custom networking needed) |
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

### IaC Validation Pipeline

All CloudFormation templates must pass validation before deployment:

| Tool | Purpose | NIST Control |
|------|---------|--------------|
| **cfn-lint** | Syntax, best practices, resource validation | CM-3 (Configuration Change) |
| **cfn-guard** | Policy-as-code for NIST 800-53 compliance | CM-6 (Configuration Settings) |

**Validation Process:**
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Developer     │────►│   cfn-lint      │────►│   cfn-guard     │────►│   Deploy        │
│   Commit        │     │   (Syntax)      │     │   (NIST Rules)  │     │   Change Set    │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
                              │                       │
                              ▼                       ▼
                        Errors block            Non-compliant
                        deployment              resources blocked
```

**cfn-guard Rule Examples:**
```guard
# NIST SC-28: RDS encryption at rest
rule rds_encryption {
    AWS::RDS::DBInstance {
        Properties.StorageEncrypted == true
    }
}

# NIST SC-7: RDS not publicly accessible
rule rds_not_public {
    AWS::RDS::DBInstance {
        Properties.PubliclyAccessible == false
    }
}

# NIST CM-8: Mandatory tagging
rule mandatory_tags {
    AWS::EC2::VPC {
        Properties.Tags EXISTS
    }
}
```

**Validation Commands:**
```bash
# Lint all templates
cfn-lint infra/cloudformation/stacks/**/*.yaml

# Validate NIST compliance
cfn-guard validate \
  -r infra/cloudformation/cfn-guard-rules/nist-800-53/phase1-controls.guard \
  -d infra/cloudformation/stacks/**/*.yaml
```

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
| Istio | 1.28.2 | Service mesh, mTLS |
| **SigNoz** | 0.74 | Unified observability (metrics, logs, traces) |
| **Kiali** | 2.20 | Istio traffic visualization |
| Trivy Operator | 0.29 | In-cluster vulnerability scanning |
| Velero | 1.17 | Backup/restore |
| Kubecost | 2.8 | Cost management (with nginx proxy for ALB routing) |
| Headlamp | 0.39 | Admin console (with Cognito OIDC) |
| LangGraph | Latest | Agent orchestration |

**Note:** SigNoz replaced the LGTM stack (Loki, Grafana, Tempo, Mimir, Prometheus) as of 2026-01-14.
Kiali was re-added (2026-01-17) for real-time Istio traffic visualization - complements SigNoz traces.

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

#### 2. SigNoz (Unified Observability)

| Property | Value |
|----------|-------|
| **Chart** | `signoz/signoz` |
| **Namespace** | `signoz` |
| **Purpose** | Unified observability platform for metrics, logs, and traces |
| **NIST Controls** | AU-2 (Audit events), AU-6 (Review), AU-9 (Protection), AU-11 (Retention), SI-4 (Monitoring) |

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SigNoz Platform                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Frontend   │   │Query Service │   │Alert Manager │   │ OTel Collector│ │
│  │    (UI)      │   │   (API)      │   │              │   │   (ingest)   │ │
│  │  Port: 3301  │   │  Port: 8080  │   │  Port: 9093  │   │ Port: 4317/18│ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│          │                  │                  │                  │         │
│          └──────────────────┴──────────────────┴──────────────────┘         │
│                                      │                                       │
│                             ┌────────▼────────┐                             │
│                             │   ClickHouse    │                             │
│                             │   (columnar DB) │                             │
│                             │  + ZooKeeper    │                             │
│                             └─────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Components:**
| Component | Replicas | CPU Request | Memory Request | Ports |
|-----------|----------|-------------|----------------|-------|
| signoz-frontend | 1 | 100m | 128Mi | 3301 (HTTP) |
| signoz-query-service | 1 | 200m | 256Mi | 8080 (HTTP) |
| signoz-otel-collector | 1 | 200m | 256Mi | 4317 (gRPC), 4318 (HTTP) |
| signoz-alertmanager | 1 | 50m | 64Mi | 9093 (HTTP) |
| clickhouse | 1 | 500m | 1Gi | 8123 (HTTP), 9000 (Native) |
| zookeeper | 1 | 100m | 256Mi | 2181 (Client) |
| k8s-infra-otel-agent | 1/node | 100m | 100Mi | N/A (DaemonSet) |

**Data Ingest:**
| Protocol | Port | Use Case |
|----------|------|----------|
| OTLP gRPC | 4317 | OpenTelemetry native apps (has issues with Istio) |
| OTLP HTTP | 4318 | **Recommended** - works reliably with Istio mTLS |

**Why SigNoz over LGTM Stack:**
- Single platform for metrics, logs, and traces (vs 5+ components)
- Native OpenTelemetry support
- Columnar ClickHouse storage (efficient for time-series)
- Lower operational complexity
- Built-in alerting and dashboards

**Storage:**
| Type | Backend | Retention |
|------|---------|-----------|
| Metrics | ClickHouse (EBS gp3) | 15 days (configurable) |
| Logs | ClickHouse (EBS gp3) | 15 days (configurable) |
| Traces | ClickHouse (EBS gp3) | 15 days (configurable) |

**Health Checks:**
- Frontend: `GET /` on port 3301
- Query Service: `GET /api/v1/health` on port 8080
- OTel Collector: `GET /` on port 13133

**Dependencies:** EBS storage class (gp3), PriorityClass for scheduling

---

#### 3. Kiali (Service Mesh Visualization)

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

#### 4. Trivy Operator (Security Scanning)

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

#### 9. AWS Cognito (Identity & Access Management)

| Property | Value |
|----------|-------|
| **Service** | AWS Cognito User Pool |
| **Region** | us-east-1 |
| **Purpose** | Centralized SSO/OIDC identity provider for all UI components |
| **NIST Controls** | IA-2 (Identification), IA-5 (Authenticator Mgmt), AC-2 (Account Mgmt) |

**Architecture:**
AWS Cognito replaced self-hosted Keycloak (as of 2026-01-14) for simplified operations and native AWS integration.

| Feature | Cognito Advantage |
|---------|-------------------|
| Management | Fully managed, no patching |
| Availability | AWS SLA, multi-AZ by default |
| Integration | Native ALB auth support |
| Cost | Pay-per-MAU, no RDS needed |

**Authentication Methods:**
| Method | Use Case | Configuration |
|--------|----------|---------------|
| ALB Cognito Action | SigNoz, Kubecost | ALB authenticates before forwarding |
| Direct OIDC | Headlamp | App handles OIDC flow directly |

**OIDC Configuration:**
| Service | Auth Method | Notes |
|---------|-------------|-------|
| SigNoz | ALB Cognito | Default route, Cognito auth on ALB |
| Headlamp | Direct OIDC | Handles own OIDC with Cognito issuer |
| Kubecost | ALB Cognito | Path `/kubecost/*` with Cognito auth |

**Cognito Endpoints:**
- Issuer URL: `https://cognito-idp.us-east-1.amazonaws.com/{user-pool-id}`
- Token endpoint: `https://{domain}.auth.us-east-1.amazoncognito.com/oauth2/token`
- Authorization: `https://{domain}.auth.us-east-1.amazoncognito.com/oauth2/authorize`

**Dependencies:** Cognito User Pool (CloudFormation), ALB for Cognito integration

---

### Add-on Port Summary

| Service | Namespace | Service Port | Target Port | Protocol | NodePort (ALB) |
|---------|-----------|--------------|-------------|----------|----------------|
| istiod | istio-system | 15010, 15012, 443 | 15010, 15012, 15017 | gRPC, HTTPS | - |
| istio-ingress | istio-system | 80, 443 | 8080, 8443 | HTTP, HTTPS | - |
| kiali | istio-system | 20001 | 20001 | HTTP | 30520 |
| signoz-frontend | signoz | 3301 | 3301 | HTTP | 30301 |
| signoz-otel-collector | signoz | 4317, 4318 | 4317, 4318 | gRPC, HTTP | - |
| trivy-operator | trivy-system | 8080 | 8080 | HTTP | - |
| velero | velero | 8085 | 8085 | HTTP | - |
| kubecost-nginx | kubecost | 80 | 80 | HTTP | 30091 |
| headlamp | headlamp | 80 | 4466 | HTTP | 30446 |

---

## Add-on Data Flow Diagrams

This section provides detailed data flow diagrams for each add-on category.

### 1. Unified Observability Flow (SigNoz)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SIGNOZ UNIFIED OBSERVABILITY                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  METRICS:                                                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ App Pod  │    │OTel Agent│    │  OTel    │    │ClickHouse│    ┌──────────┐  │
│  │ /metrics │───►│(DaemonSet)───►│Collector │───►│   (DB)   │───►│  SigNoz  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    │    UI    │  │
│                                                                   └──────────┘  │
│  LOGS:                                                                           │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │         │
│  │ App Pod  │    │OTel Agent│    │  OTel    │    │ClickHouse│         │         │
│  │ (stdout) │───►│(DaemonSet)───►│Collector │───►│   (DB)   │─────────┘         │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘                   │
│                                                                                  │
│  TRACES:                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ App Pod  │    │  Istio   │    │  OTel    │    │ClickHouse│                   │
│  │(request) │───►│ Sidecar  │───►│Collector │───►│   (DB)   │                   │
│  └──────────┘    └──────────┘    │ :4318    │    └──────────┘                   │
│                  (adds trace     └──────────┘                                   │
│                   headers)       HTTP/protobuf                                  │
│                                  (NOT gRPC!)                                    │
│                                                                                  │
│  NIST: AU-2 (Audit Events), AU-6 (Review), AU-9 (Protection), SI-4 (Monitoring)│
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2. Traffic Visualization Flow (Kiali)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TRAFFIC VISUALIZATION                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Istio   │    │Prometheus│    │  Kiali   │    │  Browser │    │ Operator │  │
│  │ Sidecars │───►│ (scrape) │───►│ (query)  │───►│   (UI)   │───►│  (view)  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │                                               │                         │
│       │                                               │                         │
│  Envoy exports      Prometheus         Kiali         Real-time                 │
│  istio_* metrics    stores metrics     queries       traffic graph             │
│  (request count,    (short-term)       Prometheus    with animations           │
│  latency, errors)                      for topology                            │
│                                                                                  │
│  NIST: AU-6 (Audit Review), SI-4 (System Monitoring)                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5. Backup Flow (Velero)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BACKUP PIPELINE                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  SCHEDULED BACKUP:                                                               │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Velero  │    │   K8s    │    │  Velero  │    │    S3    │    │ EBS Snap │  │
│  │ Schedule │───►│   API    │───►│  Server  │───►│ (manifests)───►│  (PVCs)  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                                  │
│  RESTORE:                                                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Operator │    │  Velero  │    │    S3    │    │  Velero  │    │   K8s    │  │
│  │ (trigger)│───►│  Restore │───►│ (fetch)  │───►│  Server  │───►│  Create  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                                  │
│  Schedule: Daily 2AM (7d retention), Weekly Sunday (30d retention)              │
│                                                                                  │
│  NIST: CP-9 (Backup), CP-10 (Recovery), CP-6 (Alternate Storage)               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 6. Security Scanning Flow (Trivy)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SECURITY SCANNING                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │   Pod    │    │  Trivy   │    │   Trivy  │    │   K8s    │    │ Grafana  │  │
│  │ Created  │───►│ Operator │───►│  Scanner │───►│   CRDs   │───►│Dashboard │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │                │               │                        │
│       │               │                │               │                        │
│  New pod          Watches for      Scans image    VulnerabilityReport          │
│  scheduled        pod events       for CVEs       ConfigAuditReport            │
│                                                   RbacAssessmentReport          │
│                                                                                  │
│  Scan Types: Vulnerabilities, ConfigAudit, RBAC, ExposedSecrets                │
│                                                                                  │
│  NIST: SI-2 (Flaw Remediation), RA-5 (Vulnerability Scanning), CM-8 (Inventory)│
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 7. Cost Management Flow (Kubecost)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           COST MANAGEMENT                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │Prometheus│    │ Kubecost │    │  AWS     │    │ Kubecost │    │ Operator │  │
│  │ Metrics  │───►│Cost Model│───►│ Pricing  │───►│   UI     │───►│  (view)  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │                               │                         │
│       │               │                               │                         │
│  CPU, memory      Correlates       Applies AWS    Shows cost by               │
│  usage metrics    usage with       on-demand      namespace, pod,             │
│  per pod          resources        pricing        deployment                   │
│                                                                                  │
│  Features: Cost allocation, idle detection (72hr), right-sizing recommendations│
│                                                                                  │
│  NIST: PM-3 (Resource Management)                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 8. Service Mesh Flow (Istio)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SERVICE MESH                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Service  │    │  Istio   │    │  Istio   │    │  Istio   │    │ Service  │  │
│  │    A     │───►│ Sidecar  │═══►│ Sidecar  │───►│ Sidecar  │───►│    B     │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                       │               ║               │                         │
│                       │          mTLS Encrypted       │                         │
│                       │          (SPIFFE certs)       │                         │
│                       │                               │                         │
│                       ▼                               ▼                         │
│                  ┌──────────┐                   ┌──────────┐                    │
│                  │  istiod  │                   │Prometheus│                    │
│                  │(control) │                   │ (metrics)│                    │
│                  └──────────┘                   └──────────┘                    │
│                                                                                  │
│  Features: mTLS, traffic routing, circuit breaking, retries, rate limiting     │
│                                                                                  │
│  NIST: SC-8 (Transmission Confidentiality), SC-7 (Boundary Protection)         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 9. Authentication Flow (AWS Cognito + ALB)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        AWS COGNITO + ALB AUTHENTICATION                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Operator │    │   ALB    │    │ Cognito  │    │   ALB    │    │ Backend  │  │
│  │ Browser  │───►│ (HTTPS)  │───►│  Login   │───►│ (verify) │───►│ Service  │  │
│  │          │    │          │    │          │    │          │    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │               │               │               │         │
│       │               │               │               │               │         │
│  1. Access        2. No cookie?   3. Login        4. Set cookie   5. Forward │
│     /headlamp       Redirect        via Cognito     on browser      to app    │
│                     to Cognito      hosted UI       (JWT)                      │
│                                                                                  │
│  ALB Auth Flow:                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │  Browser → ALB → Cognito Hosted UI → Cognito → ALB (set cookie) → App  │    │
│  │                                                                          │    │
│  │  Session Cookie: AWSELBAuthSessionCookie (encrypted JWT)                 │    │
│  │  Timeout: 3600 seconds (1 hour)                                          │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  Services with ALB Cognito Auth:                                                │
│  • SigNoz (default route /) - unified observability                            │
│  • Headlamp (/headlamp/*) - K8s admin console                                  │
│  • Kubecost (/kubecost/*) - cost management                                    │
│                                                                                  │
│  NIST: IA-2 (Identification), IA-5 (Authenticator Mgmt), AC-2 (Account Mgmt)   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 9b. ALB Path-Based Routing Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         ALB PATH-BASED ROUTING                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  Internet → ALB (HTTPS:443) → Cognito Auth → Target Group → EKS NodePort        │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                        HTTPS Listener (:443)                             │    │
│  │                                                                          │    │
│  │  Path Pattern         Priority   Auth          Target Group (NodePort)   │    │
│  │  ─────────────────────────────────────────────────────────────────────   │    │
│  │  /headlamp             5        redirect→     /headlamp/                 │    │
│  │  /headlamp/*          10        passthrough   headlamp-tg (30446)        │    │
│  │  /kubecost            15        redirect→     /kubecost/                 │    │
│  │  /kubecost/*          20        Cognito →     kubecost-tg (30091)        │    │
│  │  /kiali               25        redirect→     /kiali/                    │    │
│  │  /kiali/*             30        Cognito →     kiali-tg (30520)           │    │
│  │  /* (default)          -        Cognito →     signoz-tg (30301)          │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  Trailing Slash Handling:                                                       │
│  • /headlamp → 301 redirect → /headlamp/ (required for baseURL routing)        │
│  • /kubecost → 301 redirect → /kubecost/ (required for nginx proxy)            │
│  • /kiali → 301 redirect → /kiali/ (required for web_root routing)             │
│                                                                                  │
│  Kubecost nginx Proxy (in-cluster):                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │  ALB → kubecost-nginx:30091 → nginx (rewrite /kubecost/* → /*)          │    │
│  │                                     → kubecost-cost-analyzer:9090        │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  TargetGroupBinding CRDs (AWS LB Controller):                                   │
│  • signoz-tgb (namespace: signoz)                                              │
│  • headlamp-tgb (namespace: headlamp)                                          │
│  • kubecost-tgb (namespace: kubecost)                                          │
│  • kiali-tgb (namespace: istio-system)                                         │
│                                                                                  │
│  NIST: SC-8 (Transmission Confidentiality - HTTPS), IA-2 (Authentication)      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Compute Requirements

### EKS Add-on Resource Requirements

| Component | CPU Request | Memory Request | Replicas | Total CPU | Total Memory |
|-----------|-------------|----------------|----------|-----------|--------------|
| **Istio Control Plane** |
| istiod | 500m | 2Gi | 2 | 1000m | 4Gi |
| istio-ingressgateway | 100m | 128Mi | 2 | 200m | 256Mi |
| istio sidecars (per pod) | 100m | 128Mi | ~20 | 2000m | 2.5Gi |
| **Observability (SigNoz + Kiali)** |
| SigNoz Frontend | 100m | 128Mi | 1 | 100m | 128Mi |
| SigNoz Query Service | 200m | 256Mi | 1 | 200m | 256Mi |
| SigNoz OTel Collector | 200m | 256Mi | 1 | 200m | 256Mi |
| SigNoz Alertmanager | 50m | 64Mi | 1 | 50m | 64Mi |
| ClickHouse | 500m | 1Gi | 1 | 500m | 1Gi |
| ZooKeeper | 100m | 256Mi | 1 | 100m | 256Mi |
| OTel Agent (DaemonSet) | 100m | 100Mi | 3 | 300m | 300Mi |
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
│ NACLs + SGs     │             │ Node Groups     │         │ Observability   │
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
│  │  │  │ t3a.medium│  │    │  │  Gateway  │  │    │  │  Primary  │  │    (NO EKS nodes here)               │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │                                      │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                        │                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                             EKS NODE SUBNETS (100.64.0.0/16) - NON-ROUTABLE                              │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    Route: 0.0.0.0/0 → NAT (outbound) │  │
│  │  │  │  + Pods   │  │    │  │  + Pods   │  │    │  │  + Pods   │  │    Nodes & pods NOT directly         │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │    addressable from internet         │  │
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

The system uses a multi-agent architecture with intent-based routing. The Chat Agent acts as the orchestrator, routing requests to specialized agents based on user intent.

**Intent Classification:**
| Intent | Description | Agent(s) |
|--------|-------------|----------|
| `change` | Infrastructure changes | 4-Agent Pipeline (Planning → IaC → Review → Deploy) |
| `query` | Information queries | K8s Agent |
| `investigate` | Troubleshooting issues | Investigation Agent |
| `audit` | Compliance/security/cost reviews | Audit Agent |
| `conversation` | General questions | Chat Agent (direct) |

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    LANGGRAPH STATE MACHINE                                   │
│                                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              InfraAgentState                                         │   │
│  │  • messages: List[BaseMessage]     • current_agent: str                             │   │
│  │  • environment: DEV|TST|PRD        • cloudformation_templates: dict                 │   │
│  │  • validation_results: dict        • eks_cluster_status: dict                       │   │
│  │  • nist_compliance_status: dict    • investigation_output_json: str                 │   │
│  │  • audit_output_json: str          • session_expiry: datetime                       │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                                  │
│                                           ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                  Chat Agent                                         │    │
│  │                              (ORCHESTRATOR NODE)                                    │    │
│  │  • Intent classification          • Command parsing                                 │    │
│  │  • Agent routing                  • Response aggregation                            │    │
│  └────────────────────────────────────────┬───────────────────────────────────────────┘    │
│                                           │                                                  │
│     ┌──────────────────┬──────────────────┼──────────────────┬──────────────────┐          │
│     │                  │                  │                  │                  │          │
│     ▼                  ▼                  ▼                  ▼                  ▼          │
│  ┌──────────┐   ┌─────────────────────────────────────┐  ┌──────────┐   ┌──────────┐      │
│  │ K8s      │   │     4-AGENT PIPELINE (change)       │  │Investig- │   │  Audit   │      │
│  │ Agent    │   │                                     │  │ation     │   │  Agent   │      │
│  │ (query)  │   │  Planning → IaC → Review → Deploy   │  │ Agent    │   │          │      │
│  │          │   │                                     │  │          │   │          │      │
│  │• kubectl │   │ ┌────────┐ ┌────────┐ ┌────────┐   │  │• K8s     │   │• NIST    │      │
│  │• helm    │   │ │Planning│→│  IaC   │→│ Review │   │  │  diag    │   │  800-53  │      │
│  │• status  │   │ │ Agent  │ │ Agent  │ │ Agent  │   │  │• AWS     │   │• Security│      │
│  │          │   │ └────────┘ └────────┘ └───┬────┘   │  │  diag    │   │• Cost    │      │
│  │          │   │                           │        │  │• SigNoz  │   │• Drift   │      │
│  │          │   │                     ┌─────▼─────┐  │  │  query   │   │          │      │
│  │          │   │                     │Deploy/Val │  │  │          │   │          │      │
│  │          │   │                     │  Agent    │  │  │          │   │          │      │
│  │          │   │                     └───────────┘  │  │          │   │          │      │
│  └──────────┘   └─────────────────────────────────────┘  └──────────┘   └──────────┘      │
│                                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              TOOL CAPABILITIES BY AGENT                              │  │
│  ├─────────────────────────────────────────────────────────────────────────────────────┤  │
│  │ K8s Agent:          kubectl, helm, node-status, pod-status, deployments, services   │  │
│  │ Planning Agent:     generate_plan, validate_plan, estimate_impact, list_resources   │  │
│  │ IaC Agent:          cfn-lint, cfn-guard, ChangeSets, generate_cfn, generate_helm    │  │
│  │ Review Agent:       diff_analysis, security_review, compliance_check, cost_estimate │  │
│  │ Deploy Agent:       cfn_deploy, helm_upgrade, validate_deployment, rollback         │  │
│  │ Investigation:      pod_logs, events, describe, ec2_status, cloudwatch, signoz      │  │
│  │ Audit Agent:        nist_checks, iam_audit, trivy_scan, kubecost, drift_detection   │  │
│  └─────────────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

**4-Agent Pipeline Detail:**
```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                            4-AGENT CHANGE PIPELINE                                          │
│                                                                                             │
│  User: "Add a new S3 bucket for logs"                                                       │
│                     │                                                                       │
│                     ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │ PLANNING AGENT                                                                       │   │
│  │ • Analyze request scope                                                              │   │
│  │ • Identify required resources (CloudFormation, Helm, IAM)                           │   │
│  │ • Generate implementation plan                                                       │   │
│  │ • Output: planning_output.yaml                                                       │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                     │                                                                       │
│                     ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │ IAC AGENT                                                                            │   │
│  │ • Generate CloudFormation templates                                                  │   │
│  │ • Generate Helm values files                                                         │   │
│  │ • Run cfn-lint validation                                                            │   │
│  │ • Run cfn-guard NIST compliance                                                      │   │
│  │ • Output: iac_output.yaml, generated templates                                       │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                     │                                                                       │
│                     ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │ REVIEW AGENT                                                                         │   │
│  │ • Security review of generated code                                                  │   │
│  │ • Compliance verification                                                            │   │
│  │ • Cost impact estimation                                                             │   │
│  │ • Approval gate (requires human approval for PRD)                                    │   │
│  │ • Output: review_output.yaml                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                     │                                                                       │
│                     ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │ DEPLOY/VALIDATE AGENT                                                                │   │
│  │ • Execute CloudFormation deploy                                                      │   │
│  │ • Execute Helm upgrade                                                               │   │
│  │ • Validate deployment success                                                        │   │
│  │ • Rollback on failure                                                                │   │
│  │ • Output: deploy_output.yaml                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Investigation Agent Tools (15 tools):**
| Tool | Purpose | Source |
|------|---------|--------|
| `pod_health_check` | Pod status overview | kubectl |
| `pod_logs` | Container logs | kubectl |
| `pod_events` | Kubernetes events | kubectl |
| `pod_describe` | Detailed pod info | kubectl |
| `resource_usage` | CPU/Memory metrics | kubectl top |
| `node_status` | Node health | kubectl |
| `pvc_status` | PVC status | kubectl |
| `service_endpoints` | Service endpoints | kubectl |
| `ec2_status` | EC2 instance status | AWS API |
| `eks_nodegroup_status` | Node group health | AWS API |
| `cloudwatch_logs` | CloudWatch logs | AWS API |
| `ebs_status` | EBS volume status | AWS API |
| `signoz_metrics` | SigNoz metrics | SigNoz API |
| `signoz_logs` | SigNoz logs | SigNoz API |
| `signoz_traces` | SigNoz traces | SigNoz API |

**Audit Agent Tools (14 tools):**
| Tool | Purpose | Checks |
|------|---------|--------|
| `nist_sc8_check` | Transmission encryption | Istio mTLS |
| `nist_sc28_check` | Encryption at rest | EBS/S3/RDS |
| `nist_ac2_check` | Account management | IAM policies |
| `nist_ac6_check` | Least privilege | Wildcard policies |
| `nist_au2_check` | Audit logging | CloudWatch/FlowLogs |
| `nist_au3_check` | Audit content | Log completeness |
| `nist_cm2_check` | Baseline configuration | IaC compliance |
| `nist_cm3_check` | Change control | Git workflow |
| `nist_cp9_check` | Backup verification | Velero status |
| `nist_ra5_check` | Vulnerability scans | Trivy results |
| `iam_audit` | IAM policy review | AWS IAM |
| `kubecost_query` | Cost analysis | Kubecost API |
| `cfn_drift_detect` | CloudFormation drift | AWS CFN |
| `helm_drift_detect` | Helm values drift | Helm diff |

### Data Flow Diagram
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       DATA FLOWS                                             │
│                                                                                              │
│  ┌────────────┐                                                                              │
│  │  Operator  │──── CLI Command ────►┌───────────────┐                                      │
│  │            │                      │  Chat Agent   │                                      │
│  │            │◄─── Response ────────│  (Orchestr.)  │                                      │
│  └────────────┘                      └───────┬───────┘                                      │
│                                              │                                               │
│           ┌──────────────────────────────────┼──────────────────────────────────┐           │
│           │                    │             │             │                    │           │
│           ▼                    ▼             ▼             ▼                    ▼           │
│    ┌─────────────┐      ┌───────────┐ ┌───────────┐ ┌───────────┐      ┌─────────────┐     │
│    │ CloudForm.  │      │   EKS     │ │  Bedrock  │ │  SigNoz   │      │   Kubecost  │     │
│    │   Stacks    │      │  Cluster  │ │  Claude   │ │   API     │      │     API     │     │
│    └──────┬──────┘      └─────┬─────┘ └───────────┘ └─────┬─────┘      └──────┬──────┘     │
│           │                   │                           │                   │            │
│           ▼                   ▼                           │                   │            │
│    ┌─────────────┐      ┌─────────────┐                  │                   │            │
│    │    AWS      │      │ Kubernetes  │                  │                   │            │
│    │  Resources  │      │    Pods     │                  │                   │            │
│    └─────────────┘      └──────┬──────┘                  │                   │            │
│                                │                          │                   │            │
│                    ┌───────────┴───────────┐              │                   │            │
│                    ▼                       ▼              │                   │            │
│             ┌─────────────┐         ┌─────────────┐       │                   │            │
│             │    OTEL     │         │   Kiali     │       │                   │            │
│             │  Collector  │         │ (Traffic)   │       │                   │            │
│             └──────┬──────┘         └─────────────┘       │                   │            │
│                    │                                      │                   │            │
│                    │    ┌─────────────────────────────────┘                   │            │
│                    │    │                                                     │            │
│                    ▼    ▼                                                     │            │
│             ┌─────────────┐                                                   │            │
│             │ ClickHouse  │◄──────────────────────────────────────────────────┘            │
│             │  (Storage)  │     Cost metrics from Kubecost                                 │
│             └──────┬──────┘                                                                │
│                    │                                                                        │
│                    ▼                                                                        │
│             ┌─────────────┐                                                                │
│             │   SigNoz    │                                                                │
│             │ (Dashboard) │                                                                │
│             │ Metrics +   │                                                                │
│             │ Logs +      │                                                                │
│             │ Traces      │                                                                │
│             └─────────────┘                                                                │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Observability Stack (SigNoz):**
| Component | Purpose | Storage |
|-----------|---------|---------|
| OTEL Collector | Receives metrics, logs, traces via OTLP | - |
| ClickHouse | Column-oriented database for all telemetry | EBS (gp3) |
| SigNoz Frontend | Unified dashboard for metrics, logs, traces | - |
| Kiali | Istio service mesh traffic visualization | Uses Prometheus |
| Prometheus (minimal) | Istio metrics for Kiali only | Ephemeral |

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

### AWS Credential Chain

The infra-agent uses the **AWS SDK default credential chain** for all AWS API calls. This applies to both the agent CLI (running locally) and any tools that invoke `aws` CLI commands.

**Credential Resolution Order:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AWS CREDENTIAL CHAIN                              │
│                  (checked in order, first match wins)                │
├─────────────────────────────────────────────────────────────────────┤
│ 1. Environment Variables                                             │
│    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN      │
│                                                                      │
│ 2. Shared Credentials File                                           │
│    ~/.aws/credentials (default profile or AWS_PROFILE)              │
│                                                                      │
│ 3. Shared Config File                                                │
│    ~/.aws/config (supports SSO, assume role)                        │
│                                                                      │
│ 4. ECS Container Credentials                                         │
│    Task IAM role (if running in ECS)                                │
│                                                                      │
│ 5. EC2 Instance Metadata                                             │
│    Instance profile / IAM role (if running on EC2)                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Usage Scenarios:**

| Scenario | Credential Source | Configuration |
|----------|-------------------|---------------|
| Local development | `~/.aws/credentials` | `aws configure` |
| SSO authentication | `~/.aws/config` | `aws sso login --profile <name>` |
| CI/CD pipeline | Environment variables | Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Running on EC2 | Instance profile | Attach IAM role to instance |
| Running in ECS | Task role | Configure task IAM role |

**Profile Selection:**

```bash
# Use specific profile (optional)
export AWS_PROFILE=my-profile

# Or set in .env file
AWS_PROFILE=my-profile
```

**Required IAM Permissions:**

The infra-agent requires permissions for:
- **EKS**: `eks:DescribeCluster`, `eks:ListNodegroups`, `eks:DescribeNodegroup`
- **EC2**: `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`, `ec2:DescribeVolumes`
- **CloudWatch**: `logs:FilterLogEvents`, `logs:DescribeLogGroups`
- **CloudFormation**: `cloudformation:DescribeStacks`, `cloudformation:DetectStackDrift`
- **S3**: `s3:ListBuckets`, `s3:GetBucketEncryption` (for audits)
- **IAM**: `iam:ListRoles`, `iam:GetRolePolicy` (for security audits)
- **Bedrock**: `bedrock:InvokeModel` (for Claude LLM)

**Verifying Credentials:**

```bash
# Check current identity
aws sts get-caller-identity

# Expected output:
{
    "UserId": "AIDAEXAMPLE",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/operator"
}
```

---

## Known Compliance Gaps

### SC-8: Transmission Confidentiality (Partial)

**Status:** PARTIAL COMPLIANCE

**Issue:** Observability stack pods (Grafana, Loki, Prometheus, Mimir, etc.) are running WITHOUT Istio sidecar injection. Traffic between these services is not encrypted with mTLS.

**Affected Namespaces:**
| Namespace | Pods | Istio Injection | Status |
|-----------|------|-----------------|--------|
| observability | 37 | Disabled | Not compliant |
| velero | 9 | Disabled | Not compliant |
| kubecost | 5 | Disabled | Not compliant |
| trivy-system | 1 | Disabled | Not compliant |
| headlamp | 1 | **Enabled** | Compliant |

**Root Cause:** Namespaces were not labeled with `istio-injection=enabled` before deploying Helm charts.

**Resource Constraint:** Enabling sidecars on all 53 pods would require ~5.3 vCPU additional. Current cluster has only ~1.8 vCPU free.

**Mitigation Decision (2026-01-11):**
- Enable Istio sidecars on user-facing services only (Grafana, Headlamp)
- Accept risk for internal observability traffic (defense-in-depth via VPC isolation)
- Document as accepted risk for DEV environment
- Full compliance required for TST/PRD (additional nodes budgeted)

**Compensating Controls:**
- All traffic is within private VPC (100.64.x.x non-routable subnets)
- Network policies restrict pod-to-pod communication
- No external exposure without ALB + TLS termination

**Remediation Plan:**
1. Add 1 additional node when budget allows (+$110/mo)
2. Label all namespaces with `istio-injection=enabled`
3. Restart all deployments to inject sidecars
4. Verify mTLS with: `istioctl analyze` and Kiali traffic graph

---

## Version Information

| Component | Version | Notes |
|-----------|---------|-------|
| EKS | 1.34 | Latest standard support |
| Istio | 1.28 | mTLS enabled |
| **SigNoz** | 0.74 | Unified observability (metrics, logs, traces) |
| Kiali | 2.20 | Istio traffic visualization |
| Trivy Operator | 0.29 | In-cluster scanning |
| Velero | 1.17 | Backup/restore |
| Kubecost | 2.8 | Cost management |
| Headlamp | 0.39 | Admin console |
| AWS Cognito | N/A | Centralized SSO/OIDC (managed) |
| Python | 3.13+ | cfn-lint compatible |
| cfn-lint | Latest | CloudFormation linting |
| cfn-guard | 3.x | NIST policy-as-code |
| kube-linter | 0.8+ | Kubernetes security linting |
| kubeconform | 0.7+ | Kubernetes schema validation |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-04 | AI Agent | Initial architecture document |
| 1.1 | 2025-01-04 | AI Agent | Added CloudFormation and AMI constraints from lessons learned |
| 1.2 | 2025-01-04 | AI Agent | Added Bastion Access Architecture (SSM Session Manager) section |
| 1.3 | 2025-01-04 | AI Agent | Added Compute Requirements section with EKS add-on resource estimates |
| 1.4 | 2025-01-06 | AI Agent | Replaced Tempo with Prometheus+Kiali for metrics scraping and traffic visualization |
| 1.5 | 2025-01-06 | AI Agent | Corrected storage matrix (Tempo→Mimir), clarified nodes in 100.64.x.x subnets (no VPC CNI custom networking needed) |
| 1.6 | 2025-01-10 | AI Agent | Added Kafka WAL documentation for Mimir, updated data flow diagrams, added Mimir component details |
| 1.7 | 2025-01-10 | AI Agent | Replaced LGTM references with "Observability Stack" (Tempo removed) |
| 1.8 | 2025-01-10 | AI Agent | Added Tempo back for distributed tracing, added comprehensive flow diagrams for all add-ons |
| 1.9 | 2025-01-10 | AI Agent | Added Tempo to Version Information table, updated main data flow diagram to include Tempo |
| 2.0 | 2025-01-11 | AI Agent | Added Known Compliance Gaps section documenting SC-8 partial compliance for observability stack |
| 2.1 | 2025-01-11 | AI Agent | Added Keycloak SSO/OIDC for centralized authentication across all UI components |
| 2.2 | 2025-01-11 | AI Agent | Added IaC Validation Pipeline section (cfn-lint, cfn-guard for NIST compliance) |
| 3.0 | 2026-01-14 | AI Agent | Major: Replaced LGTM stack with SigNoz unified observability |
| 3.1 | 2026-01-15 | AI Agent | Replaced Keycloak with AWS Cognito (managed service) |
| 3.2 | 2026-01-17 | AI Agent | Re-added Kiali for Istio traffic visualization; updated ALB routing |
