"""Contract definitions (Pydantic models) for agent pipeline communication.

This module defines the data contracts between agents in the 4-agent pipeline:
- Planning Agent: Analyzes user requests, generates requirements and acceptance criteria
- IaC Agent: Implements infrastructure changes based on planning output
- Review Agent: Validates IaC changes against compliance and security rules
- Deploy & Validate Agent: Executes deployments and validates against acceptance criteria
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Shared Types
# =============================================================================


class Priority(str, Enum):
    """Priority levels for requirements."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeType(str, Enum):
    """Types of infrastructure changes."""

    CLOUDFORMATION = "cloudformation"
    HELM = "helm"
    KUBERNETES = "kubernetes"


class ReviewStatus(str, Enum):
    """Status of the review process."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVISION = "needs_revision"


class DeploymentStatus(str, Enum):
    """Status of deployment execution."""

    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PENDING = "pending"


class FindingSeverity(str, Enum):
    """Severity levels for review findings."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RequirementType(str, Enum):
    """Types of requirements."""

    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non-functional"
    SECURITY = "security"
    COMPLIANCE = "compliance"


# =============================================================================
# Planning Agent Contracts
# =============================================================================


class UserRequest(BaseModel):
    """Input to Planning Agent from Orchestrator.

    This is the initial request from the user, routed by the Chat Agent
    (Orchestrator) to the Planning Agent for analysis.
    """

    request_id: str = Field(description="Unique request identifier")
    user_prompt: str = Field(description="Original user request")
    environment: str = Field(default="DEV", description="Target environment")
    operator_id: str = Field(description="Who made the request")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-001",
                "user_prompt": "Add 3 replicas to SigNoz frontend",
                "environment": "DEV",
                "operator_id": "platform-team",
            }
        }


class Requirement(BaseModel):
    """A single requirement derived from user request."""

    id: str = Field(description="Requirement ID in REQ-001 format")
    description: str = Field(description="Description of the requirement")
    type: RequirementType = Field(description="Type of requirement")
    priority: Priority = Field(default=Priority.MEDIUM)
    nist_controls: list[str] = Field(
        default_factory=list, description="Related NIST 800-53 control IDs"
    )


class AcceptanceCriteria(BaseModel):
    """A testable acceptance criterion for a requirement."""

    id: str = Field(description="Acceptance criteria ID in AC-001 format")
    requirement_id: str = Field(description="Links to REQ-xxx")
    description: str = Field(description="Human-readable description")
    test_command: str = Field(description="Command to validate this criterion")
    expected_result: str = Field(description="What success looks like")


class FileToModify(BaseModel):
    """A file identified for modification."""

    path: str = Field(description="Path to the file relative to project root")
    change_type: ChangeType = Field(description="Type of infrastructure change")
    description: str = Field(description="What change is needed")


class PlanningOutput(BaseModel):
    """Output from Planning Agent.

    This is the primary output of the Planning Agent, containing all the
    information needed for the IaC Agent to implement the changes.
    """

    request_id: str = Field(description="Original request ID")
    summary: str = Field(description="1-2 sentence summary of what will be done")
    resource_types: list[str] = Field(
        default_factory=list,
        description="Types of resources being created/modified: helm, rds, s3, eks, iam, cloudformation, lambda"
    )
    requirements: list[Requirement] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriteria] = Field(default_factory=list)
    files_to_modify: list[FileToModify] = Field(default_factory=list)
    estimated_impact: str = Field(
        default="low", description="Impact level: low, medium, high"
    )
    estimated_monthly_cost: float = Field(
        default=0.0, description="Estimated monthly cost impact in USD"
    )
    cost_breakdown: str = Field(
        default="", description="Breakdown of cost estimate"
    )
    requires_approval: bool = Field(
        default=False, description="True for PRD or destructive changes"
    )
    planning_notes: str = Field(
        default="", description="Additional context for IaC agent"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-001",
                "summary": "Increase SigNoz frontend replicas from 1 to 3 for high availability",
                "requirements": [
                    {
                        "id": "REQ-001",
                        "description": "SigNoz frontend should have 3 replicas",
                        "type": "non-functional",
                        "priority": "medium",
                        "nist_controls": ["CP-10"],
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC-001",
                        "requirement_id": "REQ-001",
                        "description": "Frontend has 3 running replicas",
                        "test_command": "kubectl get deploy signoz-frontend -n signoz -o jsonpath='{.status.readyReplicas}'",
                        "expected_result": "3",
                    }
                ],
                "files_to_modify": [
                    {
                        "path": "infra/helm/values/signoz/values.yaml",
                        "change_type": "helm",
                        "description": "Update frontend.replicas from 1 to 3",
                    }
                ],
                "estimated_impact": "low",
                "requires_approval": False,
            }
        }


