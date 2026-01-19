# Infra-Agent Development Lessons Learned

This document captures lessons learned during the development of the AI Infrastructure Agent.

---

## MCP (Model Context Protocol) Integration (2026-01-19)

### What We Built

Added MCP tools for full AWS API and Git repository access, enabling drift detection and comprehensive infrastructure queries.

**Components:**
- `src/infra_agent/mcp/aws_server.py` - Generic boto3 wrapper
- `src/infra_agent/mcp/git_server.py` - GitHub/GitLab access
- `src/infra_agent/mcp/client.py` - LangChain tool adapters

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Generic `aws_api_call` over specific tools | Supports all 400+ AWS services without pre-defining |
| Direct boto3 calls (not MCP server process) | Simpler integration, same security context |
| Load tools dynamically based on query type | Reduces context size, faster responses |

### Lessons

1. **Tool Name Conflicts**: When registering tools dynamically, check if already registered to avoid "Tool names must be unique" errors.

2. **Environment Variables**: Use `dotenv.load_dotenv()` to load tokens from `.env` file - environment variables may not be passed to subprocesses.

3. **Drift Detection Needs Both Tools**: Drift queries require BOTH Git and AWS tools - added dedicated `_handle_drift_query` method that loads both.

---

## MCP Tools Must Be Registered in ALL Agents (2026-01-19)

### Problem

Agents in the 4-agent pipeline (Planning, IaC, Review, Deploy/Validate) could not execute AWS or Git operations directly. When the Review Agent tried to validate CloudFormation against deployed state, it had to display a table saying "I don't have direct AWS API access" instead of actually querying AWS.

### Root Cause

Only ChatAgent (orchestrator) and AuditAgent had MCP tools registered. Other agents inherited from `BaseAgent` but didn't register the MCP tools:

```python
# BEFORE - Missing MCP tools
class ReviewAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.REVIEW, **kwargs)
        self.register_tools(REVIEW_TOOLS)
        # NO MCP tools registered!
```

### Solution

Added `_register_mcp_tools()` to all agents:

```python
# AFTER - All agents have MCP tools
class ReviewAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.REVIEW, **kwargs)
        self.register_tools(REVIEW_TOOLS)
        self._register_mcp_tools()  # Added!

    def _register_mcp_tools(self) -> None:
        try:
            from infra_agent.mcp.client import get_aws_tools, get_git_tools
            self.register_tools(get_aws_tools())
            self.register_tools(get_git_tools())
        except Exception:
            pass  # MCP tools optional
```

### Files Modified

| File | Agent |
|------|-------|
| `src/infra_agent/agents/planning/agent.py` | PlanningAgent |
| `src/infra_agent/agents/iac/agent.py` | IaCAgent |
| `src/infra_agent/agents/review/agent.py` | ReviewAgent |
| `src/infra_agent/agents/deploy_validate/agent.py` | DeployValidateAgent |
| `src/infra_agent/agents/investigation/agent.py` | InvestigationAgent |
| `src/infra_agent/agents/k8s/agent.py` | K8sAgent |

### Key Lessons

1. **Every agent needs MCP tools**: Even agents that "shouldn't" need AWS/Git access often do for validation, drift detection, or context gathering.

2. **Fail silently on MCP errors**: Use try/except to keep MCP optional - agents should still work if MCP tools can't be loaded.

3. **Don't assume orchestrator tools propagate**: Each agent runs independently and must register its own tools.

4. **Test each agent individually**: ChatAgent working doesn't mean pipeline agents work - test each agent's tool availability.

---

## Intent Classification (2026-01-19)

### Problem

Queries like "check what is deployed" incorrectly triggered the DEPLOY pipeline.

### Root Cause

Substring matching caused "deployed" to match "deploy":

```python
# WRONG - substring match
if "deploy" in user_input.lower():  # Matches "deployed", "deployment"
    return OperationType.DEPLOY
```

### Solution

Use regex word boundaries for exact matching:

```python
import re
words = set(re.findall(r'\b\w+\b', user_input.lower()))

# CORRECT - exact word match
if words & {"deploy", "release", "rollout"}:
    return OperationType.DEPLOY
```

### Key Insight

- Intent classification is **critical** for UX - false positives frustrate users
- Use exact word matching, not substring matching
- Prioritize read-only intents (QUERY, AUDIT) over destructive intents (DEPLOY, DELETE)
- Add explicit keywords for audit/drift to ensure they route to QUERY

---

