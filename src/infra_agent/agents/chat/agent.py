"""Chat Agent - Orchestrator for the 4-agent pipeline.

The Chat Agent serves as the primary operator interface and orchestrator
for the infrastructure agent system. It:
- Parses operator commands and determines intent
- Routes requests to the appropriate pipeline or agent
- Manages the 4-agent pipeline flow (Planning -> IaC -> Review -> Deploy)
- Handles retry loops and error recovery
- Aggregates and presents responses to the operator
"""

import uuid
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from infra_agent.agents.base import BaseAgent
from infra_agent.config import Environment, get_settings
from infra_agent.core.contracts import ReviewStatus
from infra_agent.core.state import AgentType, InfraAgentState, OperationType

console = Console()


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
            self.log_action(
                state=state,
                action=f"chat_response:{intent.value if intent else 'query'}",
                success=True,
                details={"user_input": user_input[:100]},
            )
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
        self, state: InfraAgentState, user_input: str, intent: OperationType
    ) -> InfraAgentState:
        """
        Handle query requests (not infrastructure changes).

        Args:
            state: Current agent state
            user_input: User's query
            intent: Classified intent

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

        # Default to LLM response for general queries
        response = await self.invoke_llm(user_input, state)
        self.log_action(
            state=state,
            action=f"query_response:{intent.value}",
            success=True,
            details={"user_input": user_input[:100]},
        )
        state.messages.append(AIMessage(content=response))
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
        input_lower = user_input.lower()

        # Simple keyword-based classification
        if any(word in input_lower for word in ["deploy", "release", "rollout"]):
            return OperationType.DEPLOY
        elif any(word in input_lower for word in ["delete", "remove", "destroy"]):
            return OperationType.DELETE
        elif any(word in input_lower for word in ["create", "add", "new"]):
            return OperationType.CREATE
        elif any(word in input_lower for word in ["update", "modify", "change"]):
            return OperationType.UPDATE
        elif any(word in input_lower for word in ["validate", "check", "verify"]):
            return OperationType.VALIDATE
        elif any(word in input_lower for word in ["rollback", "revert"]):
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


def start_chat_session(environment: str = "dev") -> None:
    """
    Start an interactive chat session.

    Args:
        environment: Target environment (dev, tst, prd)
    """
    import asyncio

    agent = ChatAgent()
    state = create_initial_state(environment)

    console.print("[green]Chat session started. Type 'exit' to quit.[/green]\n")

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]")

            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not user_input.strip():
                continue

            # Add user message to state
            state.messages.append(HumanMessage(content=user_input))

            # Process with agent
            with console.status("[bold green]Thinking...[/bold green]"):
                state = asyncio.run(agent.process(state))

            # Display response
            if state.messages and isinstance(state.messages[-1], AIMessage):
                response = state.messages[-1].content
                console.print()
                console.print("[bold green]Agent[/bold green]:")
                console.print(Markdown(response))
                console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Session interrupted.[/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


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
