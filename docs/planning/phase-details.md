# AI Infrastructure Agent - Phase Details

This document provides detailed implementation specifications for each phase of the AI Infrastructure Agent project.

---

## Phase 1: Foundation

**Duration:** First major milestone
**Prerequisites:** None
**Goal:** Core infrastructure, networking, and agent framework

### 1A: Documentation & Planning

| Task | Description | Output |
|------|-------------|--------|
| architecture.md | Executive summary, assumptions, constraints, component diagrams | `docs/architecture.md` |
| phase-details.md | This document - detailed phase breakdown | `docs/planning/phase-details.md` |
| access-urls.md | All component URLs and access instructions | `docs/access-urls.md` |
| infrastructure-build.md | VPC/EKS build workflow | `docs/workflows/infrastructure-build.md` |
| nist-compliance.md | NIST control implementation guide | `docs/workflows/nist-compliance.md` |
| deployment-pipeline.md | CI/CD pipeline documentation | `docs/workflows/deployment-pipeline.md` |

### 1B: Agent Framework

| Component | File | Description |
|-----------|------|-------------|
| Project Setup | `pyproject.toml` | Python project with dependencies |
| Entry Point | `src/infra_agent/main.py` | CLI entry point |
| Configuration | `src/infra_agent/config.py` | Environment and settings management |
| LangGraph State | `src/infra_agent/core/state.py` | State schema for agent communication |
| Graph Builder | `src/infra_agent/core/graph.py` | LangGraph state machine construction |
| Router | `src/infra_agent/core/router.py` | Intent classification and routing |
| Base Agent | `src/infra_agent/agents/base.py` | Abstract base class for all agents |
| Chat Agent | `src/infra_agent/agents/chat/agent.py` | Supervisor agent with CLI |
| Bedrock Client | `src/infra_agent/llm/bedrock.py` | Claude via AWS Bedrock |

**Dependencies:**
```toml
[project]
name = "infra-agent"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "langgraph>=0.2.0",
    "langchain-aws>=0.2.0",
    "langchain-core>=0.3.0",
    "boto3>=1.35.0",
    "cfn-lint>=1.0.0",
    "click>=8.1.0",
    "pydantic>=2.0.0",
    "rich>=13.0.0",
    "python-dotenv>=1.0.0",
]
```

### 1C: Network Architecture

**CloudFormation Stacks:**

| Stack | Template | Resources |
|-------|----------|-----------|
| VPC | `00-foundation/vpc.yaml` | VPC, Subnets (public/private/pod), IGW, NAT Gateways |
| Security | `00-foundation/security-groups.yaml` | ALB SG, Bastion SG, EKS Nodes SG, RDS SG |
| IAM | `00-foundation/iam-roles.yaml` | EKS Cluster Role, Node Group Role, Service Account Roles |

**Subnet CIDR Allocation:**

| Type | AZ-a | AZ-b | AZ-c | Purpose |
|------|------|------|------|---------|
| Public | 10.0.0.0/22 | 10.0.4.0/22 | 10.0.8.0/22 | ALB |
| Private | 10.0.48.0/22 | 10.0.52.0/22 | 10.0.56.0/22 | Bastion, NAT, RDS |
| Pod | 100.64.0.0/18 | 100.64.64.0/18 | 100.64.128.0/18 | EKS Pods (non-routable) |

**Security Group Rules:**

```yaml
# ALB Security Group
ALBSecurityGroup:
  Ingress:
    - Port: 443, Source: 0.0.0.0/0
  Egress:
    - Port: All, Dest: EKSNodesSecurityGroup

# Bastion Security Group
BastionSecurityGroup:
  Ingress:
    - Port: 22, Source: VPN-CIDR (via Session Manager preferred)
  Egress:
    - Port: All, Dest: 0.0.0.0/0 (via NAT)

# EKS Nodes Security Group
EKSNodesSecurityGroup:
  Ingress:
    - Port: All, Source: ALBSecurityGroup
    - Port: All, Source: EKSNodesSecurityGroup (pod-to-pod)
  Egress:
    - Port: All, Dest: 0.0.0.0/0 (via NAT)

# RDS Security Group
RDSSecurityGroup:
  Ingress:
    - Port: 5432, Source: EKSNodesSecurityGroup
  Egress:
    - None
```

