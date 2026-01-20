"""Base agent class for all specialized agents with LangGraph integration."""

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from infra_agent.config import Settings, get_settings
from infra_agent.core.state import AgentType, InfraAgentState, OperationType
from infra_agent.llm.bedrock import get_bedrock_llm, get_system_prompt


# Progress callback type - receives (event_type, message, details)
ProgressCallback = Callable[[str, str, Optional[dict]], None]


class BaseAgent(ABC):
    """
    Abstract base class for all specialized agents.

    Each agent handles a specific domain:
    - Chat: Orchestrator - routes requests and manages pipeline flow
    - Planning: Analyzes requests, generates requirements and acceptance criteria
    - IaC: Implements CloudFormation/Helm changes
    - Review: Validates compliance and security
    - Deploy/Validate: Executes and validates deployments
    - K8s: Direct Kubernetes queries
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
        self._tool_map: dict[str, BaseTool] = {}

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
        self._tool_map[tool.name] = tool

    def register_tools(self, tools: list[BaseTool]) -> None:
        """Register multiple tools for this agent."""
        for tool in tools:
            self.register_tool(tool)

    def get_llm_with_tools(self) -> BaseChatModel:
        """Get LLM bound with tools for function calling."""
        if self._tools:
            return self.llm.bind_tools(self._tools)
        return self.llm

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

    @abstractmethod
    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state and return updates.

        This method is called by the LangGraph StateGraph nodes.
        It receives the PipelineState dict and returns partial updates.

        Args:
            state: Current PipelineState dictionary

        Returns:
            Dictionary with state updates
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

    async def invoke_with_tools(
        self,
        user_message: str,
        context: Optional[str] = None,
        max_iterations: int = 5,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Invoke LLM with tools in a ReAct-style loop.

        This method allows the agent to:
        1. Receive a message
        2. Decide to use a tool
        3. Execute the tool
        4. Continue reasoning until done

        Args:
            user_message: User's input message
            context: Optional additional context
            max_iterations: Maximum tool-use iterations
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (final_response, tool_calls_history)
        """
        messages = [SystemMessage(content=self.system_prompt)]

        if context:
            messages.append(SystemMessage(content=context))

        messages.append(HumanMessage(content=user_message))

        llm_with_tools = self.get_llm_with_tools()
        tool_calls_history = []

        if progress_callback:
            progress_callback("llm_start", f"Invoking {self.name}...", None)

        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback("llm_thinking", f"Reasoning... (iteration {iteration + 1}/{max_iterations})", None)

            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            # Check if there are tool calls
            if not response.tool_calls:
                # No more tool calls - return the response
                if progress_callback:
                    progress_callback("llm_done", "Processing complete", None)
                return response.content, tool_calls_history

            # Execute each tool call
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                if progress_callback:
                    # Create a friendly description of the tool call
                    args_str = ", ".join(f"{k}={v!r}" for k, v in list(tool_args.items())[:2])
                    if len(tool_args) > 2:
                        args_str += ", ..."
                    progress_callback(
                        "tool_call",
                        f"Calling {tool_name}({args_str})",
                        {"tool": tool_name, "args": tool_args}
                    )

                tool_calls_history.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "id": tool_id,
                })

                # Execute the tool
                if tool_name in self._tool_map:
                    tool = self._tool_map[tool_name]
                    try:
                        result = await tool.ainvoke(tool_args)
                        tool_result = str(result)
                        if progress_callback:
                            # Truncate result for display
                            result_preview = tool_result[:100] + "..." if len(tool_result) > 100 else tool_result
                            progress_callback("tool_result", f"Got result from {tool_name}", {"preview": result_preview})
                    except Exception as e:
                        tool_result = f"Error executing tool {tool_name}: {e}"
                        if progress_callback:
                            progress_callback("tool_error", f"Error in {tool_name}: {e}", None)
                else:
                    tool_result = f"Unknown tool: {tool_name}"
                    if progress_callback:
                        progress_callback("tool_error", f"Unknown tool: {tool_name}", None)

                # Add tool result to messages
                messages.append(
                    ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_id,
                    )
                )

        # Max iterations reached - return last response
        if progress_callback:
            progress_callback("max_iterations", f"Max iterations ({max_iterations}) reached", None)

        final_response = messages[-1]
        if isinstance(final_response, AIMessage):
            return final_response.content or "Max iterations reached", tool_calls_history
        return "Max iterations reached without final response", tool_calls_history

    async def run_tool(self, tool_name: str, **kwargs) -> str:
        """
        Run a specific tool by name.

        Args:
            tool_name: Name of the tool to run
            **kwargs: Arguments to pass to the tool

        Returns:
            Tool execution result as string
        """
        if tool_name not in self._tool_map:
            return f"Unknown tool: {tool_name}"

        tool = self._tool_map[tool_name]
        try:
            result = await tool.ainvoke(kwargs)
            return str(result)
        except Exception as e:
            return f"Error executing tool {tool_name}: {e}"

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

    def format_tool_results(self, tool_calls: list[dict[str, Any]]) -> str:
        """
        Format tool call history for context.

        Args:
            tool_calls: List of tool call records

        Returns:
            Formatted string of tool calls and results
        """
        if not tool_calls:
            return ""

        lines = ["Tool execution history:"]
        for call in tool_calls:
            lines.append(f"  - {call['tool']}({call.get('args', {})})")
            if "result" in call:
                lines.append(f"    Result: {call['result'][:200]}...")

        return "\n".join(lines)
