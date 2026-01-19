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
| FR-050 | System SHALL use Claude LLM via AWS Bedrock | Must | Implemented |
| FR-051 | System SHALL orchestrate multiple specialized agents | Must | Implemented |
| FR-052 | System SHALL detect infrastructure drift | Should | Planned |
| FR-053 | System SHALL auto-remediate configuration drift | Could | Planned |

---

## 7. Agentic Solution Requirements

This section defines detailed requirements for the 4-agent infrastructure pipeline.

### 7.1 Pipeline Architecture Requirements

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-001 | Pipeline SHALL use LangGraph StateGraph for workflow orchestration | Must | Implemented | `core/graph.py` |
| AGT-002 | Pipeline SHALL support async execution | Must | Implemented | `core/graph.py` |
| AGT-003 | Pipeline SHALL maintain conversation state across agent transitions | Must | Implemented | `PipelineState` TypedDict |
| AGT-004 | Pipeline SHALL classify user intent (change/query/conversation) | Must | Implemented | `core/router.py` |
| AGT-005 | Pipeline SHALL support retry loops (Review → IaC) with max 3 attempts | Must | Implemented | `route_from_review()` |
| AGT-006 | Pipeline SHALL support dry-run mode (no deployment) | Must | Implemented | `dry_run` flag |

**Acceptance Criteria - AGT-001:**
- AC-001.1: Pipeline compiles without errors
- AC-001.2: Pipeline nodes include: orchestrator, planning, plan_approval, iac, review, deploy_approval, deploy_validate, k8s
- AC-001.3: Pipeline handles conditional routing based on state

**Acceptance Criteria - AGT-005:**
- AC-005.1: Review agent can return "needs_revision" status
- AC-005.2: IaC agent receives review feedback on retry
- AC-005.3: Pipeline terminates after max_retries exceeded

### 7.2 Agent Requirements

#### 7.2.1 Orchestrator Agent (Chat)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-010 | Orchestrator SHALL classify user intent using keywords and LLM fallback | Must | Implemented | `agents/chat/agent.py` |
| AGT-011 | Orchestrator SHALL route change requests to Planning Agent | Must | Implemented | `route_from_orchestrator()` |
| AGT-012 | Orchestrator SHALL route query requests to K8s Agent | Must | Implemented | `route_from_orchestrator()` |
| AGT-013 | Orchestrator SHALL handle conversational requests directly | Should | Implemented | `route_from_orchestrator()` |

**Acceptance Criteria - AGT-010:**
- AC-010.1: "create vpc" classified as "change"
- AC-010.2: "list pods" classified as "query"
- AC-010.3: "hello" classified as "conversation"

#### 7.2.2 Planning Agent

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-020 | Planning Agent SHALL generate requirements from user request | Must | Implemented | `agents/planning/agent.py` |
| AGT-021 | Planning Agent SHALL generate testable acceptance criteria | Must | Implemented | `AcceptanceCriteria` model |
| AGT-022 | Planning Agent SHALL identify files to modify | Must | Implemented | `FileToModify` model |
| AGT-023 | Planning Agent SHALL map requirements to NIST controls | Should | Implemented | `Requirement.nist_controls` |
| AGT-024 | Planning Agent SHALL assess impact level (low/medium/high) | Must | Implemented | `PlanningOutput.estimated_impact` |
| AGT-025 | Planning Agent SHALL flag PRD changes as requiring approval | Must | Implemented | `PlanningOutput.requires_approval` |

**Acceptance Criteria - AGT-021:**
- AC-021.1: Each AC has a unique ID (AC-xxx format)
- AC-021.2: Each AC has a test_command that can be executed
- AC-021.3: Each AC has an expected_result for validation

**Output Contract:** `PlanningOutput` (defined in `core/contracts.py`)