### 1D: NIST Controls Implementation

| Control | Implementation | Validation |
|---------|---------------|------------|
| AU-2 | VPC Flow Logs → CloudWatch | cfn-guard rule checks FlowLog resource exists |
| AU-3 | Flow log format includes all required fields | Template specifies LogFormat |
| SC-7 | NACLs with deny rules | cfn-guard validates NACL entries |
| SC-8 | TLS-only SG rules | cfn-guard checks port 443 only for public ingress |
| AC-2 | IAM roles defined | cfn-guard validates role structure |
| AC-6 | No wildcard resources | cfn-guard checks Resource != "*" |
| CM-8 | Mandatory tags | cfn-guard validates tag presence |
| CM-3 | Git versioning | IaC_Version tag contains commit SHA |

**cfn-guard Rules:**

```ruby
# infra/cloudformation/cfn-guard-rules/nist-800-53/phase1-controls.guard

# AU-2: VPC must have flow logs
rule vpc_has_flow_logs when resourceType == "AWS::EC2::VPC" {
    # Check that a FlowLog resource exists referencing this VPC
    some %FlowLogs[*].ResourceId == this.id
}

# CM-8: All resources must have mandatory tags
rule mandatory_tags {
    Tags exists
    Tags is_list
    Tags[*] {
        Key in ["Environment", "Owner", "SecurityLevel", "IaC_Version"]
    }
}

# AC-6: No wildcard resource ARNs in IAM policies
rule no_wildcard_resources when resourceType == "AWS::IAM::Role" {
    Policies[*].PolicyDocument.Statement[*] {
        Resource != "*"
    }
}

# SC-7: NACLs must have explicit deny rules
rule nacl_has_deny when resourceType == "AWS::EC2::NetworkAcl" {
    some Entries[*].RuleAction == "deny"
}
```

### 1A-2: EKS Admin Console (Headlamp)

**Helm Values:**

```yaml
# infra/helm/values/headlamp/values.yaml
replicaCount: 2

image:
  repository: ghcr.io/headlamp-k8s/headlamp
  tag: "v0.26.0"

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: true
  className: alb
  annotations:
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
  hosts:
    - host: headlamp.infra-agent.internal
      paths:
        - path: /
          pathType: Prefix

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi

# RBAC for admin access
serviceAccount:
  create: true
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/infra-agent-dev-headlamp-role
```

---

## Phase 2: IaC Agent & EKS Cluster

**Duration:** After Phase 1 completion
**Prerequisites:** VPC, Subnets, IAM roles from Phase 1
**Goal:** CloudFormation management and EKS cluster deployment

### 2A: IaC Agent Development

| Component | File | Description |
|-----------|------|-------------|
| IaC Agent | `src/infra_agent/agents/iac/agent.py` | CloudFormation management agent |
| Tools | `src/infra_agent/agents/iac/tools.py` | cfn-lint, cfn-guard, change set tools |
| Validators | `src/infra_agent/agents/iac/validators.py` | Template validation functions |
| Templates | `src/infra_agent/agents/iac/templates.py` | Template generation utilities |

**Agent Tools:**

```python
@tool
def validate_template(template_path: str) -> dict:
    """Run cfn-lint and cfn-guard validation."""

@tool
def create_change_set(stack_name: str, template: str, params: dict) -> dict:
    """Create CloudFormation change set for review."""

@tool
def execute_change_set(change_set_name: str, stack_name: str) -> dict:
    """Execute approved change set."""

@tool
def check_mandatory_tags(template: dict) -> dict:
    """Verify template has required tags."""

@tool
def get_stack_status(stack_name: str) -> dict:
    """Get current stack status."""
```

