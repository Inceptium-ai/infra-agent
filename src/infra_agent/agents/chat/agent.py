"""Chat Agent - Primary operator interface and supervisor."""

from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from infra_agent.agents.base import BaseAgent
from infra_agent.config import Environment, get_settings
from infra_agent.core.state import AgentType, InfraAgentState, OperationType

console = Console()


class ChatAgent(BaseAgent):
    """
    Chat Agent - Supervisor agent that handles operator interaction.

    Responsibilities:
    - Parse operator commands
    - Route requests to specialized agents
    - Enforce MFA requirements
    - Aggregate and present responses
    """

    def __init__(self, **kwargs):
        """Initialize the Chat Agent."""
        super().__init__(agent_type=AgentType.CHAT, **kwargs)

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process the current state and route to appropriate agent.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        # Get the last user message
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

        # Generate response
        response = await self.invoke_llm(user_input, state)

        # Log the action
        self.log_action(
            state=state,
            action=f"chat_response:{intent.value if intent else 'query'}",
            success=True,
            details={"user_input": user_input[:100]},
        )

        state.messages.append(AIMessage(content=response))
        return state

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