# =============================================================================
# Git Configuration
# =============================================================================


class GitPlatform(str, Enum):
    """Supported Git platforms for PR/MR creation."""

    GITHUB = "github"
    GITLAB = "gitlab"


class GitBranchConfig:
    """Branch-to-environment mapping configuration.

    GitFlow-style branching strategy:
    - develop: Auto-deploys to DEV
    - release/*: Auto-deploys to TST (test)
    - main: Auto-deploys to PRD (production, requires approval)
    """

    # Base branches for each environment
    ENVIRONMENT_BRANCHES = {
        "dev": "develop",
        "tst": "release",  # release/* branches
        "prd": "main",
    }

    # Feature branch prefix
    FEATURE_BRANCH_PREFIX = "feat"

    # PR target branches by environment
    PR_TARGET_BRANCHES = {
        "dev": "develop",
        "tst": "develop",  # Release branches are cut from develop
        "prd": "main",
    }

    @classmethod
    def get_feature_branch_name(cls, request_id: str, environment: str) -> str:
        """Generate feature branch name for a request.

        Args:
            request_id: Unique request ID
            environment: Target environment (dev, tst, prd)

        Returns:
            Branch name like 'feat/dev/req-001'
        """
        return f"{cls.FEATURE_BRANCH_PREFIX}/{environment}/{request_id}"

    @classmethod
    def get_release_branch_name(cls, version: str) -> str:
        """Generate release branch name for TST deployment.

        Args:
            version: Semantic version (e.g., '1.2.0')

        Returns:
            Branch name like 'release/1.2.0'
        """
        return f"release/{version}"

    @classmethod
    def get_pr_target_branch(cls, environment: str) -> str:
        """Get the target branch for PR based on environment.

        Args:
            environment: Target environment (dev, tst, prd)

        Returns:
            Target branch name
        """
        return cls.PR_TARGET_BRANCHES.get(environment, "develop")


# =============================================================================
# IaC Agent Contracts
# =============================================================================


class CodeChange(BaseModel):
    """A single code change made by the IaC Agent."""

    file_path: str = Field(description="Path to the modified file")
    change_type: ChangeType = Field(description="Type of infrastructure change")
    diff_summary: str = Field(description="Summary of what changed")
    lines_added: int = Field(default=0)
    lines_removed: int = Field(default=0)


class GitCommit(BaseModel):
    """Git commit information for the IaC changes."""

    commit_sha: str = Field(description="Full commit SHA")
    branch: str = Field(description="Branch name")
    message: str = Field(description="Commit message")
    files_changed: list[str] = Field(default_factory=list)
    pushed_to_remote: bool = Field(
        default=False, description="Whether commit was pushed to origin"
    )


class PullRequest(BaseModel):
    """Pull/Merge request information created by IaC Agent.

    Supports both GitHub (Pull Request) and GitLab (Merge Request).
    """

    number: int = Field(description="PR/MR number")
    url: str = Field(description="URL to the pull/merge request")
    title: str = Field(description="PR/MR title")
    source_branch: str = Field(description="Source/head branch")
    target_branch: str = Field(description="Target/base branch")
    status: str = Field(default="open", description="Status: open, merged, closed")
    platform: GitPlatform = Field(
        default=GitPlatform.GITHUB, description="Git platform (github or gitlab)"
    )

    @property
    def display_name(self) -> str:
        """Return 'PR' for GitHub, 'MR' for GitLab."""
        return "MR" if self.platform == GitPlatform.GITLAB else "PR"