## Chat UI Progress Feedback (2026-01-19)

### Problem

Long-running operations (30-60s LLM calls) showed no progress, causing users to think the system hung.

### Solution

Added real-time progress feedback using Rich's `Live` display:

```python
ProgressCallback = Callable[[str, str, Optional[dict]], None]

def progress_callback(event_type: str, message: str, details: Optional[dict]) -> None:
    if event_type == "llm_thinking":
        display(f"Reasoning... (iteration {n})")
    elif event_type == "tool_call":
        display(f"> Calling {tool_name}({args})")
    elif event_type == "tool_result":
        display(f"< Got result from {tool_name}")
```

### Key Features Added

1. **Progress Panel**: Shows elapsed time, iteration count, tool calls
2. **Task Tracking**: `AgentTask` dataclass with status (running/completed/failed)
3. **Commands**: `/status` to view all tasks, `/help` for available commands

### Lessons

- Always show feedback during long operations
- Include elapsed time so users know something is happening
- Use Rich's `Live` for smooth updates without screen flicker

---

## LLM Tool Invocation Loop (2026-01-18)

### Pattern: ReAct-Style Loop

```python
async def invoke_with_tools(self, message, max_iterations=5):
    for _ in range(max_iterations):
        response = await llm.ainvoke(messages)

        if not response.tool_calls:
            return response.content  # Done

        for tool_call in response.tool_calls:
            result = await execute_tool(tool_call)
            messages.append(ToolMessage(content=result))
```

### Lessons

1. **Limit Iterations**: Set max_iterations to prevent infinite loops
2. **Pass Context**: Include relevant context in system prompt for each query type
3. **Error Handling**: Catch tool execution errors and return as ToolMessage
4. **Progress Reporting**: Add callback support for real-time feedback

---

## Agent State Management (2026-01-17)

### Using TypedDict for State

```python
class InfraAgentState(TypedDict):
    messages: list[BaseMessage]
    session_id: str
    environment: Environment
    operation_type: Optional[OperationType]
    current_agent: Optional[AgentType]
    # ... pipeline state
```

### Lessons

1. **Immutable Updates**: Always create new state dict, don't mutate
2. **Clear State Transitions**: Track `current_agent` for debugging
3. **Preserve Context**: Keep messages across agent transitions

---

## Git Integration for IaC Agent (2026-01-16)

### Branch Naming Convention

```
feat/{env}/{request-id}
fix/{env}/{request-id}
```

### Commit Message Format

```
feat: {summary}

Implements: {requirement-ids}
Files: {files-changed}

Co-Authored-By: Claude 3.5 Sonnet <noreply@anthropic.com>
```

### Lessons

1. **Environment Isolation**: Separate branches per environment
2. **Request Traceability**: Include request ID in branch name
3. **AI Attribution**: Add Co-Authored-By for transparency

---

## Validation in IaC Agent (2026-01-16)

### Self-Validation Pipeline

```
IaC Agent generates code
        │
        ▼
cfn-lint (CloudFormation)  ─── FAIL ──► Retry with feedback
        │
        PASS
        ▼
kube-linter (Kubernetes)   ─── FAIL ──► Retry with feedback
        │
        PASS
        ▼
Commit and proceed
```

### Lessons

1. **Validate Before Committing**: Run linters before creating git commit
2. **Include Error in Retry**: Pass linter errors to LLM for self-correction
3. **Max Retries**: Limit to 3 attempts before failing

---

## Investigation Agent Tools (2026-01-15)

### Tool Design Principles

1. **Focused Tools**: Each tool does one thing well
2. **Structured Output**: Return JSON for easy parsing
3. **Error Context**: Include helpful error messages
4. **Async First**: All tools should be async-capable

### Example Tool

```python
@tool
async def pod_health_check(namespace: str) -> str:
    """Check health of pods in a namespace.

    Args:
        namespace: Kubernetes namespace to check

    Returns:
        JSON with pod status, restarts, conditions
    """
```

---

## Python Environment Issues (2026-01-19)

### Problem

Mixed Python versions in venv (3.13 and 3.14) caused import errors.

### Solution

```bash
# Remove mixed venv
rm -rf .venv

# Create clean venv with specific version
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Lessons

1. **Pin Python Version**: Use specific Python version for venv
2. **Check `pip --version`**: Ensure pip matches Python version
3. **Clean Install**: When in doubt, recreate venv from scratch

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-19 | AI Agent | Initial agent lessons learned document |
