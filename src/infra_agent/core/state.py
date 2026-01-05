"""LangGraph state definitions for the Infrastructure Agent."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """Types of specialized agents."""

    CHAT = "chat"
    IAC = "iac"
    K8S = "k8s"
    DEPLOYMENT = "deployment"
    VERIFICATION = "verification"
    SECURITY = "security"
    COST = "cost"


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

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True
