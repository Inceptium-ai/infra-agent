"""MCP client adapter to expose AWS and Git tools as LangChain tools.

This module provides LangChain-compatible tool wrappers for the MCP
server functionality, enabling integration with LangChain agents.

Supports:
- AWS API access via boto3
- Git repository access via GitHub/GitLab APIs
"""

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
from langchain_core.tools import tool

from infra_agent.config import get_settings

logger = logging.getLogger(__name__)


def get_aws_tools() -> list:
    """Get AWS MCP tools wrapped as LangChain tools.

    Returns:
        List of LangChain tool objects for AWS API access
    """
    settings = get_settings()

    @tool
    def aws_api_call(
        service: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Execute any AWS API operation via boto3.

        This tool provides full access to all AWS services and operations.

        Args:
            service: AWS service name (ec2, s3, lambda, iam, rds, eks, sns, sqs,
                    cloudformation, cloudwatch, dynamodb, secretsmanager, etc.)
            operation: Operation name in snake_case (describe_instances,
                      list_buckets, list_functions, list_roles, etc.)
            parameters: Optional dict of operation parameters

        Returns:
            JSON response from AWS API

        Examples:
            - aws_api_call(service="ec2", operation="describe_instances")
            - aws_api_call(service="s3", operation="list_buckets")
            - aws_api_call(service="lambda", operation="list_functions")
            - aws_api_call(service="iam", operation="list_roles")
            - aws_api_call(service="eks", operation="describe_cluster",
                          parameters={"name": "my-cluster"})
        """
        try:
            client = boto3.client(service, region_name=settings.aws_region)

            # Validate operation exists
            if not hasattr(client, operation):
                available_ops = [
                    op for op in dir(client)
                    if not op.startswith("_") and callable(getattr(client, op, None))
                ]
                return json.dumps({
                    "error": f"Unknown operation '{operation}' for service '{service}'",
                    "hint": "Use list_service_operations to see available operations",
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

    @tool
    def list_aws_services() -> str:
        """List all available AWS services accessible via boto3.

        Returns:
            JSON array of service names (ec2, s3, lambda, iam, etc.)
        """
        try:
            session = boto3.Session(region_name=settings.aws_region)
            services = sorted(session.get_available_services())
            return json.dumps(services, indent=2)
        except Exception as e:
            logger.error(f"list_aws_services error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @tool
    def list_service_operations(service: str) -> str:
        """List available operations for an AWS service.

        Args:
            service: AWS service name (ec2, s3, lambda, etc.)

        Returns:
            JSON list of operation names for the service
        """
        try:
            client = boto3.client(service, region_name=settings.aws_region)

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
            logger.error(f"list_service_operations({service}) error: {e}")
            return json.dumps({
                "error": str(e),
                "hint": f"Service '{service}' may not exist. Use list_aws_services() to see available services.",
            }, indent=2)

    return [aws_api_call, list_aws_services, list_service_operations]


# Common AWS query patterns for routing detection
AWS_QUERY_KEYWORDS = [
    # Services
    "aws", "ec2", "s3", "lambda", "iam", "rds", "eks", "sns", "sqs",
    "cloudformation", "cloudwatch", "dynamodb", "secretsmanager",
    "elasticache", "redshift", "kinesis", "apigateway", "route53",
    "acm", "kms", "ssm", "ecs", "ecr", "elb", "alb", "nlb",
    "vpc", "subnet", "security group", "nacl",
    # Resources
    "instances", "buckets", "functions", "roles", "policies",
    "clusters", "topics", "queues", "stacks", "tables", "secrets",
    "certificates", "keys", "parameters", "tasks", "services",
    "load balancer", "target group", "auto scaling",
    # Actions (read-only patterns)
    "list", "describe", "get", "show", "what", "which", "how many",
]


def is_aws_query(user_input: str) -> bool:
    """Determine if user input is an AWS-related query.

    Args:
        user_input: User's message

    Returns:
        True if the input appears to be an AWS query
    """
    input_lower = user_input.lower()
    return any(keyword in input_lower for keyword in AWS_QUERY_KEYWORDS)


# Git query patterns for routing detection
GIT_QUERY_KEYWORDS = [
    # Platforms
    "github", "gitlab", "git repo", "repository",
    # Actions
    "read file from", "get file from", "show file from",
    "list files in", "compare branches", "file history",
    "search code", "iac files", "iac drift",
    # IaC drift detection
    "compare iac", "drift from git", "drift from repo",
    "source of truth", "compare template", "compare helm",
    "cloudformation in git", "helm values in git",
]


def is_git_query(user_input: str) -> bool:
    """Determine if user input is a Git-related query.

    Args:
        user_input: User's message

    Returns:
        True if the input appears to be a Git query
    """
    input_lower = user_input.lower()
    return any(keyword in input_lower for keyword in GIT_QUERY_KEYWORDS)


def get_git_tools() -> list:
    """Get Git MCP tools wrapped as LangChain tools.

    Returns:
        List of LangChain tool objects for Git repository access
    """
    import base64
    import os

    settings = get_settings()
    git_platform = settings.git_platform.lower()

    def _get_github_client():
        """Get GitHub client."""
        try:
            from github import Github, Auth
        except ImportError:
            raise ImportError("PyGithub not installed. Run: pip install PyGithub")

        # Load from .env file if not in environment
        from dotenv import load_dotenv
        load_dotenv()

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN or GH_TOKEN environment variable required")

        return Github(auth=Auth.Token(token))

    def _get_gitlab_client():
        """Get GitLab client."""
        try:
            import gitlab
        except ImportError:
            raise ImportError("python-gitlab not installed. Run: pip install python-gitlab")

        # Load from .env file if not in environment
        from dotenv import load_dotenv
        load_dotenv()

        token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
        if not token:
            raise ValueError("GITLAB_TOKEN or GL_TOKEN environment variable required")

        url = settings.gitlab_url or "https://gitlab.com"
        return gitlab.Gitlab(url, private_token=token)

    def _get_client():
        """Get the appropriate Git client based on config."""
        if git_platform == "gitlab":
            return _get_gitlab_client(), "gitlab"
        else:
            return _get_github_client(), "github"

    @tool
    def git_read_file(
        repo: str,
        path: str,
        ref: str = "main",
    ) -> str:
        """Read a file from a Git repository.

        Args:
            repo: Repository name (e.g., "owner/repo" for GitHub, or project path for GitLab)
            path: File path within the repository (e.g., "infra/cloudformation/vpc.yaml")
            ref: Branch, tag, or commit SHA (default: "main")

        Returns:
            File contents as string, or error message

        Examples:
            git_read_file(repo="myorg/infra-agent", path="infra/cloudformation/stacks/01-networking/vpc.yaml")
            git_read_file(repo="myorg/infra-agent", path="infra/helm/values/signoz/values.yaml", ref="develop")
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                repository = client.get_repo(repo)
                content = repository.get_contents(path, ref=ref)
                if isinstance(content, list):
                    return json.dumps({"error": f"Path '{path}' is a directory, not a file"})
                file_content = base64.b64decode(content.content).decode("utf-8")
                return file_content
            else:  # gitlab
                project = client.projects.get(repo)
                file_obj = project.files.get(file_path=path, ref=ref)
                return base64.b64decode(file_obj.content).decode("utf-8")

        except Exception as e:
            logger.error(f"git_read_file({repo}, {path}, {ref}) error: {e}")
            return json.dumps({"error": str(e), "repo": repo, "path": path}, indent=2)

    @tool
    def git_list_files(
        repo: str,
        path: str = "",
        ref: str = "main",
    ) -> str:
        """List files in a repository directory.

        Args:
            repo: Repository name
            path: Directory path (empty string for root)
            ref: Branch, tag, or commit SHA

        Returns:
            JSON list of files with name, path, and type

        Examples:
            git_list_files(repo="myorg/infra-agent", path="infra/cloudformation/stacks")
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                repository = client.get_repo(repo)
                contents = repository.get_contents(path or "", ref=ref)
                if not isinstance(contents, list):
                    contents = [contents]

                files = [{"name": item.name, "path": item.path, "type": item.type} for item in contents]
                return json.dumps(files, indent=2)

            else:  # gitlab
                project = client.projects.get(repo)
                items = project.repository_tree(path=path or "", ref=ref)
                files = [{"name": item["name"], "path": item["path"], "type": item["type"]} for item in items]
                return json.dumps(files, indent=2)

        except Exception as e:
            logger.error(f"git_list_files({repo}, {path}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @tool
    def git_list_repos(
        org_or_group: str | None = None,
        limit: int = 20,
    ) -> str:
        """List accessible repositories.

        Args:
            org_or_group: Organization (GitHub) or Group (GitLab) to filter by
            limit: Maximum number of repos to return

        Returns:
            JSON list of repositories with name, description, and URLs
        """
        try:
            client, platform = _get_client()
            repos = []

            if platform == "github":
                if org_or_group:
                    org = client.get_organization(org_or_group)
                    repo_list = org.get_repos()
                else:
                    repo_list = client.get_user().get_repos()

                for repo in repo_list[:limit]:
                    repos.append({
                        "name": repo.full_name,
                        "description": repo.description,
                        "default_branch": repo.default_branch,
                    })

            else:  # gitlab
                if org_or_group:
                    group = client.groups.get(org_or_group)
                    project_list = group.projects.list(get_all=False, per_page=limit)
                else:
                    project_list = client.projects.list(membership=True, get_all=False, per_page=limit)

                for project in project_list:
                    repos.append({
                        "name": project.path_with_namespace,
                        "description": project.description,
                        "default_branch": project.default_branch,
                    })

            return json.dumps(repos, indent=2)

        except Exception as e:
            logger.error(f"git_list_repos error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @tool
    def git_get_iac_files(
        repo: str,
        ref: str = "main",
    ) -> str:
        """Get a summary of all IaC files in the repository.

        Looks for CloudFormation, Helm, Terraform, and Kubernetes files.

        Args:
            repo: Repository name
            ref: Branch, tag, or commit SHA

        Returns:
            JSON summary of IaC files organized by type
        """
        try:
            client, platform = _get_client()
            iac_files = {"cloudformation": [], "helm": [], "terraform": [], "kubernetes": []}

            if platform == "github":
                repository = client.get_repo(repo)
                tree = repository.get_git_tree(ref, recursive=True)

                for item in tree.tree:
                    if item.type != "blob":
                        continue
                    path = item.path

                    if "cloudformation" in path.lower() and path.endswith(".yaml"):
                        iac_files["cloudformation"].append(path)
                    elif "helm" in path.lower() and "values" in path.lower() and path.endswith(".yaml"):
                        iac_files["helm"].append(path)
                    elif path.endswith(".tf"):
                        iac_files["terraform"].append(path)
                    elif ("k8s" in path.lower() or "kubernetes" in path.lower()) and path.endswith(".yaml"):
                        iac_files["kubernetes"].append(path)

            else:  # gitlab
                project = client.projects.get(repo)
                items = project.repository_tree(ref=ref, recursive=True, get_all=True)

                for item in items:
                    if item["type"] != "blob":
                        continue
                    path = item["path"]

                    if "cloudformation" in path.lower() and path.endswith(".yaml"):
                        iac_files["cloudformation"].append(path)
                    elif "helm" in path.lower() and "values" in path.lower() and path.endswith(".yaml"):
                        iac_files["helm"].append(path)
                    elif path.endswith(".tf"):
                        iac_files["terraform"].append(path)
                    elif ("k8s" in path.lower() or "kubernetes" in path.lower()) and path.endswith(".yaml"):
                        iac_files["kubernetes"].append(path)

            return json.dumps({
                "repository": repo,
                "ref": ref,
                "counts": {k: len(v) for k, v in iac_files.items()},
                "files": iac_files,
            }, indent=2)

        except Exception as e:
            logger.error(f"git_get_iac_files({repo}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @tool
    def git_compare_with_deployed(
        repo: str,
        git_path: str,
        deployed_content: str,
        ref: str = "main",
    ) -> str:
        """Compare a file in Git with its deployed version.

        Args:
            repo: Repository name
            git_path: Path to file in Git repository
            deployed_content: The actual deployed content to compare against
            ref: Branch, tag, or commit SHA

        Returns:
            JSON comparison showing if files match and differences
        """
        try:
            client, platform = _get_client()

            # Get file from Git
            if platform == "github":
                repository = client.get_repo(repo)
                content = repository.get_contents(git_path, ref=ref)
                git_content = base64.b64decode(content.content).decode("utf-8")
            else:  # gitlab
                project = client.projects.get(repo)
                file_obj = project.files.get(file_path=git_path, ref=ref)
                git_content = base64.b64decode(file_obj.content).decode("utf-8")

            # Compare
            git_lines = git_content.strip().split("\n")
            deployed_lines = deployed_content.strip().split("\n")

            matches = git_content.strip() == deployed_content.strip()

            result = {
                "repository": repo,
                "path": git_path,
                "ref": ref,
                "matches": matches,
                "git_lines": len(git_lines),
                "deployed_lines": len(deployed_lines),
            }

            if not matches:
                # Find differences (simple diff)
                import difflib
                diff = list(difflib.unified_diff(
                    git_lines, deployed_lines,
                    fromfile=f"git:{git_path}",
                    tofile="deployed",
                    lineterm=""
                ))
                result["diff_preview"] = "\n".join(diff[:50])  # First 50 lines of diff

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"git_compare_with_deployed({repo}, {git_path}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    return [git_read_file, git_list_files, git_list_repos, git_get_iac_files, git_compare_with_deployed]
