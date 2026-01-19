"""Investigation Agent - Diagnoses issues and troubleshoots problems.

The Investigation Agent is responsible for:
- Diagnosing why pods/services/nodes are unhealthy
- Troubleshooting connectivity and performance issues
- Analyzing logs, events, and metrics to find root causes
- Providing remediation recommendations
"""

import json
import uuid
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.agents.investigation.tools import INVESTIGATION_TOOLS
from infra_agent.core.contracts import (
    InvestigationFinding,
    InvestigationOutput,
    InvestigationRequest,
    InvestigationScope,
    InvestigationSeverity,
)
from infra_agent.core.state import AgentType, InfraAgentState


class InvestigationAgent(BaseAgent):
    """
    Investigation Agent - Diagnoses issues and troubleshoots problems.

    This agent operates independently from the 4-agent pipeline and is
    invoked when users ask troubleshooting questions like:
    - "Why are SigNoz pods restarting?"
    - "Debug why the service is slow"
    - "Investigate node NotReady status"
    """

    def __init__(self, **kwargs):
        """Initialize the Investigation Agent."""
        super().__init__(agent_type=AgentType.INVESTIGATION, **kwargs)
        self.register_tools(INVESTIGATION_TOOLS)

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph for investigate requests.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with investigation results
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": [AIMessage(content="No investigation query provided")]}

        # Get the last user message
        last_message = messages[-1]
        user_input = last_message.content if hasattr(last_message, "content") else str(last_message)

        # Generate request ID
        request_id = f"inv-{uuid.uuid4().hex[:8]}"

        # Create investigation request
        request = InvestigationRequest(
            request_id=request_id,
            user_prompt=user_input,
            environment=state.get("environment", "DEV"),
            operator_id=state.get("operator_id", "unknown"),
        )

        # Parse the request to understand scope
        scope, namespace, target = self._parse_investigation_request(user_input)
        request.scope = scope
        request.namespace = namespace
        request.target_resource = target

        # Run investigation
        output = await self._run_investigation(request, user_input)

        # Store output in state
        output_json = output.model_dump_json()

        # Format response for user
        response = self._format_investigation_response(output)

        return {
            "messages": [AIMessage(content=response)],
            "investigation_output_json": output_json,
        }

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process an investigation request.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content

        # Generate request ID
        request_id = f"inv-{uuid.uuid4().hex[:8]}"

        # Create investigation request
        request = InvestigationRequest(
            request_id=request_id,
            user_prompt=user_input,
            environment=state.environment.value,
            operator_id=state.operator_id or "unknown",
        )

        # Parse scope
        scope, namespace, target = self._parse_investigation_request(user_input)
        request.scope = scope
        request.namespace = namespace
        request.target_resource = target

        # Run investigation
        output = await self._run_investigation(request, user_input)

        # Store output
        state.investigation_output_json = output.model_dump_json()

        # Log action
        self.log_action(
            state=state,
            action="investigate",
            success=output.status == "completed",
            resource_type="investigation",
            resource_id=request_id,
            details={"findings_count": len(output.findings)},
        )

        # Format and send response
        response = self._format_investigation_response(output)
        state.messages.append(AIMessage(content=response))

        return state

    def _parse_investigation_request(
        self, user_input: str
    ) -> tuple[Optional[InvestigationScope], Optional[str], Optional[str]]:
        """
        Parse user input to extract investigation scope and targets.

        Args:
            user_input: User's investigation query

        Returns:
            Tuple of (scope, namespace, target_resource)
        """
        input_lower = user_input.lower()
        scope = None
        namespace = None
        target = None

        # Detect scope
        if any(word in input_lower for word in ["pod", "pods", "container"]):
            scope = InvestigationScope.POD
        elif any(word in input_lower for word in ["node", "nodes"]):
            scope = InvestigationScope.NODE
        elif any(word in input_lower for word in ["service", "svc", "endpoint"]):
            scope = InvestigationScope.SERVICE
        elif any(word in input_lower for word in ["namespace", "ns"]):
            scope = InvestigationScope.NAMESPACE
        elif any(word in input_lower for word in ["ec2", "instance", "aws", "ebs", "rds"]):
            scope = InvestigationScope.AWS
        else:
            scope = InvestigationScope.CLUSTER

        # Detect namespace
        known_namespaces = [
            "signoz", "istio-system", "kube-system", "velero",
            "kubecost", "headlamp", "trivy-system", "demo", "default"
        ]
        for ns in known_namespaces:
            if ns in input_lower:
                namespace = ns
                break

        # If namespace not found, try to extract from patterns
        if not namespace:
            import re
            ns_patterns = [
                r"namespace[s]?\s+(\S+)",
                r"in\s+(\S+)\s+namespace",
                r"-n\s+(\S+)",
            ]
            for pattern in ns_patterns:
                match = re.search(pattern, input_lower)
                if match:
                    namespace = match.group(1)
                    break

        return scope, namespace, target

    async def _run_investigation(
        self, request: InvestigationRequest, user_input: str
    ) -> InvestigationOutput:
        """
        Run the investigation using tools and LLM.

        Args:
            request: Investigation request
            user_input: Original user query

        Returns:
            Investigation output with findings
        """
        # Build investigation context
        context = self._build_investigation_context(request)

        # Invoke LLM with tools
        investigation_prompt = f"""Investigate the following issue and provide findings:

User Query: {user_input}

Scope: {request.scope.value if request.scope else 'cluster-wide'}
Namespace: {request.namespace or 'all namespaces'}
Target: {request.target_resource or 'not specified'}

Use the available tools to gather evidence:
1. Start by checking pod/node health status
2. Look at recent events for errors/warnings
3. Check logs for error patterns
4. Examine resource usage if relevant
5. Check service endpoints if connectivity is the issue

After gathering evidence, provide:
- Summary of what you found
- Root cause analysis
- Severity of each finding
- Recommended actions

Be thorough but focused on the specific issue mentioned."""

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_message=investigation_prompt,
                context=context,
                max_iterations=10,  # Allow more iterations for thorough investigation
            )

            # Parse findings from response
            findings = self._extract_findings(response, tool_calls)

            # Build output
            output = InvestigationOutput(
                request_id=request.request_id,
                status="completed",
                summary=self._extract_summary(response),
                findings=findings,
                root_cause=self._extract_root_cause(response),
                resources_examined=self._get_examined_resources(tool_calls),
                commands_executed=[f"{tc['tool']}({tc.get('args', {})})" for tc in tool_calls],
                immediate_actions=self._extract_actions(response, "immediate"),
                follow_up_actions=self._extract_actions(response, "follow_up"),
                requires_iac_change=self._check_iac_change_needed(response),
                iac_change_description=self._extract_iac_change(response),
            )

            return output

        except Exception as e:
            return InvestigationOutput(
                request_id=request.request_id,
                status="failed",
                summary=f"Investigation failed: {str(e)}",
                findings=[],
            )

    def _build_investigation_context(self, request: InvestigationRequest) -> str:
        """Build context for the investigation."""
        context = f"""Investigation Context:
- Request ID: {request.request_id}
- Environment: {request.environment}
- Timestamp: {request.timestamp}
"""
        if request.scope:
            context += f"- Scope: {request.scope.value}\n"
        if request.namespace:
            context += f"- Namespace: {request.namespace}\n"
        if request.target_resource:
            context += f"- Target: {request.target_resource}\n"

        return context

    def _extract_findings(
        self, response: str, tool_calls: list[dict[str, Any]]
    ) -> list[InvestigationFinding]:
        """Extract structured findings from LLM response."""
        findings = []
        finding_count = 0

        # Look for patterns in response that indicate findings
        response_lower = response.lower()

        # Create findings based on tool results and response analysis
        severity_keywords = {
            InvestigationSeverity.CRITICAL: ["critical", "crash", "oomkilled", "data loss"],
            InvestigationSeverity.HIGH: ["high", "failing", "error", "not ready", "unhealthy"],
            InvestigationSeverity.MEDIUM: ["medium", "warning", "restart", "pending"],
            InvestigationSeverity.LOW: ["low", "slow", "degraded"],
            InvestigationSeverity.INFO: ["info", "note", "consider"],
        }

        # Extract findings from response sections
        if "finding" in response_lower or "issue" in response_lower or "problem" in response_lower:
            # Parse response to find mentioned issues
            lines = response.split("\n")
            current_finding = None

            for line in lines:
                line_lower = line.lower().strip()

                # Detect severity from keywords
                severity = InvestigationSeverity.MEDIUM
                for sev, keywords in severity_keywords.items():
                    if any(kw in line_lower for kw in keywords):
                        severity = sev
                        break

                # Look for finding indicators
                if any(ind in line_lower for ind in ["finding:", "issue:", "problem:", "error:", "- "]):
                    if current_finding:
                        findings.append(current_finding)

                    finding_count += 1
                    current_finding = InvestigationFinding(
                        id=f"FIND-{finding_count:03d}",
                        severity=severity,
                        category="resource_health",
                        title=line.strip("- :").strip()[:100],
                        description=line.strip(),
                        evidence=[],
                        affected_resources=[],
                        recommendation="See recommendations section",
                    )

            if current_finding:
                findings.append(current_finding)

        # If no structured findings, create one from summary
        if not findings and tool_calls:
            findings.append(InvestigationFinding(
                id="FIND-001",
                severity=InvestigationSeverity.INFO,
                category="investigation_result",
                title="Investigation completed",
                description=response[:500] if response else "No specific issues found",
                evidence=[f"Executed {len(tool_calls)} diagnostic commands"],
                affected_resources=[],
                recommendation="Review the investigation summary for details",
            ))

        return findings

    def _extract_summary(self, response: str) -> str:
        """Extract summary from response."""
        # Look for summary section or use first paragraph
        if "summary:" in response.lower():
            idx = response.lower().find("summary:")
            end_idx = response.find("\n\n", idx)
            if end_idx == -1:
                end_idx = min(idx + 500, len(response))
            return response[idx + 8:end_idx].strip()

        # Use first 300 chars as summary
        return response[:300].strip() + ("..." if len(response) > 300 else "")

    def _extract_root_cause(self, response: str) -> Optional[str]:
        """Extract root cause from response."""
        keywords = ["root cause:", "caused by:", "the issue is:", "problem is:"]
        response_lower = response.lower()

        for keyword in keywords:
            if keyword in response_lower:
                idx = response_lower.find(keyword)
                end_idx = response.find("\n", idx + len(keyword))
                if end_idx == -1:
                    end_idx = min(idx + 200, len(response))
                return response[idx + len(keyword):end_idx].strip()

        return None

    def _get_examined_resources(self, tool_calls: list[dict[str, Any]]) -> list[str]:
        """Get list of resources examined during investigation."""
        resources = set()
        for tc in tool_calls:
            args = tc.get("args", {})
            if "namespace" in args:
                resources.add(f"namespace/{args['namespace']}")
            if "pod_name" in args:
                resources.add(f"pod/{args['pod_name']}")
            if "service_name" in args:
                resources.add(f"service/{args['service_name']}")
            if "cluster_name" in args:
                resources.add(f"eks/{args['cluster_name']}")

        return list(resources)

    def _extract_actions(self, response: str, action_type: str) -> list[str]:
        """Extract action recommendations from response."""
        actions = []
        response_lower = response.lower()

        if action_type == "immediate":
            keywords = ["immediately", "urgent", "now", "first", "asap"]
        else:
            keywords = ["long-term", "follow-up", "later", "consider", "should"]

        # Look for action sections
        action_sections = ["recommendation", "action", "fix", "solution", "remediation"]

        for section in action_sections:
            if section in response_lower:
                idx = response_lower.find(section)
                end_idx = response.find("\n\n", idx)
                if end_idx == -1:
                    end_idx = min(idx + 500, len(response))

                section_text = response[idx:end_idx]
                lines = section_text.split("\n")

                for line in lines:
                    line = line.strip()
                    if line.startswith("-") or line.startswith("*") or line[0:2].isdigit():
                        if action_type == "immediate":
                            if any(kw in line.lower() for kw in keywords):
                                actions.append(line.strip("- *0123456789."))
                        else:
                            if not any(kw in line.lower() for kw in ["immediately", "urgent", "asap"]):
                                actions.append(line.strip("- *0123456789."))

        return actions[:5]  # Limit to 5 actions

    def _check_iac_change_needed(self, response: str) -> bool:
        """Check if response indicates IaC changes are needed."""
        iac_keywords = [
            "helm values", "cloudformation", "yaml", "values.yaml",
            "update the config", "modify the template", "change the manifest",
            "iac", "infrastructure as code"
        ]
        response_lower = response.lower()
        return any(kw in response_lower for kw in iac_keywords)

    def _extract_iac_change(self, response: str) -> Optional[str]:
        """Extract IaC change description from response."""
        if not self._check_iac_change_needed(response):
            return None

        # Look for file paths
        import re
        file_patterns = [
            r"infra/helm/values/\S+\.yaml",
            r"infra/cloudformation/\S+\.yaml",
            r"values\.yaml",
        ]

        for pattern in file_patterns:
            match = re.search(pattern, response)
            if match:
                return f"Update {match.group(0)}"

        return "IaC modification may be required - see recommendations"

    def _format_investigation_response(self, output: InvestigationOutput) -> str:
        """Format investigation output for display."""
        lines = [
            f"**Investigation Complete** (ID: {output.request_id})\n",
            f"**Status:** {output.status.upper()}",
            f"\n**Summary:**\n{output.summary}\n",
        ]

        if output.root_cause:
            lines.append(f"**Root Cause:** {output.root_cause}\n")

        if output.findings:
            lines.append("**Findings:**")
            for finding in output.findings:
                lines.append(
                    f"- [{finding.severity.value.upper()}] {finding.id}: {finding.title}"
                )
            lines.append("")

        if output.immediate_actions:
            lines.append("**Immediate Actions:**")
            for action in output.immediate_actions:
                lines.append(f"- {action}")
            lines.append("")

        if output.follow_up_actions:
            lines.append("**Follow-up Actions:**")
            for action in output.follow_up_actions:
                lines.append(f"- {action}")
            lines.append("")

        if output.requires_iac_change:
            lines.append(f"**IaC Change Required:** {output.iac_change_description}")

        if output.resources_examined:
            lines.append(f"\n*Resources examined: {', '.join(output.resources_examined[:5])}*")

        return "\n".join(lines)
