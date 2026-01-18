# Infra-Agent System Requirements

This document defines all requirements for the AI-powered Infrastructure Agent system managing AWS EKS clusters with NIST 800-53 Rev 5 compliance.

---

## 1. Functional Requirements

### 1.1 Infrastructure Provisioning

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-001 | System SHALL provision AWS EKS clusters via CloudFormation | Must | Implemented |
| FR-002 | System SHALL support three environments: DEV, TST, PRD | Must | DEV Implemented |
| FR-003 | System SHALL deploy Kubernetes workloads via Helm charts | Must | Implemented |
| FR-004 | System SHALL validate all CloudFormation templates before deployment | Must | Implemented |
| FR-005 | System SHALL enforce IaC as the single source of truth | Must | Implemented |
| FR-006 | System SHALL support Blue/Green deployments for PRD | Should | Not Started |

### 1.2 Observability

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-010 | System SHALL collect metrics from all Kubernetes workloads | Must | Implemented (SigNoz) |
| FR-011 | System SHALL collect logs from all containers | Must | Implemented (SigNoz) |
| FR-012 | System SHALL support distributed tracing | Must | Implemented (SigNoz) |
| FR-013 | System SHALL provide unified observability dashboard | Must | Implemented (SigNoz) |
| FR-014 | System SHALL visualize service mesh traffic | Should | Implemented (Kiali) |
| FR-015 | System SHALL support alerting on metrics thresholds | Should | Implemented (SigNoz) |
| FR-016 | System SHALL provide IaC-managed observability dashboards | Must | Implemented |
| FR-017 | System SHALL provide K8s operations dashboard replacing 80% of Headlamp usage | Should | Implemented |

#### 1.2.1 Required Observability Dashboards

Dashboards are managed as IaC in `infra/helm/values/signoz/dashboards/` and deployed via script.

| Dashboard | File | Purpose | Panels |
|-----------|------|---------|--------|
| **K8s Operations** | `k8s-operations.json` | Comprehensive cluster ops (replaces Headlamp for monitoring) | 20 panels |
| **Cluster Overview** | `kubernetes-cluster-metrics.json` | Simple cluster metrics overview | 4 panels |

**K8s Operations Dashboard Sections:**

| Section | Panels | Metrics Used |
|---------|--------|--------------|
| **Pod Status** | Pods by Namespace, Pod Phase Distribution (pie) | `k8s.pod.phase` |
| **Workloads** | Deployments, StatefulSets, DaemonSets (available vs desired) | `k8s.deployment.*`, `k8s.statefulset.*`, `k8s.daemonset.*` |
| **Container Health** | Container Restarts (top 15), Restart Trend | `k8s.container.restarts` |
| **Storage** | PVC Capacity, PVC Available Space | `k8s.volume.capacity`, `k8s.volume.available` |
| **Resources** | CPU/Memory Limit Utilization by Namespace | `k8s.pod.cpu_limit_utilization`, `k8s.pod.memory_limit_utilization` |
| **Node Health** | Node Conditions (Ready, DiskPressure, MemoryPressure, PIDPressure) | `k8s.node.condition_*` |
| **Jobs & HPA** | Job Status, HPA Status | `k8s.job.*`, `k8s.hpa.*` |

**What K8s Operations Dashboard Replaces:**

| Headlamp Feature | Dashboard Coverage |
|------------------|-------------------|
| Pod list/status | ✅ Pod Status section |
| Deployment status | ✅ Workloads section |
| StatefulSet status | ✅ Workloads section |
| DaemonSet status | ✅ Workloads section |
| Container restarts | ✅ Container Health section |
| PVC usage | ✅ Storage section |
| Resource usage | ✅ Resources section |
| Node conditions | ✅ Node Health section |
| Job status | ✅ Jobs & HPA section |
| HPA status | ✅ Jobs & HPA section |
| Create/Edit resources | ❌ Use kubectl |
| Exec into pods | ❌ Use kubectl |
| View/Edit YAML | ❌ Use kubectl |

