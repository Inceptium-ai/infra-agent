"""Audit Agent - Compliance, security, cost, and drift audits.

The Audit Agent is responsible for:
- NIST 800-53 compliance verification
- Security posture assessment
- Cost optimization analysis
- Configuration drift detection
"""

import json
import uuid
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.agents.audit.tools import AUDIT_TOOLS
from infra_agent.core.contracts import (
    AuditControl,
    AuditOutput,
    AuditRequest,
    AuditType,
    CostFinding,
    DriftFinding,
    SecurityFinding,
)
from infra_agent.core.state import AgentType, InfraAgentState


class AuditAgent(BaseAgent):
    """
    Audit Agent - Compliance, security, cost, and drift audits.

    This agent operates independently from the 4-agent pipeline and is
    invoked when users request audits like:
    - "Audit NIST compliance"
    - "Run a security scan"
    - "Find idle resources and cost savings"
    - "Check for configuration drift"
    """

    def __init__(self, **kwargs):
        """Initialize the Audit Agent."""
        super().__init__(agent_type=AgentType.AUDIT, **kwargs)
        self.register_tools(AUDIT_TOOLS)

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph for audit requests.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with audit results
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": [AIMessage(content="No audit query provided")]}

        # Get the last user message
        last_message = messages[-1]
        user_input = last_message.content if hasattr(last_message, "content") else str(last_message)

        # Generate request ID
        request_id = f"audit-{uuid.uuid4().hex[:8]}"

        # Parse audit type from request
        audit_type = self._parse_audit_type(user_input)

        # Create audit request
        request = AuditRequest(
            request_id=request_id,
            user_prompt=user_input,
            audit_type=audit_type,
            environment=state.get("environment", "DEV"),
            operator_id=state.get("operator_id", "unknown"),
        )

        # Run audit
        output = await self._run_audit(request, user_input)

        # Store output in state
        output_json = output.model_dump_json()

        # Format response for user
        response = self._format_audit_response(output)

        return {
            "messages": [AIMessage(content=response)],
            "audit_output_json": output_json,
        }

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process an audit request.

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
        request_id = f"audit-{uuid.uuid4().hex[:8]}"

        # Parse audit type
        audit_type = self._parse_audit_type(user_input)

        # Create audit request
        request = AuditRequest(
            request_id=request_id,
            user_prompt=user_input,
            audit_type=audit_type,
            environment=state.environment.value,
            operator_id=state.operator_id or "unknown",
        )

        # Run audit
        output = await self._run_audit(request, user_input)

        # Store output
        state.audit_output_json = output.model_dump_json()

        # Log action
        self.log_action(
            state=state,
            action="audit",
            success=output.status == "completed",
            resource_type="audit",
            resource_id=request_id,
            details={"audit_type": audit_type.value},
        )

        # Format and send response
        response = self._format_audit_response(output)
        state.messages.append(AIMessage(content=response))

        return state

    def _parse_audit_type(self, user_input: str) -> AuditType:
        """
        Parse audit type from user input.

        Args:
            user_input: User's audit request

        Returns:
            Detected audit type
        """
        input_lower = user_input.lower()

        if any(word in input_lower for word in ["nist", "compliance", "800-53"]):
            return AuditType.COMPLIANCE
        elif any(word in input_lower for word in ["security", "vulnerability", "scan", "trivy"]):
            return AuditType.SECURITY
        elif any(word in input_lower for word in ["cost", "idle", "savings", "kubecost", "rightsiz"]):
            return AuditType.COST
        elif any(word in input_lower for word in ["drift", "configuration"]):
            return AuditType.DRIFT
        else:
            return AuditType.FULL

    async def _run_audit(
        self, request: AuditRequest, user_input: str
    ) -> AuditOutput:
        """
        Run the audit using tools and LLM.

        Args:
            request: Audit request
            user_input: Original user query

        Returns:
            Audit output with findings
        """
        # Build audit context
        context = self._build_audit_context(request)

        # Build audit prompt based on type
        audit_prompt = self._build_audit_prompt(request, user_input)

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_message=audit_prompt,
                context=context,
                max_iterations=10,
            )

            # Build output based on audit type
            output = self._build_audit_output(request, response, tool_calls)

            return output

        except Exception as e:
            return AuditOutput(
                request_id=request.request_id,
                audit_type=request.audit_type,
                status="failed",
                summary=f"Audit failed: {str(e)}",
            )

    def _build_audit_context(self, request: AuditRequest) -> str:
        """Build context for the audit."""
        context = f"""Audit Context:
- Request ID: {request.request_id}
- Audit Type: {request.audit_type.value}
- Environment: {request.environment}
- Timestamp: {request.timestamp}
"""
        if request.target_namespace:
            context += f"- Target Namespace: {request.target_namespace}\n"
        if request.target_controls:
            context += f"- Target Controls: {', '.join(request.target_controls)}\n"

        return context

    def _build_audit_prompt(self, request: AuditRequest, user_input: str) -> str:
        """Build the audit prompt based on type."""
        base_prompt = f"""Perform the following audit and provide detailed findings:

User Request: {user_input}

Audit Type: {request.audit_type.value}
"""

        if request.audit_type == AuditType.COMPLIANCE:
            return base_prompt + """
Run NIST 800-53 compliance checks:
1. Use nist_control_check for each relevant control (SC-8, SC-28, AC-2, AC-6, AU-2, AU-3, CM-2, CM-3, CP-9, RA-5)
2. Check encryption with encryption_audit
3. Check mTLS with istio_mtls_check

Provide:
- Status for each control (PASSED, FAILED, PARTIAL)
- Evidence collected
- Remediation guidance for failures
- Overall compliance score (percentage of controls passed)
"""

        elif request.audit_type == AuditType.SECURITY:
            return base_prompt + """
Run security posture assessment:
1. Check IAM policies with iam_audit
2. Check public access with public_access_check
3. Get vulnerability scan results with trivy_results
4. Audit network policies with network_policy_audit
5. Check mTLS with istio_mtls_check

Provide:
- Critical and high severity findings
- CVE IDs if applicable
- Remediation priority
- Security recommendations
"""

        elif request.audit_type == AuditType.COST:
            return base_prompt + """
Run cost optimization analysis:
1. Check for idle resources with idle_resource_check
2. Get rightsizing recommendations with rightsizing_recommendations
3. Find unattached resources with unattached_resources
4. Query Kubecost for cost data with kubecost_query

Provide:
- Identified waste and savings opportunities
- Estimated monthly savings
- Prioritized recommendations
- Resource-specific guidance
"""

        elif request.audit_type == AuditType.DRIFT:
            return base_prompt + """
Run configuration drift detection:
1. Check CloudFormation drift with cfn_drift
2. Check Helm drift with helm_drift for key releases
3. Check K8s drift with k8s_drift for deployments

Provide:
- Drifted resources
- Expected vs actual values
- Remediation commands
- IaC file references
"""

        else:  # FULL audit
            return base_prompt + """
Run comprehensive audit covering:

1. COMPLIANCE:
   - Check key NIST controls (SC-8, SC-28, AC-6)
   - Verify encryption

2. SECURITY:
   - IAM policy review
   - Public access check
   - Vulnerability scan results

3. COST:
   - Idle resource detection
   - Unattached volumes

4. DRIFT:
   - CloudFormation drift

Provide a summary with:
- Overall health score
- Top 5 recommendations
- Critical issues requiring immediate attention
"""

    def _build_audit_output(
        self, request: AuditRequest, response: str, tool_calls: list[dict[str, Any]]
    ) -> AuditOutput:
        """Build structured audit output from LLM response."""
        output = AuditOutput(
            request_id=request.request_id,
            audit_type=request.audit_type,
            status="completed",
            summary=self._extract_summary(response),
        )

        # Parse tool results for structured data
        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            # Note: In a real implementation, we'd parse the actual tool results
            # For now, we extract from the response

        # Extract compliance controls if compliance audit
        if request.audit_type in [AuditType.COMPLIANCE, AuditType.FULL]:
            output.compliance_controls = self._extract_controls(response)
            output.controls_passed = sum(1 for c in output.compliance_controls if c.status == "passed")
            output.controls_failed = sum(1 for c in output.compliance_controls if c.status == "failed")
            output.controls_partial = sum(1 for c in output.compliance_controls if c.status == "partial")

        # Extract security findings if security audit
        if request.audit_type in [AuditType.SECURITY, AuditType.FULL]:
            output.security_findings = self._extract_security_findings(response)
            output.critical_security_count = sum(1 for f in output.security_findings if f.severity == "critical")
            output.high_security_count = sum(1 for f in output.security_findings if f.severity == "high")

        # Extract cost findings if cost audit
        if request.audit_type in [AuditType.COST, AuditType.FULL]:
            output.cost_findings = self._extract_cost_findings(response)
            output.potential_savings = sum(f.potential_savings for f in output.cost_findings)

        # Extract drift findings if drift audit
        if request.audit_type in [AuditType.DRIFT, AuditType.FULL]:
            output.drift_findings = self._extract_drift_findings(response)
            output.resources_drifted = len(output.drift_findings)

        # Calculate overall score
        output.overall_score = self._calculate_score(output)

        # Extract recommendations
        output.top_recommendations = self._extract_recommendations(response)

        # Check if IaC changes needed
        output.requires_iac_change = any(
            keyword in response.lower()
            for keyword in ["helm values", "cloudformation", "yaml", "update", "modify"]
        )

        return output

    def _extract_summary(self, response: str) -> str:
        """Extract summary from response."""
        if "summary:" in response.lower():
            idx = response.lower().find("summary:")
            end_idx = response.find("\n\n", idx)
            if end_idx == -1:
                end_idx = min(idx + 500, len(response))
            return response[idx + 8:end_idx].strip()

        return response[:300].strip() + ("..." if len(response) > 300 else "")

    def _extract_controls(self, response: str) -> list[AuditControl]:
        """Extract NIST control results from response."""
        controls = []
        control_ids = ["SC-8", "SC-28", "AC-2", "AC-6", "AU-2", "AU-3", "CM-2", "CM-3", "CP-9", "RA-5"]

        control_names = {
            "SC-8": "Transmission Confidentiality",
            "SC-28": "Protection of Information at Rest",
            "AC-2": "Account Management",
            "AC-6": "Least Privilege",
            "AU-2": "Audit Events",
            "AU-3": "Content of Audit Records",
            "CM-2": "Baseline Configuration",
            "CM-3": "Configuration Change Control",
            "CP-9": "System Backup",
            "RA-5": "Vulnerability Scanning",
        }

        for control_id in control_ids:
            if control_id in response:
                # Determine status from response
                status = "unknown"
                idx = response.find(control_id)
                context = response[idx:idx + 200].lower()

                if "passed" in context or "pass" in context:
                    status = "passed"
                elif "failed" in context or "fail" in context:
                    status = "failed"
                elif "partial" in context:
                    status = "partial"

                controls.append(AuditControl(
                    control_id=control_id,
                    control_name=control_names.get(control_id, control_id),
                    status=status,
                    description=f"NIST 800-53 {control_id} check",
                    evidence=[f"See audit response for {control_id}"],
                ))

        return controls

    def _extract_security_findings(self, response: str) -> list[SecurityFinding]:
        """Extract security findings from response."""
        findings = []
        finding_count = 0

        # Look for severity indicators
        for severity in ["critical", "high", "medium", "low"]:
            if severity in response.lower():
                finding_count += 1
                findings.append(SecurityFinding(
                    id=f"SEC-{finding_count:03d}",
                    severity=severity,
                    category="security_scan",
                    title=f"{severity.capitalize()} severity finding",
                    description="See audit response for details",
                    remediation="Address based on audit recommendations",
                ))

        return findings[:10]  # Limit to 10 findings

    def _extract_cost_findings(self, response: str) -> list[CostFinding]:
        """Extract cost findings from response."""
        findings = []
        finding_count = 0

        cost_keywords = ["idle", "unattached", "oversized", "unused"]

        for keyword in cost_keywords:
            if keyword in response.lower():
                finding_count += 1
                findings.append(CostFinding(
                    id=f"COST-{finding_count:03d}",
                    category=keyword,
                    title=f"{keyword.capitalize()} resource finding",
                    description="See audit response for details",
                    current_monthly_cost=0.0,  # Would be calculated from actual data
                    potential_savings=0.0,  # Would be calculated from actual data
                    recommendation=f"Review {keyword} resources",
                ))

        return findings

    def _extract_drift_findings(self, response: str) -> list[DriftFinding]:
        """Extract drift findings from response."""
        findings = []
        finding_count = 0

        drift_types = ["cloudformation", "helm", "kubernetes"]

        for drift_type in drift_types:
            if drift_type in response.lower() and "drift" in response.lower():
                finding_count += 1
                findings.append(DriftFinding(
                    id=f"DRIFT-{finding_count:03d}",
                    resource_type=drift_type,
                    resource_name="See audit response",
                    expected_value="IaC-defined",
                    actual_value="Live state",
                    remediation=f"Re-apply {drift_type} configuration",
                ))

        return findings

    def _calculate_score(self, output: AuditOutput) -> float:
        """Calculate overall audit score."""
        scores = []

        # Compliance score
        if output.compliance_controls:
            total = len(output.compliance_controls)
            passed = output.controls_passed
            partial = output.controls_partial
            compliance_score = ((passed + (partial * 0.5)) / total) * 100 if total > 0 else 100
            scores.append(compliance_score)

        # Security score (deduct for critical/high findings)
        if output.security_findings:
            base = 100
            base -= output.critical_security_count * 20
            base -= output.high_security_count * 10
            scores.append(max(0, base))

        # Drift score
        if output.drift_findings:
            base = 100
            base -= output.resources_drifted * 15
            scores.append(max(0, base))

        if scores:
            return round(sum(scores) / len(scores), 1)
        return 100.0

    def _extract_recommendations(self, response: str) -> list[str]:
        """Extract recommendations from response."""
        recommendations = []
        response_lower = response.lower()

        recommendation_keywords = ["recommend", "should", "fix", "remediate", "address"]

        for keyword in recommendation_keywords:
            if keyword in response_lower:
                idx = response_lower.find(keyword)
                end_idx = response.find("\n", idx)
                if end_idx == -1:
                    end_idx = min(idx + 200, len(response))

                rec = response[idx:end_idx].strip()
                if rec and len(rec) > 10:
                    recommendations.append(rec[:150])

        return recommendations[:5]  # Top 5 recommendations

    def _format_audit_response(self, output: AuditOutput) -> str:
        """Format audit output for display."""
        lines = [
            f"**Audit Complete** (ID: {output.request_id})\n",
            f"**Type:** {output.audit_type.value.upper()}",
            f"**Status:** {output.status.upper()}",
        ]

        if output.overall_score is not None:
            lines.append(f"**Overall Score:** {output.overall_score}%")

        lines.append(f"\n**Summary:**\n{output.summary}\n")

        # Compliance results
        if output.compliance_controls:
            lines.append("**Compliance Results:**")
            lines.append(f"- Passed: {output.controls_passed}")
            lines.append(f"- Failed: {output.controls_failed}")
            lines.append(f"- Partial: {output.controls_partial}")
            lines.append("")

            for control in output.compliance_controls:
                status_icon = "pass" if control.status == "passed" else ("warn" if control.status == "partial" else "fail")
                lines.append(f"  [{status_icon}] {control.control_id}: {control.control_name}")
            lines.append("")

        # Security results
        if output.security_findings:
            lines.append("**Security Findings:**")
            lines.append(f"- Critical: {output.critical_security_count}")
            lines.append(f"- High: {output.high_security_count}")
            for finding in output.security_findings[:5]:
                lines.append(f"  [{finding.severity.upper()}] {finding.id}: {finding.title}")
            lines.append("")

        # Cost results
        if output.cost_findings:
            lines.append("**Cost Findings:**")
            if output.potential_savings > 0:
                lines.append(f"- Potential Monthly Savings: ${output.potential_savings:.2f}")
            for finding in output.cost_findings[:5]:
                lines.append(f"  - {finding.id}: {finding.title}")
            lines.append("")

        # Drift results
        if output.drift_findings:
            lines.append("**Drift Findings:**")
            lines.append(f"- Resources Drifted: {output.resources_drifted}")
            for finding in output.drift_findings[:5]:
                lines.append(f"  - {finding.id}: {finding.resource_type}/{finding.resource_name}")
            lines.append("")

        # Recommendations
        if output.top_recommendations:
            lines.append("**Top Recommendations:**")
            for i, rec in enumerate(output.top_recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        if output.requires_iac_change:
            lines.append("**Note:** IaC changes may be required to address findings.")

        return "\n".join(lines)
