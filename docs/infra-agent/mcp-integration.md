# MCP Integration Reference

This document describes the MCP (Model Context Protocol) integration in infra-agent, enabling full AWS and Git API access.

---

## Overview

The infra-agent uses MCP to provide:
- **AWS API Access**: Execute any boto3 operation (200+ services)
- **Git Repository Access**: Read files from GitHub/GitLab repositories
- **IaC Drift Detection**: Compare Git source with deployed state

## Architecture

```
┌─────────────────────────────────────┐
│         Agent (any type)            │
│   - ChatAgent, PlanningAgent, etc.  │
└──────────────┬──────────────────────┘
               │ calls tools via LangChain
               ▼
┌─────────────────────────────────────┐
│       MCP Client Adapter            │
│   src/infra_agent/mcp/client.py     │
│   - get_aws_tools()                 │
│   - get_git_tools()                 │
└──────────────┬──────────────────────┘
               │ wraps as @tool
               ▼
┌─────────────────────────────────────┐
│        boto3 / GitHub API           │
│   - Direct API calls                │
│   - Credential handling             │
└─────────────────────────────────────┘
```

## File Structure

```
src/infra_agent/mcp/
├── __init__.py         # Package exports
├── aws_server.py       # AWS MCP server (FastMCP)
├── git_server.py       # Git MCP server (FastMCP)
└── client.py           # LangChain tool adapters
```

---

## AWS Tools

### Source: `src/infra_agent/mcp/client.py`

### 1. `aws_api_call`

Execute any AWS API operation via boto3.

```python
@tool
def aws_api_call(
    service: str,
    operation: str,
    parameters: dict[str, Any] | None = None,
) -> str:
    """Execute any AWS API operation via boto3.

    Args:
        service: AWS service name (ec2, s3, lambda, iam, rds, eks, sns, sqs,
                cloudformation, cloudwatch, dynamodb, secretsmanager, etc.)
        operation: Operation name in snake_case (describe_instances,
                  list_buckets, list_functions, list_roles, etc.)
        parameters: Optional dict of operation parameters

    Returns:
        JSON response from AWS API
    """
```

**Examples:**

```python
# List EC2 instances
aws_api_call(service="ec2", operation="describe_instances")

# List running instances only
aws_api_call(
    service="ec2",
    operation="describe_instances",
    parameters={"Filters": [{"Name": "instance-state-name", "Values": ["running"]}]}
)

# List S3 buckets
aws_api_call(service="s3", operation="list_buckets")

# Describe EKS cluster
aws_api_call(
    service="eks",
    operation="describe_cluster",
    parameters={"name": "infra-agent-dev-cluster"}
)

# List CloudFormation stacks
aws_api_call(service="cloudformation", operation="list_stacks")
```

### 2. `list_aws_services`

List all available AWS services.

```python
@tool
def list_aws_services() -> str:
    """List all available AWS services accessible via boto3.

    Returns:
        JSON array of service names (ec2, s3, lambda, iam, etc.)
    """
```

### 3. `list_service_operations`

List operations available for a specific AWS service.

```python
@tool
def list_service_operations(service: str) -> str:
    """List available operations for an AWS service.

    Args:
        service: AWS service name (ec2, s3, lambda, etc.)

    Returns:
        JSON list of operation names for the service
    """
```

---

## Git Tools

### Source: `src/infra_agent/mcp/client.py`

### 1. `git_read_file`

Read a file from a Git repository.

```python
@tool
def git_read_file(
    repo: str,
    path: str,
    ref: str = "main",
) -> str:
    """Read a file from a Git repository.

    Args:
        repo: Repository name (e.g., "owner/repo" for GitHub, project path for GitLab)
        path: File path within the repository
        ref: Branch, tag, or commit SHA (default: "main")

    Returns:
        File contents as string, or error message
    """
```

**Examples:**

```python
# Read CloudFormation template
git_read_file(
    repo="Inceptium-ai/infra-agent",
    path="infra/cloudformation/stacks/01-networking/vpc.yaml"
)

# Read Helm values from specific branch
git_read_file(
    repo="Inceptium-ai/infra-agent",
    path="infra/helm/values/signoz/values.yaml",
    ref="develop"
)
```

### 2. `git_list_files`

List files in a repository directory.

```python
@tool
def git_list_files(
    repo: str,
    path: str = "",
    ref: str = "main",
) -> str:
    """List files in a repository directory.

    Args:
        repo: Repository name
        path: Directory path (empty string for root)
        ref: Branch, tag, or commit SHA

    Returns:
        JSON list of files with name, path, and type
    """
```

### 3. `git_list_repos`

List accessible repositories.

```python
@tool
def git_list_repos(
    org_or_group: str | None = None,
    limit: int = 20,
) -> str:
    """List accessible repositories.

    Args:
        org_or_group: Organization (GitHub) or Group (GitLab) to filter by
        limit: Maximum number of repos to return

    Returns:
        JSON list of repositories with name, description, and URLs
    """
```

### 4. `git_get_iac_files`

Get summary of all IaC files in a repository.

```python
@tool
def git_get_iac_files(
    repo: str,
    ref: str = "main",
) -> str:
    """Get a summary of all IaC files in the repository.

    Looks for CloudFormation, Helm, Terraform, and Kubernetes files.

    Args:
        repo: Repository name
        ref: Branch, tag, or commit SHA

    Returns:
        JSON summary of IaC files organized by type
    """
```

### 5. `git_compare_with_deployed`

Compare a file in Git with its deployed version (drift detection).

