# Infra-Agent Architecture

This document describes the AI-powered Infrastructure Agent architecture, including the multi-agent system, 4-agent pipeline, and MCP integration.

---

## Overview

Infra-Agent is a CLI tool that uses AI to manage AWS EKS infrastructure. It routes user requests to specialized agents and ensures all changes go through IaC.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    INFRA-AGENT                                       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │                              CHAT AGENT                                      │    │
│  │                           (Orchestrator)                                     │    │
│  │                                                                              │    │
│  │   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐             │    │
│  │   │  Intent  │───►│  Router  │───►│  Tools   │───►│ Response │             │    │
│  │   │ Classify │    │          │    │ Execute  │    │ Format   │             │    │
│  │   └──────────┘    └──────────┘    └──────────┘    └──────────┘             │    │
│  │                          │                                                   │    │
│  │         ┌────────────────┼────────────────┬────────────────┐                │    │
│  │         ▼                ▼                ▼                ▼                │    │
│  │   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐             │    │
│  │   │   K8s    │    │  Audit   │    │  Invest  │    │ Pipeline │             │    │
│  │   │  Agent   │    │  Agent   │    │  Agent   │    │ (4-step) │             │    │
│  │   └──────────┘    └──────────┘    └──────────┘    └──────────┘             │    │
│  │                                                                              │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │                           MCP TOOL PROVIDERS                                 │    │
│  │                                                                              │    │
│  │   ┌──────────────────┐         ┌──────────────────┐                         │    │
│  │   │   AWS MCP Server │         │   Git MCP Server │                         │    │
│  │   │                  │         │                  │                         │    │
│  │   │  aws_api_call    │         │  git_read_file   │                         │    │
│  │   │  list_services   │         │  git_list_files  │                         │    │
│  │   │  list_operations │         │  git_get_iac     │                         │    │
│  │   │                  │         │  git_compare     │                         │    │
│  │   └──────────────────┘         └──────────────────┘                         │    │
│  │            │                            │                                    │    │
│  │            ▼                            ▼                                    │    │
│  │      boto3 (AWS)              GitHub/GitLab APIs                            │    │
│  │                                                                              │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Intent Classification

The Chat Agent classifies user intent to route to the appropriate handler:

| Intent | Keywords | Handler |
|--------|----------|---------|
| **INVESTIGATE** | "why", "debug", "troubleshoot", "failing" | Investigation Agent |
| **AUDIT** | "audit", "compliance", "security", "drift" | Audit Agent |
| **QUERY** | "list", "show", "get", "describe" | K8s/AWS/Git Tools |
| **DEPLOY** | "deploy", "release", "rollout" | 4-Agent Pipeline |
| **CREATE** | "create", "add", "provision" | 4-Agent Pipeline |
| **UPDATE** | "update", "modify", "scale", "configure" | 4-Agent Pipeline |
| **DELETE** | "delete", "remove", "destroy" | 4-Agent Pipeline |

