"""Chat Agent - Orchestrator for the 4-agent pipeline.

The Chat Agent serves as the primary operator interface and orchestrator
for the infrastructure agent system. It:
- Parses operator commands and determines intent
- Routes requests to the appropriate pipeline or agent
- Manages the 4-agent pipeline flow (Planning -> IaC -> Review -> Deploy)
- Handles retry loops and error recovery
- Aggregates and presents responses to the operator

CRITICAL: This agent MUST NOT allow the LLM to generate fake deployment outputs.
All infrastructure changes must go through the pipeline with verification.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from infra_agent.agents.base import BaseAgent, ProgressCallback
from infra_agent.config import Environment, get_settings
from infra_agent.core.contracts import ReviewStatus
from infra_agent.core.state import AgentType, InfraAgentState, OperationType

console = Console()
logger = logging.getLogger(__name__)


def _detect_fake_deployment_output(response: str) -> bool:
    """
    Detect if an LLM response looks like a fake deployment output.

    This guards against the LLM hallucinating deployment results when
    no actual deployment was performed.

    Args:
        response: The LLM response text

    Returns:
        True if the response appears to be fake deployment output
    """
    # Patterns that indicate fake deployment claims
    fake_deployment_patterns = [
        # Fake success claims
        r"deployment\s+(complete|successful|succeeded)",
        r"stack\s+update\s+(complete|successful)",
        r"✅\s*(deployment|deploy|update)\s*(complete|success)",
        r"successfully\s+(deployed|created|updated)\s+",

        # Fake instance IDs (obvious placeholder patterns)
        r"i-0[a-f0-9]{16}",  # EC2 instance ID pattern
        r"lt-0[a-f0-9]{16}",  # Launch Template ID pattern
        r"arn:aws:[a-z]+:[a-z0-9-]+:\d{12}:",  # ARN pattern

        # Fake command outputs
        r"```\s*\n?\s*\{\s*[\"']?Stack(Id|Status|Name)",  # Fake CloudFormation output
        r"UPDATE_COMPLETE",
        r"CREATE_COMPLETE",

        # Progress indicators that suggest execution
        r"Step \d+.*\[COMPLETE\]",
        r"⏳.*Stack Update In Progress",
        r"Monitoring\s+Deployment",
    ]

    response_lower = response.lower()

    # Check for fake patterns
    for pattern in fake_deployment_patterns:
        if re.search(pattern, response, re.IGNORECASE):
            logger.warning(f"Detected potential fake deployment output matching pattern: {pattern}")
            return True

    # Check for combination of deployment keywords + resource IDs
    has_deployment_claim = any(kw in response_lower for kw in [
        "deployed", "deployment complete", "successfully created",
        "stack update complete", "update_complete", "create_complete"
    ])

    has_resource_id = bool(re.search(r"i-[a-f0-9]{8,}", response)) or \
                      bool(re.search(r"lt-[a-f0-9]{8,}", response)) or \
                      bool(re.search(r"arn:aws:", response))

    if has_deployment_claim and has_resource_id:
        logger.warning("Detected deployment claim with resource IDs - likely hallucination")
        return True

    return False


def _sanitize_hallucinated_response(response: str) -> str:
    """
    Replace hallucinated deployment content with a safe message.

    Args:
        response: The original LLM response

    Returns:
        Sanitized response with warning
    """
    return """⚠️ **HALLUCINATION DETECTED**

The AI attempted to generate a fake deployment output. This has been blocked.

**What happened:**
- Your request appears to be an infrastructure change request
- The system attempted to respond without actually executing the change
- This is a safety mechanism to prevent false claims of deployment

**What to do:**
- Use `infra-agent pipeline -e <env>` for infrastructure changes
- Or explicitly say "create", "deploy", "update" to trigger the pipeline
- The system will then execute real commands with verification

**Your original request:**
"{original_request}"

Please rephrase your request as an explicit infrastructure change command.
""".format(original_request=response[:200] + "..." if len(response) > 200 else response)


@dataclass
class AgentTask:
    """Represents a running agent task."""
    task_id: str
    agent_type: str
    description: str
    started_at: datetime
    status: str = "running"  # running, completed, failed
    current_step: str = ""
    tool_calls: list[str] = field(default_factory=list)


# Global registry of active tasks
_active_tasks: dict[str, AgentTask] = {}


def register_task(task: AgentTask) -> None:
    """Register a new active task."""
    _active_tasks[task.task_id] = task


def update_task(task_id: str, **kwargs) -> None:
    """Update a task's properties."""
    if task_id in _active_tasks:
        for key, value in kwargs.items():
            setattr(_active_tasks[task_id], key, value)


