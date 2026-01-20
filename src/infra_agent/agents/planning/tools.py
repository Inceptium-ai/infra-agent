"""Tools for the Planning Agent.

These tools help the Planning Agent analyze user requests and identify
the infrastructure files that need modification.
"""

import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class FileSearchInput(BaseModel):
    """Input for file search tool."""

    search_term: str = Field(description="Term to search for in file paths")
    file_type: Optional[str] = Field(
        default=None, description="File extension to filter by (e.g., 'yaml', 'json')"
    )


class FileSearchTool(BaseTool):
    """Tool to search for infrastructure files by name or content."""

    name: str = "file_search"
    description: str = """Search for infrastructure files in the project.
    Searches in infra/cloudformation/ and infra/helm/values/ directories.
    Returns a list of matching file paths."""
    args_schema: type[BaseModel] = FileSearchInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, search_term: str, file_type: Optional[str] = None) -> str:
        """Execute the file search."""
        infra_path = self.project_root / "infra"

        results = []

        # Search CloudFormation stacks
        cfn_path = infra_path / "cloudformation" / "stacks"
        if cfn_path.exists():
            pattern = f"**/*{search_term}*"
            if file_type:
                pattern = f"**/*{search_term}*.{file_type}"
            for f in cfn_path.glob(pattern):
                results.append(str(f.relative_to(self.project_root)))

        # Search Helm values
        helm_path = infra_path / "helm" / "values"
        if helm_path.exists():
            pattern = f"**/*{search_term}*"
            if file_type:
                pattern = f"**/*{search_term}*.{file_type}"
            for f in helm_path.glob(pattern):
                results.append(str(f.relative_to(self.project_root)))

        if results:
            return "Found files:\n" + "\n".join(f"  - {r}" for r in results)
        return f"No files found matching '{search_term}'"


class GrepSearchInput(BaseModel):
    """Input for content search tool."""

    pattern: str = Field(description="Text pattern to search for")
    directory: Optional[str] = Field(
        default=None, description="Directory to search in (relative to project root)"
    )