**Dashboard Persistence:**

Dashboards are stored in SigNoz's ClickHouse database (EBS-backed PV) and survive normal restarts. However, if SigNoz requires reinstallation (e.g., PV AZ-binding issues), dashboards must be redeployed from IaC:

```bash
./scripts/deploy-signoz-dashboards.sh --delete-existing
```

### 1.3 Security Scanning

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-020 | System SHALL scan container images for vulnerabilities | Must | Implemented (Trivy) |
| FR-021 | System SHALL audit Kubernetes RBAC configurations | Must | Implemented (Trivy) |
| FR-022 | System SHALL detect exposed secrets in images | Must | Implemented (Trivy) |
| FR-023 | System SHALL generate vulnerability reports as Kubernetes CRDs | Should | Implemented (Trivy) |

### 1.4 Backup & Recovery

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-030 | System SHALL backup Kubernetes resources to S3 | Must | Implemented (Velero) |
| FR-031 | System SHALL backup persistent volumes (EBS snapshots) | Must | Implemented (Velero) |
| FR-032 | System SHALL support scheduled backups (daily, weekly) | Must | Configured |
| FR-033 | System SHALL support point-in-time restore | Should | Implemented |
| FR-034 | System SHALL achieve 4-hour RTO for disaster recovery | Should | Not Validated |

### 1.5 Cost Management

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-040 | System SHALL track costs by namespace | Must | Implemented (Kubecost) |
| FR-041 | System SHALL track costs by deployment/pod | Should | Implemented (Kubecost) |
| FR-042 | System SHALL detect idle resources | Should | Implemented (Kubecost) |
| FR-043 | System SHALL provide right-sizing recommendations | Should | Implemented (Kubecost) |

### 1.6 AI Agent Capabilities

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-050 | System SHALL use Claude LLM via AWS Bedrock | Must | Planned |
| FR-051 | System SHALL orchestrate multiple specialized agents | Must | Planned |
| FR-052 | System SHALL detect infrastructure drift | Should | Planned |
| FR-053 | System SHALL auto-remediate configuration drift | Could | Planned |

---

## 2. Non-Functional Requirements

### 2.1 Performance

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-001 | EKS cluster SHALL handle minimum 100 pods | Must | Validated |
| NFR-002 | Observability data retention SHALL be minimum 15 days | Must | Configured |
| NFR-003 | Log query response time SHALL be < 5 seconds for 24hr range | Should | Not Validated |
| NFR-004 | Metrics query response time SHALL be < 3 seconds | Should | Not Validated |

### 2.2 Availability

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-010 | EKS control plane availability SHALL be 99.95% (AWS SLA) | Must | AWS Managed |
| NFR-011 | Worker nodes SHALL span minimum 3 Availability Zones | Must | Implemented |
| NFR-012 | Observability stack SHALL survive single node failure | Should | Partial (StatefulSet) |
| NFR-013 | System SHALL support graceful shutdown/startup procedures | Must | Implemented |

### 2.3 Scalability

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-020 | Worker node group SHALL auto-scale 3-10 nodes | Must | Configured |
| NFR-021 | System SHALL support Horizontal Pod Autoscaling | Should | Not Configured |
| NFR-022 | ClickHouse storage SHALL be expandable without downtime | Could | Not Validated |

### 2.4 Security (See Section 3 for NIST details)

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-030 | All data at rest SHALL be encrypted (KMS) | Must | Implemented |
| NFR-031 | All data in transit SHALL be encrypted (TLS/mTLS) | Must | Partial |
| NFR-032 | All user access SHALL require authentication | Must | Implemented (Cognito) |
| NFR-033 | No IAM wildcard permissions | Must | Implemented |

### 2.5 Operability

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-040 | System SHALL be deployable from IaC in < 1 hour | Should | Not Validated |
| NFR-041 | All configuration SHALL be version controlled (Git) | Must | Implemented |
| NFR-042 | System SHALL provide Kubernetes admin UI | Should | Implemented (Headlamp) |
| NFR-043 | System SHALL support SSM Session Manager for bastion access | Must | Implemented |

