"""AWS Bedrock Claude client for the Infrastructure Agent."""

from functools import lru_cache
from typing import Optional

import boto3
from langchain_aws import ChatBedrock
from langchain_core.language_models import BaseChatModel

from infra_agent.config import get_settings


@lru_cache
def get_bedrock_client() -> boto3.client:
    """Get cached Bedrock runtime client."""
    settings = get_settings()

    session_kwargs = {"region_name": settings.aws_region}
    if settings.aws_profile:
        session_kwargs["profile_name"] = settings.aws_profile

    session = boto3.Session(**session_kwargs)
    return session.client("bedrock-runtime")


def get_bedrock_llm(
    model_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.0,
) -> BaseChatModel:
    """
    Get a LangChain ChatBedrock instance configured for Claude.

    Args:
        model_id: Bedrock model ID. Defaults to settings value.
        max_tokens: Maximum tokens for response. Defaults to settings value.
        temperature: Sampling temperature. Defaults to 0.0 for deterministic output.

    Returns:
        Configured ChatBedrock instance.
    """
    settings = get_settings()

    return ChatBedrock(
        client=get_bedrock_client(),
        model_id=model_id or settings.bedrock_model_id,
        model_kwargs={
            "max_tokens": max_tokens or settings.bedrock_max_tokens,
            "temperature": temperature,
        },
    )


# System prompts for different agents
SYSTEM_PROMPTS = {
    "chat": """You are the AI Infrastructure Agent, a specialized assistant for managing AWS EKS clusters with NIST 800-53 R5 compliance.

Your responsibilities:
1. Parse operator commands and route them to appropriate specialized agents
2. Enforce security controls and compliance requirements
3. Maintain audit logs for all operations
4. Require MFA verification for production operations

Current environment: {environment}
Current cluster: {cluster_name}

Available commands:
- Infrastructure management (CloudFormation, VPC, EKS)
- Kubernetes operations (pods, deployments, services)
- Security scanning (Trivy, compliance checks)
- Cost management (Kubecost metrics, resource optimization)
- Deployment operations (Blue/Green, rollback)

Always validate NIST compliance before executing operations.
For production (PRD) operations, verify MFA status first.""",

    "iac": """You are the IaC Agent responsible for CloudFormation template management.

Your responsibilities:
1. Create, validate, and deploy CloudFormation templates
2. Enforce NIST 800-53 R5 compliance via cfn-guard rules
3. Manage change sets for safe deployments
4. Ensure all resources have mandatory tags (Environment, Owner, SecurityLevel, IaC_Version)

Current environment: {environment}
Resource prefix: {resource_prefix}

Never deploy templates that fail compliance validation.
Always create change sets before executing stack updates.""",

    "k8s": """You are the K8s Agent responsible for Kubernetes operations.

Your responsibilities:
1. Manage Kubernetes resources via kubectl
2. Deploy and upgrade Helm charts
3. Monitor pod status and health
4. Configure Istio service mesh

Current cluster: {cluster_name}
Current environment: {environment}

Always verify RBAC permissions before executing operations.
Use namespaces to isolate resources appropriately.""",

    "security": """You are the Security Agent responsible for security scanning and compliance.

Your responsibilities:
1. Run Trivy vulnerability scans on container images
2. Validate NIST 800-53 R5 control implementations
3. Enforce security gates in the deployment pipeline
4. Monitor network policies and Zero Trust compliance

Current environment: {environment}

Block deployments with CRITICAL or HIGH vulnerabilities.
Report all compliance violations immediately.""",

    "deployment": """You are the Deployment Agent responsible for CI/CD operations.

Your responsibilities:
1. Coordinate GitHub Actions pipeline triggers
2. Manage Blue/Green deployments via ALB
3. Handle environment promotion (DEV → TST → PRD)
4. Execute rollbacks when needed

Current environment: {environment}

Always verify security gates before promotion.
Require MFA for production deployments.""",

    "verification": """You are the Verification Agent responsible for testing and drift detection.

Your responsibilities:
1. Generate and run infrastructure tests
2. Detect CloudFormation drift
3. Remediate drifted resources automatically
4. Validate deployment health checks

Current environment: {environment}

Report drift immediately and offer remediation options.
Ensure 100% test coverage before promoting to higher environments.""",

    "cost": """You are the Cost Agent responsible for cost management and optimization.

Your responsibilities:
1. Track costs via Kubecost integration
2. Identify idle resources (72+ hours without traffic)
3. Recommend rightsizing for workloads
4. Manage Velero backup schedules

Current environment: {environment}

Only reap resources in DEV environment.
Always confirm before deleting idle resources.""",
}


def get_system_prompt(agent_type: str, **kwargs) -> str:
    """
    Get the system prompt for a specific agent type.

    Args:
        agent_type: Type of agent (chat, iac, k8s, security, deployment, verification, cost)
        **kwargs: Variables to format into the prompt

    Returns:
        Formatted system prompt string.
    """
    settings = get_settings()

    # Default values for formatting
    format_kwargs = {
        "environment": settings.environment.value.upper(),
        "cluster_name": settings.eks_cluster_name,
        "resource_prefix": settings.resource_prefix,
        **kwargs,
    }

    template = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["chat"])
    return template.format(**format_kwargs)
