"""LangGraph workflow for the 4-agent infrastructure pipeline.

This module implements the agentic workflow using LangGraph's StateGraph.

Pipeline Flow with Approval Gates:

    User Request
         │
         ▼
    ┌─────────────┐
    │ ORCHESTRATOR│ ──→ (query) ──→ K8S_AGENT ──→ END
    │   (chat)    │
    └─────────────┘
         │ (change)
         ▼
    ┌─────────────┐
    │  PLANNING   │
    └─────────────┘
         │
         ▼
    ┌─────────────────────────────────────────┐
    │  APPROVAL GATE 1: Plan Approval         │
    │  - Show requirements & acceptance criteria
    │  - Show files to be modified            │
    │  - User approves or rejects             │
    └─────────────────────────────────────────┘
         │ (approved)
         ▼
    ┌─────────────┐
    │     IAC     │ ◄────────────────────┐
    └─────────────┘                      │
         │                               │
         ▼                               │
    ┌─────────────┐                      │
    │   REVIEW    │ ─(needs_revision)────┘
    └─────────────┘
         │ (passed)
         ▼
    ┌─────────────────────────────────────────┐
    │  APPROVAL GATE 2: Deploy Approval       │
    │  - Show review results                  │
    │  - Show COST ESTIMATE                   │
    │  - User approves or rejects             │
    └─────────────────────────────────────────┘
         │ (approved)
         ▼
    ┌─────────────┐
    │   DEPLOY    │ ─(validation_failed)─┘
    │  VALIDATE   │
    └─────────────┘
         │ (success)
         ▼
       END
"""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from infra_agent.core.state import AgentType, InfraAgentState


class PipelineState(TypedDict):
    """State schema for the LangGraph pipeline.

    This is a simplified TypedDict for LangGraph compatibility.
    The full InfraAgentState is stored in 'agent_state'.
    """
    # Message history with automatic aggregation
    messages: Annotated[list[BaseMessage], add_messages]

    # Current pipeline stage
    current_stage: str

    # Request classification
    request_type: Literal["change", "query", "conversation"]

    # Retry tracking
    retry_count: int
    max_retries: int

    # Pipeline outputs (JSON serialized)
    planning_output: str | None
    iac_output: str | None
    review_output: str | None
    deployment_output: str | None

    # Review status for routing
    review_status: Literal["passed", "needs_revision", "failed"] | None

    # Deployment status for routing
    deployment_status: Literal["success", "failed", "rolled_back"] | None

    # Error tracking
    last_error: str | None

    # Full agent state (serialized)
    agent_state_json: str | None

    # === NEW: Approval Gates ===
    # Mode flags
    dry_run: bool  # If True, stop after review (no deploy)

    # Approval states
    plan_approved: bool | None  # None = pending, True = approved, False = rejected
    deploy_approved: bool | None  # None = pending, True = approved, False = rejected

    # Approval prompts (for UI to display)
    pending_approval: Literal["plan", "deploy"] | None
    approval_prompt: str | None  # Human-readable prompt for approval
    cost_estimate: str | None  # Cost estimate for display


def create_initial_state(
    user_message: str,
    dry_run: bool = False,
) -> PipelineState:
    """Create initial pipeline state from user message."""
    return PipelineState(
        messages=[HumanMessage(content=user_message)],
        current_stage="orchestrator",
        request_type="conversation",
        retry_count=0,
        max_retries=3,
        planning_output=None,
        iac_output=None,
        review_output=None,
        deployment_output=None,
        review_status=None,
        deployment_status=None,
        last_error=None,
        agent_state_json=None,
        # Approval gates
        dry_run=dry_run,
        plan_approved=None,
        deploy_approved=None,
        pending_approval=None,
        approval_prompt=None,
        cost_estimate=None,
    )


# Router function to classify intent
def route_from_orchestrator(state: PipelineState) -> str:
    """Route from orchestrator based on request type and current progress."""
    request_type = state.get("request_type", "conversation")

    if request_type == "change":
        # Check if we're resuming from an approval gate
        # IMPORTANT: Check deploy approval BEFORE plan approval (deploy is further along)
        if state.get("deploy_approved") is True and state.get("review_output"):
            return "deploy_validate"
        # If plan is already approved, skip to IaC
        if state.get("plan_approved") is True and state.get("planning_output"):
            return "iac"
        # Fresh request - start with planning
        return "planning"
    elif request_type == "query":
        return "k8s"
    else:
        return END


def route_from_planning(state: PipelineState) -> str:
    """Route from planning - always go to plan approval gate."""
    return "plan_approval"


def route_from_plan_approval(state: PipelineState) -> str:
    """Route from plan approval gate."""
    plan_approved = state.get("plan_approved")

    if plan_approved is None:
        # Waiting for approval - pause here
        return END  # Will resume after approval
    elif plan_approved:
        return "iac"
    else:
        # Rejected
        return END