```python
@tool
def git_compare_with_deployed(
    repo: str,
    git_path: str,
    deployed_content: str,
    ref: str = "main",
) -> str:
    """Compare a file in Git with its deployed version.

    Args:
        repo: Repository name
        git_path: Path to file in Git repository
        deployed_content: The actual deployed content to compare against
        ref: Branch, tag, or commit SHA

    Returns:
        JSON comparison showing if files match and differences
    """
```

---

## Agent Integration

All pipeline agents register MCP tools via the `_register_mcp_tools()` method in `BaseAgent`:

```python
# src/infra_agent/agents/base.py

def _register_mcp_tools(self) -> None:
    """Register MCP tools (AWS and Git) for this agent."""
    try:
        from infra_agent.mcp.client import get_aws_tools, get_git_tools

        # Register AWS tools
        aws_tools = get_aws_tools()
        for tool in aws_tools:
            self.register_tool(tool)

        # Register Git tools
        git_tools = get_git_tools()
        for tool in git_tools:
            self.register_tool(tool)

    except Exception as e:
        # Silent fail - MCP tools are optional enhancements
        logger.warning(f"Failed to register MCP tools: {e}")
```

### Agents with MCP Tools

| Agent | AWS Tools | Git Tools | Total Tools |
|-------|-----------|-----------|-------------|
| ChatAgent | Dynamic | Dynamic | On-demand |
| PlanningAgent | YES | YES | 12 |
| IaCAgent | YES | YES | 8 |
| ReviewAgent | YES | YES | 14 |
| DeployValidateAgent | YES | YES | 14 |
| InvestigationAgent | YES | YES | 23 |
| AuditAgent | YES | YES | 22 |
| K8sAgent | YES | YES | 8 |

---

## MCP Server (Standalone)

The agent includes a standalone MCP server that can be run independently:

### CLI Command

```bash
# Start with stdio transport (default)
infra-agent mcp-server

# Start with SSE transport
infra-agent mcp-server -t sse
```

### Code: `src/infra_agent/main.py`

```python
@cli.command("mcp-server")
@click.option(
    "--transport", "-t",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
)
def mcp_server(transport: str) -> None:
    """Start the AWS MCP server for full AWS API access."""
    from infra_agent.mcp import create_aws_mcp_server

    mcp = create_aws_mcp_server()
    mcp.run(transport=transport)
```

---

## Configuration

### AWS Credentials

The MCP client uses the standard boto3 credential chain:

1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. `~/.aws/credentials` file
3. `~/.aws/config` file
4. ECS/EC2 instance role

### Git Credentials

**GitHub:**
- Set `GITHUB_TOKEN` or `GH_TOKEN` environment variable

**GitLab:**
- Set `GITLAB_TOKEN` or `GL_TOKEN` environment variable
- Optionally set `GITLAB_URL` for self-hosted instances

### Settings (`.env`)

```bash
# AWS Region
AWS_REGION=us-east-1

# Git Platform (github or gitlab)
GIT_PLATFORM=github

# GitLab URL (for self-hosted)
GITLAB_URL=https://gitlab.example.com

# GitHub Token
GITHUB_TOKEN=ghp_xxxxx

# GitLab Token
GITLAB_TOKEN=glpat-xxxxx
```

---

## Query Routing

The ChatAgent detects AWS and Git queries using keyword matching:

### AWS Keywords

```python
AWS_QUERY_KEYWORDS = [
    # Services
    "aws", "ec2", "s3", "lambda", "iam", "rds", "eks", "sns", "sqs",
    "cloudformation", "cloudwatch", "dynamodb", "secretsmanager",
    "elasticache", "redshift", "kinesis", "apigateway", "route53",
    "acm", "kms", "ssm", "ecs", "ecr", "elb", "alb", "nlb",
    "vpc", "subnet", "security group", "nacl",
    # Resources
    "instances", "buckets", "functions", "roles", "policies",
    "clusters", "topics", "queues", "stacks", "tables", "secrets",
    # Actions
    "list", "describe", "get", "show", "what", "which", "how many",
]
```

### Git Keywords

```python
GIT_QUERY_KEYWORDS = [
    # Platforms
    "github", "gitlab", "git repo", "repository",
    # Actions
    "read file from", "get file from", "show file from",
    "list files in", "compare branches", "file history",
    "search code", "iac files", "iac drift",
    # IaC drift detection
    "compare iac", "drift from git", "drift from repo",
    "source of truth", "compare template", "compare helm",
]
```

---

## Error Handling

All MCP tools handle errors gracefully:

```python
try:
    client = boto3.client(service, region_name=settings.aws_region)
    method = getattr(client, operation)
    response = method(**(parameters or {}))
    return json.dumps(response, indent=2, default=str)

except NoCredentialsError:
    return json.dumps({
        "error": "AWS credentials not configured",
        "hint": "Ensure AWS credentials are set via environment variables or ~/.aws/credentials",
    }, indent=2)

except ClientError as e:
    error_code = e.response.get("Error", {}).get("Code", "Unknown")
    error_message = e.response.get("Error", {}).get("Message", str(e))
    return json.dumps({
        "error": error_message,
        "code": error_code,
        "service": service,
        "operation": operation,
    }, indent=2)
```

---

## Security Considerations

1. **Read-only by convention**: The LLM should primarily use describe/list/get operations
2. **Credential handling**: Uses existing AWS credential chain from `.env`
3. **Audit logging**: All API calls are logged for NIST AU-2 compliance
4. **Error sanitization**: AWS errors returned without exposing credentials
5. **Fault tolerance**: MCP tool registration failures are silent (agents continue without MCP)