def complete_task(task_id: str, status: str = "completed") -> None:
    """Mark a task as complete."""
    if task_id in _active_tasks:
        _active_tasks[task_id].status = status


def get_active_tasks() -> list[AgentTask]:
    """Get all active tasks."""
    return [t for t in _active_tasks.values() if t.status == "running"]


def get_all_tasks() -> list[AgentTask]:
    """Get all tasks (including completed)."""
    return list(_active_tasks.values())


class ChatAgent(BaseAgent):
    """
    Chat Agent - Orchestrator for the 4-agent pipeline.

    Responsibilities:
    - Parse operator commands and classify intent
    - Route infrastructure change requests to the 4-agent pipeline
    - Manage pipeline flow: Planning -> IaC -> Review -> Deploy & Validate
    - Handle retry loops when Review or Deploy fails
    - Route query requests directly to specialized agents
    - Enforce MFA requirements for production operations
    - Present results to the operator
    """

    def __init__(self, **kwargs):
        """Initialize the Chat Agent."""
        super().__init__(agent_type=AgentType.CHAT, **kwargs)
        self._planning_agent = None
        self._iac_agent = None
        self._review_agent = None
        self._deploy_validate_agent = None
        self._k8s_agent = None
        self._investigation_agent = None
        self._audit_agent = None

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph orchestration.

        This is called as the entry node in the LangGraph StateGraph.
        It classifies intent and sets up routing for the rest of the pipeline.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state dictionary with request_type set
        """
        from infra_agent.core.router import classify_intent

        # Check if we're resuming from an approval gate
        # If plan was just approved, we should continue to IaC (not re-classify)
        if state.get("plan_approved") is True and state.get("planning_output"):
            # Resuming after plan approval - keep the change type and continue
            return {
                "request_type": "change",
                "messages": [AIMessage(content="Plan approved. Proceeding with implementation...")],
            }

        # Check if deploy was just approved
        if state.get("deploy_approved") is True and state.get("review_output"):
            return {
                "request_type": "change",
                "messages": [AIMessage(content="Deployment approved. Proceeding...")],
            }

        messages = state.get("messages", [])
        if not messages:
            return {"request_type": "conversation"}

        # Get the last user message
        last_message = messages[-1]
        if hasattr(last_message, "content"):
            user_input = last_message.content
        else:
            user_input = str(last_message)

        # Classify intent using router
        intent = await classify_intent(user_input, use_llm=True, llm=self.llm)

        # Generate response message for conversation type
        if intent == "conversation":
            response = await self._generate_conversational_response(user_input)
            return {
                "request_type": intent,
                "messages": [AIMessage(content=response)],
            }

        # Route investigate and audit requests to specialized agents
        if intent == "investigate":
            investigation_agent = self._get_investigation_agent()
            result = await investigation_agent.process_pipeline(state)
            return {
                "request_type": intent,
                "messages": result.get("messages", []),
                "investigation_output_json": result.get("investigation_output_json"),
            }

        if intent == "audit":
            audit_agent = self._get_audit_agent()
            result = await audit_agent.process_pipeline(state)
            return {
                "request_type": intent,
                "messages": result.get("messages", []),
                "audit_output_json": result.get("audit_output_json"),
            }

        return {
            "request_type": intent,
            "messages": [
                AIMessage(
                    content=f"Processing {intent} request: {user_input[:100]}..."
                )
            ],
        }

    async def _generate_conversational_response(self, user_input: str) -> str:
        """Generate a conversational response using LLM."""
        from langchain_core.messages import SystemMessage, HumanMessage as HM

        messages = [
            SystemMessage(content=self.system_prompt),
            HM(content=user_input),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process the current state and route to appropriate agent.

        Handles two modes:
        1. Pipeline continuation: If pipeline is active, continue to next agent
        2. New request: Classify intent and start appropriate flow

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        # Check if a pipeline is in progress
        if state.is_pipeline_active():
            return await self._continue_pipeline(state)

        # Get the last user message for new requests
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content

        # Check session validity
        if not state.is_session_valid():
            response = "Session expired or invalid. Please authenticate first."
            state.messages.append(AIMessage(content=response))
            return state

        # Route based on intent
        intent = await self._classify_intent(user_input, state)
        state.operation_type = intent

        # Check MFA for sensitive operations
        if state.check_mfa_required() and not state.mfa_verified:
            response = (
                "This operation requires MFA verification.\n"
                "Please verify your identity with MFA before proceeding."
            )
            state.messages.append(AIMessage(content=response))
            return state

        # Route to appropriate flow
        if self._is_infrastructure_change_request(intent):
            # Start 4-agent pipeline
            return await self._start_pipeline(state, user_input)
        elif self._is_query_request(intent):
            # Route to appropriate query agent
            return await self._handle_query(state, user_input, intent)
        else:
            # Conversational response
            response = await self.invoke_llm(user_input, state)

            # CRITICAL: Check for hallucinated deployment output
            if _detect_fake_deployment_output(response):
                logger.error(f"Blocked hallucinated deployment output for input: {user_input[:100]}")
                response = _sanitize_hallucinated_response(user_input)

            self.log_action(
                state=state,
                action=f"chat_response:{intent.value if intent else 'query'}",
                success=True,
                details={"user_input": user_input[:100]},
            )
            state.messages.append(AIMessage(content=response))
            return state

    async def process_with_callback(
        self,
        state: InfraAgentState,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> InfraAgentState:
        """
        Process the current state with progress callback support.

        Same as process() but passes progress callback to handlers for
        real-time progress reporting.

        Args:
            state: Current agent state
            progress_callback: Optional callback for progress updates

        Returns:
            Updated agent state
        """
        # Check if a pipeline is in progress
        if state.is_pipeline_active():
            if progress_callback:
                progress_callback("pipeline", "Continuing pipeline...", None)
            return await self._continue_pipeline(state)

        # Get the last user message for new requests
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content

        # Check session validity
        if not state.is_session_valid():
            response = "Session expired or invalid. Please authenticate first."
            state.messages.append(AIMessage(content=response))
            return state

        # Route based on intent
        if progress_callback:
            progress_callback("classifying", "Classifying intent...", None)

        intent = await self._classify_intent(user_input, state)
        state.operation_type = intent

        if progress_callback:
            intent_name = intent.value if intent else "query"
            progress_callback("classified", f"Intent: {intent_name}", {"intent": intent_name})

        # Check MFA for sensitive operations
        if state.check_mfa_required() and not state.mfa_verified:
            response = (
                "This operation requires MFA verification.\n"
                "Please verify your identity with MFA before proceeding."
            )
            state.messages.append(AIMessage(content=response))
            return state

        # Route to appropriate flow
        if self._is_infrastructure_change_request(intent):
            if progress_callback:
                progress_callback("pipeline_start", "Starting infrastructure change pipeline...", None)
            # Start 4-agent pipeline
            return await self._start_pipeline(state, user_input)
        elif self._is_query_request(intent):
            if progress_callback:
                progress_callback("query_start", f"Processing {intent.value if intent else 'query'}...", None)
            # Route to appropriate query agent with callback
            return await self._handle_query(state, user_input, intent, progress_callback)
        else:
            # Conversational response
            if progress_callback:
                progress_callback("llm_start", "Generating response...", None)
            response = await self.invoke_llm(user_input, state)

            # CRITICAL: Check for hallucinated deployment output
            if _detect_fake_deployment_output(response):
                logger.error(f"Blocked hallucinated deployment output for input: {user_input[:100]}")
                response = _sanitize_hallucinated_response(user_input)

            self.log_action(
                state=state,
                action=f"chat_response:{intent.value if intent else 'query'}",
                success=True,
                details={"user_input": user_input[:100]},
            )
            if progress_callback:
                progress_callback("llm_done", "Response complete", None)
            state.messages.append(AIMessage(content=response))
            return state

    async def _start_pipeline(
        self, state: InfraAgentState, user_input: str
    ) -> InfraAgentState:
        """
        Start the 4-agent pipeline for an infrastructure change request.

        Args:
            state: Current agent state
            user_input: User's request

        Returns:
            Updated state after Planning Agent processes
        """
        # Generate request ID
        request_id = f"req-{uuid.uuid4().hex[:8]}"

        # Initialize pipeline
        state.start_pipeline(request_id)

        # Log pipeline start
        self.log_action(
            state=state,
            action="start_pipeline",
            success=True,
            resource_type="pipeline",
            resource_id=request_id,
            details={"user_input": user_input[:100]},
        )

        # Notify user
        state.messages.append(
            AIMessage(
                content=f"**Starting infrastructure change pipeline** (Request: {request_id})\n\n"
                "Step 1: Planning Agent analyzing request..."
            )
        )

        # Run Planning Agent
        planning_agent = self._get_planning_agent()
        state = await planning_agent.process(state)

        # Continue to next stage
        return await self._continue_pipeline(state)

    async def _continue_pipeline(self, state: InfraAgentState) -> InfraAgentState:
        """
        Continue the pipeline to the next stage.

        Args:
            state: Current agent state

        Returns:
            Updated state after next agent processes
        """
        stage = state.current_pipeline_stage

        if stage == "iac":
            # Run IaC Agent
            state.messages.append(
                AIMessage(content="\nStep 2: IaC Agent implementing changes...")
            )
            iac_agent = self._get_iac_agent()
            state = await iac_agent.process(state)
            return await self._continue_pipeline(state)

        elif stage == "review":
            # Run Review Agent
            state.messages.append(
                AIMessage(content="\nStep 3: Review Agent validating changes...")
            )
            review_agent = self._get_review_agent()
            state = await review_agent.process(state)

            # Check if we need to retry
            if state.current_pipeline_stage == "iac":
                # Review failed, going back to IaC
                return await self._continue_pipeline(state)
            return await self._continue_pipeline(state)

        elif stage == "deploy_validate":
            # Run Deploy & Validate Agent
            state.messages.append(
                AIMessage(content="\nStep 4: Deploy & Validate Agent executing...")
            )
            deploy_agent = self._get_deploy_validate_agent()
            state = await deploy_agent.process(state)

            # Check if we need to retry
            if state.current_pipeline_stage == "iac":
                # Validation failed, going back to IaC
                return await self._continue_pipeline(state)
            return state

        elif stage in ["completed", "failed"]:
            # Pipeline finished
            return self._finalize_pipeline(state)

        return state

    def _finalize_pipeline(self, state: InfraAgentState) -> InfraAgentState:
        """
        Finalize the pipeline and generate summary.

        Args:
            state: Current agent state

        Returns:
            Updated state with final summary
        """
        success = state.current_pipeline_stage == "completed"
        request_id = state.active_request_id

        if success:
            summary = (
                f"\n**Pipeline Complete** (Request: {request_id})\n\n"
                "All stages completed successfully:\n"
                "- Planning: OK\n"
                "- IaC Implementation: OK\n"
                "- Review: PASSED\n"
                "- Deploy & Validate: SUCCESS\n"
            )
        else:
            summary = (
                f"\n**Pipeline Failed** (Request: {request_id})\n\n"
                f"Error: {state.last_error or 'Unknown error'}\n"
                f"Retries: {state.pipeline_retry_count}/{state.max_pipeline_retries}\n"
            )

        self.log_action(
            state=state,
            action="finalize_pipeline",
            success=success,
            resource_type="pipeline",
            resource_id=request_id,
            details={"status": state.current_pipeline_stage},
        )

        state.messages.append(AIMessage(content=summary))
        return state

    async def _handle_query(
        self,
        state: InfraAgentState,
        user_input: str,
        intent: OperationType,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> InfraAgentState:
        """
        Handle query requests (not infrastructure changes).

        Args:
            state: Current agent state
            user_input: User's query
            intent: Classified intent
            progress_callback: Optional callback for progress updates

        Returns:
            Updated state with query response
        """
        # Route to K8s agent for Kubernetes queries
        if any(
            keyword in user_input.lower()
            for keyword in ["pod", "node", "namespace", "helm", "kubectl", "k8s"]
        ):
            k8s_agent = self._get_k8s_agent()
            return await k8s_agent.process(state)

        # Route to appropriate tools
        from infra_agent.mcp.client import is_aws_query, is_git_query

        # Drift/audit queries need BOTH Git and AWS tools
        is_drift_query = any(kw in user_input.lower() for kw in ["drift", "compare", "audit"])
        if is_drift_query and (is_git_query(user_input) or is_aws_query(user_input)):
            return await self._handle_drift_query(state, user_input, progress_callback)

        if is_git_query(user_input):
            return await self._handle_git_query(state, user_input, progress_callback)

        if is_aws_query(user_input):
            return await self._handle_aws_query(state, user_input, progress_callback)

        # Default to LLM response for general queries
        response = await self.invoke_llm(user_input, state)

        # CRITICAL: Check for hallucinated deployment output
        if _detect_fake_deployment_output(response):
            logger.error(f"Blocked hallucinated deployment output in query handler for: {user_input[:100]}")
            response = _sanitize_hallucinated_response(user_input)

        self.log_action(
            state=state,
            action=f"query_response:{intent.value}",
            success=True,
            details={"user_input": user_input[:100]},
        )
        state.messages.append(AIMessage(content=response))
        return state

    async def _handle_aws_query(
        self,
        state: InfraAgentState,
        user_input: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> InfraAgentState:
        """
        Handle AWS-related queries using MCP tools.

        Args:
            state: Current agent state
            user_input: User's AWS query
            progress_callback: Optional callback for progress updates

        Returns:
            Updated state with AWS query response
        """
        from infra_agent.mcp.client import get_aws_tools

        # Register AWS tools only if not already registered
        if "aws_api_call" not in self._tool_map:
            aws_tools = get_aws_tools()
            self.register_tools(aws_tools)

        # Invoke LLM with AWS tools
        context = """You have access to AWS API tools to query AWS resources.