---

## 3. NIST 800-53 Rev 5 Compliance Requirements

### 3.1 Access Control (AC)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| AC-2 | Account Management | AWS Cognito user pool, Cognito groups | Implemented |
| AC-3 | Access Enforcement | K8s RBAC, Cognito → K8s role mapping | Implemented |
| AC-6 | Least Privilege | No wildcard IAM, scoped K8s roles | Implemented |
| AC-17 | Remote Access | SSM Session Manager (no SSH) | Implemented |

### 3.2 Audit and Accountability (AU)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| AU-2 | Audit Events | VPC Flow Logs, K8s audit logs, SigNoz | Implemented |
| AU-3 | Content of Audit Records | User identity in K8s audit (via EKS OIDC) | Implemented |
| AU-6 | Audit Review | SigNoz dashboards, Kiali traffic graph | Implemented |
| AU-9 | Protection of Audit Information | EBS encryption, access controls | Implemented |
| AU-11 | Audit Record Retention | 15 days (configurable) | Configured |

### 3.3 Configuration Management (CM)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| CM-2 | Baseline Configuration | CloudFormation templates, Helm values | Implemented |
| CM-3 | Configuration Change Control | Git + IaC only, no direct changes | Implemented |
| CM-6 | Configuration Settings | cfn-guard NIST rules | Implemented |
| CM-8 | System Component Inventory | Mandatory tagging, Trivy inventory | Implemented |

### 3.4 Contingency Planning (CP)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| CP-6 | Alternate Storage Site | S3 cross-region replication | Not Implemented |
| CP-9 | System Backup | Velero daily/weekly backups | Implemented |
| CP-10 | System Recovery | Velero restore, CloudFormation re-deploy | Implemented |

### 3.5 Identification and Authentication (IA)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| IA-2 | Identification and Authentication | AWS Cognito OIDC | Implemented |
| IA-5 | Authenticator Management | Cognito password policies | Implemented |
| IA-8 | Identification of Non-Organizational Users | N/A (internal only) | N/A |

### 3.6 Risk Assessment (RA)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| RA-5 | Vulnerability Scanning | Trivy Operator continuous scanning | Implemented |

### 3.7 System and Communications Protection (SC)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| SC-7 | Boundary Protection | VPC, NACLs, Security Groups, non-routable pod subnets | Implemented |
| SC-8 | Transmission Confidentiality | Istio mTLS, ALB TLS 1.3 | **Partial** |
| SC-28 | Protection of Information at Rest | KMS encryption (EBS, S3, Secrets) | Implemented |

**SC-8 Gap:** Istio mTLS not enabled on all namespaces due to resource constraints. See Known Compliance Gaps in architecture.md.

### 3.8 System and Information Integrity (SI)

| Control | Requirement | Implementation | Status |
|---------|-------------|----------------|--------|
| SI-2 | Flaw Remediation | Trivy vulnerability reports | Implemented |
| SI-4 | System Monitoring | SigNoz metrics/logs/traces | Implemented |

---

## 4. Infrastructure Requirements

### 4.1 AWS Resources

| Resource | Configuration | Environment |
|----------|--------------|-------------|
| **VPC** | Primary: 10.0.0.0/16, Secondary: 100.64.0.0/16 | All |
| **Subnets** | 3 public, 3 private, 3 EKS node (per AZ) | All |
| **NAT Gateways** | 3 (one per AZ) | All |
| **EKS Cluster** | v1.34, private endpoint only | All |
| **Node Group** | t3a.xlarge, min 3, max 10 | DEV |
| **Bastion** | t3a.medium, SSM-only access | All |
| **ALB** | HTTPS:443, Cognito auth | All |
| **Cognito** | User pool, app client, domain | All |
| **S3** | Velero backups | All |
| **KMS** | EKS secrets encryption | All |

