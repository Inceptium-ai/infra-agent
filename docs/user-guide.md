# Infra-Agent Operator Guide

A comprehensive guide for operators to interact with the AI Infrastructure Agent for managing AWS EKS clusters.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [How the Agent Works](#how-the-agent-works)
3. [Investigating Issues](#investigating-issues)
4. [Running Audits](#running-audits)
5. [Making Infrastructure Changes](#making-infrastructure-changes)
6. [Creating New Infrastructure](#creating-new-infrastructure)
7. [Querying Infrastructure](#querying-infrastructure)
8. [Pipeline Artifacts](#pipeline-artifacts)
9. [Common Workflows](#common-workflows)

---

## Quick Start

### Prerequisites

**1. Install infra-agent (using virtual environment):**
```bash
cd /Users/ymuwakki/infra-agent

# Create and activate virtual environment (one-time)
python3 -m venv .venv
source .venv/bin/activate

# Install infra-agent in editable mode
pip install -e .
```

**Note:** Always activate the venv before running infra-agent:
```bash
source /Users/ymuwakki/infra-agent/.venv/bin/activate
```

**2. Start SSM tunnel (required for EKS access):**

The EKS cluster has a **private endpoint only** - there is no public API access. The SSM tunnel creates a secure connection through the bastion host so the agent can run `kubectl` and `helm` commands against the cluster.

```bash
# Keep this running in a separate terminal
./scripts/tunnel.sh
```

**3. Configure kubectl (one-time after tunnel starts):**
```bash
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1
sed -i.bak 's|https://C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com|https://localhost:6443|' ~/.kube/config
kubectl config set-cluster arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster --insecure-skip-tls-verify=true
```

**4. Configure environment (optional):**
```bash
# Copy example and set your values
cp .env.example .env

# Required for Investigation/Audit agents to query SigNoz:
# SIGNOZ_API_KEY=your-signoz-api-key
```

### Why the Tunnel is Required

| Agent | Why Tunnel Needed |
|-------|-------------------|
| Investigation Agent | Runs `kubectl logs`, `kubectl describe`, `kubectl get events` |
| Audit Agent | Runs `kubectl get networkpolicies`, checks Trivy reports, Velero status |
| K8s Agent | Runs `kubectl get pods`, `helm list`, status queries |
| Deploy Agent | Runs `helm upgrade`, validates deployments |

Without the tunnel, any command that touches the Kubernetes API will fail with connection errors.

### Running the Agent

```bash
# Interactive chat mode (recommended)
infra-agent chat -e dev

# Pipeline mode with approval gates
infra-agent pipeline -e dev

# Dry-run mode (no actual deployments)
infra-agent pipeline -e dev --dry-run
```

---

## Quick Reference: Example Commands

Here are 15 example prompts showing what you can do with infra-agent:

### Investigation Examples (Troubleshooting)

| # | What You Say | What Happens |
|---|--------------|--------------|
| 1 | `Why are SigNoz pods restarting?` | Checks pod events, logs, resource usage; identifies OOMKilled or CrashLoopBackOff; suggests fixes |
| 2 | `Debug why the frontend is returning 503 errors` | Examines service endpoints, pod health, Istio config; finds unhealthy backends |
| 3 | `Investigate high memory usage in signoz namespace` | Queries SigNoz metrics, kubectl top; identifies memory-hungry pods |
| 4 | `Why are nodes showing NotReady?` | Checks node conditions, EC2 status, EKS nodegroup; finds disk pressure or network issues |

### Audit Examples (Compliance & Cost)

| # | What You Say | What Happens |
|---|--------------|--------------|
| 5 | `Audit NIST 800-53 compliance` | Checks SC-8 (mTLS), SC-28 (encryption), AC-6 (least privilege), AU-2 (logging); scores 0-100% |
| 6 | `Run a security scan` | Checks IAM policies, public access, Trivy vulnerabilities, network policies; lists findings |
| 7 | `Find cost optimization opportunities` | Queries Kubecost, finds idle pods, unattached EBS, oversized resources; estimates savings |
| 8 | `Check for configuration drift` | Compares CloudFormation stacks and Helm releases against live state; lists drifted resources |

### Change Examples (4-Agent Pipeline)

| # | What You Say | What Happens |
|---|--------------|--------------|
| 9 | `Scale SigNoz frontend to 3 replicas` | Planning → IaC (updates Helm values) → Review → Deploy; creates PR, runs helm upgrade |
| 10 | `Increase node group max size to 10` | Planning → IaC (updates CloudFormation) → Review → Deploy; creates PR, deploys stack |
| 11 | `Enable Istio mTLS STRICT for signoz namespace` | Planning → IaC (creates PeerAuthentication) → Review → Deploy |

### Create Examples (New Resources)

| # | What You Say | What Happens |
|---|--------------|--------------|
| 12 | `Create an S3 bucket for logs with encryption` | Generates CloudFormation template with SSE, versioning, public access block; deploys |
| 13 | `Create a new namespace called staging with Istio` | Generates namespace YAML with `istio-injection: enabled` label; applies |
| 14 | `Add an IAM role for the demo app with S3 read access` | Generates CloudFormation with scoped IAM policy; deploys |

### Query Examples (Information Only)

| # | What You Say | What Happens |
|---|--------------|--------------|
| 15 | `List all pods in signoz namespace` | Runs `kubectl get pods -n signoz`; shows table |
| 16 | `Show node status` | Runs `kubectl get nodes -o wide`; shows Ready/NotReady status |
| 17 | `What Helm releases are installed?` | Runs `helm list -A`; shows all releases |

### Example Session

```
$ infra-agent chat -e dev

╭──────────────── infra-agent ────────────────╮
│ AI Infrastructure Agent v0.1.0              │
│ AWS EKS Management with NIST 800-53 R5      │
╰─────────────────────────────────────────────╯

Environment: DEV
EKS Cluster: infra-agent-dev-cluster

You: Why are SigNoz pods restarting?

Agent: Investigating pods in signoz namespace...

**Investigation Complete** (ID: inv-a1b2c3)

**Root Cause:** ClickHouse pods hitting 256Mi memory limit under query load.

**Findings:**
- [HIGH] 15 OOMKilled events in past hour
- [MEDIUM] Memory at 98% utilization

**Recommendation:** Increase memory limit to 1Gi
**IaC Change Required:** Yes - update infra/helm/values/signoz/values.yaml

You: Update SigNoz ClickHouse memory limit to 1Gi

Agent: Starting 4-agent pipeline...

Step 1: Planning Agent → Plan generated
Step 2: IaC Agent → Modified values.yaml, PR #42 created
Step 3: Review Agent → Passed (no security issues)
Step 4: Deploy Agent → helm upgrade complete

**Pipeline Complete** - Successfully updated memory limit

You: List pods in signoz namespace

Agent:
NAME                          READY   STATUS    RESTARTS   AGE
signoz-clickhouse-0           1/1     Running   0          2m
signoz-frontend-7d8f9b6c5     1/1     Running   0          1d
...
```

---

## How the Agent Works

### Intent Classification

When you send a message, the agent automatically classifies your intent and routes to the appropriate handler:

| Your Intent | Example Phrases | What Happens |
|-------------|-----------------|--------------|
| **Investigate** | "why is", "debug", "troubleshoot", "failing", "not working" | → Investigation Agent diagnoses the issue |
| **Audit** | "audit", "compliance", "security scan", "cost analysis", "drift" | → Audit Agent runs assessment |
| **Change** | "update", "modify", "scale", "enable", "configure" | → 4-Agent Pipeline (Planning → IaC → Review → Deploy) |
| **Create** | "create", "add", "deploy", "install" | → 4-Agent Pipeline |
| **Delete** | "delete", "remove", "destroy" | → 4-Agent Pipeline (requires approval) |
| **Query** | "list", "show", "get", "describe", "status" | → K8s Agent (direct query) |

### The 4-Agent Pipeline

For infrastructure changes, your request flows through:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Planning   │───►│     IaC      │───►│    Review    │───►│   Deploy &   │
│    Agent     │    │    Agent     │    │    Agent     │    │   Validate   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
  requirements.yaml   changes.yaml      review.yaml       validation.yaml
```

---

## Investigating Issues

Use investigation when something is broken, slow, or behaving unexpectedly.

### Example Prompts

```
Why are SigNoz pods restarting?
```
```
Debug why the frontend service is returning 503 errors
```
```
Investigate high memory usage in the signoz namespace
```
```
Troubleshoot connectivity issues between services in demo namespace
```
```
Why are nodes showing NotReady status?
```
```
Diagnose why PVCs are stuck in Pending state
```

### What Happens

1. **Agent gathers evidence** using tools:
   - Checks pod health, events, logs
   - Examines resource usage (CPU/memory)
   - Queries AWS for EC2/EBS/EKS status
   - Analyzes metrics and traces

2. **Agent produces findings** with:
   - Root cause analysis
   - Severity ratings (CRITICAL, HIGH, MEDIUM, LOW)
   - Immediate remediation steps
   - Long-term recommendations

### Example Session

**You:** `Why are SigNoz pods restarting?`

**Agent:**
```
**Investigation Complete** (ID: inv-a1b2c3d4)

**Status:** COMPLETED

**Summary:**
SigNoz ClickHouse pods are experiencing OOMKilled events due to memory limits
being set too low for current query workload.

**Root Cause:** Memory limit of 256Mi is insufficient for ClickHouse under
normal query load. Pods are being terminated when memory exceeds limit.

**Findings:**
- [HIGH] FIND-001: ClickHouse pods OOMKilled
  Evidence: 15 OOMKilled events in past 1 hour
  Affected: signoz-clickhouse-0, signoz-clickhouse-1

- [MEDIUM] FIND-002: Memory utilization at 98%
  Evidence: kubectl top shows 250Mi/256Mi usage

**Immediate Actions:**
- Increase memory limit to 1Gi in Helm values

**Follow-up Actions:**
- Add memory-based HPA for ClickHouse pods
- Monitor memory trends in SigNoz dashboard

**IaC Change Required:** Yes
Update: infra/helm/values/signoz/values.yaml
Change: clickhouse.resources.limits.memory: "256Mi" → "1Gi"

*Resources examined: namespace/signoz, pod/signoz-clickhouse-0, pod/signoz-clickhouse-1*
```

### After Investigation

If the agent identifies an IaC change is needed, follow up with:

```
Update SigNoz ClickHouse memory limit to 1Gi
```

This triggers the 4-Agent Pipeline to make the change properly through IaC.

---

## Running Audits

Use audits to assess compliance, security posture, cost optimization, or configuration drift.

### Audit Types

| Type | What to Say | What It Checks |
|------|-------------|----------------|
| **Compliance** | "audit NIST compliance" | SC-8, SC-28, AC-2, AC-6, AU-2, CM-2, CP-9, RA-5 |
| **Security** | "run a security scan" | IAM, public access, vulnerabilities, network policies |
| **Cost** | "find cost savings" | Idle resources, rightsizing, unattached volumes |
| **Drift** | "check for drift" | CloudFormation, Helm, K8s resource drift |
| **Full** | "audit everything" | All of the above |

### Example Prompts

```
Audit my infrastructure for NIST 800-53 compliance
```
```
Run a security scan and identify vulnerabilities
```
```
Find idle resources and cost optimization opportunities
```
```
Check for configuration drift in CloudFormation stacks
```
```
Assess security posture of the signoz namespace
```

### Example Session - Compliance Audit

**You:** `Audit NIST compliance`

**Agent:**
```
**Audit Complete** (ID: audit-x1y2z3)

**Type:** COMPLIANCE
**Status:** COMPLETED
**Overall Score:** 85%

**Summary:**
NIST 800-53 Rev 5 compliance audit completed. 12 controls passed, 1 failed,
2 partially implemented.

**Compliance Results:**
- Passed: 12
- Failed: 1
- Partial: 2

  [PASS] SC-28: Protection of Information at Rest
    Evidence: All EBS volumes encrypted, S3 buckets have encryption enabled

  [PASS] AC-2: Account Management
    Evidence: Cognito user pool configured with 2 groups (platform-admins, developers)

  [PASS] AU-2: Audit Events
    Evidence: CloudTrail enabled, VPC Flow Logs active, EKS audit logging on

  [PARTIAL] SC-8: Transmission Confidentiality
    Evidence: Istio mTLS enabled for 5/8 namespaces
    Remediation: Enable STRICT mTLS for velero, trivy-system, kiali-operator

  [FAIL] AC-6: Least Privilege
    Evidence: Role "infra-agent-dev-deploy-role" has AdministratorAccess
    Remediation: Replace with scoped IAM policy

**Top Recommendations:**
1. Remove AdministratorAccess from infra-agent-dev-deploy-role
2. Enable Istio mTLS STRICT for remaining namespaces
3. Add NetworkPolicies to demo namespace

**Note:** IaC changes required to remediate findings.
```

### Example Session - Cost Audit

**You:** `Find idle resources and cost savings`

**Agent:**
```
**Audit Complete** (ID: audit-c0s7)

**Type:** COST
**Status:** COMPLETED

**Summary:**
Cost optimization audit found $127/month in potential savings across idle
resources, oversized workloads, and unattached volumes.

**Cost Findings:**
- [COST-001] Idle pods detected
  Category: idle
  Resources: 3 pods with <5m CPU usage for 72+ hours
  Potential Savings: $15/month

- [COST-002] Unattached EBS volumes
  Category: unattached
  Resources: 5 volumes totaling 100GB (vol-abc123, vol-def456, ...)
  Current Cost: $8/month
  Potential Savings: $8/month

- [COST-003] Oversized pods
  Category: oversized
  Resources: signoz-frontend using 50m/500m CPU requested
  Potential Savings: $25/month
  Recommendation: Reduce CPU request to 100m

- [COST-004] Unassociated Elastic IPs
  Category: unattached
  Resources: 2 EIPs (52.1.2.3, 52.4.5.6)
  Current Cost: $7.30/month
  Potential Savings: $7.30/month

**Total Potential Monthly Savings:** $127.30

**Top Recommendations:**
1. Delete 5 unattached EBS volumes (save $8/month)
2. Release 2 unused Elastic IPs (save $7.30/month)
3. Rightsize signoz-frontend CPU request (save $25/month)
4. Review 3 idle pods for removal
```

---

## Making Infrastructure Changes

Use change requests to modify existing infrastructure. Changes go through the full 4-Agent Pipeline with approval gates.

### Example Prompts

```
Scale SigNoz frontend to 3 replicas for high availability
```
```
Increase node group max size to 10 nodes
```
```
Enable Istio mTLS STRICT mode for the signoz namespace
```
```
Update Velero backup retention to 30 days
```
```
Add resource limits to all pods in demo namespace
```
```
Configure HPA for signoz-frontend with min 2 max 5 replicas
```

### What Happens - Full Pipeline Example

**You:** `Scale SigNoz frontend to 3 replicas`

**Step 1: Planning Agent**
```
**Starting infrastructure change pipeline** (Request: req-f7e8d9c0)

Step 1: Planning Agent analyzing request...

**Plan Generated:**

Summary: Increase SigNoz frontend replicas from 1 to 3 for high availability

Requirements:
- REQ-001: SigNoz frontend deployment SHALL have 3 replicas
  Type: non-functional
  Priority: medium
  NIST Controls: CP-10 (System Recovery)

Acceptance Criteria:
- AC-001: Frontend has 3 running replicas
  Test: kubectl get deploy signoz-frontend -n signoz -o jsonpath='{.status.readyReplicas}'
  Expected: 3

Files to Modify:
- infra/helm/values/signoz/values.yaml
  Change: frontend.replicaCount: 1 → 3

Estimated Impact: low
Estimated Monthly Cost: +$0 (no new resources)
Requires Approval: No

─────────────────────────────────────────
Approve this plan? [y/n]:
```

**You:** `y`

**Step 2: IaC Agent**
```
Step 2: IaC Agent implementing changes...

Modified: infra/helm/values/signoz/values.yaml
  - frontend.replicaCount: 1 → 3

Self-validation:
  - kube-linter: PASSED (0 errors, 0 warnings)

Git Operations:
  - Branch: feat/dev/req-f7e8d9c0
  - Commit: abc123def "feat: Scale SigNoz frontend to 3 replicas"
  - Pushed to: origin/feat/dev/req-f7e8d9c0
  - PR #42 created: https://github.com/org/infra-agent/pull/42
```

**Step 3: Review Agent**
```
Step 3: Review Agent validating changes...

Validation Results:
  - kube-linter: PASSED
  - Security scan: PASSED (no secrets detected)

Cost Estimate: +$0/month (using existing node capacity)

Review Status: PASSED

─────────────────────────────────────────
Proceed with deployment? [y/n]:
```

**You:** `y`

**Step 4: Deploy & Validate Agent**
```
Step 4: Deploy & Validate Agent executing...

Deployment Actions:
  - helm upgrade signoz signoz/signoz -n signoz -f values.yaml
  - Status: SUCCESS
  - Duration: 45.2s

Validation Results:
  - AC-001: PASSED
    Actual: 3
    Expected: 3

**Pipeline Complete** (Request: req-f7e8d9c0)

All stages completed successfully:
- Planning: OK
- IaC Implementation: OK
- Review: PASSED
- Deploy & Validate: SUCCESS

Summary: Successfully scaled SigNoz frontend to 3 replicas
```

### Files Produced

After the pipeline completes, artifacts are saved to:

```
.infra-agent/requests/req-f7e8d9c0/
├── requirements.yaml     # Planning output
├── changes.yaml          # IaC changes made
├── review.yaml           # Validation results
├── validation.yaml       # Deployment results
└── summary.md            # Human-readable summary (for PR description)
```

---

## Creating New Infrastructure

Use create requests to provision new resources. These also go through the 4-Agent Pipeline.

### Example Prompts - Kubernetes

```
Deploy Kiali for Istio traffic visualization
```
```
Create a new namespace called staging with Istio injection enabled
```
```
Install Prometheus for Kiali metrics
```
```
Add a new HorizontalPodAutoscaler for the demo-frontend deployment
```

### Example Prompts - AWS

```
Create a new S3 bucket for application logs with encryption enabled
```
```
Add a new security group rule allowing port 8080 from the VPC CIDR
```
```
Create an RDS PostgreSQL instance for the application database
```
```
Add a new IAM role for the demo application with S3 read access
```

### Example Session - Create S3 Bucket

**You:** `Create a new S3 bucket for application logs with encryption and versioning`

**Agent:**
```
**Starting infrastructure change pipeline** (Request: req-s3logs01)

Step 1: Planning Agent analyzing request...

**Plan Generated:**

Summary: Create S3 bucket for application logs with encryption, versioning,
and public access block

Requirements:
- REQ-001: S3 bucket SHALL be created with name pattern {prefix}-app-logs
- REQ-002: S3 bucket SHALL have SSE-S3 encryption enabled (SC-28)
- REQ-003: S3 bucket SHALL have versioning enabled (CP-9)
- REQ-004: S3 bucket SHALL block all public access (AC-3)

Acceptance Criteria:
- AC-001: Bucket exists
  Test: aws s3api head-bucket --bucket infra-agent-dev-app-logs
  Expected: Exit code 0

- AC-002: Encryption enabled
  Test: aws s3api get-bucket-encryption --bucket infra-agent-dev-app-logs
  Expected: SSEAlgorithm: AES256

- AC-003: Versioning enabled
  Test: aws s3api get-bucket-versioning --bucket infra-agent-dev-app-logs
  Expected: Status: Enabled

- AC-004: Public access blocked
  Test: aws s3api get-public-access-block --bucket infra-agent-dev-app-logs
  Expected: BlockPublicAcls: true, BlockPublicPolicy: true

Files to Modify:
- infra/cloudformation/stacks/02-data/app-logs-bucket.yaml (NEW)

Estimated Impact: low
Estimated Monthly Cost: ~$2.30/month (assuming 100GB storage)

─────────────────────────────────────────
Approve this plan? [y/n]:
```

### Files Created for CloudFormation

The IaC Agent creates:

```yaml
# infra/cloudformation/stacks/02-data/app-logs-bucket.yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: S3 bucket for application logs

Parameters:
  Environment:
    Type: String
    Default: dev
  ResourcePrefix:
    Type: String
    Default: infra-agent

Resources:
  AppLogsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${ResourcePrefix}-${Environment}-app-logs'
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      VersioningConfiguration:
        Status: Enabled
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      Tags:
        - Key: Environment
          Value: !Ref Environment
        - Key: ManagedBy
          Value: infra-agent

Outputs:
  BucketName:
    Value: !Ref AppLogsBucket
    Export:
      Name: !Sub '${ResourcePrefix}-${Environment}-app-logs-bucket'
```

---

## Querying Infrastructure

Use queries to get information without making changes. Queries are handled directly by the K8s Agent.

### Example Prompts

```
List all pods in the signoz namespace
```
```
Show me the status of all deployments
```
```
Get the logs from signoz-frontend pod
```
```
Describe the signoz-clickhouse-0 pod
```
```
What Helm releases are installed?
```
```
Show me the node status
```
```
List all PVCs across all namespaces
```

### Example Session

**You:** `List all pods in signoz namespace`

**Agent:**
```
**Pods in signoz namespace:**

NAME                                    READY   STATUS    RESTARTS   AGE
signoz-clickhouse-0                     1/1     Running   0          2d
signoz-clickhouse-1                     1/1     Running   0          2d
signoz-clickhouse-2                     1/1     Running   0          2d
signoz-frontend-7d8f9b6c5-abc12         1/1     Running   0          1d
signoz-frontend-7d8f9b6c5-def34         1/1     Running   0          1d
signoz-frontend-7d8f9b6c5-ghi56         1/1     Running   0          1d
signoz-otel-collector-6b7c8d9e0-jkl78   1/1     Running   0          2d
signoz-query-service-5a6b7c8d9-mno90    1/1     Running   0          2d
```

**You:** `Show node status`

**Agent:**
```
**Cluster Nodes:**

NAME                          STATUS   ROLES    AGE   VERSION   CPU   MEMORY
ip-10-0-1-123.ec2.internal    Ready    <none>   5d    v1.34.0   4     16Gi
ip-10-0-2-456.ec2.internal    Ready    <none>   5d    v1.34.0   4     16Gi
ip-10-0-3-789.ec2.internal    Ready    <none>   5d    v1.34.0   4     16Gi

All 3 nodes are Ready across 3 availability zones.
```

---

## Pipeline Artifacts

Every change request produces artifacts in `.infra-agent/requests/{request-id}/`:

### requirements.yaml

```yaml
# Planning Agent output
request_id: req-f7e8d9c0
summary: Scale SigNoz frontend to 3 replicas for high availability
resource_types:
  - helm
requirements:
  - id: REQ-001
    description: SigNoz frontend deployment SHALL have 3 replicas
    type: non-functional
    priority: medium
    nist_controls:
      - CP-10
acceptance_criteria:
  - id: AC-001
    requirement_id: REQ-001
    description: Frontend has 3 running replicas
    test_command: kubectl get deploy signoz-frontend -n signoz -o jsonpath='{.status.readyReplicas}'
    expected_result: "3"
files_to_modify:
  - path: infra/helm/values/signoz/values.yaml
    change_type: helm
    description: Update frontend.replicaCount from 1 to 3
estimated_impact: low
estimated_monthly_cost: 0.0
requires_approval: false
```

### changes.yaml

```yaml
# IaC Agent output
request_id: req-f7e8d9c0
code_changes:
  - file_path: infra/helm/values/signoz/values.yaml
    change_type: helm
    diff_summary: Changed frontend.replicaCount from 1 to 3
    lines_added: 1
    lines_removed: 1
git_commit:
  commit_sha: abc123def456789
  branch: feat/dev/req-f7e8d9c0
  message: "feat: Scale SigNoz frontend to 3 replicas"
  files_changed:
    - infra/helm/values/signoz/values.yaml
  pushed_to_remote: true
pull_request:
  number: 42
  url: https://github.com/org/infra-agent/pull/42
  title: "feat: Scale SigNoz frontend to 3 replicas"
  source_branch: feat/dev/req-f7e8d9c0
  target_branch: develop
  status: open
  platform: github
self_lint_passed: true
retry_count: 0
```

### review.yaml

```yaml
# Review Agent output
request_id: req-f7e8d9c0
status: passed
cfn_guard_passed: true
cfn_lint_passed: true
kube_linter_passed: true
security_scan_passed: true
findings: []
cost_estimate:
  monthly_delta: 0.0
  affected_resources:
    - signoz-frontend
  notes: Using existing node capacity
blocking_findings: 0
warning_findings: 0
should_retry: false
```

### validation.yaml

```yaml
# Deploy & Validate Agent output
request_id: req-f7e8d9c0
status: success
deployment_actions:
  - action_type: helm_upgrade
    resource_name: signoz
    status: success
    duration_seconds: 45.2
    output: "Release 'signoz' has been upgraded"
validation_results:
  - acceptance_criteria_id: AC-001
    passed: true
    actual_result: "3"
    expected_result: "3"
    test_command: kubectl get deploy signoz-frontend -n signoz -o jsonpath='{.status.readyReplicas}'
all_validations_passed: true
summary: Successfully scaled SigNoz frontend to 3 replicas
deployment_duration_seconds: 45.2
```

### summary.md

```markdown
# Change Request: req-f7e8d9c0

## Summary
Scale SigNoz frontend to 3 replicas for high availability

## Requirements
- [x] REQ-001: SigNoz frontend deployment SHALL have 3 replicas

## Changes Made
- `infra/helm/values/signoz/values.yaml`: Changed frontend.replicaCount from 1 to 3

## Validation Results
- [x] AC-001: Frontend has 3 running replicas (actual: 3, expected: 3)

## Deployment
- Status: SUCCESS
- Duration: 45.2 seconds
- Method: helm upgrade

---
Generated by Infra-Agent
```

---

## Common Workflows

### Workflow 1: Diagnose and Fix an Issue

```bash
# 1. Investigate the problem
You: "Why are pods crashing in the demo namespace?"

# Agent investigates and identifies: OOMKilled, needs more memory

# 2. Make the fix
You: "Increase memory limit for demo pods to 512Mi"

# Agent runs 4-agent pipeline to update Helm values
```

### Workflow 2: Security Hardening

```bash
# 1. Run security audit
You: "Audit security posture"

# Agent identifies: mTLS not enabled, IAM too permissive

# 2. Fix mTLS
You: "Enable Istio mTLS STRICT mode for all namespaces"

# 3. Fix IAM (manual - requires careful policy design)
You: "Show me the current IAM policy for infra-agent-dev-deploy-role"
# Review and create scoped policy manually
```

### Workflow 3: Cost Optimization

```bash
# 1. Find savings
You: "Find cost optimization opportunities"

# Agent identifies: unattached volumes, idle pods, oversized resources

# 2. Clean up unattached volumes (manual via AWS console or CLI)
# Agent provides volume IDs

# 3. Rightsize workloads
You: "Reduce CPU request for signoz-frontend to 100m"
```

### Workflow 4: Compliance Remediation

```bash
# 1. Check compliance
You: "Audit NIST compliance"

# Agent shows: SC-8 partial (mTLS), CP-9 passed, etc.

# 2. Fix compliance gaps
You: "Enable encryption for all S3 buckets"
You: "Configure Velero backups for the demo namespace"
```

### Workflow 5: New Feature Deployment

```bash
# 1. Create namespace
You: "Create a new namespace called feature-x with Istio injection"

# 2. Deploy application
You: "Deploy the feature-x Helm chart to the feature-x namespace"

# 3. Verify
You: "List pods in feature-x namespace"
You: "Check service endpoints in feature-x namespace"
```

---

## Tips and Best Practices

### Be Specific
```bash
# Good - specific namespace and resource
"Why are pods restarting in the signoz namespace?"

# Vague - agent has to guess
"Why are pods restarting?"
```

### Use Action Words
```bash
# Investigation keywords
"investigate", "debug", "troubleshoot", "why is", "diagnose"

# Audit keywords
"audit", "compliance", "security scan", "cost analysis", "drift"

# Change keywords
"update", "modify", "scale", "configure", "enable"

# Create keywords
"create", "add", "deploy", "install", "provision"
```

### Follow the IaC Principle
- Never ask the agent to run `kubectl apply` or `kubectl patch` directly
- Always let changes flow through the pipeline to update IaC files
- This ensures all changes are version-controlled and auditable

### Review Before Approving
- Read the plan before approving
- Check the files being modified
- Verify the acceptance criteria make sense
- Review cost estimates for new resources

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-18 | AI Agent | Initial comprehensive operator guide |
