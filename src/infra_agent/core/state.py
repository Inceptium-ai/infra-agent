"""LangGraph state definitions for the Infrastructure Agent."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """Types of specialized agents.

    The 4-agent pipeline architecture:
    - CHAT: Orchestrator that routes requests and manages pipeline flow
    - PLANNING: Analyzes requests, generates requirements and acceptance criteria
    - IAC: Implements infrastructure changes based on planning output
    - REVIEW: Validates IaC changes against compliance and security rules
    - DEPLOY_VALIDATE: Executes deployments and validates against acceptance criteria

    Additional agents for direct queries:
    - K8S: Direct Kubernetes queries (not part of change pipeline)
    - COST: Standalone cost queries (not part of change pipeline)
    - INVESTIGATION: Diagnoses issues, troubleshoots problems
    - AUDIT: Compliance, security, cost, and drift audits
    """

    CHAT = "chat"
    PLANNING = "planning"
    IAC = "iac"
    REVIEW = "review"
    DEPLOY_VALIDATE = "deploy_validate"
    K8S = "k8s"
    COST = "cost"
    INVESTIGATION = "investigation"
    AUDIT = "audit"
    # Legacy types (kept for backward compatibility)
    DEPLOYMENT = "deployment"
    VERIFICATION = "verification"
    SECURITY = "security"


class OperationType(str, Enum):
    """Types of operations."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    VALIDATE = "validate"
    QUERY = "query"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"


class Environment(str, Enum):
    """Deployment environments."""

    DEV = "DEV"
    TST = "TST"
    PRD = "PRD"