### 4.2 EKS Add-ons (AWS Managed)

| Add-on | Version | Purpose |
|--------|---------|---------|
| VPC CNI | v1.21+ | Pod networking |
| CoreDNS | v1.12+ | DNS resolution |
| kube-proxy | v1.34+ | Service proxy |
| EBS CSI Driver | v1.54+ | Persistent volumes |

### 4.3 Helm Chart Add-ons

| Add-on | Namespace | Chart | Purpose |
|--------|-----------|-------|---------|
| Istio | istio-system | istio/base, istiod, gateway | Service mesh, mTLS |
| SigNoz | signoz | signoz/signoz | Observability |
| Kiali | istio-system | kiali/kiali-operator | Traffic visualization |
| Trivy | trivy-system | aqua/trivy-operator | Security scanning |
| Velero | velero | vmware-tanzu/velero | Backup/restore |
| Kubecost | kubecost | kubecost/cost-analyzer | Cost management |
| Headlamp | headlamp | headlamp/headlamp | Admin console |

### 4.4 Compute Requirements

| Category | CPU (vCPU) | Memory (Gi) |
|----------|------------|-------------|
| Istio + sidecars | ~3.2 | ~7 |
| SigNoz + ClickHouse | ~1.5 | ~2.5 |
| Security/Operations | ~0.5 | ~1.2 |
| AWS Controllers | ~0.4 | ~0.5 |
| K8s Core | ~0.6 | ~0.7 |
| **Total (no buffer)** | **~6.2** | **~12** |
| **Total (30% buffer)** | **~8** | **~16** |

**Recommended:** 3x t3a.xlarge nodes (4 vCPU, 16 Gi each) = 12 vCPU, 48 Gi total

### 4.5 EKS Node Lifecycle

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| NFR-050 | EKS nodes SHALL terminate on scale-down (not stop) | Must | By Design |
| NFR-051 | EKS nodes SHALL launch fresh on scale-up (not start) | Must | By Design |
| NFR-052 | PersistentVolumes SHALL survive node termination | Must | Implemented |
| NFR-053 | Bastion instance SHALL stop/start (preserve state) | Must | Implemented |

**Design Rationale:**

EKS Managed Node Groups use AWS Auto Scaling Groups (ASG), which are designed for ephemeral compute:

| Component | Scale Down | Scale Up | State |
|-----------|------------|----------|-------|
| **EKS Nodes** | Terminate | Launch new | Ephemeral (cattle) |
| **Bastion** | Stop | Start | Persistent (pet) |

**Why nodes terminate (not stop):**
- Kubernetes nodes are "cattle, not pets" - designed to be disposable
- ASG manages instance lifecycle - terminate/launch is the only supported operation
- Fresh nodes ensure clean state without configuration drift
- AWS best practice for managed Kubernetes

**What IS preserved across node termination:**
- EBS PersistentVolumes (AZ-bound, reattach to new nodes in same AZ)
- Kubernetes state (stored in etcd on AWS-managed control plane)
- Pod definitions (Deployments/StatefulSets recreate pods on new nodes)
- ConfigMaps and Secrets (stored in etcd)

**What is NOT preserved:**
- Local ephemeral storage (emptyDir volumes)
- Node-specific cache (container image cache rebuilt)
- In-memory state (pods restart fresh)

**Alternative for stop/start behavior (NOT recommended):**
- Self-managed node groups with standalone EC2 instances
- Adds operational complexity
- Loses ASG benefits (auto-replacement, rolling updates)
- Not aligned with Kubernetes design principles

---

## 5. Operational Requirements

### 5.1 Startup Procedure

| Step | Requirement | Implementation |
|------|-------------|----------------|
| 1 | Start bastion instance | scripts/graceful-startup.sh |
| 2 | Wait for SSM agent (60s) | scripts/graceful-startup.sh |
| 3 | Scale nodes to minimum 3 | scripts/graceful-startup.sh |
| 4 | Wait for nodes Ready | kubectl get nodes -w |
| 5 | Verify StatefulSets recovered | kubectl get pods -n signoz |

