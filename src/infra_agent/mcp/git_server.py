"""Git MCP Server - GitHub and GitLab API access.

This module provides an MCP server that enables access to Git repositories
via GitHub or GitLab APIs, supporting IaC drift detection by comparing
repository contents with deployed resources.
"""

import base64
import json
import logging
import os
from functools import lru_cache
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from infra_agent.config import get_settings

logger = logging.getLogger(__name__)


def create_git_mcp_server() -> FastMCP:
    """Create MCP server with Git repository access.

    Returns:
        FastMCP server instance configured with Git tools
    """
    settings = get_settings()
    git_platform = settings.git_platform.lower()

    mcp = FastMCP(
        name="infra-agent-git",
        instructions=f"""Git Repository Server for infra-agent.

Platform: {git_platform.upper()}
{f"GitLab URL: {settings.gitlab_url}" if git_platform == "gitlab" and settings.gitlab_url else ""}

Available tools:
- git_read_file: Read a file from a repository
- git_list_files: List files in a repository directory
- git_list_repos: List accessible repositories
- git_get_file_history: Get commit history for a file
- git_compare_branches: Compare two branches
- git_search_code: Search for code in repositories

Use these tools to:
- Compare IaC templates in Git with deployed AWS/K8s resources
- Detect configuration drift between source and deployed state
- Review infrastructure code changes
""",
    )

    @lru_cache
    def get_github_client():
        """Get GitHub client."""
        try:
            from github import Github, Auth
        except ImportError:
            raise ImportError("PyGithub not installed. Run: pip install PyGithub")

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN or GH_TOKEN environment variable required")

        return Github(auth=Auth.Token(token))

    @lru_cache
    def get_gitlab_client():
        """Get GitLab client."""
        try:
            import gitlab
        except ImportError:
            raise ImportError("python-gitlab not installed. Run: pip install python-gitlab")

        token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
        if not token:
            raise ValueError("GITLAB_TOKEN or GL_TOKEN environment variable required")

        url = settings.gitlab_url or "https://gitlab.com"
        return gitlab.Gitlab(url, private_token=token)

    def _get_client():
        """Get the appropriate Git client based on config."""
        if git_platform == "gitlab":
            return get_gitlab_client(), "gitlab"
        else:
            return get_github_client(), "github"

    @mcp.tool()
    async def git_read_file(
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
            # Read CloudFormation template
            git_read_file(repo="myorg/infra-agent", path="infra/cloudformation/stacks/01-networking/vpc.yaml")

            # Read Helm values from specific branch
            git_read_file(repo="myorg/infra-agent", path="infra/helm/values/signoz/values.yaml", ref="develop")
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                repository = client.get_repo(repo)
                content = repository.get_contents(path, ref=ref)
                if isinstance(content, list):
                    return json.dumps({"error": f"Path '{path}' is a directory, not a file"})

                # Decode base64 content
                file_content = base64.b64decode(content.content).decode("utf-8")
                return file_content

            else:  # gitlab
                project = client.projects.get(repo)
                file_obj = project.files.get(file_path=path, ref=ref)
                return base64.b64decode(file_obj.content).decode("utf-8")

        except Exception as e:
            logger.error(f"git_read_file({repo}, {path}, {ref}) error: {e}")
            return json.dumps({
                "error": str(e),
                "repo": repo,
                "path": path,
                "ref": ref,
            }, indent=2)

    @mcp.tool()
    async def git_list_files(
        repo: str,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
    ) -> str:
        """List files in a repository directory.

        Args:
            repo: Repository name
            path: Directory path (empty string for root)
            ref: Branch, tag, or commit SHA
            recursive: If True, list all files recursively

        Returns:
            JSON list of files with name, path, type, and size

        Examples:
            # List root directory
            git_list_files(repo="myorg/infra-agent")

            # List CloudFormation stacks
            git_list_files(repo="myorg/infra-agent", path="infra/cloudformation/stacks")

            # List all files recursively
            git_list_files(repo="myorg/infra-agent", path="infra/helm", recursive=True)
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                repository = client.get_repo(repo)

                if recursive:
                    # Use Git tree API for recursive listing
                    tree = repository.get_git_tree(ref, recursive=True)
                    files = []
                    for item in tree.tree:
                        if path and not item.path.startswith(path):
                            continue
                        files.append({
                            "name": item.path.split("/")[-1],
                            "path": item.path,
                            "type": "dir" if item.type == "tree" else "file",
                            "size": item.size if item.type == "blob" else None,
                        })
                    return json.dumps(files, indent=2)
                else:
                    contents = repository.get_contents(path or "", ref=ref)
                    if not isinstance(contents, list):
                        contents = [contents]

                    files = []
                    for item in contents:
                        files.append({
                            "name": item.name,
                            "path": item.path,
                            "type": item.type,
                            "size": item.size,
                        })
                    return json.dumps(files, indent=2)

            else:  # gitlab
                project = client.projects.get(repo)
                items = project.repository_tree(path=path or "", ref=ref, recursive=recursive)

                files = []
                for item in items:
                    files.append({
                        "name": item["name"],
                        "path": item["path"],
                        "type": "dir" if item["type"] == "tree" else "file",
                    })
                return json.dumps(files, indent=2)

        except Exception as e:
            logger.error(f"git_list_files({repo}, {path}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def git_list_repos(
        org_or_group: str | None = None,
        search: str | None = None,
        limit: int = 20,
    ) -> str:
        """List accessible repositories.

        Args:
            org_or_group: Organization (GitHub) or Group (GitLab) to filter by
            search: Search query to filter repositories
            limit: Maximum number of repos to return (default: 20)

        Returns:
            JSON list of repositories with name, description, and URLs

        Examples:
            # List all accessible repos
            git_list_repos()

            # List repos in an organization
            git_list_repos(org_or_group="myorg")

            # Search for infrastructure repos
            git_list_repos(search="infra")
        """
        try:
            client, platform = _get_client()
            repos = []

            if platform == "github":
                if org_or_group:
                    org = client.get_organization(org_or_group)
                    repo_list = org.get_repos()
                elif search:
                    repo_list = client.search_repositories(query=search)
                else:
                    repo_list = client.get_user().get_repos()

                for repo in repo_list[:limit]:
                    repos.append({
                        "name": repo.full_name,
                        "description": repo.description,
                        "url": repo.html_url,
                        "default_branch": repo.default_branch,
                        "private": repo.private,
                    })

            else:  # gitlab
                if org_or_group:
                    group = client.groups.get(org_or_group)
                    project_list = group.projects.list(get_all=False, per_page=limit)
                elif search:
                    project_list = client.projects.list(search=search, get_all=False, per_page=limit)
                else:
                    project_list = client.projects.list(membership=True, get_all=False, per_page=limit)

                for project in project_list:
                    repos.append({
                        "name": project.path_with_namespace,
                        "description": project.description,
                        "url": project.web_url,
                        "default_branch": project.default_branch,
                        "private": project.visibility == "private",
                    })

            return json.dumps(repos, indent=2)

        except Exception as e:
            logger.error(f"git_list_repos error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def git_get_file_history(
        repo: str,
        path: str,
        ref: str = "main",
        limit: int = 10,
    ) -> str:
        """Get commit history for a specific file.

        Args:
            repo: Repository name
            path: File path
            ref: Branch to get history from
            limit: Maximum number of commits to return

        Returns:
            JSON list of commits with SHA, message, author, and date

        Examples:
            git_get_file_history(repo="myorg/infra-agent", path="infra/cloudformation/stacks/02-eks/cluster.yaml")
        """
        try:
            client, platform = _get_client()
            commits = []

            if platform == "github":
                repository = client.get_repo(repo)
                commit_list = repository.get_commits(sha=ref, path=path)

                for commit in commit_list[:limit]:
                    commits.append({
                        "sha": commit.sha[:8],
                        "message": commit.commit.message.split("\n")[0],
                        "author": commit.commit.author.name,
                        "date": commit.commit.author.date.isoformat(),
                    })

            else:  # gitlab
                project = client.projects.get(repo)
                commit_list = project.commits.list(ref_name=ref, path=path, get_all=False, per_page=limit)

                for commit in commit_list:
                    commits.append({
                        "sha": commit.short_id,
                        "message": commit.title,
                        "author": commit.author_name,
                        "date": commit.created_at,
                    })

            return json.dumps(commits, indent=2)

        except Exception as e:
            logger.error(f"git_get_file_history({repo}, {path}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def git_compare_branches(
        repo: str,
        base: str,
        head: str,
    ) -> str:
        """Compare two branches and show differences.

        Args:
            repo: Repository name
            base: Base branch (e.g., "main")
            head: Head branch to compare (e.g., "feature/update-vpc")

        Returns:
            JSON with commits ahead/behind and changed files

        Examples:
            git_compare_branches(repo="myorg/infra-agent", base="main", head="develop")
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                repository = client.get_repo(repo)
                comparison = repository.compare(base, head)

                changed_files = []
                for file in comparison.files[:50]:  # Limit files
                    changed_files.append({
                        "filename": file.filename,
                        "status": file.status,
                        "additions": file.additions,
                        "deletions": file.deletions,
                    })

                return json.dumps({
                    "base": base,
                    "head": head,
                    "ahead_by": comparison.ahead_by,
                    "behind_by": comparison.behind_by,
                    "total_commits": comparison.total_commits,
                    "changed_files_count": len(comparison.files),
                    "changed_files": changed_files,
                }, indent=2)

            else:  # gitlab
                project = client.projects.get(repo)
                comparison = project.repository_compare(base, head)

                changed_files = []
                for diff in comparison.get("diffs", [])[:50]:
                    changed_files.append({
                        "filename": diff["new_path"],
                        "status": "added" if diff["new_file"] else "modified" if not diff["deleted_file"] else "deleted",
                    })

                return json.dumps({
                    "base": base,
                    "head": head,
                    "total_commits": len(comparison.get("commits", [])),
                    "changed_files_count": len(comparison.get("diffs", [])),
                    "changed_files": changed_files,
                }, indent=2)

        except Exception as e:
            logger.error(f"git_compare_branches({repo}, {base}, {head}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def git_search_code(
        query: str,
        repo: str | None = None,
        file_extension: str | None = None,
        limit: int = 20,
    ) -> str:
        """Search for code in repositories.

        Args:
            query: Search query (code snippet, function name, etc.)
            repo: Optional repository to search in (searches all accessible if not specified)
            file_extension: Optional file extension filter (e.g., "yaml", "py")
            limit: Maximum results to return

        Returns:
            JSON list of matches with file path, repository, and matching lines

        Examples:
            # Search for NIST control references
            git_search_code(query="SC-28", file_extension="yaml")

            # Search for specific resource in a repo
            git_search_code(query="eks-cluster", repo="myorg/infra-agent")
        """
        try:
            client, platform = _get_client()

            if platform == "github":
                # Build search query
                search_query = query
                if repo:
                    search_query += f" repo:{repo}"
                if file_extension:
                    search_query += f" extension:{file_extension}"

                results = client.search_code(query=search_query)
                matches = []

                for item in results[:limit]:
                    matches.append({
                        "repository": item.repository.full_name,
                        "path": item.path,
                        "url": item.html_url,
                        "score": item.score,
                    })

                return json.dumps({
                    "query": query,
                    "total_matches": results.totalCount,
                    "results": matches,
                }, indent=2)

            else:  # gitlab
                # GitLab search is project-scoped or group-scoped
                if repo:
                    project = client.projects.get(repo)
                    results = project.search("blobs", query)
                else:
                    # Search globally (limited)
                    results = client.search("blobs", query)

                matches = []
                for item in results[:limit]:
                    if file_extension and not item.get("filename", "").endswith(f".{file_extension}"):
                        continue
                    matches.append({
                        "repository": item.get("project_id"),
                        "path": item.get("filename"),
                        "ref": item.get("ref"),
                    })

                return json.dumps({
                    "query": query,
                    "results": matches,
                }, indent=2)

        except Exception as e:
            logger.error(f"git_search_code({query}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def git_get_iac_files(
        repo: str,
        ref: str = "main",
    ) -> str:
        """Get a summary of all IaC files in the repository.

        This tool specifically looks for infrastructure-as-code files:
        - CloudFormation templates (*.yaml in cloudformation/)
        - Helm values (*.yaml in helm/values/)
        - Terraform files (*.tf)
        - Kubernetes manifests (*.yaml in k8s/)

        Args:
            repo: Repository name
            ref: Branch, tag, or commit SHA

        Returns:
            JSON summary of IaC files organized by type

        Examples:
            git_get_iac_files(repo="myorg/infra-agent")
        """
        try:
            client, platform = _get_client()
            iac_files = {
                "cloudformation": [],
                "helm": [],
                "terraform": [],
                "kubernetes": [],
            }

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

            # Add counts
            summary = {
                "repository": repo,
                "ref": ref,
                "counts": {k: len(v) for k, v in iac_files.items()},
                "files": iac_files,
            }

            return json.dumps(summary, indent=2)

        except Exception as e:
            logger.error(f"git_get_iac_files({repo}) error: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    return mcp


def run_server(transport: str = "stdio") -> None:
    """Run the Git MCP server.

    Args:
        transport: Transport mechanism ("stdio" or "sse")
    """
    mcp = create_git_mcp_server()
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_server()