**Important**: Uses exact word matching with regex boundaries to avoid false positives (e.g., "deployed" doesn't match "deploy").

---

## 4-Agent Pipeline

For infrastructure changes, requests flow through four specialized agents:

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              4-AGENT PIPELINE                                         │
├──────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│  User Request: "Scale SigNoz frontend to 3 replicas"                                 │
│                                 │                                                     │
│                                 ▼                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │ STEP 1: PLANNING AGENT                                                          │ │
│  │                                                                                  │ │
│  │ Input: User request                                                             │ │
│  │ Output: requirements.yaml                                                       │ │
│  │   - Requirements (REQ-001: Frontend SHALL have 3 replicas)                      │ │
│  │   - Acceptance Criteria (AC-001: readyReplicas == 3)                            │ │
│  │   - Files to modify                                                             │ │
│  │   - Impact assessment                                                           │ │
│  │   - NIST control mapping                                                        │ │
│  │                                                                                  │ │
│  │ [APPROVAL GATE: User reviews plan]                                              │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                 │                                                     │
│                                 ▼                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │ STEP 2: IAC AGENT                                                               │ │
│  │                                                                                  │ │
│  │ Input: requirements.yaml                                                        │ │
│  │ Output: changes.yaml                                                            │ │
│  │   - Modified IaC files (CloudFormation/Helm)                                    │ │
│  │   - Self-validation (cfn-lint, kube-linter)                                     │ │
│  │   - Git commit + push                                                           │ │
│  │   - Pull request creation                                                       │ │
│  │                                                                                  │ │
│  │ [RETRY LOOP: If validation fails, retry up to 3 times]                          │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                 │                                                     │
│                                 ▼                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │ STEP 3: REVIEW AGENT                                                            │ │
│  │                                                                                  │ │
│  │ Input: changes.yaml                                                             │ │
│  │ Output: review.yaml                                                             │ │
│  │   - cfn-guard (NIST compliance)                                                 │ │
│  │   - Security scan (no secrets)                                                  │ │
│  │   - Cost estimate                                                               │ │
│  │   - PASS/FAIL/NEEDS_REVISION                                                    │ │
│  │                                                                                  │ │
│  │ [APPROVAL GATE: User reviews before deploy]                                     │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                 │                                                     │
│                                 ▼                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │ STEP 4: DEPLOY & VALIDATE AGENT                                                 │ │
│  │                                                                                  │ │
│  │ Input: review.yaml (PASSED)                                                     │ │
│  │ Output: validation.yaml                                                         │ │
│  │   - Deploy (cloudformation deploy / helm upgrade)                               │ │
│  │   - Run acceptance criteria tests                                               │ │
│  │   - SUCCESS/FAILURE                                                             │ │
│  │                                                                                  │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
│  Artifacts saved to: .infra-agent/requests/{request-id}/                             │
│                                                                                       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Pipeline Artifacts

Each pipeline run produces:

| File | Agent | Contents |
|------|-------|----------|
| `requirements.yaml` | Planning | Requirements, acceptance criteria, files to modify |
| `changes.yaml` | IaC | Code changes, git commit, PR info |
| `review.yaml` | Review | Validation results, cost estimate |
| `validation.yaml` | Deploy | Deployment status, test results |
| `summary.md` | All | Human-readable summary |

---

## MCP Integration

The agent uses Model Context Protocol (MCP) for full AWS API and Git repository access. **All pipeline agents have MCP tools registered** to enable direct AWS and Git operations during their workflow.

### MCP Tools in All Agents

Every agent in the system has AWS and Git MCP tools registered at initialization:

```python
# Pattern used in all agents
def __init__(self, **kwargs):
    super().__init__(agent_type=AgentType.XXX, **kwargs)
    self.register_tools(AGENT_SPECIFIC_TOOLS)
    self._register_mcp_tools()  # AWS + Git tools

def _register_mcp_tools(self) -> None:
    """Register MCP tools for AWS API and Git repository access."""
    try:
        from infra_agent.mcp.client import get_aws_tools, get_git_tools
        self.register_tools(get_aws_tools())
        self.register_tools(get_git_tools())
    except Exception:
        pass  # MCP tools optional - fail silently
```

**Agent MCP Tool Status:**

| Agent | AWS Tools | Git Tools | Total Tools | Purpose |
|-------|-----------|-----------|-------------|---------|
| ChatAgent | Dynamic | Dynamic | On-demand | Routes queries to appropriate tools |
| AuditAgent | YES | YES | 22 | Compliance checks, drift detection |
| PlanningAgent | YES | YES | 12 | Query current state for planning |
| IaCAgent | YES | YES | 8 | Validate changes against deployed state |
| ReviewAgent | YES | YES | 14 | Security scans, cost estimates |
| DeployValidateAgent | YES | YES | 14 | Verify deployment success |
| InvestigationAgent | YES | YES | 23 | Diagnose AWS resource issues |
| K8sAgent | YES | YES | 8 | AWS context for K8s queries |

### AWS MCP Server

Provides access to any AWS service via boto3:

```python
# Generic tool that can call ANY boto3 operation
aws_api_call(
    service="ec2",           # Any AWS service
    operation="describe_instances",  # Any operation
    parameters={"Filters": [...]}    # Optional parameters
)
```

**Supported Services**: EC2, S3, Lambda, IAM, RDS, EKS, CloudFormation, CloudWatch, SNS, SQS, and all 400+ boto3 services.

### Git MCP Server

Provides access to GitHub/GitLab repositories:

```python
git_read_file(repo="owner/repo", path="infra/vpc.yaml")
git_get_iac_files(repo="owner/repo")  # Find all CloudFormation/Helm files
git_compare_with_deployed(repo, path, deployed_content)  # Drift detection
```

### Drift Detection Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  User Query  │───►│  Git Tools   │───►│  AWS Tools   │───►│   Compare    │
│  "check      │    │  read IaC    │    │  query state │    │   & Report   │
│   drift"     │    │  from repo   │    │  from AWS    │    │   findings   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

---

## Chat Session Features

### Progress Feedback

Real-time progress during LLM operations:

```
Agent (working...)

┌ Progress ─────────────────────────────────────────┐
│ [0.2s] Invoking Chat Agent...                    │
│ [0.5s] Reasoning... (iteration 1/5)              │
│ [2.1s] > Calling aws_api_call(service='ec2',...)│
│ [3.8s] < Got result from aws_api_call            │
│ [5.0s] Processing complete                       │
└──────────────────────────────────────────────────┘

Completed in 5.0s with 1 tool calls
```

### Chat Commands

| Command | Description |
|---------|-------------|
| `/status` | Show all agent tasks |
| `/help` | Show available commands |
| `/clear` | Clear screen |
| `exit` | Exit session |

---

## Code Structure

```
src/infra_agent/
├── agents/
│   ├── base.py           # BaseAgent class with invoke_with_tools
│   ├── chat/
│   │   └── agent.py      # ChatAgent (orchestrator)
│   ├── planning/
│   │   └── agent.py      # PlanningAgent
│   ├── iac/
│   │   └── agent.py      # IaCAgent
│   ├── review/
│   │   └── agent.py      # ReviewAgent
│   └── deploy_validate/
│       └── agent.py      # DeployValidateAgent
├── mcp/
│   ├── aws_server.py     # AWS MCP server
│   ├── git_server.py     # Git MCP server
│   └── client.py         # LangChain tool adapters
├── core/
│   ├── state.py          # InfraAgentState
│   ├── contracts.py      # Pydantic models
│   └── graph.py          # LangGraph pipeline
├── config.py             # Settings
└── main.py               # CLI entry point
```

---

## LLM Configuration

| Setting | Value |
|---------|-------|
| Model | Claude 3.5 Sonnet v2 (via AWS Bedrock) |
| Region | us-east-1 |
| Max Tokens | 4096 |
| Temperature | 0.1 (low for determinism) |

---

## Related Documents

- [user-guide.md](user-guide.md) - How to use the CLI
- [requirements.md](requirements.md) - Agent requirements (AGT-*)
- [knowledge-base.md](knowledge-base.md) - Known AWS/K8s limitations, patterns, troubleshooting
- [lessons-learned.md](lessons-learned.md) - Agent development lessons

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-19 | AI Agent | Initial agent architecture document |