### 2B: EKS Cluster Deployment

**CloudFormation Stacks:**

| Stack | Template | Resources |
|-------|----------|-----------|
| EKS Cluster | `03-eks/cluster.yaml` | EKS Cluster, OIDC Provider, KMS Key |
| Node Groups | `03-eks/node-groups.yaml` | Managed Node Groups, Launch Templates |
| Add-ons | `03-eks/addons.yaml` | VPC CNI, CoreDNS, kube-proxy, EBS CSI, LB Controller |

**EKS Configuration:**

```yaml
# Key settings
EKSCluster:
  Version: "1.32"
  EndpointPrivateAccess: true
  EndpointPublicAccess: false  # Zero Trust
  EncryptionConfig:
    Provider: KMS
    Resources: ["secrets"]
  Logging:
    - api
    - audit
    - authenticator
    - controllerManager
    - scheduler

NodeGroup:
  InstanceTypes: ["m5.large", "m5a.large"]
  ScalingConfig:
    MinSize: 2
    MaxSize: 10
    DesiredSize: 3
  Subnets: Pod Subnets (100.64.x.x)
```

**NIST Controls:**

| Control | Implementation |
|---------|---------------|
| SC-28 | KMS encryption for Kubernetes secrets |
| AC-6 | IRSA for pod-level AWS permissions |
| CM-8 | All resources tagged |

---

## Phase 3: K8s Agent & Core Services

**Duration:** After Phase 2 completion
**Prerequisites:** Running EKS cluster
**Goal:** Kubernetes operations and observability stack

### K8s Agent

| Component | File | Description |
|-----------|------|-------------|
| K8s Agent | `src/infra_agent/agents/k8s/agent.py` | Kubernetes operations agent |
| kubectl | `src/infra_agent/agents/k8s/kubectl.py` | kubectl command wrapper |
| Helm | `src/infra_agent/agents/k8s/helm.py` | Helm chart management |

**Agent Tools:**

```python
@tool
def kubectl_get(resource: str, namespace: str) -> dict:
    """Get Kubernetes resources."""

@tool
def helm_install(release: str, chart: str, values: dict) -> dict:
    """Install Helm chart."""

@tool
def helm_upgrade(release: str, chart: str, values: dict) -> dict:
    """Upgrade Helm release."""

@tool
def get_pod_logs(pod: str, namespace: str) -> str:
    """Get pod logs."""
```

### Helm Deployments

| Release | Chart | Namespace | Purpose |
|---------|-------|-----------|---------|
| istio-base | istio/base | istio-system | Istio CRDs |
| istiod | istio/istiod | istio-system | Istio control plane |
| istio-gateway | istio/gateway | istio-system | Ingress gateway |
| loki | grafana/loki | observability | Log aggregation |
| tempo | grafana/tempo | observability | Distributed tracing |
| mimir | grafana/mimir | observability | Metrics storage |
| grafana | grafana/grafana | observability | Visualization |
| metrics-server | metrics-server/metrics-server | kube-system | HPA metrics |
| cluster-autoscaler | autoscaler/cluster-autoscaler | kube-system | Node autoscaling |

---

## Phase 4: Security Agent & Scanning

**Duration:** After Phase 3 completion
**Prerequisites:** K8s Agent, EKS cluster
**Goal:** Security scanning and compliance validation

### Security Agent

| Component | File | Description |
|-----------|------|-------------|
| Security Agent | `src/infra_agent/agents/security/agent.py` | Security operations |
| Trivy | `src/infra_agent/agents/security/trivy.py` | Vulnerability scanning |
| NIST | `src/infra_agent/agents/security/nist.py` | NIST control validation |

**Agent Tools:**