class IaCOutput(BaseModel):
    """Output from IaC Agent.

    This contains the code changes made and is passed to the Review Agent
    for validation.
    """

    request_id: str = Field(description="Original request ID")
    planning_output: PlanningOutput = Field(
        description="Pass through planning output for downstream agents"
    )
    code_changes: list[CodeChange] = Field(default_factory=list)
    git_commit: Optional[GitCommit] = Field(
        default=None, description="Git commit info if changes were committed"
    )
    pull_request: Optional[PullRequest] = Field(
        default=None, description="PR info if a pull request was created"
    )
    self_lint_passed: bool = Field(
        default=False, description="Did cfn-lint/kube-linter pass on self-check?"
    )
    self_lint_warnings: list[str] = Field(default_factory=list)
    retry_count: int = Field(
        default=0, description="How many times we've retried from review"
    )
    notes: str = Field(default="", description="Notes for review agent")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-001",
                "code_changes": [
                    {
                        "file_path": "infra/helm/values/signoz/values.yaml",
                        "change_type": "helm",
                        "diff_summary": "Changed frontend.replicas: 1 -> 3",
                        "lines_added": 1,
                        "lines_removed": 1,
                    }
                ],
                "self_lint_passed": True,
                "retry_count": 0,
            }
        }


# =============================================================================
# Review Agent Contracts
# =============================================================================


class Finding(BaseModel):
    """A single review finding from validation tools."""

    id: str = Field(description="Finding ID in FIND-001 format")
    severity: FindingSeverity = Field(description="Severity level")
    source: str = Field(
        description="Source of finding: cfn-guard, cfn-lint, kube-linter, security, cost"
    )
    file_path: str = Field(description="File where the issue was found")
    line_number: Optional[int] = Field(default=None)
    rule_id: str = Field(description="Rule ID, e.g., W3010, NIST-AC-6")
    message: str = Field(description="Description of the issue")
    remediation: str = Field(description="How to fix this issue")


class CostEstimate(BaseModel):
    """Estimated cost impact of the change."""

    monthly_delta: float = Field(
        description="Estimated monthly cost change in USD (can be negative)"
    )
    affected_resources: list[str] = Field(default_factory=list)
    notes: str = Field(default="")


class ReviewOutput(BaseModel):
    """Output from Review Agent.

    This contains the validation results and determines whether the pipeline
    should proceed to deployment or return to IaC for revision.
    """

    request_id: str = Field(description="Original request ID")
    iac_output: IaCOutput = Field(
        description="Pass through IaC output for downstream agents"
    )
    status: ReviewStatus = Field(description="Overall review status")
    findings: list[Finding] = Field(default_factory=list)

    # Gate results
    cfn_guard_passed: bool = Field(default=True)
    cfn_lint_passed: bool = Field(default=True)
    kube_linter_passed: bool = Field(default=True)
    security_scan_passed: bool = Field(default=True)

    # Cost analysis
    cost_estimate: Optional[CostEstimate] = Field(default=None)

    # Summary
    blocking_findings: int = Field(
        default=0, description="Count of error-level findings"
    )
    warning_findings: int = Field(
        default=0, description="Count of warning-level findings"
    )
    review_notes: str = Field(
        default="", description="Notes for IaC agent if revision needed"
    )

    # Retry loop control
    max_retries: int = Field(default=3)
    should_retry: bool = Field(
        default=False, description="True if blocking findings and retries left"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-001",
                "status": "passed",
                "cfn_guard_passed": True,
                "cfn_lint_passed": True,
                "kube_linter_passed": True,
                "security_scan_passed": True,
                "blocking_findings": 0,
                "warning_findings": 0,
                "should_retry": False,
            }
        }


# =============================================================================
# Deploy & Validate Agent Contracts
# =============================================================================


class DeploymentAction(BaseModel):
    """A single deployment action taken."""

    action_type: str = Field(
        description="Type: cloudformation_deploy, helm_upgrade, kubectl_apply"
    )
    resource_name: str = Field(description="Name of the resource being deployed")
    status: str = Field(description="Status: success, failed, skipped")
    duration_seconds: float = Field(default=0.0)
    output: str = Field(default="", description="Command output or error message")