def route_from_review(state: PipelineState) -> str:
    """Route from review agent based on review status."""
    review_status = state.get("review_status")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    dry_run = state.get("dry_run", False)

    if review_status == "passed":
        if dry_run:
            return END  # Dry run stops here
        return "deploy_approval"
    elif review_status == "needs_revision" and retry_count < max_retries:
        return "iac"  # Retry loop
    else:
        return END  # Failed, report to user


def route_from_deploy_approval(state: PipelineState) -> str:
    """Route from deploy approval gate."""
    deploy_approved = state.get("deploy_approved")

    if deploy_approved is None:
        # Waiting for approval - pause here
        return END
    elif deploy_approved:
        return "deploy_validate"
    else:
        # Rejected
        return END


def route_from_deploy(state: PipelineState) -> str:
    """Route from deploy agent based on deployment status."""
    deployment_status = state.get("deployment_status")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if deployment_status == "success":
        return END
    elif deployment_status == "failed" and retry_count < max_retries:
        return "iac"  # Back to IaC for fix
    else:
        return END  # Failed or rolled back


def build_agent_graph():
    """Build the LangGraph StateGraph for the 4-agent pipeline.

    Returns:
        Compiled LangGraph workflow
    """
    from infra_agent.agents.chat.agent import ChatAgent
    from infra_agent.agents.planning.agent import PlanningAgent
    from infra_agent.agents.iac.agent import IaCAgent
    from infra_agent.agents.review.agent import ReviewAgent
    from infra_agent.agents.deploy_validate.agent import DeployValidateAgent
    from infra_agent.agents.k8s.agent import K8sAgent

    # Initialize agents
    chat_agent = ChatAgent()
    planning_agent = PlanningAgent()
    iac_agent = IaCAgent()
    review_agent = ReviewAgent()
    deploy_agent = DeployValidateAgent()
    k8s_agent = K8sAgent()

    # Create the graph
    graph = StateGraph(PipelineState)

    # Define node functions that wrap agent processing
    async def orchestrator_node(state: PipelineState) -> PipelineState:
        """Orchestrator node - classifies intent and routes."""
        result = await chat_agent.process_pipeline(state)
        return result

    async def planning_node(state: PipelineState) -> PipelineState:
        """Planning agent node."""
        from infra_agent.core.artifacts import get_artifact_manager
        from infra_agent.core.contracts import PlanningOutput

        result = await planning_agent.process_pipeline(state)
        merged = {**state, **result, "current_stage": "planning"}

        # Save planning artifacts
        if merged.get("planning_output"):
            try:
                artifact_mgr = get_artifact_manager()
                planning = PlanningOutput.model_validate_json(merged["planning_output"])
                artifact_mgr.save_planning_output(planning)
            except Exception:
                pass  # Don't fail pipeline on artifact save error

        return merged

    async def plan_approval_node(state: PipelineState) -> PipelineState:
        """Plan approval gate - prepares approval prompt."""
        planning_output = state.get("planning_output")

        if not planning_output:
            return {
                **state,
                "pending_approval": None,
                "plan_approved": False,
                "messages": [AIMessage(content="**Error:** No planning output to approve")],
            }

        # Parse planning output for display
        try:
            from infra_agent.core.contracts import PlanningOutput
            plan = PlanningOutput.model_validate_json(planning_output)

            # Build approval prompt
            prompt_lines = [
                "## Plan Approval Required\n",
                f"**Summary:** {plan.summary}\n",
                "### Requirements:",
            ]
            for req in plan.requirements:
                prompt_lines.append(f"- [{req.id}] {req.description}")

            prompt_lines.append("\n### Acceptance Criteria:")
            for ac in plan.acceptance_criteria:
                prompt_lines.append(f"- [{ac.id}] {ac.description}")

            prompt_lines.append("\n### Files to Modify:")
            for f in plan.files_to_modify:
                prompt_lines.append(f"- `{f.path}` ({f.change_type.value})")
                prompt_lines.append(f"  {f.description}")

            prompt_lines.append(f"\n**Impact:** {plan.estimated_impact}")

            if plan.requires_approval:
                prompt_lines.append("\n**Note:** This change requires explicit approval (production/destructive)")

            prompt_lines.append("\n---\n**Approve this plan to proceed with implementation?**")

            approval_prompt = "\n".join(prompt_lines)

        except Exception as e:
            approval_prompt = f"**Error parsing plan:** {e}\n\nRaw output:\n{planning_output[:500]}"

        return {
            **state,
            "pending_approval": "plan",
            "plan_approved": None,  # Waiting for user input
            "approval_prompt": approval_prompt,
            "messages": [AIMessage(content=approval_prompt)],
        }

    async def iac_node(state: PipelineState) -> PipelineState:
        """IaC agent node."""
        from infra_agent.core.artifacts import get_artifact_manager
        from infra_agent.core.contracts import IaCOutput

        result = await iac_agent.process_pipeline(state)
        merged = {**state, **result, "current_stage": "iac"}

        # Save IaC artifacts
        if merged.get("iac_output"):
            try:
                artifact_mgr = get_artifact_manager()
                iac = IaCOutput.model_validate_json(merged["iac_output"])
                artifact_mgr.save_iac_output(iac)
            except Exception:
                pass  # Don't fail pipeline on artifact save error

        return merged

    async def review_node(state: PipelineState) -> PipelineState:
        """Review agent node."""
        from infra_agent.core.artifacts import get_artifact_manager
        from infra_agent.core.contracts import ReviewOutput

        result = await review_agent.process_pipeline(state)
        merged = {**state, **result, "current_stage": "review"}

        # Save review artifacts and generate summary
        if merged.get("review_output"):
            try:
                artifact_mgr = get_artifact_manager()
                review = ReviewOutput.model_validate_json(merged["review_output"])
                artifact_mgr.save_review_output(review)
                # Generate summary after review (we have all info now)
                artifact_mgr.generate_summary(review.request_id)
            except Exception:
                pass  # Don't fail pipeline on artifact save error

        return merged

    async def deploy_approval_node(state: PipelineState) -> PipelineState:
        """Deploy approval gate - shows cost estimate and review results."""
        review_output = state.get("review_output")

        if not review_output:
            return {
                **state,
                "pending_approval": None,
                "deploy_approved": False,
                "messages": [AIMessage(content="**Error:** No review output for deployment approval")],
            }

        try:
            from infra_agent.core.contracts import ReviewOutput
            review = ReviewOutput.model_validate_json(review_output)

            prompt_lines = [
                "## Deploy Approval Required\n",
                f"**Review Status:** {review.status.value.upper()}\n",
                "### Validation Results:",
                f"- cfn-guard (NIST): {'PASS' if review.cfn_guard_passed else 'FAIL'}",
                f"- cfn-lint: {'PASS' if review.cfn_lint_passed else 'FAIL'}",
                f"- kube-linter: {'PASS' if review.kube_linter_passed else 'FAIL'}",
                f"- Security scan: {'PASS' if review.security_scan_passed else 'FAIL'}",
                f"\n**Findings:** {review.blocking_findings} errors, {review.warning_findings} warnings",
            ]

            # Cost estimate - prominent display
            cost_str = None
            if review.cost_estimate:
                cost = review.cost_estimate
                cost_str = f"${cost.monthly_delta:+.2f}/month"
                prompt_lines.append("\n### Cost Impact")
                prompt_lines.append(f"**Estimated Change:** {cost_str}")
                if cost.affected_resources:
                    prompt_lines.append(f"**Affected Resources:** {', '.join(cost.affected_resources)}")
                if cost.notes:
                    prompt_lines.append(f"**Notes:** {cost.notes}")
            else:
                prompt_lines.append("\n### Cost Impact")
                prompt_lines.append("**Estimated Change:** No significant cost impact detected")

            prompt_lines.append("\n---\n**Approve deployment to proceed?**")

            approval_prompt = "\n".join(prompt_lines)

        except Exception as e:
            approval_prompt = f"**Error parsing review:** {e}\n\n**Approve deployment?**"
            cost_str = None

        return {
            **state,
            "pending_approval": "deploy",
            "deploy_approved": None,
            "approval_prompt": approval_prompt,
            "cost_estimate": cost_str,
            "messages": [AIMessage(content=approval_prompt)],
        }

    async def deploy_node(state: PipelineState) -> PipelineState:
        """Deploy & validate agent node."""
        from infra_agent.core.artifacts import get_artifact_manager
        from infra_agent.core.contracts import DeploymentOutput

        result = await deploy_agent.process_pipeline(state)
        merged = {**state, **result, "current_stage": "deploy_validate"}

        # Save deployment artifacts and regenerate summary
        if merged.get("deployment_output"):
            try:
                artifact_mgr = get_artifact_manager()
                deployment = DeploymentOutput.model_validate_json(merged["deployment_output"])
                artifact_mgr.save_deployment_output(deployment)
                # Regenerate summary with validation results
                artifact_mgr.generate_summary(deployment.request_id)
            except Exception:
                pass  # Don't fail pipeline on artifact save error

        return merged

    async def k8s_node(state: PipelineState) -> PipelineState:
        """K8s query agent node."""
        result = await k8s_agent.process_pipeline(state)
        return {**state, **result, "current_stage": "k8s"}

    # Add nodes
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("planning", planning_node)
    graph.add_node("plan_approval", plan_approval_node)
    graph.add_node("iac", iac_node)
    graph.add_node("review", review_node)
    graph.add_node("deploy_approval", deploy_approval_node)
    graph.add_node("deploy_validate", deploy_node)
    graph.add_node("k8s", k8s_node)

    # Set entry point
    graph.set_entry_point("orchestrator")

    # Add edges with conditional routing
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "planning": "planning",
            "iac": "iac",  # For resuming after plan approval
            "deploy_validate": "deploy_validate",  # For resuming after deploy approval
            "k8s": "k8s",
            END: END,
        }
    )

    # Planning goes to approval gate
    graph.add_edge("planning", "plan_approval")

    # Plan approval routes based on approval status
    graph.add_conditional_edges(
        "plan_approval",
        route_from_plan_approval,
        {
            "iac": "iac",
            END: END,
        }
    )

    # IaC always goes to Review
    graph.add_edge("iac", "review")

    # Review has conditional routing (pass/retry/fail)
    graph.add_conditional_edges(
        "review",
        route_from_review,
        {
            "deploy_approval": "deploy_approval",
            "iac": "iac",
            END: END,
        }
    )

    # Deploy approval routes based on approval status
    graph.add_conditional_edges(
        "deploy_approval",
        route_from_deploy_approval,
        {
            "deploy_validate": "deploy_validate",
            END: END,
        }
    )

    # Deploy has conditional routing (success/retry/fail)
    graph.add_conditional_edges(
        "deploy_validate",
        route_from_deploy,
        {
            "iac": "iac",
            END: END,
        }
    )

    # K8s queries go directly to END
    graph.add_edge("k8s", END)

    # Compile the graph
    return graph.compile()