```python
@tool
def scan_image(image: str) -> dict:
    """Scan container image with Trivy."""

@tool
def validate_nist_control(control_id: str, config: dict) -> dict:
    """Validate specific NIST control."""

@tool
def check_security_gates(results: dict) -> dict:
    """Evaluate all security gates."""

@tool
def get_vulnerability_report(namespace: str) -> dict:
    """Get Trivy Operator report."""
```

### Trivy Operator Deployment

```yaml
# infra/helm/values/trivy-operator/values.yaml
operator:
  vulnerabilityScannerEnabled: true
  configAuditScannerEnabled: true
  rbacAssessmentScannerEnabled: true

trivy:
  severity: "CRITICAL,HIGH,MEDIUM"
  ignoreUnfixed: true

compliance:
  cron: "0 */6 * * *"  # Scan every 6 hours
```

---

## Phase 5: Deployment Agent & CI/CD

**Duration:** After Phase 4 completion
**Prerequisites:** Security Agent, EKS cluster
**Goal:** Automated deployments and Blue/Green strategy

### Deployment Agent

| Component | File | Description |
|-----------|------|-------------|
| Deploy Agent | `src/infra_agent/agents/deployment/agent.py` | Deployment orchestration |
| GitHub | `src/infra_agent/agents/deployment/github_actions.py` | GitHub Actions integration |
| Blue/Green | `src/infra_agent/agents/deployment/blue_green.py` | Blue/Green deployment |

**Agent Tools:**

```python
@tool
def trigger_pipeline(workflow: str, inputs: dict) -> dict:
    """Trigger GitHub Actions workflow."""

@tool
def blue_green_deploy(service: str, version: str) -> dict:
    """Initiate Blue/Green deployment."""

@tool
def shift_traffic(blue_weight: int, green_weight: int) -> dict:
    """Shift traffic between environments."""

@tool
def rollback(service: str, version: str) -> dict:
    """Rollback to previous version."""
```

### GitHub Actions Workflows

| Workflow | Trigger | Actions |
|----------|---------|---------|
| ci.yaml | Push to any branch | Lint, Test, Build |
| deploy-dev.yaml | Merge to develop | Deploy to DEV, Run tests |
| deploy-tst.yaml | DEV tests pass | Deploy to TST, Run tests |
| deploy-prd.yaml | TST tests pass | Blue/Green deploy to PRD |

---

## Phase 6: Verification Agent & Drift Detection

**Duration:** After Phase 5 completion
**Prerequisites:** Deployment Agent
**Goal:** Automated testing and drift management

### Verification Agent

| Component | File | Description |
|-----------|------|-------------|
| Verify Agent | `src/infra_agent/agents/verification/agent.py` | Testing and validation |
| Drift | `src/infra_agent/agents/verification/drift.py` | Drift detection |
| Test Gen | `src/infra_agent/agents/verification/test_generator.py` | Auto-generate tests |

**Agent Tools:**

```python
@tool
def detect_drift(stack_name: str) -> dict:
    """Detect CloudFormation drift."""

@tool
def remediate_drift(stack_name: str, resource_id: str) -> dict:
    """Revert drifted resource."""

@tool
def generate_tests(template_path: str) -> dict:
    """Auto-generate infrastructure tests."""

@tool
def run_health_check(service: str) -> dict:
    """Validate service health."""
```

---

## Phase 7: Cost Agent & Operations

**Duration:** After Phase 6 completion
**Prerequisites:** Verification Agent
**Goal:** Cost management and resource optimization

### Cost Agent

| Component | File | Description |
|-----------|------|-------------|
| Cost Agent | `src/infra_agent/agents/cost/agent.py` | Cost management |
| Kubecost | `src/infra_agent/agents/cost/kubecost.py` | Kubecost integration |
| Reaper | `src/infra_agent/agents/cost/reaper.py` | Idle resource cleanup |

**Agent Tools:**