Use aws_api_call to execute boto3 operations.
Use list_aws_services to discover available services.
Use list_service_operations to see operations for a specific service.

For read-only queries, use describe_* or list_* operations.
Generate the correct service name, operation name, and parameters.

Examples:
- "list EC2 instances" -> aws_api_call(service="ec2", operation="describe_instances")
- "show S3 buckets" -> aws_api_call(service="s3", operation="list_buckets")
- "list Lambda functions" -> aws_api_call(service="lambda", operation="list_functions")
- "show IAM roles" -> aws_api_call(service="iam", operation="list_roles")
- "list CloudFormation stacks" -> aws_api_call(service="cloudformation", operation="list_stacks")
"""

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_input,
                context=context,
                progress_callback=progress_callback,
            )

            self.log_action(
                state=state,
                action="aws_query",
                success=True,
                details={
                    "user_input": user_input[:100],
                    "tool_calls": [tc["tool"] for tc in tool_calls],
                },
            )

            state.messages.append(AIMessage(content=response))
            return state

        except Exception as e:
            error_msg = f"Error executing AWS query: {e}"
            self.log_action(
                state=state,
                action="aws_query",
                success=False,
                details={"user_input": user_input[:100], "error": str(e)},
            )
            state.messages.append(AIMessage(content=error_msg))
            return state

    async def _handle_git_query(
        self,
        state: InfraAgentState,
        user_input: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> InfraAgentState:
        """
        Handle Git-related queries using MCP tools.

        Supports GitHub and GitLab based on configuration.
        Used for reading IaC files and detecting drift from source of truth.

        Args:
            state: Current agent state
            user_input: User's Git query
            progress_callback: Optional callback for progress updates

        Returns:
            Updated state with Git query response
        """
        from infra_agent.mcp.client import get_git_tools

        # Register Git tools only if not already registered
        if "git_read_file" not in self._tool_map:
            git_tools = get_git_tools()
            self.register_tools(git_tools)

        # Invoke LLM with Git tools
        context = """You have access to Git repository tools to read files and detect IaC drift.

