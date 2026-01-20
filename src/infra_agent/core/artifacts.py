"""Artifact persistence for pipeline traceability.

This module handles persisting pipeline artifacts to the git repo for:
- Audit trail and compliance (NIST AU-3, AU-12)
- Traceability between requirements and implementation
- PR descriptions and documentation
- Future reference and debugging
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from infra_agent.core.contracts import (
    DeploymentOutput,
    IaCOutput,
    PlanningOutput,
    ReviewOutput,
)


class ArtifactManager:
    """Manages pipeline artifact persistence to git repo."""

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize the artifact manager.

        Args:
            project_root: Root of the git repo. Defaults to infra-agent root.
        """
        if project_root is None:
            project_root = Path(__file__).parent.parent.parent.parent
        self._project_root = project_root
        self._artifacts_dir = project_root / ".infra-agent" / "requests"

    def get_request_dir(self, request_id: str) -> Path:
        """Get the directory for a specific request's artifacts."""
        return self._artifacts_dir / request_id

    def ensure_request_dir(self, request_id: str) -> Path:
        """Create and return the request artifacts directory."""
        request_dir = self.get_request_dir(request_id)
        request_dir.mkdir(parents=True, exist_ok=True)
        return request_dir

    def save_planning_output(self, output: PlanningOutput) -> Path:
        """Save planning output as requirements.yaml.

        Args:
            output: PlanningOutput from Planning Agent

        Returns:
            Path to the saved file
        """
        request_dir = self.ensure_request_dir(output.request_id)
        file_path = request_dir / "requirements.yaml"

        data = {
            "# Request": output.request_id,
            "# Generated": datetime.utcnow().isoformat() + "Z",
            "request_id": output.request_id,
            "summary": output.summary,
            "resource_types": output.resource_types,
            "estimated_impact": output.estimated_impact,
            "estimated_monthly_cost": output.estimated_monthly_cost,
            "cost_breakdown": output.cost_breakdown,
            "requires_approval": output.requires_approval,
            "requirements": [
                {
                    "id": req.id,
                    "description": req.description,
                    "type": req.type.value if hasattr(req.type, 'value') else req.type,
                    "priority": req.priority.value if hasattr(req.priority, 'value') else req.priority,
                    "nist_controls": req.nist_controls,
                }
                for req in output.requirements
            ],
            "acceptance_criteria": [
                {
                    "id": ac.id,
                    "requirement_id": ac.requirement_id,
                    "description": ac.description,
                    "test_command": ac.test_command,
                    "expected_result": ac.expected_result,
                }
                for ac in output.acceptance_criteria
            ],
            "files_to_modify": [
                {
                    "path": f.path,
                    "change_type": f.change_type.value if hasattr(f.change_type, 'value') else f.change_type,
                    "description": f.description,
                }
                for f in output.files_to_modify
            ],
            "planning_notes": output.planning_notes,
        }

        self._write_yaml(file_path, data, header=f"# Requirements for request: {output.request_id}")
        return file_path

    def save_iac_output(self, output: IaCOutput) -> Path:
        """Save IaC output as changes.yaml.

        Args:
            output: IaCOutput from IaC Agent

        Returns:
            Path to the saved file
        """
        request_dir = self.ensure_request_dir(output.request_id)
        file_path = request_dir / "changes.yaml"

        data = {
            "request_id": output.request_id,
            "generated": datetime.utcnow().isoformat() + "Z",
            "self_lint_passed": output.self_lint_passed,
            "self_lint_warnings": output.self_lint_warnings,
            "retry_count": output.retry_count,
            "code_changes": [
                {
                    "file_path": change.file_path,
                    "change_type": change.change_type.value if hasattr(change.change_type, 'value') else change.change_type,
                    "diff_summary": change.diff_summary,
                    "lines_added": change.lines_added,
                    "lines_removed": change.lines_removed,
                }
                for change in output.code_changes
            ],
            "git_commit": None,
            "pull_request": None,
            "notes": output.notes,
        }

        # Add git commit info if present
        if output.git_commit:
            data["git_commit"] = {
                "commit_sha": output.git_commit.commit_sha,
                "branch": output.git_commit.branch,
                "message": output.git_commit.message,
                "files_changed": output.git_commit.files_changed,
                "pushed_to_remote": output.git_commit.pushed_to_remote,
            }

        # Add PR info if present
        if output.pull_request:
            data["pull_request"] = {
                "number": output.pull_request.number,
                "url": output.pull_request.url,
                "title": output.pull_request.title,
                "source_branch": output.pull_request.source_branch,
                "target_branch": output.pull_request.target_branch,
                "status": output.pull_request.status,
                "platform": output.pull_request.platform.value,
            }

        self._write_yaml(file_path, data, header=f"# IaC Changes for request: {output.request_id}")
        return file_path

    def save_review_output(self, output: ReviewOutput) -> Path:
        """Save review output as review.yaml.

        Args:
            output: ReviewOutput from Review Agent

        Returns:
            Path to the saved file
        """
        request_dir = self.ensure_request_dir(output.request_id)
        file_path = request_dir / "review.yaml"

        data = {
            "request_id": output.request_id,
            "generated": datetime.utcnow().isoformat() + "Z",
            "status": output.status.value,
            "gates": {
                "cfn_guard_passed": output.cfn_guard_passed,
                "cfn_lint_passed": output.cfn_lint_passed,
                "kube_linter_passed": output.kube_linter_passed,
                "security_scan_passed": output.security_scan_passed,
            },
            "summary": {
                "blocking_findings": output.blocking_findings,
                "warning_findings": output.warning_findings,
                "should_retry": output.should_retry,
                "max_retries": output.max_retries,
            },
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity.value if hasattr(f.severity, 'value') else f.severity,
                    "source": f.source,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "rule_id": f.rule_id,
                    "message": f.message,
                    "remediation": f.remediation,
                }
                for f in output.findings
            ],
            "cost_estimate": None,
            "review_notes": output.review_notes,
        }

        # Add cost estimate if present
        if output.cost_estimate:
            data["cost_estimate"] = {
                "monthly_delta": output.cost_estimate.monthly_delta,
                "affected_resources": output.cost_estimate.affected_resources,
                "notes": output.cost_estimate.notes,
            }

        self._write_yaml(file_path, data, header=f"# Review Results for request: {output.request_id}")
        return file_path

    def save_deployment_output(self, output: DeploymentOutput) -> Path:
        """Save deployment output as validation.yaml.

        Args:
            output: DeploymentOutput from Deploy & Validate Agent

        Returns:
            Path to the saved file
        """
        request_dir = self.ensure_request_dir(output.request_id)
        file_path = request_dir / "validation.yaml"

        data = {
            "request_id": output.request_id,
            "generated": datetime.utcnow().isoformat() + "Z",
            "status": output.status.value,
            "deployment_duration_seconds": output.deployment_duration_seconds,
            "all_validations_passed": output.all_validations_passed,
            "deployment_actions": [
                {
                    "action_type": action.action_type,
                    "resource_name": action.resource_name,
                    "status": action.status,
                    "duration_seconds": action.duration_seconds,
                    "output": action.output[:500] if action.output else "",
                }
                for action in output.deployment_actions
            ],
            "validation_results": [
                {
                    "acceptance_criteria_id": v.acceptance_criteria_id,
                    "passed": v.passed,
                    "actual_result": v.actual_result,
                    "expected_result": v.expected_result,
                    "test_command": v.test_command,
                    "error_message": v.error_message,
                }
                for v in output.validation_results
            ],
            "rollback_info": None,
            "summary": output.summary,
            "should_retry_iac": output.should_retry_iac,
            "retry_guidance": output.retry_guidance,
        }

        # Add rollback info if present
        if output.rollback_info:
            data["rollback_info"] = {
                "rollback_performed": output.rollback_info.rollback_performed,
                "rollback_successful": output.rollback_info.rollback_successful,
                "rollback_details": output.rollback_info.rollback_details,
            }

        self._write_yaml(file_path, data, header=f"# Validation Results for request: {output.request_id}")
        return file_path

    def generate_summary(self, request_id: str) -> Path:
        """Generate summary.md from all artifacts.

        Args:
            request_id: The request ID

        Returns:
            Path to the generated summary.md
        """
        request_dir = self.get_request_dir(request_id)
        summary_path = request_dir / "summary.md"

        lines = [
            f"# Infrastructure Change Request: {request_id}",
            f"",
            f"**Generated:** {datetime.utcnow().isoformat()}Z",
            "",
        ]

        # Load and summarize requirements
        req_file = request_dir / "requirements.yaml"
        if req_file.exists():
            req_data = self._read_yaml(req_file)
            lines.extend([
                "## Summary",
                "",
                req_data.get("summary", "No summary available"),
                "",
                f"**Impact:** {req_data.get('estimated_impact', 'unknown')}",
                f"**Requires Approval:** {req_data.get('requires_approval', False)}",
                "",
                "## Requirements",
                "",
            ])
            for req in req_data.get("requirements", []):
                nist = ", ".join(req.get("nist_controls", []))
                lines.append(f"- **[{req['id']}]** {req['description']}")
                if nist:
                    lines.append(f"  - NIST Controls: {nist}")
            lines.append("")

            lines.append("## Acceptance Criteria")
            lines.append("")
            for ac in req_data.get("acceptance_criteria", []):
                lines.append(f"- **[{ac['id']}]** {ac['description']}")
                lines.append(f"  - Test: `{ac['test_command']}`")
                lines.append(f"  - Expected: {ac['expected_result']}")
            lines.append("")

            lines.append("## Files Modified")
            lines.append("")
            for f in req_data.get("files_to_modify", []):
                lines.append(f"- `{f['path']}` ({f['change_type']})")
                lines.append(f"  - {f['description']}")
            lines.append("")

        # Load and summarize changes
        changes_file = request_dir / "changes.yaml"
        if changes_file.exists():
            changes_data = self._read_yaml(changes_file)
            lines.extend([
                "## Code Changes",
                "",
                f"**Self-lint passed:** {changes_data.get('self_lint_passed', 'N/A')}",
                "",
            ])
            for change in changes_data.get("code_changes", []):
                lines.append(f"- `{change['file_path']}`")
                lines.append(f"  - +{change['lines_added']} / -{change['lines_removed']} lines")
            lines.append("")

            if changes_data.get("git_commit"):
                gc = changes_data["git_commit"]
                lines.append(f"**Git Commit:** `{gc['commit_sha'][:8]}` on branch `{gc['branch']}`")
                lines.append("")

            if changes_data.get("pull_request"):
                pr = changes_data["pull_request"]
                lines.append(f"**Pull Request:** [{pr['title']}]({pr['url']})")
                lines.append("")

        # Load and summarize review
        review_file = request_dir / "review.yaml"
        if review_file.exists():
            review_data = self._read_yaml(review_file)
            status = review_data.get("status", "unknown")
            status_icon = "✅" if status == "passed" else "❌" if status == "failed" else "⚠️"

            lines.extend([
                "## Review Results",
                "",
                f"**Status:** {status_icon} {status.upper()}",
                "",
                "| Gate | Result |",
                "|------|--------|",
            ])
            gates = review_data.get("gates", {})
            for gate, passed in gates.items():
                icon = "✅" if passed else "❌"
                lines.append(f"| {gate.replace('_', ' ').title()} | {icon} |")
            lines.append("")

            summary = review_data.get("summary", {})
            if summary.get("blocking_findings", 0) > 0:
                lines.append(f"**Blocking Issues:** {summary['blocking_findings']}")
                lines.append("")
                for finding in review_data.get("findings", []):
                    if finding.get("severity") == "error":
                        lines.append(f"- [{finding['rule_id']}] {finding['message']}")
                        lines.append(f"  - File: `{finding['file_path']}`")
                        lines.append(f"  - Fix: {finding['remediation']}")
                lines.append("")

            if review_data.get("cost_estimate"):
                ce = review_data["cost_estimate"]
                lines.append(f"**Estimated Cost Impact:** ${ce['monthly_delta']:+.2f}/month")
                lines.append("")

        # Load and summarize validation
        validation_file = request_dir / "validation.yaml"
        if validation_file.exists():
            val_data = self._read_yaml(validation_file)
            status = val_data.get("status", "unknown")
            status_icon = "✅" if status == "success" else "❌"

            lines.extend([
                "## Deployment & Validation",
                "",
                f"**Status:** {status_icon} {status.upper()}",
                f"**Duration:** {val_data.get('deployment_duration_seconds', 0):.1f}s",
                f"**All Validations Passed:** {val_data.get('all_validations_passed', False)}",
                "",
            ])

            if val_data.get("validation_results"):
                lines.append("### Acceptance Criteria Results")
                lines.append("")
                lines.append("| Criteria | Status | Result |")
                lines.append("|----------|--------|--------|")
                for v in val_data["validation_results"]:
                    icon = "✅" if v["passed"] else "❌"
                    lines.append(f"| {v['acceptance_criteria_id']} | {icon} | {v['actual_result'][:50]} |")
                lines.append("")

        # Footer
        lines.extend([
            "---",
            "",
            "*Generated by Infra-Agent Pipeline*",
        ])

        summary_path.write_text("\n".join(lines))
        return summary_path

    def _write_yaml(self, path: Path, data: dict[str, Any], header: str = "") -> None:
        """Write data to YAML file with optional header comment."""
        content = ""
        if header:
            content = header + "\n\n"

        # Custom YAML dump settings for readability
        yaml_content = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        content += yaml_content
        path.write_text(content)

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        """Read YAML file and return data."""
        content = path.read_text()
        return yaml.safe_load(content) or {}


# Singleton instance
_artifact_manager: Optional[ArtifactManager] = None


def get_artifact_manager() -> ArtifactManager:
    """Get the singleton artifact manager instance."""
    global _artifact_manager
    if _artifact_manager is None:
        _artifact_manager = ArtifactManager()
    return _artifact_manager
