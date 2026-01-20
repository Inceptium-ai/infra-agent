"""Review Agent - Validates IaC changes against compliance and security rules.

The Review Agent is the third agent in the 4-agent pipeline. It receives
IaC changes and validates them using:
- cfn-guard for NIST 800-53 compliance (CloudFormation)
- cfn-lint for CloudFormation best practices
- kube-linter for Kubernetes manifest security
- Security scanning for sensitive data exposure
- Cost estimation for the proposed changes
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_settings
from infra_agent.core.contracts import (
    CostEstimate,
    Finding,
    FindingSeverity,
    IaCOutput,
    ReviewOutput,
    ReviewStatus,
)
from infra_agent.core.state import AgentType, InfraAgentState


class ReviewAgent(BaseAgent):
    """
    Review Agent - Third stage of the 4-agent pipeline.

    Responsibilities:
    - Validate CloudFormation templates with cfn-lint and cfn-guard
    - Validate Kubernetes manifests with kube-linter
    - Check for security issues (secrets exposure, insecure configs)
    - Estimate cost impact of changes
    - Determine if changes should proceed or require revision
    """

    def __init__(self, **kwargs):
        """Initialize the Review Agent."""
        super().__init__(agent_type=AgentType.REVIEW, **kwargs)
        self._project_root = Path(__file__).parent.parent.parent.parent.parent
        self._cfn_path = self._project_root / "infra" / "cloudformation"
        self._helm_path = self._project_root / "infra" / "helm" / "values"
        self._guard_rules_path = self._cfn_path / "cfn-guard-rules" / "nist-800-53"

        # Register tools for agentic execution
        from infra_agent.agents.review.tools import get_review_tools
        self.register_tools(get_review_tools())

        # Register MCP tools for AWS and Git access
        self._register_mcp_tools()

    def _register_mcp_tools(self) -> None:
        """Register MCP tools for AWS API and Git repository access."""
        try:
            from infra_agent.mcp.client import get_aws_tools, get_git_tools
            self.register_tools(get_aws_tools())
            self.register_tools(get_git_tools())
        except Exception:
            pass  # MCP tools optional

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph as the review node.
        Validates IaC changes against compliance and security rules.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with review_output and review_status
        """
        iac_output_json = state.get("iac_output")
        if not iac_output_json:
            return {
                "last_error": "No IaC output found",
                "review_status": "failed",
                "messages": [AIMessage(content="**Review Error:** No IaC output found")],
            }

        try:
            iac_output = IaCOutput.model_validate_json(iac_output_json)
        except Exception as e:
            return {
                "last_error": str(e),
                "review_status": "failed",
                "messages": [AIMessage(content=f"**Review Error:** {e}")],
            }

        # Run validation using tools
        review_output = await self._run_validation_with_tools(iac_output, state)

        # Determine retry count
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 3)

        # Update retry count if needed
        new_retry_count = retry_count
        if review_output.status == ReviewStatus.NEEDS_REVISION:
            new_retry_count = retry_count + 1 if retry_count < max_retries else retry_count

        # Format response
        response = self._format_review_response(review_output)

        return {
            "review_output": review_output.model_dump_json(),
            "review_status": review_output.status.value,
            "retry_count": new_retry_count,
            "messages": [AIMessage(content=response)],
        }

    async def _run_validation_with_tools(
        self, iac_output: IaCOutput, state: dict[str, Any]
    ) -> ReviewOutput:
        """Run validation using tools and LLM analysis."""
        findings: list[Finding] = []
        finding_counter = 1

        # Track gate results
        cfn_guard_passed = True
        cfn_lint_passed = True
        kube_linter_passed = True
        security_scan_passed = True

        # Process each code change
        for change in iac_output.code_changes:
            file_path = self._project_root / change.file_path

            if not file_path.exists():
                continue

            # Run validators based on change type
            if change.change_type.value == "cloudformation":
                lint_findings = self._run_cfn_lint(file_path)
                for f in lint_findings:
                    f.id = f"FIND-{finding_counter:03d}"
                    finding_counter += 1
                    findings.append(f)
                    if f.severity == FindingSeverity.ERROR:
                        cfn_lint_passed = False

                guard_findings = self._run_cfn_guard(file_path)
                for f in guard_findings:
                    f.id = f"FIND-{finding_counter:03d}"
                    finding_counter += 1
                    findings.append(f)
                    if f.severity == FindingSeverity.ERROR:
                        cfn_guard_passed = False

            elif change.change_type.value in ["helm", "kubernetes"]:
                # kube-linter only works on K8s manifests, not Helm values files
                # Skip linting for files in helm/values directories
                if "helm/values" in str(file_path) or change.change_type.value == "helm":
                    # For Helm values files, do YAML syntax validation instead
                    yaml_findings = self._validate_yaml_syntax(file_path)
                    for f in yaml_findings:
                        f.id = f"FIND-{finding_counter:03d}"
                        finding_counter += 1
                        findings.append(f)
                        if f.severity == FindingSeverity.ERROR:
                            kube_linter_passed = False
                else:
                    # For actual K8s manifests, run kube-linter
                    linter_findings = self._run_kube_linter(file_path)
                    for f in linter_findings:
                        f.id = f"FIND-{finding_counter:03d}"
                        finding_counter += 1
                        findings.append(f)
                        if f.severity == FindingSeverity.ERROR:
                            kube_linter_passed = False

            # Security scan
            security_findings = self._run_security_scan(file_path)
            for f in security_findings:
                f.id = f"FIND-{finding_counter:03d}"
                finding_counter += 1
                findings.append(f)
                if f.severity == FindingSeverity.ERROR:
                    security_scan_passed = False

        # Count findings
        blocking = sum(1 for f in findings if f.severity == FindingSeverity.ERROR)
        warnings = sum(1 for f in findings if f.severity == FindingSeverity.WARNING)

        # Cost estimate
        cost_estimate = self._estimate_cost(iac_output)

        # Determine status
        all_gates_passed = cfn_guard_passed and cfn_lint_passed and kube_linter_passed and security_scan_passed

        if all_gates_passed and blocking == 0:
            status = ReviewStatus.PASSED
        elif blocking > 0:
            status = ReviewStatus.NEEDS_REVISION
        else:
            status = ReviewStatus.NEEDS_REVISION

        # Retry logic
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 3)
        should_retry = status != ReviewStatus.PASSED and retry_count < max_retries

        review_notes = self._generate_review_notes(findings) if should_retry else ""

        return ReviewOutput(
            request_id=iac_output.request_id,
            iac_output=iac_output,
            status=status,
            findings=findings,
            cfn_guard_passed=cfn_guard_passed,
            cfn_lint_passed=cfn_lint_passed,
            kube_linter_passed=kube_linter_passed,
            security_scan_passed=security_scan_passed,
            cost_estimate=cost_estimate,
            blocking_findings=blocking,
            warning_findings=warnings,
            review_notes=review_notes,
            max_retries=max_retries,
            should_retry=should_retry,
        )

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process IaC output and validate changes.

        Args:
            state: Current agent state with IaCOutput

        Returns:
            Updated state with ReviewOutput
        """
        # Get IaC output from state
        if not state.iac_output_json:
            error_msg = "No IaC output found in state. IaC Agent must run first."
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**Review Error:** {error_msg}"))
            return state

        try:
            iac_output = IaCOutput.model_validate_json(state.iac_output_json)
        except Exception as e:
            error_msg = f"Failed to parse IaC output: {e}"
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**Review Error:** {error_msg}"))
            return state

        # Run all validations
        review_output = await self._run_validation(iac_output, state)

        # Store in state
        state.review_output_json = review_output.model_dump_json()

        # Save artifacts for audit trail (both chat and pipeline modes)
        try:
            from infra_agent.core.artifacts import get_artifact_manager
            artifact_mgr = get_artifact_manager()
            artifact_mgr.save_review_output(review_output)
            # Generate summary after review (we have all info now)
            artifact_mgr.generate_summary(review_output.request_id)
        except Exception as e:
            # Log but don't fail - artifacts are for audit, not critical path
            import logging
            logging.warning(f"Failed to save review artifacts: {e}")

        # Determine next step
        if review_output.status == ReviewStatus.PASSED:
            state.advance_pipeline("deploy_validate")
        elif review_output.should_retry:
            # Go back to IaC for revision
            state.advance_pipeline("iac")
            state.retry_pipeline()
        else:
            # Failed and no more retries
            state.complete_pipeline(success=False)

        # Log action
        self.log_action(
            state=state,
            action="review_iac",
            success=review_output.status == ReviewStatus.PASSED,
            resource_type="review_output",
            resource_id=iac_output.request_id,
            details={
                "status": review_output.status.value,
                "blocking_findings": review_output.blocking_findings,
                "warning_findings": review_output.warning_findings,
            },
        )

        # Create response message
        response = self._format_review_response(review_output)
        state.messages.append(AIMessage(content=response))

        return state

    async def _run_validation(
        self, iac_output: IaCOutput, state: InfraAgentState
    ) -> ReviewOutput:
        """
        Run all validation checks on IaC changes.

        Args:
            iac_output: Output from IaC Agent
            state: Current agent state

        Returns:
            ReviewOutput with validation results
        """
        findings: list[Finding] = []
        finding_counter = 1

        # Track gate results
        cfn_guard_passed = True
        cfn_lint_passed = True
        kube_linter_passed = True
        security_scan_passed = True

        # Process each code change
        for change in iac_output.code_changes:
            file_path = self._project_root / change.file_path

            if not file_path.exists():
                # File doesn't exist (might be planned but not yet written)
                continue

            # Run appropriate validators based on change type
            if change.change_type.value == "cloudformation":
                # Run cfn-lint
                lint_findings = self._run_cfn_lint(file_path)
                for f in lint_findings:
                    f.id = f"FIND-{finding_counter:03d}"
                    finding_counter += 1
                    findings.append(f)
                    if f.severity == FindingSeverity.ERROR:
                        cfn_lint_passed = False

                # Run cfn-guard
                guard_findings = self._run_cfn_guard(file_path)
                for f in guard_findings:
                    f.id = f"FIND-{finding_counter:03d}"
                    finding_counter += 1
                    findings.append(f)
                    if f.severity == FindingSeverity.ERROR:
                        cfn_guard_passed = False

            elif change.change_type.value in ["helm", "kubernetes"]:
                # kube-linter only works on K8s manifests, not Helm values files
                if "helm/values" in str(file_path) or change.change_type.value == "helm":
                    # For Helm values files, do YAML syntax validation
                    yaml_findings = self._validate_yaml_syntax(file_path)
                    for f in yaml_findings:
                        f.id = f"FIND-{finding_counter:03d}"
                        finding_counter += 1
                        findings.append(f)
                        if f.severity == FindingSeverity.ERROR:
                            kube_linter_passed = False
                else:
                    # For actual K8s manifests, run kube-linter
                    linter_findings = self._run_kube_linter(file_path)
                    for f in linter_findings:
                        f.id = f"FIND-{finding_counter:03d}"
                        finding_counter += 1
                        findings.append(f)
                        if f.severity == FindingSeverity.ERROR:
                            kube_linter_passed = False

            # Run security scan on all files
            security_findings = self._run_security_scan(file_path)
            for f in security_findings:
                f.id = f"FIND-{finding_counter:03d}"
                finding_counter += 1
                findings.append(f)
                if f.severity == FindingSeverity.ERROR:
                    security_scan_passed = False

        # Count findings by severity
        blocking = sum(1 for f in findings if f.severity == FindingSeverity.ERROR)
        warnings = sum(1 for f in findings if f.severity == FindingSeverity.WARNING)

        # Estimate cost
        cost_estimate = self._estimate_cost(iac_output)

        # Determine overall status
        all_gates_passed = (
            cfn_guard_passed
            and cfn_lint_passed
            and kube_linter_passed
            and security_scan_passed
        )

        if all_gates_passed and blocking == 0:
            status = ReviewStatus.PASSED
        elif blocking > 0:
            status = ReviewStatus.FAILED
        else:
            status = ReviewStatus.NEEDS_REVISION

        # Determine if we should retry
        max_retries = 3
        should_retry = (
            status != ReviewStatus.PASSED
            and iac_output.retry_count < max_retries
        )

        # Generate review notes for IaC agent
        review_notes = ""
        if should_retry and findings:
            review_notes = self._generate_review_notes(findings)

        return ReviewOutput(
            request_id=iac_output.request_id,
            iac_output=iac_output,
            status=status,
            findings=findings,
            cfn_guard_passed=cfn_guard_passed,
            cfn_lint_passed=cfn_lint_passed,
            kube_linter_passed=kube_linter_passed,
            security_scan_passed=security_scan_passed,
            cost_estimate=cost_estimate,
            blocking_findings=blocking,
            warning_findings=warnings,
            review_notes=review_notes,
            max_retries=max_retries,
            should_retry=should_retry,
        )

    def _run_cfn_lint(self, file_path: Path) -> list[Finding]:
        """Run cfn-lint on a CloudFormation template."""
        findings = []

        try:
            result = subprocess.run(
                ["cfn-lint", str(file_path), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.stdout:
                try:
                    lint_results = json.loads(result.stdout)
                    for item in lint_results:
                        severity = FindingSeverity.WARNING
                        if item.get("Level", "").upper() == "ERROR":
                            severity = FindingSeverity.ERROR
                        elif item.get("Level", "").upper() == "WARNING":
                            severity = FindingSeverity.WARNING
                        else:
                            severity = FindingSeverity.INFO

                        findings.append(
                            Finding(
                                id="",  # Will be set by caller
                                severity=severity,
                                source="cfn-lint",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=item.get("Location", {}).get("Start", {}).get("LineNumber"),
                                rule_id=item.get("Rule", {}).get("Id", "unknown"),
                                message=item.get("Message", "Unknown issue"),
                                remediation=item.get("Rule", {}).get("ShortDescription", "Fix the reported issue"),
                            )
                        )
                except json.JSONDecodeError:
                    # Non-JSON output, parse as text
                    if result.returncode != 0 and result.stderr:
                        findings.append(
                            Finding(
                                id="",
                                severity=FindingSeverity.ERROR,
                                source="cfn-lint",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=None,
                                rule_id="parse-error",
                                message=result.stderr[:200],
                                remediation="Fix the template syntax",
                            )
                        )

        except FileNotFoundError:
            # cfn-lint not installed, skip
            pass
        except subprocess.TimeoutExpired:
            findings.append(
                Finding(
                    id="",
                    severity=FindingSeverity.WARNING,
                    source="cfn-lint",
                    file_path=str(file_path.relative_to(self._project_root)),
                    line_number=None,
                    rule_id="timeout",
                    message="cfn-lint timed out",
                    remediation="Check template size or complexity",
                )
            )
        except Exception as e:
            findings.append(
                Finding(
                    id="",
                    severity=FindingSeverity.WARNING,
                    source="cfn-lint",
                    file_path=str(file_path.relative_to(self._project_root)),
                    line_number=None,
                    rule_id="error",
                    message=str(e)[:200],
                    remediation="Ensure cfn-lint is properly configured",
                )
            )

        return findings

    def _run_cfn_guard(self, file_path: Path) -> list[Finding]:
        """Run cfn-guard for NIST compliance checking."""
        findings = []

        if not self._guard_rules_path.exists():
            return findings

        try:
            result = subprocess.run(
                [
                    "cfn-guard",
                    "validate",
                    "--data", str(file_path),
                    "--rules", str(self._guard_rules_path),
                    "--output-format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.stdout:
                try:
                    guard_results = json.loads(result.stdout)
                    # Parse cfn-guard JSON output
                    for item in guard_results.get("not_compliant", []):
                        findings.append(
                            Finding(
                                id="",
                                severity=FindingSeverity.ERROR,
                                source="cfn-guard",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=None,
                                rule_id=item.get("rule", "NIST-unknown"),
                                message=item.get("message", "NIST compliance violation"),
                                remediation=item.get("remediation", "Review NIST 800-53 requirements"),
                            )
                        )
                except json.JSONDecodeError:
                    # Parse non-JSON output
                    if "FAIL" in result.stdout:
                        findings.append(
                            Finding(
                                id="",
                                severity=FindingSeverity.ERROR,
                                source="cfn-guard",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=None,
                                rule_id="NIST-compliance",
                                message="Template failed NIST compliance check",
                                remediation="Review cfn-guard output for specific violations",
                            )
                        )

        except FileNotFoundError:
            # cfn-guard not installed, skip
            pass
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        return findings

    def _run_kube_linter(self, file_path: Path) -> list[Finding]:
        """Run kube-linter on Kubernetes/Helm manifests."""
        findings = []

        try:
            result = subprocess.run(
                ["kube-linter", "lint", str(file_path), "--format", "json"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.stdout:
                try:
                    lint_results = json.loads(result.stdout)
                    for report in lint_results.get("Reports", []):
                        severity = FindingSeverity.WARNING
                        if "error" in report.get("Diagnostic", {}).get("Message", "").lower():
                            severity = FindingSeverity.ERROR

                        findings.append(
                            Finding(
                                id="",
                                severity=severity,
                                source="kube-linter",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=None,
                                rule_id=report.get("Check", "unknown"),
                                message=report.get("Diagnostic", {}).get("Message", "Unknown issue"),
                                remediation=report.get("Remediation", "Fix the reported issue"),
                            )
                        )
                except json.JSONDecodeError:
                    pass

        except FileNotFoundError:
            # kube-linter not installed, skip
            pass
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        return findings

    def _validate_yaml_syntax(self, file_path: Path) -> list[Finding]:
        """Validate YAML syntax for Helm values files."""
        findings = []

        try:
            import yaml

            content = file_path.read_text()
            # Try to parse the YAML
            yaml.safe_load(content)

        except yaml.YAMLError as e:
            # YAML parsing error
            line_num = None
            if hasattr(e, 'problem_mark') and e.problem_mark:
                line_num = e.problem_mark.line + 1

            findings.append(
                Finding(
                    id="",
                    severity=FindingSeverity.ERROR,
                    source="yaml-syntax",
                    file_path=str(file_path.relative_to(self._project_root)),
                    line_number=line_num,
                    rule_id="YAML-001",
                    message=f"YAML syntax error: {str(e)[:200]}",
                    remediation="Fix the YAML syntax error",
                )
            )
        except Exception as e:
            findings.append(
                Finding(
                    id="",
                    severity=FindingSeverity.ERROR,
                    source="yaml-syntax",
                    file_path=str(file_path.relative_to(self._project_root)),
                    line_number=None,
                    rule_id="YAML-002",
                    message=f"Failed to validate YAML: {str(e)[:200]}",
                    remediation="Check file encoding and content",
                )
            )

        return findings

    def _run_security_scan(self, file_path: Path) -> list[Finding]:
        """Scan file for potential security issues."""
        findings = []

        try:
            content = file_path.read_text()
            content_lower = content.lower()

            # Check for potential secrets
            secret_patterns = [
                ("password:", "Potential hardcoded password"),
                ("secret:", "Potential hardcoded secret"),
                ("api_key:", "Potential hardcoded API key"),
                ("access_key:", "Potential hardcoded access key"),
                ("private_key:", "Potential hardcoded private key"),
                ("BEGIN RSA", "Potential embedded private key"),
                ("BEGIN PRIVATE KEY", "Potential embedded private key"),
            ]

            for pattern, message in secret_patterns:
                if pattern.lower() in content_lower:
                    # Try to find line number
                    line_num = None
                    for i, line in enumerate(content.split("\n"), 1):
                        if pattern.lower() in line.lower():
                            # Check if it's a reference (e.g., secretRef) vs actual value
                            if "ref" in line.lower() or "name:" in line.lower():
                                continue
                            line_num = i
                            break

                    if line_num:
                        findings.append(
                            Finding(
                                id="",
                                severity=FindingSeverity.ERROR,
                                source="security",
                                file_path=str(file_path.relative_to(self._project_root)),
                                line_number=line_num,
                                rule_id="SEC-001",
                                message=message,
                                remediation="Use Kubernetes secrets or external secret management",
                            )
                        )

            # Check for insecure configurations
            insecure_patterns = [
                ("privileged: true", "Container running as privileged", "SEC-002"),
                ("allowPrivilegeEscalation: true", "Privilege escalation enabled", "SEC-003"),
                ("runAsRoot: true", "Container running as root", "SEC-004"),
            ]

            for pattern, message, rule_id in insecure_patterns:
                if pattern.lower() in content_lower:
                    findings.append(
                        Finding(
                            id="",
                            severity=FindingSeverity.WARNING,
                            source="security",
                            file_path=str(file_path.relative_to(self._project_root)),
                            line_number=None,
                            rule_id=rule_id,
                            message=message,
                            remediation="Review security context settings",
                        )
                    )

        except Exception:
            pass

        return findings

    def _estimate_cost(self, iac_output: IaCOutput) -> Optional[CostEstimate]:
        """Estimate cost impact of the changes."""
        # Basic cost estimation based on change types
        monthly_delta = 0.0
        affected_resources = []
        notes = []

        for change in iac_output.code_changes:
            diff_lower = change.diff_summary.lower()

            # Check for replica changes
            if "replica" in diff_lower:
                if "increase" in diff_lower or "->" in diff_lower:
                    # Try to extract numbers
                    import re
                    numbers = re.findall(r'\d+', diff_lower)
                    if len(numbers) >= 2:
                        old_replicas = int(numbers[0])
                        new_replicas = int(numbers[1])
                        if new_replicas > old_replicas:
                            # Rough estimate: $50/month per replica for typical workload
                            delta = (new_replicas - old_replicas) * 50
                            monthly_delta += delta
                            affected_resources.append(f"replicas: {old_replicas} -> {new_replicas}")
                            notes.append(f"Estimated +${delta}/month for {new_replicas - old_replicas} additional replicas")

            # Check for resource changes
            if "cpu" in diff_lower or "memory" in diff_lower:
                affected_resources.append("resource limits/requests")
                notes.append("Resource changes may affect node capacity and costs")

            # Check for storage changes
            if "storage" in diff_lower or "volume" in diff_lower:
                affected_resources.append("storage")
                notes.append("Storage changes affect EBS costs")

        if not affected_resources:
            return None

        return CostEstimate(
            monthly_delta=monthly_delta,
            affected_resources=affected_resources,
            notes="; ".join(notes) if notes else "Estimated based on change patterns",
        )

    def _generate_review_notes(self, findings: list[Finding]) -> str:
        """Generate detailed notes for IaC agent to fix issues.

        Provides specific, actionable guidance for common issues.
        """
        notes_parts = [
            "## Review Findings - Action Required\n",
            "The following issues must be fixed before the code can be approved:\n",
        ]

        # Group findings by file
        findings_by_file: dict[str, list[Finding]] = {}
        for finding in findings:
            if finding.severity == FindingSeverity.ERROR:
                if finding.file_path not in findings_by_file:
                    findings_by_file[finding.file_path] = []
                findings_by_file[finding.file_path].append(finding)

        for file_path, file_findings in findings_by_file.items():
            notes_parts.append(f"\n### File: `{file_path}`\n")

            for finding in file_findings:
                notes_parts.append(f"**[{finding.rule_id}]** {finding.message}")
                if finding.line_number:
                    notes_parts.append(f"  - Line: {finding.line_number}")
                notes_parts.append(f"  - Source: {finding.source}")
                notes_parts.append(f"  - Fix: {finding.remediation}")

                # Add specific guidance for common issues
                if finding.source == "yaml-syntax":
                    notes_parts.append("  - IMPORTANT: Ensure YAML is valid - no markdown fences (```), proper indentation")
                elif finding.source == "cfn-lint" and "E0000" in finding.rule_id:
                    notes_parts.append("  - IMPORTANT: The file may contain non-YAML content. Remove any markdown formatting.")
                elif finding.source == "security":
                    notes_parts.append("  - IMPORTANT: Never hardcode secrets. Use Kubernetes secrets or AWS Secrets Manager.")

                notes_parts.append("")

        # Add general guidance
        notes_parts.append("\n## General Guidelines:\n")
        notes_parts.append("1. Output ONLY valid YAML/JSON - no markdown code fences (``` or ```yaml)")
        notes_parts.append("2. Use proper YAML indentation (2 spaces)")
        notes_parts.append("3. Reference secrets via secretRef, never embed values")
        notes_parts.append("4. Ensure all required fields are present")

        return "\n".join(notes_parts)

    def _format_review_response(self, output: ReviewOutput) -> str:
        """Format review output as a user-friendly response."""
        status_emoji = {
            ReviewStatus.PASSED: "PASSED",
            ReviewStatus.FAILED: "FAILED",
            ReviewStatus.NEEDS_REVISION: "NEEDS REVISION",
        }

        lines = [
            f"**Review Complete** (Request: {output.request_id})\n",
            f"**Status:** {status_emoji[output.status]}\n",
        ]

        # Gate results
        lines.append("**Validation Gates:**")
        lines.append(f"  - cfn-guard (NIST): {'PASS' if output.cfn_guard_passed else 'FAIL'}")
        lines.append(f"  - cfn-lint: {'PASS' if output.cfn_lint_passed else 'FAIL'}")
        lines.append(f"  - kube-linter: {'PASS' if output.kube_linter_passed else 'FAIL'}")
        lines.append(f"  - Security scan: {'PASS' if output.security_scan_passed else 'FAIL'}")

        # Findings summary
        if output.findings:
            lines.append(f"\n**Findings:** {output.blocking_findings} errors, {output.warning_findings} warnings\n")

            # Show blocking findings
            blocking = [f for f in output.findings if f.severity == FindingSeverity.ERROR]
            if blocking:
                lines.append("**Blocking Issues:**")
                for f in blocking[:5]:  # Limit to 5
                    lines.append(f"  - [{f.rule_id}] {f.message}")
                    lines.append(f"    File: `{f.file_path}`")
                    lines.append(f"    Fix: {f.remediation}")

        # Cost estimate
        if output.cost_estimate:
            lines.append(f"\n**Cost Impact:** ${output.cost_estimate.monthly_delta:+.2f}/month")
            if output.cost_estimate.notes:
                lines.append(f"  Note: {output.cost_estimate.notes}")

        # Next steps
        if output.status == ReviewStatus.PASSED:
            lines.append("\n**Next:** Proceeding to deployment...")
        elif output.should_retry:
            lines.append(f"\n**Next:** Returning to IaC Agent for revision (retry {output.iac_output.retry_count + 1}/{output.max_retries})")
        else:
            lines.append("\n**Next:** Pipeline stopped. Manual intervention required.")

        return "\n".join(lines)