#### 7.2.3 IaC Agent

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-030 | IaC Agent SHALL implement changes based on PlanningOutput | Must | Implemented | `agents/iac/agent.py` |
| AGT-031 | IaC Agent SHALL modify CloudFormation templates | Must | Implemented | `_generate_file_change()` |
| AGT-032 | IaC Agent SHALL modify Helm values files | Must | Implemented | `_generate_file_change()` |
| AGT-033 | IaC Agent SHALL self-validate with cfn-lint before Review | Must | Implemented | `_validate_with_cfn_lint()` |
| AGT-034 | IaC Agent SHALL self-validate with kube-linter before Review | Must | Implemented | `_validate_with_kube_linter()` |
| AGT-035 | IaC Agent SHALL create feature branch per environment | Must | Implemented | `GitBranchConfig` |
| AGT-036 | IaC Agent SHALL commit changes with Co-Authored-By | Must | Implemented | `_create_git_commit()` |
| AGT-037 | IaC Agent SHALL push to remote origin | Must | Implemented | `_create_git_commit()` |
| AGT-038 | IaC Agent SHALL create PR/MR via REST API | Must | Implemented | `_create_github_pr()`, `_create_gitlab_mr()` |
| AGT-039 | IaC Agent SHALL handle retry with Review feedback | Must | Implemented | `review_notes` parameter |

**Acceptance Criteria - AGT-035:**
- AC-035.1: DEV changes create branch `feat/dev/{request-id}`
- AC-035.2: TST changes create branch `feat/tst/{request-id}`
- AC-035.3: PRD changes create branch `feat/prd/{request-id}`

**Acceptance Criteria - AGT-038:**
- AC-038.1: GitHub PR created via `POST /repos/{owner}/{repo}/pulls`
- AC-038.2: GitLab MR created via `POST /projects/{id}/merge_requests`
- AC-038.3: PR/MR body includes requirements and acceptance criteria

**Output Contract:** `IaCOutput` (defined in `core/contracts.py`)

#### 7.2.4 Review Agent

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-040 | Review Agent SHALL validate with cfn-guard (NIST rules) | Must | Implemented | `agents/review/tools.py` |
| AGT-041 | Review Agent SHALL validate with cfn-lint | Must | Implemented | `agents/review/tools.py` |
| AGT-042 | Review Agent SHALL validate with kube-linter | Must | Implemented | `agents/review/tools.py` |
| AGT-043 | Review Agent SHALL run security scan (secrets detection) | Must | Implemented | `agents/review/tools.py` |
| AGT-044 | Review Agent SHALL estimate cost impact | Should | Implemented | `CostEstimate` model |
| AGT-045 | Review Agent SHALL count blocking vs warning findings | Must | Implemented | `ReviewOutput.blocking_findings` |
| AGT-046 | Review Agent SHALL return status: passed/needs_revision/failed | Must | Implemented | `ReviewStatus` enum |
| AGT-047 | Review Agent SHALL provide remediation guidance for findings | Must | Implemented | `Finding.remediation` |

**Acceptance Criteria - AGT-046:**
- AC-046.1: "passed" when all gates pass and 0 blocking findings
- AC-046.2: "needs_revision" when blocking findings exist and retries left
- AC-046.3: "failed" when max retries exceeded

**Output Contract:** `ReviewOutput` (defined in `core/contracts.py`)

#### 7.2.5 Deploy & Validate Agent

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-050 | Deploy Agent SHALL execute CloudFormation deployments | Must | Implemented | `agents/deploy_validate/agent.py` |
| AGT-051 | Deploy Agent SHALL execute Helm upgrades | Must | Implemented | `agents/deploy_validate/agent.py` |
| AGT-052 | Deploy Agent SHALL validate acceptance criteria after deploy | Must | Implemented | `_validate_acceptance_criteria()` |
| AGT-053 | Deploy Agent SHALL rollback on validation failure | Must | Implemented | `RollbackInfo` model |
| AGT-054 | Deploy Agent SHALL report deployment duration | Should | Implemented | `DeploymentOutput.deployment_duration_seconds` |

**Acceptance Criteria - AGT-052:**
- AC-052.1: Each AC test_command is executed
- AC-052.2: actual_result is compared to expected_result
- AC-052.3: ValidationResult records pass/fail for each AC

**Output Contract:** `DeploymentOutput` (defined in `core/contracts.py`)

