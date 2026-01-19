"""Intent classification router for the Infrastructure Agent.

This module provides intent classification to route user requests
to the appropriate pipeline path:
- change: Infrastructure changes → 4-agent pipeline
- query: Information queries → K8s agent direct
- investigate: Troubleshooting and diagnostics → Investigation Agent
- audit: Compliance, security, cost, drift audits → Audit Agent
- conversation: General chat → Orchestrator response
"""

import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

from infra_agent.llm.bedrock import get_bedrock_llm


# Keywords for quick classification (before LLM)
CHANGE_KEYWORDS = [
    "create", "add", "deploy", "update", "modify", "change", "delete", "remove",
    "scale", "upgrade", "install", "configure", "enable", "disable", "set",
    "increase", "decrease", "replicas", "rollback", "restart", "migrate",
]

QUERY_KEYWORDS = [
    "get", "list", "show", "describe", "what", "which", "how many", "status",
    "check", "view", "display", "tell me", "logs", "events", "pods", "nodes",
    "namespaces", "services", "deployments",
]

# Investigation keywords - troubleshooting and diagnostics
INVESTIGATE_KEYWORDS = [
    "investigate", "diagnose", "debug", "troubleshoot", "why is", "why are",
    "not working", "failing", "error", "issue", "problem", "crashing",
    "restarting", "stuck", "pending", "unhealthy", "down", "slow",
    "root cause", "what's wrong", "help me understand",
]

# Audit keywords - compliance, security, cost, drift
AUDIT_KEYWORDS = [
    "audit", "compliance", "nist", "security scan", "security check",
    "security posture", "cost analysis", "cost optimization", "drift",
    "drift detection", "review compliance", "assess security",
    "vulnerability scan", "check compliance", "cost review",
]

# System prompt for LLM-based classification
CLASSIFICATION_PROMPT = """You are an intent classifier for an infrastructure management system.

Classify user requests into one of five categories:

1. CHANGE - Infrastructure modifications that require the 4-agent pipeline:
   - Creating, updating, or deleting AWS resources
   - Deploying or modifying Kubernetes workloads
   - Scaling applications (replicas, node groups)
   - Installing or upgrading Helm charts
   - Modifying CloudFormation templates
   - Any operation that changes infrastructure state

2. QUERY - Information requests that can be answered directly:
   - Status checks (pod status, deployment health)
   - Listing resources (pods, services, nodes)
   - Viewing logs or events
   - Describing current configuration
   - Any read-only operation

3. INVESTIGATE - Troubleshooting and diagnostic requests:
   - "Why is X not working?"
   - "Debug why pods are restarting"
   - "Diagnose the issue with service Y"
   - "Troubleshoot the slow response times"
   - Root cause analysis
   - Finding why something is failing, stuck, pending, or unhealthy

4. AUDIT - Compliance, security, cost, and drift assessment:
   - "Audit NIST compliance"
   - "Run a security scan"
   - "Check for cost optimization opportunities"
   - "Detect configuration drift"
   - "Review security posture"
   - Any compliance or security assessment

5. CONVERSATION - General chat or unclear requests:
   - Greetings or pleasantries
   - Questions about the agent itself
   - Unclear or ambiguous requests
   - Help requests

Respond with ONLY one word: CHANGE, QUERY, INVESTIGATE, AUDIT, or CONVERSATION

Examples:
- "Add 3 replicas to the SigNoz frontend" → CHANGE
- "Deploy the new version of the API" → CHANGE
- "What pods are running in signoz namespace?" → QUERY
- "Show me the status of all deployments" → QUERY
- "Why are SigNoz pods restarting?" → INVESTIGATE
- "Debug why the service is slow" → INVESTIGATE
- "Audit my infrastructure for NIST compliance" → AUDIT
- "Find idle resources and cost savings" → AUDIT
- "Check for configuration drift" → AUDIT
- "Hello, how are you?" → CONVERSATION
- "What can you do?" → CONVERSATION
"""