Available tools:
- git_read_file(repo, path, ref): Read a file from a Git repository
- git_list_files(repo, path, ref): List files in a directory
- git_list_repos(org_or_group, limit): List accessible repositories
- git_get_iac_files(repo, ref): Get summary of all IaC files (CloudFormation, Helm, Terraform, K8s)
- git_compare_with_deployed(repo, git_path, deployed_content, ref): Compare Git file with deployed version

For IaC drift detection:
1. Use git_get_iac_files to discover IaC files in the repository
2. Use git_read_file to read specific CloudFormation or Helm files
3. Use git_compare_with_deployed to compare with deployed state

Examples:
- "list IaC files in repo" -> git_get_iac_files(repo="owner/infra-agent")
- "read vpc template" -> git_read_file(repo="owner/infra-agent", path="infra/cloudformation/stacks/01-networking/vpc.yaml")
- "show CloudFormation files" -> git_list_files(repo="owner/infra-agent", path="infra/cloudformation/stacks")
"""

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_input,
                context=context,
                progress_callback=progress_callback,
            )

            self.log_action(
                state=state,
                action="git_query",
                success=True,
                details={
                    "user_input": user_input[:100],
                    "tool_calls": [tc["tool"] for tc in tool_calls],
                },
            )

            state.messages.append(AIMessage(content=response))
            return state

        except Exception as e:
            error_msg = f"Error executing Git query: {e}"
            self.log_action(
                state=state,
                action="git_query",
                success=False,
                details={"user_input": user_input[:100], "error": str(e)},
            )
            state.messages.append(AIMessage(content=error_msg))
            return state

    async def _handle_drift_query(
        self,
        state: InfraAgentState,
        user_input: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> InfraAgentState:
        """
        Handle drift/audit queries that need BOTH Git and AWS tools.

        Args:
            state: Current agent state
            user_input: User's drift query
            progress_callback: Optional callback for progress updates

        Returns:
            Updated state with drift analysis response
        """
        from infra_agent.mcp.client import get_aws_tools, get_git_tools

        # Register BOTH Git and AWS tools
        if "git_read_file" not in self._tool_map:
            git_tools = get_git_tools()
            self.register_tools(git_tools)

        if "aws_api_call" not in self._tool_map:
            aws_tools = get_aws_tools()
            self.register_tools(aws_tools)

        context = """You have access to BOTH Git and AWS tools for drift detection.

