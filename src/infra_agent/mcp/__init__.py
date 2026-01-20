"""MCP (Model Context Protocol) servers for AWS and Git access.

This module provides MCP servers that enable:
- Full AWS API access via boto3 (all 415+ services)
- Git repository access via GitHub/GitLab APIs

These enable the infrastructure agent to:
- Query any AWS resource
- Read IaC files from Git repositories
- Compare deployed resources with source of truth in Git
- Detect configuration drift
"""

from infra_agent.mcp.aws_server import create_aws_mcp_server
from infra_agent.mcp.git_server import create_git_mcp_server
from infra_agent.mcp.client import get_aws_tools, get_git_tools, is_aws_query, is_git_query

__all__ = [
    "create_aws_mcp_server",
    "create_git_mcp_server",
    "get_aws_tools",
    "get_git_tools",
    "is_aws_query",
    "is_git_query",
]