### 7.3 Approval Gate Requirements

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-060 | Pipeline SHALL pause at Plan Approval gate | Must | Implemented | `plan_approval_node()` |
| AGT-061 | Plan Approval SHALL display requirements and files to modify | Must | Implemented | `approval_prompt` |
| AGT-062 | Pipeline SHALL pause at Deploy Approval gate | Must | Implemented | `deploy_approval_node()` |
| AGT-063 | Deploy Approval SHALL display cost estimate | Must | Implemented | `cost_estimate` |
| AGT-064 | Deploy Approval SHALL display review results | Must | Implemented | `approval_prompt` |
| AGT-065 | Rejected approval SHALL terminate pipeline gracefully | Must | Implemented | `route_from_*_approval()` |

**Acceptance Criteria - AGT-063:**
- AC-063.1: Cost estimate shown in format "$+X.XX/month" or "$-X.XX/month"
- AC-063.2: Affected resources listed
- AC-063.3: "No significant cost impact" shown when no estimate available

### 7.4 Git Integration Requirements

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-070 | System SHALL support GitHub via REST API | Must | Implemented | `_create_github_pr()` |
| AGT-071 | System SHALL support GitLab via REST API | Must | Implemented | `_create_gitlab_mr()` |
| AGT-072 | Git platform SHALL be configurable via GIT_PLATFORM env var | Must | Implemented | `config.py` |
| AGT-073 | Branch naming SHALL follow pattern feat/{env}/{request-id} | Must | Implemented | `GitBranchConfig` |
| AGT-074 | PR target SHALL be develop for DEV, main for PRD | Must | Implemented | `GitBranchConfig.PR_TARGET_BRANCHES` |

**Acceptance Criteria - AGT-070:**
- AC-070.1: GitHub token read from GH_TOKEN or GITHUB_TOKEN env var
- AC-070.2: API call to `https://api.github.com/repos/{owner}/{repo}/pulls`
- AC-070.3: PR number and URL returned in PullRequest model

**Acceptance Criteria - AGT-071:**
- AC-071.1: GitLab token read from GITLAB_TOKEN or GL_TOKEN env var
- AC-071.2: API call to `{gitlab_url}/api/v4/projects/{path}/merge_requests`
- AC-071.3: MR number (iid) and URL returned in PullRequest model

### 7.5 Contract Requirements

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-080 | All agent outputs SHALL be Pydantic models | Must | Implemented | `core/contracts.py` |
| AGT-081 | Contracts SHALL be JSON serializable | Must | Implemented | `model_dump_json()` |
| AGT-082 | PlanningOutput SHALL pass through to downstream agents | Must | Implemented | `IaCOutput.planning_output` |
| AGT-083 | IaCOutput SHALL pass through to Review and Deploy agents | Must | Implemented | `ReviewOutput.iac_output` |

### 7.6 CLI Requirements

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-090 | CLI SHALL provide `pipeline` command | Must | Implemented | `main.py` |
| AGT-091 | CLI SHALL support --environment flag (dev/tst/prd) | Must | Implemented | `main.py` |
| AGT-092 | CLI SHALL support --dry-run flag | Must | Implemented | `main.py` |
| AGT-093 | CLI SHALL display approval prompts interactively | Must | Implemented | Rich Confirm |
| AGT-094 | CLI SHALL display pipeline progress | Must | Implemented | Rich Console |

**Test Command:**
```bash
infra-agent pipeline --environment dev --dry-run
```

### 7.7 Artifact Persistence Requirements

Pipeline artifacts SHALL be persisted to the git repo for traceability, audit, and compliance.

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-100 | Pipeline artifacts SHALL be persisted to `.infra-agent/requests/{request-id}/` | Must | Implemented | `core/artifacts.py` |
| AGT-101 | Planning output SHALL be saved as `requirements.yaml` | Must | Implemented | `ArtifactManager.save_planning_output()` |
| AGT-102 | IaC output SHALL be saved as `changes.yaml` | Must | Implemented | `ArtifactManager.save_iac_output()` |
| AGT-103 | Review output SHALL be saved as `review.yaml` | Must | Implemented | `ArtifactManager.save_review_output()` |
| AGT-104 | Deployment output SHALL be saved as `validation.yaml` | Must | Implemented | `ArtifactManager.save_deployment_output()` |
| AGT-105 | Human-readable summary SHALL be generated as `summary.md` | Must | Implemented | `ArtifactManager.generate_summary()` |
| AGT-106 | Artifacts SHALL use YAML format for human readability | Must | Implemented | PyYAML |
| AGT-107 | Artifacts SHALL be committed to git with IaC changes | Should | Pending | `IaCAgent._create_git_commit()` |
| AGT-108 | Summary.md SHALL be suitable for PR/MR descriptions | Should | Implemented | Markdown format |