## Git Tools (for reading IaC source of truth):
- git_read_file(repo, path, ref): Read CloudFormation/Helm files from Git
- git_list_files(repo, path, ref): List files in a directory
- git_get_iac_files(repo, ref): Get summary of all IaC files
- git_compare_with_deployed(repo, git_path, deployed_content, ref): Compare Git vs deployed

## AWS Tools (for querying deployed infrastructure):
- aws_api_call(service, operation, parameters): Query any AWS service
  - CloudFormation: list_stacks, describe_stacks, detect_stack_drift
  - EKS: describe_cluster, list_nodegroups, describe_nodegroup
  - EC2: describe_instances, describe_vpcs, describe_subnets
  - S3: list_buckets
  - IAM: list_roles

## Drift Detection Workflow:
1. Use git_get_iac_files to discover IaC files in the repository
2. Use aws_api_call to query deployed CloudFormation stacks
3. Compare stack names and resources
4. Use aws_api_call with detect_stack_drift for detailed drift
5. Report any discrepancies between Git (source of truth) and AWS (deployed)

For the infra-agent project, the repo is likely 'Inceptium-ai/infra-agent' on GitHub.
"""

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_input,
                context=context,
                max_iterations=10,  # More iterations for complex drift analysis
                progress_callback=progress_callback,
            )

            self.log_action(
                state=state,
                action="drift_query",
                success=True,
                details={
                    "user_input": user_input[:100],
                    "tool_calls": [tc["tool"] for tc in tool_calls],
                },
            )

            state.messages.append(AIMessage(content=response))
            return state

        except Exception as e:
            error_msg = f"Error executing drift analysis: {e}"
            self.log_action(
                state=state,
                action="drift_query",
                success=False,
                details={"user_input": user_input[:100], "error": str(e)},
            )
            state.messages.append(AIMessage(content=error_msg))
            return state

    def _is_infrastructure_change_request(self, intent: Optional[OperationType]) -> bool:
        """Determine if the intent requires the 4-agent pipeline."""
        if intent is None:
            return False
        return intent in [
            OperationType.CREATE,
            OperationType.UPDATE,
            OperationType.DELETE,
            OperationType.DEPLOY,
        ]

    def _is_query_request(self, intent: Optional[OperationType]) -> bool:
        """Determine if the intent is a query (not a change)."""
        if intent is None:
            return True
        return intent in [OperationType.QUERY, OperationType.VALIDATE]

    def _get_planning_agent(self):
        """Lazy load Planning Agent."""
        if self._planning_agent is None:
            from infra_agent.agents.planning import PlanningAgent
            self._planning_agent = PlanningAgent(llm=self.llm)
        return self._planning_agent

    def _get_iac_agent(self):
        """Lazy load IaC Agent."""
        if self._iac_agent is None:
            from infra_agent.agents.iac.agent import IaCAgent
            self._iac_agent = IaCAgent(llm=self.llm)
        return self._iac_agent

    def _get_review_agent(self):
        """Lazy load Review Agent."""
        if self._review_agent is None:
            from infra_agent.agents.review import ReviewAgent
            self._review_agent = ReviewAgent(llm=self.llm)
        return self._review_agent

    def _get_deploy_validate_agent(self):
        """Lazy load Deploy & Validate Agent."""
        if self._deploy_validate_agent is None:
            from infra_agent.agents.deploy_validate import DeployValidateAgent
            self._deploy_validate_agent = DeployValidateAgent(llm=self.llm)
        return self._deploy_validate_agent

    def _get_k8s_agent(self):
        """Lazy load K8s Agent."""
        if self._k8s_agent is None:
            from infra_agent.agents.k8s.agent import K8sAgent
            self._k8s_agent = K8sAgent(llm=self.llm)
        return self._k8s_agent

    def _get_investigation_agent(self):
        """Lazy load Investigation Agent."""
        if self._investigation_agent is None:
            from infra_agent.agents.investigation import InvestigationAgent
            self._investigation_agent = InvestigationAgent(llm=self.llm)
        return self._investigation_agent

    def _get_audit_agent(self):
        """Lazy load Audit Agent."""
        if self._audit_agent is None:
            from infra_agent.agents.audit import AuditAgent
            self._audit_agent = AuditAgent(llm=self.llm)
        return self._audit_agent

    async def _classify_intent(
        self, user_input: str, state: InfraAgentState
    ) -> Optional[OperationType]:
        """
        Classify the user's intent from their input.

        Args:
            user_input: User's message
            state: Current state

        Returns:
            Classified operation type
        """
        import re

        input_lower = user_input.lower()
        words = set(re.findall(r'\b\w+\b', input_lower))

        # Audit/drift queries should NOT trigger pipeline
        # Check these FIRST to prevent false positives
        audit_keywords = {"drift", "audit", "compliance", "security scan", "cost analysis"}
        if any(kw in input_lower for kw in audit_keywords):
            return OperationType.QUERY

        # Query keywords - read-only operations
        query_keywords = {"list", "show", "describe", "get", "what", "which", "how many", "read", "compare"}
        if words & query_keywords and not words & {"deploy", "create", "delete", "update"}:
            return OperationType.QUERY

        # Infrastructure change keywords - use exact word matching to avoid
        # "deployed" matching "deploy", "created" matching "create", etc.
        if words & {"deploy", "release", "rollout"}:
            return OperationType.DEPLOY
        elif words & {"delete", "remove", "destroy"}:
            return OperationType.DELETE
        elif words & {"create", "add"}:
            # "new" is too common, exclude it from triggering CREATE
            return OperationType.CREATE
        elif words & {"update", "modify", "change", "edit"}:
            return OperationType.UPDATE
        elif words & {"validate", "check", "verify"}:
            return OperationType.VALIDATE
        elif words & {"rollback", "revert"}:
            return OperationType.ROLLBACK

        return OperationType.QUERY


def create_initial_state(environment: str) -> InfraAgentState:
    """Create an initial state for a chat session."""
    settings = get_settings()

    env_map = {"dev": Environment.DEV, "tst": Environment.TST, "prd": Environment.PRD}

    return InfraAgentState(
        environment=env_map.get(environment, Environment.DEV),
        eks_cluster_name=settings.eks_cluster_name,
        operator_authenticated=True,  # TODO: Implement proper auth
        mfa_verified=environment != "prd",  # PRD requires explicit MFA
    )


def show_status() -> None:
    """Display status of all tasks."""
    tasks = get_all_tasks()

    if not tasks:
        console.print("[dim]No tasks recorded yet.[/dim]")
        return

    table = Table(title="Agent Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Started", style="blue")
    table.add_column("Current Step", style="yellow")

    for task in tasks:
        status_style = {
            "running": "[bold yellow]RUNNING[/bold yellow]",
            "completed": "[bold green]COMPLETED[/bold green]",
            "failed": "[bold red]FAILED[/bold red]",
        }.get(task.status, task.status)

        elapsed = datetime.now() - task.started_at
        elapsed_str = f"{int(elapsed.total_seconds())}s ago"

        table.add_row(
            task.task_id[:8],
            task.agent_type,
            status_style,
            elapsed_str,
            task.current_step[:50] if task.current_step else "-",
        )

    console.print(table)


def show_help() -> None:
    """Display available commands."""
    help_text = """