class ValidationResult(BaseModel):
    """Result of a validation check."""

    passed: bool
    control_id: Optional[str] = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SecurityGate(BaseModel):
    """Security gate status."""

    gate_name: str
    passed: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class AuditLogEntry(BaseModel):
    """Audit log entry for compliance."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent: AgentType
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    environment: Environment
    operator_id: Optional[str] = None
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)


class DriftResult(BaseModel):
    """CloudFormation drift detection result."""

    stack_name: str
    status: Literal["IN_SYNC", "DRIFTED", "UNKNOWN"]
    drifted_resources: list[dict[str, Any]] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class InfraAgentState(BaseModel):
    """
    Central state for the Infrastructure Agent LangGraph.

    This state is shared across all agents and tracks:
    - Conversation messages
    - Current operation context
    - Infrastructure state
    - Security and compliance status
    - Audit trail
    """

    # Conversation state
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)

    # Current operation context
    current_agent: AgentType = Field(default=AgentType.CHAT)
    operation_type: Optional[OperationType] = None
    pending_action: Optional[str] = None

    # Environment context
    environment: Environment = Field(default=Environment.DEV)

    # CloudFormation state
    cloudformation_templates: dict[str, Any] = Field(default_factory=dict)
    pending_change_sets: list[dict[str, Any]] = Field(default_factory=list)
    validation_results: list[ValidationResult] = Field(default_factory=list)

    # Kubernetes state
    eks_cluster_name: Optional[str] = None
    eks_cluster_status: dict[str, Any] = Field(default_factory=dict)
    helm_releases: list[dict[str, Any]] = Field(default_factory=list)
    pod_status: dict[str, Any] = Field(default_factory=dict)

    # Security state
    nist_compliance_status: dict[str, ValidationResult] = Field(default_factory=dict)
    trivy_scan_results: dict[str, Any] = Field(default_factory=dict)
    security_gates: list[SecurityGate] = Field(default_factory=list)
    security_gates_passed: bool = False

    # Cost state
    kubecost_metrics: dict[str, Any] = Field(default_factory=dict)
    reap_candidates: list[dict[str, Any]] = Field(default_factory=list)

    # Deployment state
    pipeline_status: dict[str, Any] = Field(default_factory=dict)
    deployment_stage: Optional[str] = None
    rollback_available: bool = False
    active_deployment: Optional[dict[str, Any]] = None

    # Verification state
    drift_results: list[DriftResult] = Field(default_factory=list)
    test_coverage: dict[str, Any] = Field(default_factory=dict)
    verification_passed: bool = False

    # Audit trail (AU-2 compliance)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)

    # Authentication state (AC-2, IA-5 compliance)
    operator_id: Optional[str] = None
    operator_authenticated: bool = False
    mfa_verified: bool = False
    assumed_role_arn: Optional[str] = None
    session_expiry: Optional[datetime] = None

    # Error handling
    last_error: Optional[str] = None

    # Pipeline state (4-agent architecture)
    current_pipeline_stage: Optional[str] = Field(
        default=None,
        description="Current stage: planning, iac, review, deploy_validate, completed, failed",
    )
    active_request_id: Optional[str] = Field(
        default=None, description="ID of the current pipeline request"
    )
    pipeline_retry_count: int = Field(
        default=0, description="Number of retries in current pipeline execution"
    )
    max_pipeline_retries: int = Field(default=3, description="Maximum pipeline retries")

    # Serialized pipeline outputs (stored as JSON strings to avoid circular imports)
    # These are populated during pipeline execution and used for context passing
    planning_output_json: Optional[str] = Field(
        default=None, description="Serialized PlanningOutput from Planning Agent"
    )
    iac_output_json: Optional[str] = Field(
        default=None, description="Serialized IaCOutput from IaC Agent"
    )
    review_output_json: Optional[str] = Field(
        default=None, description="Serialized ReviewOutput from Review Agent"
    )
    deployment_output_json: Optional[str] = Field(
        default=None, description="Serialized DeploymentOutput from Deploy Agent"
    )
    investigation_output_json: Optional[str] = Field(
        default=None, description="Serialized InvestigationOutput from Investigation Agent"
    )
    audit_output_json: Optional[str] = Field(
        default=None, description="Serialized AuditOutput from Audit Agent"
    )

    def add_audit_entry(
        self,
        agent: AgentType,
        action: str,
        success: bool,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Add an entry to the audit log."""
        entry = AuditLogEntry(
            agent=agent,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            environment=self.environment,
            operator_id=self.operator_id,
            success=success,
            details=details or {},
        )
        self.audit_log.append(entry)

    def add_validation_result(self, result: ValidationResult) -> None:
        """Add a validation result."""
        self.validation_results.append(result)
        if result.control_id:
            self.nist_compliance_status[result.control_id] = result

    def check_mfa_required(self) -> bool:
        """Check if MFA is required for current operation."""
        if self.environment == Environment.PRD:
            return True
        if self.operation_type in [OperationType.DELETE, OperationType.DEPLOY]:
            return True
        return False

    def is_session_valid(self) -> bool:
        """Check if the current session is valid."""
        if not self.operator_authenticated:
            return False
        if self.session_expiry and datetime.utcnow() > self.session_expiry:
            return False
        if self.check_mfa_required() and not self.mfa_verified:
            return False
        return True

    def start_pipeline(self, request_id: str) -> None:
        """Initialize a new pipeline execution."""
        self.active_request_id = request_id
        self.current_pipeline_stage = "planning"
        self.pipeline_retry_count = 0
        self.planning_output_json = None
        self.iac_output_json = None
        self.review_output_json = None
        self.deployment_output_json = None
        self.last_error = None

    def advance_pipeline(self, next_stage: str) -> None:
        """Advance to the next pipeline stage."""
        self.current_pipeline_stage = next_stage

    def retry_pipeline(self) -> bool:
        """Attempt to retry the pipeline. Returns True if retry is allowed."""
        if self.pipeline_retry_count < self.max_pipeline_retries:
            self.pipeline_retry_count += 1
            return True
        return False

    def complete_pipeline(self, success: bool) -> None:
        """Mark the pipeline as completed."""
        self.current_pipeline_stage = "completed" if success else "failed"

    def is_pipeline_active(self) -> bool:
        """Check if a pipeline is currently in progress."""
        return self.current_pipeline_stage in ["planning", "iac", "review", "deploy_validate"]

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True