class ValidationResult(BaseModel):
    """Result of validating one acceptance criterion."""

    acceptance_criteria_id: str = Field(description="Links to AC-xxx")
    passed: bool = Field(description="Whether the criterion was met")
    actual_result: str = Field(description="What the test actually returned")
    expected_result: str = Field(description="What was expected")
    test_command: str = Field(description="Command that was executed")
    error_message: Optional[str] = Field(default=None)


class RollbackInfo(BaseModel):
    """Rollback information if deployment failed."""

    rollback_performed: bool = Field(default=False)
    rollback_successful: bool = Field(default=False)
    rollback_details: str = Field(default="")


class DeploymentOutput(BaseModel):
    """Output from Deploy & Validate Agent.

    This is the final output of the pipeline, containing deployment status
    and validation results.
    """

    request_id: str = Field(description="Original request ID")
    status: DeploymentStatus = Field(description="Overall deployment status")

    # Deployment actions
    deployment_actions: list[DeploymentAction] = Field(default_factory=list)

    # Validation against acceptance criteria
    validation_results: list[ValidationResult] = Field(default_factory=list)
    all_validations_passed: bool = Field(default=False)

    # Rollback info (if applicable)
    rollback_info: Optional[RollbackInfo] = Field(default=None)

    # Cost actuals (post-deployment)
    actual_cost_impact: Optional[CostEstimate] = Field(default=None)

    # Summary
    summary: str = Field(default="", description="Human-readable summary")
    deployment_duration_seconds: float = Field(default=0.0)

    # Retry loop control
    should_retry_iac: bool = Field(
        default=False, description="True if validation failed, needs code fix"
    )
    retry_guidance: str = Field(
        default="", description="What IaC agent should fix on retry"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-001",
                "status": "success",
                "deployment_actions": [
                    {
                        "action_type": "helm_upgrade",
                        "resource_name": "signoz",
                        "status": "success",
                        "duration_seconds": 45.2,
                    }
                ],
                "validation_results": [
                    {
                        "acceptance_criteria_id": "AC-001",
                        "passed": True,
                        "actual_result": "3",
                        "expected_result": "3",
                        "test_command": "kubectl get deploy signoz-frontend -n signoz -o jsonpath='{.status.readyReplicas}'",
                    }
                ],
                "all_validations_passed": True,
                "summary": "Successfully increased SigNoz frontend replicas to 3",
                "deployment_duration_seconds": 45.2,
            }
        }


# =============================================================================
# Pipeline State
# =============================================================================


# =============================================================================
# Investigation Agent Contracts
# =============================================================================


class InvestigationScope(str, Enum):
    """Scope of investigation."""

    POD = "pod"
    NODE = "node"
    NAMESPACE = "namespace"
    SERVICE = "service"
    CLUSTER = "cluster"
    AWS = "aws"