**Artifact Directory Structure:**
```
.infra-agent/requests/
└── req-abc123/
    ├── requirements.yaml   # Planning output: requirements, acceptance criteria
    ├── changes.yaml        # IaC output: code changes, git commit, PR info
    ├── review.yaml         # Review output: findings, gate results, cost estimate
    ├── validation.yaml     # Deployment output: actions, test results
    └── summary.md          # Human-readable summary for PR description
```

**NIST Compliance:**
- AU-3 (Content of Audit Records): Artifacts capture what, when, who, outcome
- AU-12 (Audit Generation): Automatic persistence at each pipeline stage
- CM-3 (Configuration Change Control): Full traceability from request to deployment

### 7.8 Context-Aware Test Coverage Requirements

The Planning Agent SHALL generate context-aware acceptance criteria and test commands based on resource type.

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-110 | Planning Agent SHALL detect resource types from user requests | Must | Implemented | `agents/planning/agent.py` |
| AGT-111 | Helm/K8s resources SHALL have pod health, readiness, PVC, and endpoint tests | Must | Implemented | Planning prompt |
| AGT-112 | RDS resources SHALL have instance status, connectivity, security, and encryption tests | Must | Implemented | Planning prompt |
| AGT-113 | S3 resources SHALL have bucket existence, encryption, public access, and versioning tests | Must | Implemented | Planning prompt |
| AGT-114 | EKS node groups SHALL have node status, count, and ASG health tests | Must | Implemented | Planning prompt |
| AGT-115 | IAM resources SHALL have role existence, policy attachment, and trust relationship tests | Must | Implemented | Planning prompt |
| AGT-116 | CloudFormation stacks SHALL have stack status, outputs, and drift tests | Must | Implemented | Planning prompt |
| AGT-117 | Lambda functions SHALL have function existence, state, and invoke tests | Must | Implemented | Planning prompt |
| AGT-118 | Planning output SHALL include resource_types list for downstream agents | Must | Implemented | `PlanningOutput.resource_types` |
| AGT-119 | Planning output SHALL include estimated_monthly_cost based on resource guidelines | Should | Implemented | `PlanningOutput.estimated_monthly_cost` |

**Test Coverage by Resource Type:**

| Resource Type | Required Test Categories | Example Test Commands |
|---------------|-------------------------|----------------------|
| **Helm/K8s** | Pod health, Container readiness, PVC status, Service endpoints | `kubectl get pods -n <ns> -o jsonpath='{.items[*].status.phase}'` |
| **RDS** | Instance status, Connectivity, Security groups, Encryption | `aws rds describe-db-instances --query 'DBInstances[0].DBInstanceStatus'` |
| **S3** | Bucket existence, Encryption, Public access block, Versioning | `aws s3api head-bucket --bucket <name>` |
| **EKS** | Node status, Node count, ASG health | `kubectl get nodes -l eks.amazonaws.com/nodegroup=<name>` |
| **IAM** | Role existence, Policy attachment, Trust relationship | `aws iam get-role --role-name <name>` |
| **CloudFormation** | Stack status, Outputs, Drift detection | `aws cloudformation describe-stacks --stack-name <name>` |
| **Lambda** | Function existence, State active, Can invoke | `aws lambda get-function --function-name <name>` |

**Cost Estimation Guidelines:**

| Resource Category | Cost Range | Notes |
|-------------------|------------|-------|
| EC2/EKS nodes | $70-150/month per node | t3a.xlarge typical |
| Fargate | $40/vCPU/month | Pay per pod |
| EBS gp3 | $0.08/GB/month | Plus IOPS if provisioned |
| S3 | $0.023/GB/month | Standard class |
| RDS db.t3.medium | ~$50/month | Development |
| RDS db.r5.large | ~$200/month | Production |
| NAT Gateway | ~$45/month | Plus data transfer |
| ALB | ~$25/month | Plus LCU charges |