def classify_intent_keywords(
    message: str,
) -> Literal["change", "query", "investigate", "audit", "conversation"] | None:
    """
    Quick keyword-based intent classification.

    Args:
        message: User's input message

    Returns:
        Intent type if confidently determined, None if LLM needed
    """
    message_lower = message.lower()

    # Check for investigate keywords first (highest priority for troubleshooting)
    for keyword in INVESTIGATE_KEYWORDS:
        if keyword in message_lower:
            return "investigate"

    # Check for audit keywords
    for keyword in AUDIT_KEYWORDS:
        if keyword in message_lower:
            return "audit"

    # Check for change keywords at the start (imperative form)
    for keyword in CHANGE_KEYWORDS:
        if message_lower.startswith(keyword) or f" {keyword} " in message_lower:
            # Double-check it's not a query about changes
            if not any(q in message_lower for q in ["what", "which", "how", "list", "show"]):
                return "change"

    # Check for query keywords
    for keyword in QUERY_KEYWORDS:
        if message_lower.startswith(keyword) or f" {keyword} " in message_lower:
            return "query"

    # Can't determine confidently
    return None


async def classify_intent_llm(
    message: str,
    llm: BaseChatModel | None = None,
) -> Literal["change", "query", "investigate", "audit", "conversation"]:
    """
    LLM-based intent classification for ambiguous cases.

    Args:
        message: User's input message
        llm: Language model to use (defaults to Bedrock)

    Returns:
        Classified intent type
    """
    if llm is None:
        llm = get_bedrock_llm()

    messages = [
        SystemMessage(content=CLASSIFICATION_PROMPT),
        HumanMessage(content=message),
    ]

    response = await llm.ainvoke(messages)
    result = response.content.strip().upper()

    # Parse response
    if "INVESTIGATE" in result:
        return "investigate"
    elif "AUDIT" in result:
        return "audit"
    elif "CHANGE" in result:
        return "change"
    elif "QUERY" in result:
        return "query"
    else:
        return "conversation"


async def classify_intent(
    message: str,
    use_llm: bool = True,
    llm: BaseChatModel | None = None,
) -> Literal["change", "query", "investigate", "audit", "conversation"]:
    """
    Classify user intent using keywords first, then LLM if needed.

    Args:
        message: User's input message
        use_llm: Whether to fall back to LLM for ambiguous cases
        llm: Language model to use (defaults to Bedrock)

    Returns:
        Classified intent type
    """
    # Try quick keyword classification first
    intent = classify_intent_keywords(message)
    if intent is not None:
        return intent

    # Fall back to LLM if enabled
    if use_llm:
        return await classify_intent_llm(message, llm)

    # Default to conversation if no LLM
    return "conversation"


def is_production_operation(message: str, environment: str) -> bool:
    """
    Check if an operation targets production environment.

    Args:
        message: User's input message
        environment: Current environment setting

    Returns:
        True if operation targets production
    """
    message_lower = message.lower()

    # Explicit production mentions
    if any(p in message_lower for p in ["prod", "production", "prd"]):
        return True

    # Current environment is production
    if environment.upper() in ["PRD", "PROD", "PRODUCTION"]:
        return True

    return False


def requires_approval(message: str, intent: str, environment: str) -> bool:
    """
    Check if an operation requires human approval.

    Args:
        message: User's input message
        intent: Classified intent
        environment: Current environment

    Returns:
        True if approval is required
    """
    # Only changes require approval
    if intent != "change":
        return False

    # Production changes always require approval
    if is_production_operation(message, environment):
        return True

    # Destructive operations require approval
    destructive_keywords = ["delete", "remove", "destroy", "terminate", "drop"]
    if any(k in message.lower() for k in destructive_keywords):
        return True

    return False


def extract_target_resource(message: str) -> dict[str, str | None]:
    """
    Extract target resource information from user message.

    Args:
        message: User's input message

    Returns:
        Dictionary with resource type and name if found
    """
    result = {"type": None, "name": None, "namespace": None}

    message_lower = message.lower()

    # Resource type patterns
    resource_patterns = {
        "deployment": r"deployment[s]?\s+(\S+)",
        "pod": r"pod[s]?\s+(\S+)",
        "service": r"service[s]?\s+(\S+)",
        "statefulset": r"statefulset[s]?\s+(\S+)",
        "daemonset": r"daemonset[s]?\s+(\S+)",
        "namespace": r"namespace[s]?\s+(\S+)",
        "node": r"node[s]?\s+(\S+)",
        "helm": r"(?:helm\s+)?(?:chart|release)[s]?\s+(\S+)",
        "stack": r"(?:cloudformation\s+)?stack[s]?\s+(\S+)",
    }

    for resource_type, pattern in resource_patterns.items():
        match = re.search(pattern, message_lower)
        if match:
            result["type"] = resource_type
            result["name"] = match.group(1)
            break

    # Namespace extraction
    ns_match = re.search(r"(?:in|namespace|ns)\s+(\S+)", message_lower)
    if ns_match:
        result["namespace"] = ns_match.group(1)

    return result
