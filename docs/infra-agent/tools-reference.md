# Agent Tools Reference

This document provides a comprehensive reference for all tools available to infra-agent agents.

---

## Table of Contents

1. [MCP Tools (All Agents)](#mcp-tools-all-agents)
2. [Investigation Tools](#investigation-tools)
3. [Audit Tools](#audit-tools)
4. [Review Tools](#review-tools)
5. [Tool Registration](#tool-registration)

---

## MCP Tools (All Agents)

These tools are available to all agents via the MCP client adapter.

### AWS Tools

| Tool | Signature | Description |
|------|-----------|-------------|
| `aws_api_call` | `(service: str, operation: str, parameters: dict = None) -> str` | Execute any boto3 API operation |
| `list_aws_services` | `() -> str` | List all available AWS services |
| `list_service_operations` | `(service: str) -> str` | List operations for an AWS service |

### Git Tools

| Tool | Signature | Description |
|------|-----------|-------------|
| `git_read_file` | `(repo: str, path: str, ref: str = "main") -> str` | Read file from repository |
| `git_list_files` | `(repo: str, path: str = "", ref: str = "main") -> str` | List files in directory |
| `git_list_repos` | `(org_or_group: str = None, limit: int = 20) -> str` | List accessible repositories |
| `git_get_iac_files` | `(repo: str, ref: str = "main") -> str` | Get IaC files summary |
| `git_compare_with_deployed` | `(repo: str, git_path: str, deployed_content: str, ref: str = "main") -> str` | Compare Git vs deployed |

---

## Investigation Tools

**Source:** `src/infra_agent/agents/investigation/tools.py`

### Kubernetes Tools

#### `pod_health_check`

Check pod health status in a namespace.

```python
def pod_health_check(
    namespace: str = "default",
    label_selector: Optional[str] = None
) -> str:
    """
    Args:
        namespace: Kubernetes namespace to check
        label_selector: Optional label selector (e.g., "app=signoz")

    Returns:
        Pod status summary including restarts, phase, and conditions
    """
```

#### `pod_logs`

Get logs from a pod.

```python
def pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: Optional[str] = None,
    tail_lines: int = 100,
    previous: bool = False
) -> str:
    """
    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        container: Specific container name (optional)
        tail_lines: Number of lines to retrieve
        previous: Get logs from previous container instance

    Returns:
        Pod logs
    """
```

#### `pod_events`

Get Kubernetes events for a namespace.

```python
def pod_events(
    namespace: str = "default",
    field_selector: Optional[str] = None
) -> str:
    """
    Args:
        namespace: Kubernetes namespace
        field_selector: Optional filter (e.g., "involvedObject.name=my-pod")

    Returns:
        Recent events sorted by timestamp
    """
```

#### `pod_describe`

Get detailed pod description.

```python
def pod_describe(
    pod_name: str,
    namespace: str = "default"
) -> str:
    """
    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        Detailed pod description including events and conditions
    """
```

#### `resource_usage`

Get CPU and memory usage for pods.

```python
def resource_usage(namespace: str = "default") -> str:
    """
    Args:
        namespace: Kubernetes namespace

    Returns:
        Resource usage for pods (requires metrics-server)
    """
```

#### `node_status`

Get status of all cluster nodes.

```python
def node_status() -> str:
    """
    Returns:
        Node status including conditions and resource capacity
    """
```

#### `pvc_status`

Get PersistentVolumeClaim status.

```python
def pvc_status(namespace: str = "default") -> str:
    """
    Args:
        namespace: Kubernetes namespace

    Returns:
        PVC status including bound status and capacity
    """
```

#### `service_endpoints`

Get service endpoints to check connectivity.

```python
def service_endpoints(
    namespace: str = "default",
    service_name: Optional[str] = None
) -> str:
    """
    Args:
        namespace: Kubernetes namespace
        service_name: Specific service name (optional)

    Returns:
        Service endpoints and their status
    """
```

### AWS Investigation Tools

#### `ec2_status`

Check EC2 instance status.

```python
def ec2_status(instance_ids: Optional[str] = None) -> str:
    """
    Args:
        instance_ids: Comma-separated instance IDs (optional)

    Returns:
        EC2 instance status including health checks
    """
```

#### `eks_nodegroup_status`

Check EKS node group status.

```python
def eks_nodegroup_status(
    cluster_name: str,
    nodegroup_name: Optional[str] = None
) -> str:
    """
    Args:
        cluster_name: EKS cluster name
        nodegroup_name: Specific node group name (optional)

    Returns:
        Node group status including health and scaling
    """
```

#### `cloudwatch_logs`

Query CloudWatch Logs.

```python
def cloudwatch_logs(
    log_group: str,
    filter_pattern: str = "",
    hours: int = 1
) -> str:
    """
    Args:
        log_group: CloudWatch log group name
        filter_pattern: Filter pattern for logs (optional)
        hours: How many hours back to search

    Returns:
        Matching log events
    """
```

#### `ebs_status`

Check EBS volume status.

```python
def ebs_status(volume_ids: Optional[str] = None) -> str:
    """
    Args:
        volume_ids: Comma-separated volume IDs (optional)

    Returns:
        EBS volume status including attachment state
    """
```

### Observability Tools

#### `signoz_metrics`

Query SigNoz metrics.

```python
def signoz_metrics(
    metric_name: str,
    namespace: Optional[str] = None,
    duration: str = "1h"
) -> str:
    """
    Args:
        metric_name: Name of the metric (e.g., "k8s.pod.cpu.usage")
        namespace: Filter by namespace
        duration: Time range (e.g., "1h", "30m")

    Returns:
        Metric values
    """
```

#### `signoz_logs`

Query SigNoz logs.

```python
def signoz_logs(
    namespace: str,
    query: Optional[str] = None,
    severity: Optional[str] = None,
    duration: str = "1h"
) -> str:
    """
    Args:
        namespace: Kubernetes namespace
        query: Search query (optional)
        severity: Filter by severity (error, warn, info)
        duration: Time range

    Returns:
        Log entries
    """
```

#### `signoz_traces`

Query SigNoz traces (informational).

```python
def signoz_traces(
    service_name: str,
    operation: Optional[str] = None,
    min_duration_ms: Optional[int] = None
) -> str:
    """
    Args:
        service_name: Name of the service
        operation: Filter by operation name
        min_duration_ms: Filter by minimum duration

    Returns:
        Instructions for viewing traces in SigNoz
    """
```

### Investigation Tools Export

```python
INVESTIGATION_TOOLS = [
    pod_health_check,
    pod_logs,
    pod_events,
    pod_describe,
    resource_usage,
    node_status,
    pvc_status,
    service_endpoints,
    ec2_status,
    eks_nodegroup_status,
    cloudwatch_logs,
    ebs_status,
    signoz_metrics,
    signoz_logs,
    signoz_traces,
]
```

---

## Audit Tools

**Source:** `src/infra_agent/agents/audit/tools.py`

### Compliance Tools

#### `nist_control_check`

Check NIST 800-53 control implementation.

```python
def nist_control_check(control_id: str) -> str:
    """
    Args:
        control_id: NIST control ID (e.g., "SC-8", "AC-6", "AU-2")

    Returns:
        Control status and evidence

    Supported Controls:
        - SC-8: Transmission Confidentiality (Istio mTLS)
        - SC-28: Encryption at Rest (EBS, S3)
        - AC-2: Account Management (Cognito)
        - AC-6: Least Privilege (IAM)
        - AU-2: Audit Events (CloudTrail, VPC Flow Logs)
        - AU-3: Audit Content (K8s audit logs)
        - CM-2: Baseline Configuration (CloudFormation)
        - CM-3: Change Control (Git)
        - CP-9: System Backup (Velero)
        - RA-5: Vulnerability Scanning (Trivy)
    """
```

#### `encryption_audit`

Audit encryption at rest and in transit.

```python
def encryption_audit() -> str:
    """
    Returns:
        Comprehensive encryption status for EBS, RDS, Secrets Manager
    """
```

#### `istio_mtls_check`

Check Istio mTLS configuration.

```python
def istio_mtls_check() -> str:
    """
    Returns:
        mTLS status for each namespace (STRICT/PERMISSIVE)
    """
```

### Security Tools

#### `iam_audit`

Audit IAM policies for security issues.

```python
def iam_audit() -> str:
    """
    Returns:
        IAM security findings (admin policies, user counts)
    """
```

#### `public_access_check`

Check for publicly accessible resources.

```python
def public_access_check() -> str:
    """
    Returns:
        List of potentially public resources (S3, security groups)
    """
```

#### `trivy_results`

Get Trivy vulnerability scan results.

```python
def trivy_results(namespace: str = "default") -> str:
    """
    Args:
        namespace: Kubernetes namespace to check

    Returns:
        Vulnerability summary (CRITICAL, HIGH counts)
    """
```

#### `network_policy_audit`

Audit Kubernetes NetworkPolicies.

```python
def network_policy_audit() -> str:
    """
    Returns:
        NetworkPolicy coverage assessment
    """
```

### Cost Tools

#### `kubecost_query`

Query Kubecost for cost data.

```python
def kubecost_query(query_type: str = "summary") -> str:
    """
    Args:
        query_type: Type of query (summary, namespace, idle)

    Returns:
        Cost data or instructions for Kubecost access
    """
```

#### `idle_resource_check`

Check for idle resources.

```python
def idle_resource_check() -> str:
    """
    Returns:
        List of potentially idle resources (low CPU pods, pending PVCs)
    """
```

#### `rightsizing_recommendations`

Get rightsizing recommendations.

```python
def rightsizing_recommendations() -> str:
    """
    Returns:
        Rightsizing recommendations for over-provisioned pods
    """
```

#### `unattached_resources`

Find unattached EBS volumes and Elastic IPs.

```python
def unattached_resources() -> str:
    """
    Returns:
        List of unattached resources with costs
    """
```

### Drift Tools

#### `cfn_drift`

Detect CloudFormation drift.

```python
def cfn_drift(stack_name: Optional[str] = None) -> str:
    """
    Args:
        stack_name: Specific stack to check (all if not specified)

    Returns:
        Drift detection results (IN_SYNC/DRIFTED)
    """
```

#### `helm_drift`

Check Helm release for drift.

```python
def helm_drift(release_name: str, namespace: str = "default") -> str:
    """
    Args:
        release_name: Name of the Helm release
        namespace: Kubernetes namespace

    Returns:
        Drift status and comparison instructions
    """
```

#### `k8s_drift`

Check Kubernetes resources for drift.

```python
def k8s_drift(resource_type: str, namespace: str = "default") -> str:
    """
    Args:
        resource_type: Type of resource (deployment, service, configmap)
        namespace: Kubernetes namespace

    Returns:
        Drift indicators (resources without IaC annotations)
    """
```

### Audit Tools Export

```python
AUDIT_TOOLS = [
    nist_control_check,
    encryption_audit,
    istio_mtls_check,
    iam_audit,
    public_access_check,
    trivy_results,
    network_policy_audit,
    kubecost_query,
    idle_resource_check,
    rightsizing_recommendations,
    unattached_resources,
    cfn_drift,
    helm_drift,
    k8s_drift,
]
```

---

## Review Tools

**Source:** `src/infra_agent/agents/review/tools.py`

### Validation Tools

#### `CfnLintTool`

Run cfn-lint on CloudFormation templates.

```python
class CfnLintTool(BaseTool):
    """
    name: "cfn_lint"
    description: Validate CloudFormation template syntax and best practices

    Args:
        file_path: Path to CloudFormation template

    Returns:
        List of errors, warnings, and informational messages
    """
```

#### `CfnGuardTool`

Run cfn-guard for NIST 800-53 compliance.

```python
class CfnGuardTool(BaseTool):
    """
    name: "cfn_guard"
    description: Check CloudFormation for NIST 800-53 compliance

    Args:
        file_path: Path to CloudFormation template
        rules_path: Path to cfn-guard rules (defaults to NIST rules)

    Returns:
        Compliance violations and remediation guidance
    """
```

#### `KubeLinterTool`

Run kube-linter on Kubernetes manifests.

```python
class KubeLinterTool(BaseTool):
    """
    name: "kube_linter"
    description: Check K8s manifests for security best practices

    Args:
        file_path: Path to Kubernetes manifest or Helm values

    Returns:
        Security findings (runAsRoot, missing limits, etc.)
    """
```

#### `KubeconformTool`

Validate Kubernetes manifests against schemas.

```python
class KubeconformTool(BaseTool):
    """
    name: "kubeconform"
    description: Validate K8s manifests against API schemas

    Args:
        file_path: Path to Kubernetes manifest

    Returns:
        Schema validation results
    """
```

### Security Tools

#### `SecretsScanTool`

Scan files for potential secrets.

```python
class SecretsScanTool(BaseTool):
    """
    name: "secrets_scan"
    description: Scan for secrets, API keys, passwords

    Args:
        file_path: Path to file to scan

    Returns:
        Potential issues found

    Patterns detected:
        - password:, password=
        - secret:, api_key:, apikey:
        - access_key:, accesskey:
        - private_key:
        - BEGIN RSA/EC PRIVATE KEY
        - AKIA (AWS access key prefix)
    """
```

### Cost Tools

#### `CostEstimateTool`

Estimate cost impact of changes.

```python
class CostEstimateTool(BaseTool):
    """
    name: "cost_estimate"
    description: Estimate monthly cost impact

    Args:
        change_description: Description of infrastructure change
        resource_type: Type of resource (ec2, eks, rds, s3, etc.)

    Returns:
        Rough cost estimates based on AWS pricing

    Cost estimates (per month):
        - replica: $50
        - ec2_small: $30 (t3.small)
        - ec2_medium: $60 (t3.medium)
        - ec2_large: $120 (t3.large)
        - eks_node_small: $100
        - eks_node_large: $200
        - rds_small: $50 (db.t3.small)
        - rds_medium: $100 (db.t3.medium)
        - ebs_gb: $0.10/GB
        - s3_gb: $0.023/GB
        - nat_gateway: $45
        - alb: $25
    """
```

### Review Tools Export

```python
def get_review_tools() -> list[BaseTool]:
    return [
        CfnLintTool(),
        CfnGuardTool(),
        KubeLinterTool(),
        KubeconformTool(),
        SecretsScanTool(),
        CostEstimateTool(),
    ]
```

---

## Tool Registration

### BaseAgent Pattern

All agents inherit from `BaseAgent` which provides tool registration:

```python
# src/infra_agent/agents/base.py

class BaseAgent:
    def __init__(self, environment: str = "dev"):
        self._tools: list[BaseTool] = []
        self._tool_map: dict[str, BaseTool] = {}

        # Register MCP tools (AWS + Git)
        self._register_mcp_tools()

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool for this agent."""
        if tool.name not in self._tool_map:
            self._tools.append(tool)
            self._tool_map[tool.name] = tool

    def register_tools(self, tools: list[BaseTool]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    def _register_mcp_tools(self) -> None:
        """Register MCP tools (AWS and Git)."""
        try:
            from infra_agent.mcp.client import get_aws_tools, get_git_tools
            self.register_tools(get_aws_tools())
            self.register_tools(get_git_tools())
        except Exception as e:
            logger.warning(f"Failed to register MCP tools: {e}")
```

### Agent-Specific Tools

Each agent registers its own specific tools:

```python
# Investigation Agent
class InvestigationAgent(BaseAgent):
    def __init__(self, environment: str = "dev"):
        super().__init__(environment)
        from .tools import INVESTIGATION_TOOLS
        self.register_tools(INVESTIGATION_TOOLS)

# Audit Agent
class AuditAgent(BaseAgent):
    def __init__(self, environment: str = "dev"):
        super().__init__(environment)
        from .tools import AUDIT_TOOLS
        self.register_tools(AUDIT_TOOLS)

# Review Agent
class ReviewAgent(BaseAgent):
    def __init__(self, environment: str = "dev"):
        super().__init__(environment)
        from .tools import get_review_tools
        self.register_tools(get_review_tools())
```

### Tool Counts by Agent

| Agent | MCP (AWS+Git) | Specialized | Total |
|-------|---------------|-------------|-------|
| ChatAgent | 8 (dynamic) | 0 | ~8 |
| PlanningAgent | 8 | 4 | 12 |
| IaCAgent | 8 | 0 | 8 |
| ReviewAgent | 8 | 6 | 14 |
| DeployValidateAgent | 8 | 6 | 14 |
| InvestigationAgent | 8 | 15 | 23 |
| AuditAgent | 8 | 14 | 22 |
| K8sAgent | 8 | 0 | 8 |