class InfraAgentPipeline:
    """High-level interface for running the infrastructure agent pipeline."""

    def __init__(self):
        """Initialize the pipeline."""
        self._graph = None

    @property
    def graph(self):
        """Lazy-load the graph."""
        if self._graph is None:
            self._graph = build_agent_graph()
        return self._graph

    async def run(
        self,
        user_message: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run the pipeline with a user message.

        Args:
            user_message: The user's input message
            dry_run: If True, stop after review without deploying

        Returns:
            Final pipeline state with results
        """
        initial_state = create_initial_state(user_message, dry_run=dry_run)
        final_state = await self.graph.ainvoke(initial_state)
        return final_state

    async def stream(
        self,
        user_message: str,
        dry_run: bool = False,
    ):
        """Stream pipeline execution with a user message.

        Args:
            user_message: The user's input message
            dry_run: If True, stop after review without deploying

        Yields:
            State updates as the pipeline progresses
        """
        initial_state = create_initial_state(user_message, dry_run=dry_run)
        async for state in self.graph.astream(initial_state):
            yield state

    async def resume_with_approval(
        self,
        state: PipelineState,
        approved: bool,
    ) -> dict[str, Any]:
        """Resume pipeline after approval decision.

        Args:
            state: Current pipeline state (paused at approval gate)
            approved: User's approval decision

        Returns:
            Final pipeline state after resuming
        """
        pending = state.get("pending_approval")

        if pending == "plan":
            state["plan_approved"] = approved
            state["pending_approval"] = None
            if approved:
                state["messages"] = [AIMessage(content="**Plan approved.** Proceeding with implementation...")]
            else:
                state["messages"] = [AIMessage(content="**Plan rejected.** Pipeline stopped.")]
        elif pending == "deploy":
            state["deploy_approved"] = approved
            state["pending_approval"] = None
            if approved:
                state["messages"] = [AIMessage(content="**Deployment approved.** Proceeding...")]
            else:
                state["messages"] = [AIMessage(content="**Deployment rejected.** Pipeline stopped.")]

        if not approved:
            return state

        # Continue the pipeline
        final_state = await self.graph.ainvoke(state)
        return final_state

    async def stream_with_approval(
        self,
        state: PipelineState,
        approved: bool,
    ):
        """Stream pipeline resumption after approval.

        Args:
            state: Current pipeline state
            approved: User's approval decision

        Yields:
            State updates as pipeline continues
        """
        pending = state.get("pending_approval")

        if pending == "plan":
            state["plan_approved"] = approved
            state["pending_approval"] = None
        elif pending == "deploy":
            state["deploy_approved"] = approved
            state["pending_approval"] = None

        if not approved:
            yield {"rejected": {"messages": [AIMessage(content="Pipeline stopped by user.")]}}
            return

        async for update in self.graph.astream(state):
            yield update

    def get_graph_visualization(self) -> str:
        """Get a Mermaid diagram of the graph.

        Returns:
            Mermaid diagram string
        """
        return self.graph.get_graph().draw_mermaid()


# Singleton instance
_pipeline: InfraAgentPipeline | None = None


def get_pipeline() -> InfraAgentPipeline:
    """Get the singleton pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = InfraAgentPipeline()
    return _pipeline
