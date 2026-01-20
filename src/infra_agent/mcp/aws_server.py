"""AWS MCP Server - Full AWS API access via boto3.

This module provides an MCP (Model Context Protocol) server that enables
execution of any AWS API operation through a generic boto3 wrapper.

Supported services include: EC2, S3, Lambda, IAM, RDS, EKS, SNS, SQS,
CloudFormation, CloudWatch, DynamoDB, and 200+ other AWS services.
"""

import json
import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
from mcp.server.fastmcp import FastMCP

from infra_agent.config import get_settings

logger = logging.getLogger(__name__)


def create_aws_mcp_server() -> FastMCP:
    """Create MCP server with full AWS access.

    Returns:
        FastMCP server instance configured with AWS tools
    """
    settings = get_settings()

    mcp = FastMCP(
        name="infra-agent-aws",
        instructions=f"""AWS API Server for infra-agent.

Environment: {settings.environment.value.upper()}
Region: {settings.aws_region}

Available tools:
- aws_api_call: Execute ANY boto3 operation (ec2, s3, lambda, iam, etc.)
- list_aws_services: Discover all available AWS services
- describe_service_operations: See operations available for a service

Examples:
- aws_api_call(service="ec2", operation="describe_instances")
- aws_api_call(service="s3", operation="list_buckets")
- aws_api_call(service="lambda", operation="list_functions")
- aws_api_call(service="iam", operation="list_roles")
- aws_api_call(service="cloudformation", operation="list_stacks")
""",
    )

    @lru_cache
    def get_session() -> boto3.Session:
        """Get cached boto3 session."""
        return boto3.Session(region_name=settings.aws_region)

    @mcp.tool()
    async def aws_api_call(
        service: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Execute any AWS API operation via boto3.

        This tool provides full access to all AWS services and operations.
        Use describe_service_operations to discover available operations.

        Args:
            service: AWS service name in lowercase (e.g., "ec2", "s3", "lambda",
                    "iam", "rds", "eks", "sns", "sqs", "cloudformation",
                    "cloudwatch", "dynamodb", "secretsmanager", etc.)
            operation: Operation name in snake_case (e.g., "describe_instances",
                      "list_buckets", "list_functions", "list_roles")
            parameters: Optional dict of operation parameters. Refer to boto3
                       documentation for required and optional parameters.

        Returns:
            JSON-formatted response from AWS API, or error message if failed.

        Examples:
            # List EC2 instances
            aws_api_call(service="ec2", operation="describe_instances")

            # List running EC2 instances only
            aws_api_call(
                service="ec2",
                operation="describe_instances",
                parameters={"Filters": [{"Name": "instance-state-name", "Values": ["running"]}]}
            )

            # List S3 buckets
            aws_api_call(service="s3", operation="list_buckets")

            # List Lambda functions
            aws_api_call(service="lambda", operation="list_functions")

            # List IAM roles
            aws_api_call(service="iam", operation="list_roles")

            # List CloudFormation stacks
            aws_api_call(service="cloudformation", operation="list_stacks")

            # Describe EKS cluster
            aws_api_call(
                service="eks",
                operation="describe_cluster",
                parameters={"name": "my-cluster"}
            )

            # List SNS topics
            aws_api_call(service="sns", operation="list_topics")

            # List SQS queues
            aws_api_call(service="sqs", operation="list_queues")

            # Get CloudWatch alarms
            aws_api_call(service="cloudwatch", operation="describe_alarms")

            # List RDS instances
            aws_api_call(service="rds", operation="describe_db_instances")

            # List DynamoDB tables
            aws_api_call(service="dynamodb", operation="list_tables")

            # List Secrets Manager secrets
            aws_api_call(service="secretsmanager", operation="list_secrets")
        """
        try:
            session = get_session()
            client = session.client(service)

            # Validate operation exists
            if not hasattr(client, operation):
                available_ops = [
                    op for op in dir(client)
                    if not op.startswith("_") and callable(getattr(client, op, None))
                ]
                return json.dumps({
                    "error": f"Unknown operation '{operation}' for service '{service}'",
                    "hint": "Use describe_service_operations to see available operations",
                    "sample_operations": available_ops[:10],
                }, indent=2)

            method = getattr(client, operation)
            response = method(**(parameters or {}))

            # Remove ResponseMetadata for cleaner output
            if isinstance(response, dict):
                response.pop("ResponseMetadata", None)

            logger.info(f"AWS API call: {service}.{operation} - Success")
            return json.dumps(response, indent=2, default=str)

        except NoCredentialsError:
            logger.error(f"AWS API call: {service}.{operation} - No credentials")
            return json.dumps({
                "error": "AWS credentials not configured",
                "hint": "Ensure AWS credentials are set via environment variables or ~/.aws/credentials",
            }, indent=2)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"AWS API call: {service}.{operation} - ClientError: {error_code}")
            return json.dumps({
                "error": error_message,
                "code": error_code,
                "service": service,
                "operation": operation,
            }, indent=2)

        except BotoCoreError as e:
            logger.error(f"AWS API call: {service}.{operation} - BotoCoreError: {e}")
            return json.dumps({
                "error": str(e),
                "service": service,
                "operation": operation,
            }, indent=2)

        except Exception as e:
            logger.error(f"AWS API call: {service}.{operation} - Error: {e}")
            return json.dumps({
                "error": str(e),
                "service": service,
                "operation": operation,
            }, indent=2)

    @mcp.tool()
    async def list_aws_services() -> str:
        """List all available AWS services accessible via boto3.

        Returns a sorted list of service names that can be used with aws_api_call.

        Returns:
            JSON array of service names (e.g., ["ec2", "s3", "lambda", ...])

        Example:
            list_aws_services()
            # Returns: ["accessanalyzer", "acm", "apigateway", "ec2", "eks", ...]
        """
        try:
            session = get_session()
            services = sorted(session.get_available_services())
            return json.dumps(services, indent=2)
        except Exception as e:
            logger.error(f"list_aws_services error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def describe_service_operations(service: str) -> str:
        """List available operations for an AWS service.

        Use this to discover what operations are available before calling aws_api_call.

        Args:
            service: AWS service name (e.g., "ec2", "s3", "lambda")

        Returns:
            JSON array of operation names available for the service

        Example:
            describe_service_operations(service="ec2")
            # Returns: ["describe_instances", "describe_vpcs", "run_instances", ...]
        """
        try:
            session = get_session()
            client = session.client(service)

            # Get all callable methods that don't start with underscore
            operations = sorted([
                op for op in dir(client)
                if not op.startswith("_")
                and callable(getattr(client, op, None))
                and not op.startswith("get_paginator")
                and not op.startswith("get_waiter")
                and op not in ("can_paginate", "close", "exceptions", "meta")
            ])

            return json.dumps({
                "service": service,
                "operation_count": len(operations),
                "operations": operations,
            }, indent=2)

        except Exception as e:
            logger.error(f"describe_service_operations({service}) error: {e}")
            return json.dumps({
                "error": str(e),
                "hint": f"Service '{service}' may not exist. Use list_aws_services() to see available services.",
            }, indent=2)

    return mcp


def run_server(transport: str = "stdio") -> None:
    """Run the AWS MCP server.

    Args:
        transport: Transport mechanism ("stdio" or "sse")
    """
    mcp = create_aws_mcp_server()
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_server()
