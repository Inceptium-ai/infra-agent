"""Investigation Agent - Diagnoses issues and troubleshoots problems.

The Investigation Agent is responsible for:
- Diagnosing why pods/services/nodes are unhealthy
- Troubleshooting connectivity and performance issues
- Analyzing logs, events, and metrics to find root causes
- Providing remediation recommendations
"""

from infra_agent.agents.investigation.agent import InvestigationAgent

__all__ = ["InvestigationAgent"]