### 7.9 Investigation Agent Requirements

The Investigation Agent diagnoses issues and troubleshoots problems. It operates independently from the 4-agent pipeline.

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-120 | Investigation Agent SHALL diagnose pod/node/service health issues | Must | Implemented | `agents/investigation/agent.py` |
| AGT-121 | Investigation Agent SHALL analyze logs and events for error patterns | Must | Implemented | `agents/investigation/tools.py` |
| AGT-122 | Investigation Agent SHALL check resource usage (CPU/memory) | Must | Implemented | `resource_usage` tool |
| AGT-123 | Investigation Agent SHALL check AWS resource status (EC2, EBS, EKS) | Must | Implemented | `ec2_status`, `ebs_status`, `eks_nodegroup_status` tools |
| AGT-124 | Investigation Agent SHALL query CloudWatch logs | Should | Implemented | `cloudwatch_logs` tool |
| AGT-125 | Investigation Agent SHALL provide root cause analysis | Must | Implemented | `InvestigationOutput.root_cause` |
| AGT-126 | Investigation Agent SHALL identify if IaC changes are needed | Should | Implemented | `InvestigationOutput.requires_iac_change` |

**Investigation Tools (15 tools):**

| Tool | Purpose | Command/API |
|------|---------|-------------|
| `pod_health_check` | Check pod status | `kubectl get pods -n <ns> -o wide` |
| `pod_logs` | Get pod logs | `kubectl logs <pod> -n <ns> --tail=100` |
| `pod_events` | Get K8s events | `kubectl get events -n <ns> --sort-by=.lastTimestamp` |
| `pod_describe` | Detailed pod info | `kubectl describe pod <pod> -n <ns>` |
| `resource_usage` | CPU/Memory usage | `kubectl top pods -n <ns>` |
| `node_status` | Node health | `kubectl get nodes -o wide` |
| `pvc_status` | PVC status | `kubectl get pvc -n <ns>` |
| `service_endpoints` | Service endpoints | `kubectl get endpoints -n <ns>` |
| `ec2_status` | EC2 instance status | `aws ec2 describe-instance-status` |
| `eks_nodegroup_status` | Node group status | `aws eks describe-nodegroup` |
| `cloudwatch_logs` | CloudWatch logs | `aws logs filter-log-events` |
| `ebs_status` | EBS volume status | `aws ec2 describe-volumes` |
| `signoz_metrics` | SigNoz metrics | SigNoz API |
| `signoz_logs` | SigNoz logs | SigNoz API |
| `signoz_traces` | SigNoz traces | SigNoz API |

**Output Contract:** `InvestigationOutput` (defined in `core/contracts.py`)

### 7.10 Audit Agent Requirements

The Audit Agent performs compliance, security, cost, and drift audits. It operates independently from the 4-agent pipeline.

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-130 | Audit Agent SHALL verify NIST 800-53 compliance controls | Must | Implemented | `nist_control_check` tool |
| AGT-131 | Audit Agent SHALL audit encryption at rest and in transit | Must | Implemented | `encryption_audit`, `istio_mtls_check` tools |
| AGT-132 | Audit Agent SHALL audit IAM policies and public access | Must | Implemented | `iam_audit`, `public_access_check` tools |
| AGT-133 | Audit Agent SHALL retrieve Trivy vulnerability scan results | Must | Implemented | `trivy_results` tool |
| AGT-134 | Audit Agent SHALL detect idle and unattached resources | Should | Implemented | `idle_resource_check`, `unattached_resources` tools |
| AGT-135 | Audit Agent SHALL detect CloudFormation and Helm drift | Must | Implemented | `cfn_drift`, `helm_drift`, `k8s_drift` tools |
| AGT-136 | Audit Agent SHALL provide overall compliance score | Should | Implemented | `AuditOutput.overall_score` |
| AGT-137 | Audit Agent SHALL provide prioritized recommendations | Must | Implemented | `AuditOutput.top_recommendations` |

**Audit Types:**