class GrepSearchTool(BaseTool):
    """Tool to search file contents for specific patterns."""

    name: str = "grep_search"
    description: str = """Search file contents for a pattern.
    Useful for finding where specific resources, values, or configurations are defined."""
    args_schema: type[BaseModel] = GrepSearchInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, pattern: str, directory: Optional[str] = None) -> str:
        """Execute grep search."""
        search_dir = self.project_root / "infra"
        if directory:
            search_dir = self.project_root / directory

        if not search_dir.exists():
            return f"Directory not found: {search_dir}"

        try:
            result = subprocess.run(
                ["grep", "-r", "-l", "-n", pattern, str(search_dir)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.stdout:
                lines = result.stdout.strip().split("\n")
                # Convert absolute paths to relative
                relative_lines = []
                for line in lines[:20]:  # Limit to 20 results
                    try:
                        path_part = line.split(":")[0]
                        rel_path = Path(path_part).relative_to(self.project_root)
                        rest = line[len(path_part) :]
                        relative_lines.append(f"{rel_path}{rest}")
                    except (ValueError, IndexError):
                        relative_lines.append(line)

                return "Found matches:\n" + "\n".join(relative_lines)

            return f"No matches found for '{pattern}'"

        except subprocess.TimeoutExpired:
            return "Search timed out"
        except FileNotFoundError:
            return "grep command not found"
        except Exception as e:
            return f"Search error: {e}"


class NamespaceInfoInput(BaseModel):
    """Input for namespace info tool."""

    namespace: str = Field(description="Kubernetes namespace name")


class NamespaceInfoTool(BaseTool):
    """Tool to get information about a Kubernetes namespace configuration."""

    name: str = "namespace_info"
    description: str = """Get configuration info about a Kubernetes namespace.
    Returns details about Helm values files and related configurations."""
    args_schema: type[BaseModel] = NamespaceInfoInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, namespace: str) -> str:
        """Get namespace configuration info."""
        helm_path = self.project_root / "infra" / "helm" / "values"

        info_parts = [f"Namespace: {namespace}"]

        # Check for direct namespace directory
        ns_dir = helm_path / namespace
        if ns_dir.exists():
            info_parts.append(f"\nHelm values directory: infra/helm/values/{namespace}/")
            yaml_files = list(ns_dir.glob("*.yaml"))
            if yaml_files:
                info_parts.append("Files:")
                for f in yaml_files:
                    info_parts.append(f"  - {f.name}")

        # Check for related files
        related = list(helm_path.glob(f"**/*{namespace}*.yaml"))
        if related:
            info_parts.append("\nRelated files:")
            for f in related:
                rel_path = f.relative_to(self.project_root)
                info_parts.append(f"  - {rel_path}")

        if len(info_parts) == 1:
            return f"No configuration found for namespace '{namespace}'"

        return "\n".join(info_parts)


class NISTControlInput(BaseModel):
    """Input for NIST control lookup tool."""

    control_id: str = Field(description="NIST 800-53 control ID (e.g., CM-3, AC-2)")


class NISTControlTool(BaseTool):
    """Tool to get information about NIST 800-53 controls."""

    name: str = "nist_control"
    description: str = """Look up NIST 800-53 control information.
    Returns description and relevant cfn-guard rules."""
    args_schema: type[BaseModel] = NISTControlInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    # Common NIST 800-53 controls relevant to infrastructure
    CONTROL_INFO: dict = {
        "AC-2": {
            "name": "Account Management",
            "description": "Manage system accounts, including creation, modification, and deletion",
            "relevance": "IAM roles, Kubernetes RBAC",
        },
        "AC-3": {
            "name": "Access Enforcement",
            "description": "Enforce approved authorizations for logical access",
            "relevance": "Security groups, network policies",
        },
        "AC-6": {
            "name": "Least Privilege",
            "description": "Employ least privilege principle",
            "relevance": "IAM policies, RBAC roles",
        },
        "AU-2": {
            "name": "Audit Events",
            "description": "Define auditable events",
            "relevance": "CloudTrail, K8s audit logs",
        },
        "AU-3": {
            "name": "Content of Audit Records",
            "description": "Audit records contain required information",
            "relevance": "Log configuration, audit policies",
        },
        "CM-2": {
            "name": "Baseline Configuration",
            "description": "Develop and maintain baseline configurations",
            "relevance": "CloudFormation templates, Helm values",
        },
        "CM-3": {
            "name": "Configuration Change Control",
            "description": "Control changes to system configuration",
            "relevance": "IaC change management, Git commits",
        },
        "CM-8": {
            "name": "System Component Inventory",
            "description": "Maintain inventory of system components",
            "relevance": "Resource tagging, asset tracking",
        },
        "CP-9": {
            "name": "System Backup",
            "description": "Conduct backups of system data and configurations",
            "relevance": "Velero backups, EBS snapshots",
        },
        "CP-10": {
            "name": "System Recovery and Reconstitution",
            "description": "Recover and reconstitute system to known state",
            "relevance": "Disaster recovery, multi-AZ deployment",
        },
        "IA-5": {
            "name": "Authenticator Management",
            "description": "Manage system authenticators",
            "relevance": "Secrets management, credential rotation",
        },
        "SC-7": {
            "name": "Boundary Protection",
            "description": "Monitor and control communications at external boundaries",
            "relevance": "VPC, security groups, NACLs",
        },
        "SC-8": {
            "name": "Transmission Confidentiality",
            "description": "Protect transmitted information confidentiality",
            "relevance": "TLS, mTLS (Istio)",
        },
        "SC-13": {
            "name": "Cryptographic Protection",
            "description": "Implement cryptographic mechanisms",
            "relevance": "Encryption at rest, KMS",
        },
        "SI-4": {
            "name": "System Monitoring",
            "description": "Monitor system for attacks and indicators of compromise",
            "relevance": "Observability stack, alerting",
        },
    }

    def _run(self, control_id: str) -> str:
        """Look up NIST control information."""
        control_id = control_id.upper()

        # Check for exact match or partial match
        info = self.CONTROL_INFO.get(control_id)
        if not info:
            # Try partial match
            for cid, cinfo in self.CONTROL_INFO.items():
                if control_id in cid:
                    info = cinfo
                    control_id = cid
                    break

        if not info:
            available = ", ".join(sorted(self.CONTROL_INFO.keys()))
            return f"Control '{control_id}' not found. Available: {available}"

        # Check for cfn-guard rules
        guard_path = self.project_root / "infra" / "cloudformation" / "cfn-guard-rules" / "nist-800-53"
        rule_files = []
        if guard_path.exists():
            for rule_file in guard_path.glob("*.guard"):
                try:
                    content = rule_file.read_text()
                    if control_id in content:
                        rule_files.append(rule_file.name)
                except Exception:
                    pass

        result = [
            f"**{control_id}: {info['name']}**",
            f"\nDescription: {info['description']}",
            f"\nRelevance: {info['relevance']}",
        ]

        if rule_files:
            result.append(f"\ncfn-guard rules: {', '.join(rule_files)}")

        return "\n".join(result)


def get_planning_tools() -> list[BaseTool]:
    """Get all tools available to the Planning Agent."""
    return [
        FileSearchTool(),
        GrepSearchTool(),
        NamespaceInfoTool(),
        NISTControlTool(),
    ]