**Available Commands:**

| Command | Description |
|---------|-------------|
| `/status` | Show status of all agent tasks |
| `/help` | Show this help message |
| `/clear` | Clear the screen |
| `exit`, `quit`, `q` | Exit the chat session |

**Tips:**
- Progress updates appear in real-time as the agent works
- Use Ctrl+C to interrupt a long-running operation
- The agent can query AWS, Git, and Kubernetes resources
"""
    console.print(Markdown(help_text))


def start_chat_session(environment: str = "dev") -> None:
    """
    Start an interactive chat session with real-time progress feedback.

    Args:
        environment: Target environment (dev, tst, prd)
    """
    import asyncio

    agent = ChatAgent()
    state = create_initial_state(environment)

    console.print("[green]Chat session started.[/green]")
    console.print("[dim]Type '/help' for commands, 'exit' to quit.[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]")

            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not user_input.strip():
                continue

            # Handle special commands
            if user_input.startswith("/"):
                cmd = user_input.lower().strip()
                if cmd == "/status":
                    show_status()
                    continue
                elif cmd == "/help":
                    show_help()
                    continue
                elif cmd == "/clear":
                    console.clear()
                    continue
                else:
                    console.print(f"[yellow]Unknown command: {cmd}. Type /help for available commands.[/yellow]")
                    continue

            # Add user message to state
            state.messages.append(HumanMessage(content=user_input))

            # Create a task for tracking
            task_id = f"task-{uuid.uuid4().hex[:8]}"
            task = AgentTask(
                task_id=task_id,
                agent_type="chat",
                description=user_input[:50],
                started_at=datetime.now(),
            )
            register_task(task)

            # Progress display state
            progress_lines: list[str] = []
            start_time = time.time()

            def progress_callback(event_type: str, message: str, details: Optional[dict]) -> None:
                """Handle progress updates."""
                elapsed = time.time() - start_time
                timestamp = f"[dim][{elapsed:.1f}s][/dim]"

                if event_type == "llm_start":
                    progress_lines.append(f"{timestamp} {message}")
                    update_task(task_id, current_step=message)
                elif event_type == "llm_thinking":
                    progress_lines.append(f"{timestamp} [cyan]{message}[/cyan]")
                    update_task(task_id, current_step=message)
                elif event_type == "tool_call":
                    progress_lines.append(f"{timestamp} [yellow]> {message}[/yellow]")
                    update_task(task_id, current_step=f"Tool: {message}")
                    if details and "tool" in details:
                        task.tool_calls.append(details["tool"])
                elif event_type == "tool_result":
                    progress_lines.append(f"{timestamp} [green]< {message}[/green]")
                elif event_type == "tool_error":
                    progress_lines.append(f"{timestamp} [red]! {message}[/red]")
                elif event_type == "llm_done":
                    progress_lines.append(f"{timestamp} [bold green]{message}[/bold green]")
                elif event_type == "max_iterations":
                    progress_lines.append(f"{timestamp} [bold yellow]{message}[/bold yellow]")

            # Process with real-time progress display
            async def process_with_progress():
                nonlocal state
                state = await agent.process_with_callback(state, progress_callback)

            console.print()
            console.print("[bold]Agent[/bold] [dim](working...)[/dim]")

            # Use Live display for real-time updates
            with Live(console=console, refresh_per_second=4, transient=True) as live:
                async def update_display():
                    nonlocal state
                    # Start processing in background
                    process_task = asyncio.create_task(process_with_progress())

                    while not process_task.done():
                        # Update live display
                        if progress_lines:
                            display_text = Text()
                            for line in progress_lines[-10:]:  # Show last 10 lines
                                display_text.append_text(Text.from_markup(line + "\n"))
                            live.update(Panel(display_text, title="Progress", border_style="blue"))
                        await asyncio.sleep(0.1)

                    # Wait for completion
                    await process_task

                asyncio.run(update_display())

            # Mark task complete
            complete_task(task_id, "completed")

            # Show final progress summary
            if progress_lines:
                console.print()
                elapsed = time.time() - start_time
                console.print(f"[dim]Completed in {elapsed:.1f}s with {len(task.tool_calls)} tool calls[/dim]")

            # Display response
            if state.messages and isinstance(state.messages[-1], AIMessage):
                response = state.messages[-1].content
                console.print()
                console.print("[bold green]Agent[/bold green]:")
                console.print(Markdown(response))
                console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Operation cancelled.[/yellow]")
            if 'task_id' in dir():
                complete_task(task_id, "failed")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if 'task_id' in dir():
                complete_task(task_id, "failed")


def execute_command(command: str, environment: str = "dev") -> str:
    """
    Execute a single command and return the response.

    Args:
        command: Command to execute
        environment: Target environment

    Returns:
        Agent response
    """
    import asyncio

    agent = ChatAgent()
    state = create_initial_state(environment)

    # Add command as message
    state.messages.append(HumanMessage(content=command))

    # Process
    state = asyncio.run(agent.process(state))

    # Return response
    if state.messages and isinstance(state.messages[-1], AIMessage):
        return state.messages[-1].content

    return "No response generated."