| Type | Description | Tools Used |
|------|-------------|------------|
| COMPLIANCE | NIST 800-53 control verification | `nist_control_check`, `encryption_audit`, `istio_mtls_check` |
| SECURITY | Security posture assessment | `iam_audit`, `public_access_check`, `trivy_results`, `network_policy_audit` |
| COST | Cost optimization analysis | `kubecost_query`, `idle_resource_check`, `rightsizing_recommendations`, `unattached_resources` |
| DRIFT | Configuration drift detection | `cfn_drift`, `helm_drift`, `k8s_drift` |
| FULL | Comprehensive audit covering all areas | All tools |

**Audit Tools (14 tools):**

| Tool | Purpose | Command/API |
|------|---------|-------------|
| `nist_control_check` | NIST control verification | Multiple checks (SC-8, SC-28, AC-2, etc.) |
| `encryption_audit` | Encryption at rest/transit | AWS describe + Istio check |
| `istio_mtls_check` | Istio mTLS verification | `kubectl get peerauthentication` |
| `iam_audit` | IAM policy review | `aws iam list-*`, `get-role` |
| `public_access_check` | Public access detection | S3, SG checks |
| `trivy_results` | Vulnerability scan results | `kubectl get vulnerabilityreports` |
| `network_policy_audit` | Network policy review | `kubectl get networkpolicies` |
| `kubecost_query` | Cost data | Kubecost API |
| `idle_resource_check` | Idle resources | `kubectl top pods` |
| `rightsizing_recommendations` | Rightsizing analysis | Usage vs requests |
| `unattached_resources` | Unattached volumes/IPs | `aws ec2 describe-volumes` |
| `cfn_drift` | CloudFormation drift | `aws cloudformation detect-stack-drift` |
| `helm_drift` | Helm values drift | `helm get values` |
| `k8s_drift` | K8s resource drift | Compare live vs IaC |

**Output Contract:** `AuditOutput` (defined in `core/contracts.py`)

### 7.11 Traceability Matrix

| Requirement | Implementation File | Test File | Status |
|-------------|---------------------|-----------|--------|
| AGT-001 | `core/graph.py` | `tests/test_graph.py` | Needs Test |
| AGT-010 | `agents/chat/agent.py` | `tests/agents/test_chat.py` | Needs Test |
| AGT-020-025 | `agents/planning/agent.py` | `tests/agents/test_planning.py` | Needs Test |
| AGT-030-039 | `agents/iac/agent.py` | `tests/agents/test_iac.py` | Needs Test |
| AGT-040-047 | `agents/review/agent.py` | `tests/agents/test_review.py` | Needs Test |
| AGT-050-054 | `agents/deploy_validate/agent.py` | `tests/agents/test_deploy.py` | Needs Test |
| AGT-060-065 | `core/graph.py` | `tests/test_approval_gates.py` | Needs Test |
| AGT-070-074 | `agents/iac/agent.py` | `tests/agents/test_git_integration.py` | Needs Test |
| AGT-080-083 | `core/contracts.py` | `tests/test_contracts.py` | Needs Test |
| AGT-090-094 | `main.py` | `tests/test_cli.py` | Needs Test |
| AGT-100-108 | `core/artifacts.py` | `tests/test_artifacts.py` | Needs Test |
| AGT-110-119 | `agents/planning/agent.py` | `tests/agents/test_planning.py` | Needs Test |
| AGT-120-126 | `agents/investigation/agent.py` | `tests/agents/test_investigation.py` | Needs Test |
| AGT-130-137 | `agents/audit/agent.py` | `tests/agents/test_audit.py` | Needs Test |

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

### Phase 2: AI Agent Implementation ✅ COMPLETE

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FUT-001 | LangGraph agent orchestration | High | ✅ Implemented (Section 7) |
| FUT-002 | Claude integration via Bedrock | High | ✅ Implemented |
| FUT-003 | Automated drift detection | Medium | Planned |
| FUT-004 | Auto-remediation workflows | Medium | Planned |

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
| 1.3 | 2026-01-18 | AI Agent | Add Section 7: Agentic Solution Requirements (AGT-001 to AGT-094), update FR-050/FR-051 to Implemented, mark Phase 2 complete |