class InvestigationSeverity(str, Enum):
    """Severity levels for investigation findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class InvestigationRequest(BaseModel):
    """Input to Investigation Agent from Orchestrator."""

    request_id: str = Field(description="Unique request identifier")
    user_prompt: str = Field(description="Original user request")
    environment: str = Field(default="DEV", description="Target environment")
    operator_id: str = Field(description="Who made the request")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    scope: Optional[InvestigationScope] = Field(
        default=None, description="Scope of investigation if known"
    )
    target_resource: Optional[str] = Field(
        default=None, description="Specific resource to investigate"
    )
    namespace: Optional[str] = Field(
        default=None, description="Target namespace if applicable"
    )


class InvestigationFinding(BaseModel):
    """A single finding from an investigation."""

    id: str = Field(description="Finding ID in FIND-001 format")
    severity: InvestigationSeverity = Field(description="Severity of finding")
    category: str = Field(
        description="Category: resource_health, configuration, connectivity, capacity"
    )
    title: str = Field(description="Brief title of the finding")
    description: str = Field(description="Detailed description")
    evidence: list[str] = Field(
        default_factory=list, description="Evidence collected (command outputs, metrics)"
    )
    affected_resources: list[str] = Field(
        default_factory=list, description="List of affected resources"
    )
    recommendation: str = Field(description="Recommended action")


class InvestigationOutput(BaseModel):
    """Output from Investigation Agent."""

    request_id: str = Field(description="Original request ID")
    status: str = Field(
        default="completed", description="Status: completed, in_progress, failed"
    )
    summary: str = Field(description="Brief summary of investigation results")
    findings: list[InvestigationFinding] = Field(default_factory=list)
    root_cause: Optional[str] = Field(
        default=None, description="Identified root cause if determined"
    )
    resources_examined: list[str] = Field(
        default_factory=list, description="Resources that were examined"
    )
    commands_executed: list[str] = Field(
        default_factory=list, description="Commands/queries executed during investigation"
    )
    immediate_actions: list[str] = Field(
        default_factory=list, description="Immediate remediation actions"
    )
    follow_up_actions: list[str] = Field(
        default_factory=list, description="Long-term follow-up actions"
    )
    requires_iac_change: bool = Field(
        default=False, description="True if issue requires IaC modification"
    )
    iac_change_description: Optional[str] = Field(
        default=None, description="Description of IaC change needed"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "inv-001",
                "status": "completed",
                "summary": "SigNoz pods restarting due to OOMKilled",
                "findings": [
                    {
                        "id": "FIND-001",
                        "severity": "high",
                        "category": "capacity",
                        "title": "ClickHouse pods hitting memory limits",
                        "description": "ClickHouse pods are being OOMKilled due to insufficient memory limits",
                        "evidence": ["OOMKilled events in past 1h", "Memory utilization at 98%"],
                        "affected_resources": ["signoz-0", "signoz-1"],
                        "recommendation": "Increase memory limit to 1Gi in Helm values",
                    }
                ],
                "root_cause": "Memory limit 256Mi insufficient for ClickHouse query load",
                "requires_iac_change": True,
                "iac_change_description": "Update infra/helm/values/signoz/values.yaml memory.limits",
            }
        }


# =============================================================================
# Audit Agent Contracts
# =============================================================================


class AuditType(str, Enum):
    """Types of audits."""

    COMPLIANCE = "compliance"
    SECURITY = "security"
    COST = "cost"
    DRIFT = "drift"
    FULL = "full"


class AuditRequest(BaseModel):
    """Input to Audit Agent from Orchestrator."""

    request_id: str = Field(description="Unique request identifier")
    user_prompt: str = Field(description="Original user request")
    audit_type: AuditType = Field(default=AuditType.FULL, description="Type of audit")
    environment: str = Field(default="DEV", description="Target environment")
    operator_id: str = Field(description="Who made the request")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    target_namespace: Optional[str] = Field(
        default=None, description="Specific namespace to audit"
    )
    target_controls: list[str] = Field(
        default_factory=list, description="Specific NIST controls to check"
    )


class AuditControl(BaseModel):
    """Result of a single NIST control check."""

    control_id: str = Field(description="NIST control ID (e.g., SC-8)")
    control_name: str = Field(description="Control name")
    status: str = Field(description="Status: passed, failed, partial, not_applicable")
    description: str = Field(description="What was checked")
    evidence: list[str] = Field(
        default_factory=list, description="Evidence collected"
    )
    remediation: Optional[str] = Field(
        default=None, description="Remediation guidance if failed"
    )


class SecurityFinding(BaseModel):
    """A security finding from audit."""

    id: str = Field(description="Finding ID in SEC-001 format")
    severity: str = Field(description="Severity: critical, high, medium, low")
    category: str = Field(
        description="Category: vulnerability, misconfiguration, exposure, secret"
    )
    title: str = Field(description="Brief title")
    description: str = Field(description="Detailed description")
    affected_resources: list[str] = Field(default_factory=list)
    cve_ids: list[str] = Field(
        default_factory=list, description="CVE IDs if applicable"
    )
    remediation: str = Field(description="How to fix")


class CostFinding(BaseModel):
    """A cost optimization finding from audit."""

    id: str = Field(description="Finding ID in COST-001 format")
    category: str = Field(
        description="Category: idle, oversized, unattached, reserved"
    )
    title: str = Field(description="Brief title")
    description: str = Field(description="Detailed description")
    affected_resources: list[str] = Field(default_factory=list)
    current_monthly_cost: float = Field(description="Current monthly cost in USD")
    potential_savings: float = Field(description="Potential monthly savings in USD")
    recommendation: str = Field(description="Recommended action")


class DriftFinding(BaseModel):
    """A drift detection finding from audit."""

    id: str = Field(description="Finding ID in DRIFT-001 format")
    resource_type: str = Field(
        description="Type: cloudformation, helm, kubernetes"
    )
    resource_name: str = Field(description="Name of the drifted resource")
    expected_value: str = Field(description="Expected value from IaC")
    actual_value: str = Field(description="Actual value in deployed state")
    source_file: Optional[str] = Field(
        default=None, description="IaC source file"
    )
    remediation: str = Field(description="How to remediate drift")


class AuditOutput(BaseModel):
    """Output from Audit Agent."""

    request_id: str = Field(description="Original request ID")
    audit_type: AuditType = Field(description="Type of audit performed")
    status: str = Field(
        default="completed", description="Status: completed, in_progress, failed"
    )
    summary: str = Field(description="Brief summary of audit results")
    overall_score: Optional[float] = Field(
        default=None, description="Overall compliance/health score 0-100"
    )

    # Compliance audit results
    compliance_controls: list[AuditControl] = Field(default_factory=list)
    controls_passed: int = Field(default=0)
    controls_failed: int = Field(default=0)
    controls_partial: int = Field(default=0)

    # Security audit results
    security_findings: list[SecurityFinding] = Field(default_factory=list)
    critical_security_count: int = Field(default=0)
    high_security_count: int = Field(default=0)

    # Cost audit results
    cost_findings: list[CostFinding] = Field(default_factory=list)
    total_monthly_cost: float = Field(default=0.0)
    potential_savings: float = Field(default=0.0)

    # Drift audit results
    drift_findings: list[DriftFinding] = Field(default_factory=list)
    resources_drifted: int = Field(default=0)
    resources_in_sync: int = Field(default=0)

    # Recommendations
    top_recommendations: list[str] = Field(
        default_factory=list, description="Top recommendations from audit"
    )
    requires_iac_change: bool = Field(
        default=False, description="True if issues require IaC modification"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "audit-001",
                "audit_type": "compliance",
                "status": "completed",
                "summary": "NIST 800-53 compliance audit completed with 85% score",
                "overall_score": 85.0,
                "controls_passed": 12,
                "controls_failed": 1,
                "controls_partial": 2,
                "critical_security_count": 0,
                "high_security_count": 3,
                "top_recommendations": [
                    "Fix wildcard IAM policy in infra-agent-dev-deploy-role",
                    "Patch 3 HIGH vulnerabilities in container images",
                ],
            }
        }


# =============================================================================
# Pipeline State
# =============================================================================


class PipelineStage(str, Enum):
    """Current stage in the agent pipeline."""

    PLANNING = "planning"
    IAC = "iac"
    REVIEW = "review"
    DEPLOY_VALIDATE = "deploy_validate"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineState(BaseModel):
    """Tracks the state of a pipeline execution.

    This is used by the Orchestrator (Chat Agent) to manage the flow
    between agents and handle retries.
    """

    request_id: str = Field(description="Unique request identifier")
    current_stage: PipelineStage = Field(default=PipelineStage.PLANNING)

    # Outputs from each stage
    user_request: Optional[UserRequest] = Field(default=None)
    planning_output: Optional[PlanningOutput] = Field(default=None)
    iac_output: Optional[IaCOutput] = Field(default=None)
    review_output: Optional[ReviewOutput] = Field(default=None)
    deployment_output: Optional[DeploymentOutput] = Field(default=None)

    # Retry tracking
    pipeline_retry_count: int = Field(default=0)
    max_pipeline_retries: int = Field(default=3)

    # Error tracking
    last_error: Optional[str] = Field(default=None)

    def can_retry(self) -> bool:
        """Check if pipeline can retry from current stage."""
        return self.pipeline_retry_count < self.max_pipeline_retries

    def increment_retry(self) -> None:
        """Increment retry count."""
        self.pipeline_retry_count += 1