```python
@tool
def get_cost_allocation(namespace: str) -> dict:
    """Get cost breakdown from Kubecost."""

@tool
def identify_idle_resources(hours: int = 72) -> list:
    """Find resources with no traffic."""

@tool
def reap_resource(resource_type: str, resource_id: str) -> dict:
    """Delete idle resource (DEV only)."""

@tool
def generate_cost_report(period: str) -> dict:
    """Generate cost report."""
```

### Velero Backup Configuration

```yaml
# infra/helm/values/velero/values.yaml
configuration:
  provider: aws
  backupStorageLocation:
    bucket: infra-agent-dev-velero-backups
    config:
      region: us-east-1
  volumeSnapshotLocation:
    config:
      region: us-east-1

schedules:
  daily-backup:
    schedule: "0 1 * * *"
    template:
      ttl: "720h"  # 30 days
      includedNamespaces:
        - "*"
```

---

## Phase 8: Multi-Environment & Production

**Duration:** After Phase 7 completion
**Prerequisites:** All agents operational
**Goal:** TST and PRD environment deployment

### Environment Configuration

| Environment | AWS Account | EKS Cluster | RDS Instance |
|-------------|-------------|-------------|--------------|
| DEV | dev-account | infra-agent-dev-cluster | infra-agent-dev-postgres |
| TST | tst-account | infra-agent-tst-cluster | infra-agent-tst-postgres |
| PRD | prd-account | infra-agent-prd-cluster | infra-agent-prd-postgres |

### PRD-Specific Controls

| Feature | Implementation |
|---------|---------------|
| MFA Gate | All PRD operations require MFA verification |
| JIT Access | Temporary STS AssumeRole tokens (1 hour max) |
| Approval | Human approval required for PRD deployments |
| Cross-Region Backup | Velero backups to us-west-2 |
| Blue/Green | ALB target group switching for zero downtime |

---

## Phase 9: Testing & Documentation

**Duration:** Final phase
**Prerequisites:** All phases complete
**Goal:** Complete testing and documentation

### Test Coverage

| Test Type | Framework | Coverage Target |
|-----------|-----------|-----------------|
| Unit | pytest | 80%+ per agent |
| Integration | pytest + moto | AWS service interactions |
| Compliance | cfn-guard + custom | 100% NIST controls |
| E2E | pytest | Full deployment workflow |

### Documentation Deliverables

| Document | Purpose |
|----------|---------|
| architecture.md | System architecture |
| phase-details.md | Implementation guide |
| access-urls.md | Component access |
| operator-runbook.md | Day-to-day operations |
| nist-compliance-report.md | Control attestation |
| api-reference.md | Agent API documentation |

---

## Success Criteria

### Phase 1 Success
- [ ] All documentation created
- [ ] VPC deployed with Zero Trust networking
- [ ] Chat Agent responds to commands
- [ ] cfn-guard validates templates

### Phase 2 Success
- [ ] IaC Agent creates/updates stacks
- [ ] EKS cluster running
- [ ] kubectl access working

### Phase 3 Success
- [ ] Istio mTLS enabled
- [ ] LGTM stack operational
- [ ] Grafana dashboards accessible

### Phase 4 Success
- [ ] Trivy scans pass
- [ ] NIST controls validated
- [ ] Security gates enforced

### Phase 5 Success
- [ ] GitHub Actions pipelines working
- [ ] Blue/Green deployments functional
- [ ] Rollback tested

### Phase 6 Success
- [ ] Drift detection operational
- [ ] Auto-remediation working
- [ ] Test coverage generated

### Phase 7 Success
- [ ] Kubecost reporting costs
- [ ] Velero backups running
- [ ] Idle resource reaping (DEV)

### Phase 8 Success
- [ ] TST environment operational
- [ ] PRD environment operational
- [ ] Cross-region backup verified

### Phase 9 Success
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Security assessment passed