**Critical:** ALWAYS scale to minimum 3 nodes for multi-AZ coverage. EBS volumes are AZ-bound.

### 5.2 Shutdown Procedure

| Step | Requirement | Implementation |
|------|-------------|----------------|
| 1 | Verify no critical jobs running | kubectl get jobs -A |
| 2 | Scale nodes to 0 | scripts/graceful-shutdown.sh |
| 3 | Wait for nodes terminated | aws eks describe-nodegroup |
| 4 | Stop bastion instance | scripts/graceful-shutdown.sh |

### 5.3 IaC Validation

| Type | Tool | Must Pass |
|------|------|-----------|
| CloudFormation syntax | cfn-lint | 0 errors |
| CloudFormation NIST | cfn-guard | 0 FAIL |
| Kubernetes schema | kubeconform | 0 invalid |
| Kubernetes security | kube-linter | 0 errors |

**Never deploy without validation.**

### 5.4 Dashboard Deployment

SigNoz dashboards are managed as IaC and deployed via script.

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/deploy-signoz-dashboards.sh` | Deploy all dashboards from IaC | `./scripts/deploy-signoz-dashboards.sh` |
| Same script with flag | Clean deploy (delete existing first) | `./scripts/deploy-signoz-dashboards.sh --delete-existing` |

**Prerequisites:**
- SSM tunnel running (`./scripts/tunnel.sh`)
- `SIGNOZ_API_KEY` in `.env` file (create in SigNoz UI → Settings → API Keys)
- `jq` installed (`brew install jq`)

**Dashboard IaC Location:**
```
infra/helm/values/signoz/dashboards/
├── k8s-operations.json           # Comprehensive K8s operations
├── kubernetes-cluster-metrics.json  # Simple cluster overview
└── README.md                     # Documentation
```

**When to Run:**
- After fresh SigNoz installation
- After SigNoz reinstallation (PV issues)
- After adding new dashboard JSON files to the IaC directory
- After cluster recovery from backup

### 5.5 Access Methods

| Service | Internet (ALB) | Local (port-forward) |
|---------|----------------|---------------------|
| SigNoz | https://{alb}/ | localhost:3301 |
| Headlamp | https://{alb}/headlamp/ | localhost:8080 |
| Kubecost | https://{alb}/kubecost/ | localhost:9091 |
| Kiali | https://{alb}/kiali/ | localhost:20001 |

---

## 6. Future Requirements (Roadmap)

### Phase 2: AI Agent Implementation

| ID | Requirement | Priority |
|----|-------------|----------|
| FUT-001 | LangGraph agent orchestration | High |
| FUT-002 | Claude integration via Bedrock | High |
| FUT-003 | Automated drift detection | Medium |
| FUT-004 | Auto-remediation workflows | Medium |

### Phase 3: Production Readiness

| ID | Requirement | Priority |
|----|-------------|----------|
| FUT-010 | TST environment deployment | High |
| FUT-011 | PRD environment deployment | High |
| FUT-012 | Blue/Green deployment automation | High |
| FUT-013 | Cross-region DR (S3 replication) | Medium |
| FUT-014 | Full SC-8 compliance (mTLS everywhere) | High |

### Phase 4: Advanced Features

| ID | Requirement | Priority |
|----|-------------|----------|
| FUT-020 | GitOps with ArgoCD | Medium |
| FUT-021 | Policy enforcement with OPA/Gatekeeper | Medium |
| FUT-022 | Service mesh authorization policies | Medium |
| FUT-023 | Secret rotation automation | Low |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-17 | AI Agent | Initial requirements document |
| 1.1 | 2026-01-17 | AI Agent | Add EKS Node Lifecycle requirements (NFR-050 to NFR-053) |
| 1.2 | 2026-01-18 | AI Agent | Add observability dashboard requirements (FR-016, FR-017), dashboard deployment script |
