"""Base agent class for all specialized agents."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from infra_agent.config import Settings, get_settings
from infra_agent.core.state import AgentType, InfraAgentState, OperationType
from infra_agent.llm.bedrock import get_bedrock_llm, get_system_prompt


class BaseAgent(ABC):
    """
    Abstract base class for all specialized agents.

    Each agent handles a specific domain:
    - Chat: Operator interface and routing
    - IaC: CloudFormation management
    - K8s: Kubernetes operations
    - Security: Scanning and compliance
    - Deployment: CI/CD operations
    - Verification: Testing and drift detection
    - Cost: Cost management and optimization
    """

    def __init__(
        self,
        agent_type: AgentType,
        llm: Optional[BaseChatModel] = None,
        settings: Optional[Settings] = None,
    ):
        """
        Initialize the agent.

        Args:
            agent_type: Type of this agent
            llm: Language model instance. If None, creates default Bedrock client.
            settings: Application settings. If None, loads from environment.
        """
        self.agent_type = agent_type
        self.settings = settings or get_settings()
        self.llm = llm or get_bedrock_llm()
        self._tools: list[BaseTool] = []

    @property
    def name(self) -> str:
        """Get the agent name."""
        return f"{self.agent_type.value}_agent"

    @property
    def system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return get_system_prompt(self.agent_type.value)

    @property
    def tools(self) -> list[BaseTool]:
        """Get the tools available to this agent."""
        return self._tools

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool for this agent to use."""
        self._tools.append(tool)

    def register_tools(self, tools: list[BaseTool]) -> None:
        """Register multiple tools for this agent."""
        self._tools.extend(tools)

    @abstractmethod
    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process the current state and return updated state.

        This is the main entry point called by the LangGraph orchestrator.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        pass

    async def invoke_llm(
        self,
        user_message: str,
        state: InfraAgentState,
        additional_context: Optional[str] = None,
    ) -> str:
        """
        Invoke the LLM with the current context.

        Args:
            user_message: User's input message
            state: Current agent state
            additional_context: Optional additional context to include

        Returns:
            LLM response content
        """
        messages = [
            SystemMessage(content=self.system_prompt),
        ]

        if additional_context:
            messages.append(SystemMessage(content=additional_context))

        # Add conversation history
        for msg in state.messages[-10:]:  # Last 10 messages for context
            messages.append(msg)

        # Add current user message
        messages.append(HumanMessage(content=user_message))

        response = await self.llm.ainvoke(messages)
        return response.content

    def log_action(
        self,
        state: InfraAgentState,
        action: str,
        success: bool,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Log an action to the audit trail.

        Args:
            state: Current agent state
            action: Description of the action
            success: Whether the action succeeded
            resource_type: Type of resource affected
            resource_id: ID of resource affected
            details: Additional details about the action
        """
        state.add_audit_entry(
            agent=self.agent_type,
            action=action,
            success=success,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )

    def validate_mfa(self, state: InfraAgentState) -> bool:
        """
        Validate MFA status for operations requiring it.

        Args:
            state: Current agent state

        Returns:
            True if MFA is valid or not required, False otherwise
        """
        if not state.check_mfa_required():
            return True
        return state.mfa_verified

    def validate_session(self, state: InfraAgentState) -> bool:
        """
        Validate the current session.

        Args:
            state: Current agent state

        Returns:
            True if session is valid, False otherwise
        """
        return state.is_session_valid()

    def get_operation_context(self, state: InfraAgentState) -> dict[str, Any]:
        """
        Get context information for the current operation.

        Args:
            state: Current agent state

        Returns:
            Dictionary with operation context
        """
        return {
            "environment": state.environment.value,
            "operator_id": state.operator_id,
            "mfa_verified": state.mfa_verified,
            "current_agent": state.current_agent.value,
            "operation_type": state.operation_type.value if state.operation_type else None,
        }
