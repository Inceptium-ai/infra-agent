"""Tools for the Review Agent.

These tools help the Review Agent validate IaC changes against
compliance rules, security policies, and best practices.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class CfnLintInput(BaseModel):
    """Input for cfn-lint tool."""

    file_path: str = Field(description="Path to CloudFormation template")


class CfnLintTool(BaseTool):
    """Tool to run cfn-lint on CloudFormation templates."""

    name: str = "cfn_lint"
    description: str = """Run cfn-lint to validate CloudFormation template syntax and best practices.
    Returns a list of errors, warnings, and informational messages."""
    args_schema: type[BaseModel] = CfnLintInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, file_path: str) -> str:
        """Execute cfn-lint."""
        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"File not found: {file_path}"

        try:
            result = subprocess.run(
                ["cfn-lint", str(full_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return "cfn-lint: All checks passed"

            output = result.stdout + result.stderr
            return f"cfn-lint results:\n{output}"

        except FileNotFoundError:
            return "cfn-lint not installed. Install with: pip install cfn-lint"
        except subprocess.TimeoutExpired:
            return "cfn-lint timed out"
        except Exception as e:
            return f"cfn-lint error: {e}"


class CfnGuardInput(BaseModel):
    """Input for cfn-guard tool."""

    file_path: str = Field(description="Path to CloudFormation template")
    rules_path: Optional[str] = Field(
        default=None, description="Path to cfn-guard rules (defaults to NIST rules)"
    )


class CfnGuardTool(BaseTool):
    """Tool to run cfn-guard for NIST 800-53 compliance."""

    name: str = "cfn_guard"
    description: str = """Run cfn-guard to check CloudFormation template for NIST 800-53 compliance.
    Returns compliance violations and remediation guidance."""
    args_schema: type[BaseModel] = CfnGuardInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, file_path: str, rules_path: Optional[str] = None) -> str:
        """Execute cfn-guard."""
        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"File not found: {file_path}"

        # Default to NIST rules
        if rules_path:
            rules_full_path = self.project_root / rules_path
        else:
            rules_full_path = self.project_root / "infra/cloudformation/cfn-guard-rules/nist-800-53"

        if not rules_full_path.exists():
            return f"Rules not found: {rules_full_path}"

        try:
            result = subprocess.run(
                [
                    "cfn-guard",
                    "validate",
                    "--data", str(full_path),
                    "--rules", str(rules_full_path),
                    "--show-summary", "all",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout + result.stderr
            if result.returncode == 0:
                return f"cfn-guard: All NIST controls passed\n{output}"

            return f"cfn-guard NIST compliance results:\n{output}"

        except FileNotFoundError:
            return "cfn-guard not installed. Install from: https://github.com/aws-cloudformation/cloudformation-guard"
        except subprocess.TimeoutExpired:
            return "cfn-guard timed out"
        except Exception as e:
            return f"cfn-guard error: {e}"


class KubeLinterInput(BaseModel):
    """Input for kube-linter tool."""

    file_path: str = Field(description="Path to Kubernetes manifest or Helm values")


class KubeLinterTool(BaseTool):
    """Tool to run kube-linter on Kubernetes manifests."""

    name: str = "kube_linter"
    description: str = """Run kube-linter to check Kubernetes manifests for security best practices.
    Checks for issues like running as root, missing resource limits, etc."""
    args_schema: type[BaseModel] = KubeLinterInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, file_path: str) -> str:
        """Execute kube-linter."""
        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"File not found: {file_path}"

        try:
            result = subprocess.run(
                ["kube-linter", "lint", str(full_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return "kube-linter: All checks passed"

            output = result.stdout + result.stderr
            return f"kube-linter results:\n{output}"

        except FileNotFoundError:
            return "kube-linter not installed. Install from: https://github.com/stackrox/kube-linter"
        except subprocess.TimeoutExpired:
            return "kube-linter timed out"
        except Exception as e:
            return f"kube-linter error: {e}"


class KubeconformInput(BaseModel):
    """Input for kubeconform tool."""

    file_path: str = Field(description="Path to Kubernetes manifest")


class KubeconformTool(BaseTool):
    """Tool to validate Kubernetes manifests against schemas."""

    name: str = "kubeconform"
    description: str = """Run kubeconform to validate Kubernetes manifests against API schemas.
    Checks that manifests conform to the Kubernetes API specification."""
    args_schema: type[BaseModel] = KubeconformInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(self, file_path: str) -> str:
        """Execute kubeconform."""
        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"File not found: {file_path}"

        try:
            result = subprocess.run(
                ["kubeconform", "-summary", str(full_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return f"kubeconform: Valid\n{result.stdout}"

            output = result.stdout + result.stderr
            return f"kubeconform results:\n{output}"

        except FileNotFoundError:
            return "kubeconform not installed. Install from: https://github.com/yannh/kubeconform"
        except subprocess.TimeoutExpired:
            return "kubeconform timed out"
        except Exception as e:
            return f"kubeconform error: {e}"


class SecretsScanInput(BaseModel):
    """Input for secrets scan tool."""

    file_path: str = Field(description="Path to file to scan")


class SecretsScanTool(BaseTool):
    """Tool to scan files for potential secrets or sensitive data."""

    name: str = "secrets_scan"
    description: str = """Scan a file for potential secrets, API keys, passwords, or other sensitive data.
    Returns any potential issues found."""
    args_schema: type[BaseModel] = SecretsScanInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    # Patterns to look for
    PATTERNS: list[tuple[str, str]] = [
        ("password:", "Potential hardcoded password"),
        ("password=", "Potential hardcoded password"),
        ("secret:", "Potential hardcoded secret"),
        ("api_key:", "Potential hardcoded API key"),
        ("apikey:", "Potential hardcoded API key"),
        ("access_key:", "Potential hardcoded access key"),
        ("accesskey:", "Potential hardcoded access key"),
        ("private_key:", "Potential hardcoded private key"),
        ("BEGIN RSA PRIVATE KEY", "Embedded private key"),
        ("BEGIN PRIVATE KEY", "Embedded private key"),
        ("BEGIN EC PRIVATE KEY", "Embedded EC private key"),
        ("AKIA", "Potential AWS access key"),
    ]

    def _run(self, file_path: str) -> str:
        """Scan file for secrets."""
        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"File not found: {file_path}"

        try:
            content = full_path.read_text()
            findings = []

            for pattern, description in self.PATTERNS:
                if pattern.lower() in content.lower():
                    # Find line number
                    for i, line in enumerate(content.split("\n"), 1):
                        if pattern.lower() in line.lower():
                            # Skip if it's a reference (secretRef, etc.)
                            if "ref" in line.lower() and "secret" in line.lower():
                                continue
                            findings.append(f"Line {i}: {description}")

            if findings:
                return "Potential secrets found:\n" + "\n".join(findings)

            return "No secrets detected"

        except Exception as e:
            return f"Scan error: {e}"


class CostEstimateInput(BaseModel):
    """Input for cost estimation tool."""

    change_description: str = Field(description="Description of the infrastructure change")
    resource_type: str = Field(description="Type of resource: ec2, eks, rds, s3, etc.")


class CostEstimateTool(BaseTool):
    """Tool to estimate cost impact of infrastructure changes."""

    name: str = "cost_estimate"
    description: str = """Estimate the monthly cost impact of an infrastructure change.
    Provides rough estimates based on AWS pricing."""
    args_schema: type[BaseModel] = CostEstimateInput

    # Rough monthly cost estimates per unit
    COST_ESTIMATES: dict[str, float] = {
        "replica": 50.0,  # Per additional replica (compute + memory)
        "ec2_small": 30.0,  # t3.small
        "ec2_medium": 60.0,  # t3.medium
        "ec2_large": 120.0,  # t3.large
        "eks_node_small": 100.0,  # EKS node (t3.medium)
        "eks_node_large": 200.0,  # EKS node (t3.large)
        "rds_small": 50.0,  # db.t3.small
        "rds_medium": 100.0,  # db.t3.medium
        "ebs_gb": 0.10,  # Per GB-month
        "s3_gb": 0.023,  # Per GB-month
        "nat_gateway": 45.0,  # Per NAT gateway
        "alb": 25.0,  # Per ALB
    }

    def _run(self, change_description: str, resource_type: str) -> str:
        """Estimate cost."""
        desc_lower = change_description.lower()
        resource_lower = resource_type.lower()

        estimates = []

        # Check for common patterns
        if "replica" in desc_lower:
            import re
            numbers = re.findall(r'\d+', change_description)
            if len(numbers) >= 1:
                replicas = int(numbers[-1])
                cost = replicas * self.COST_ESTIMATES["replica"]
                estimates.append(f"{replicas} replicas: ~${cost:.2f}/month")

        if "node" in resource_lower or "eks" in resource_lower:
            cost = self.COST_ESTIMATES["eks_node_small"]
            estimates.append(f"EKS node: ~${cost:.2f}/month")

        if "storage" in desc_lower or "volume" in desc_lower or "ebs" in resource_lower:
            import re
            numbers = re.findall(r'\d+', change_description)
            if numbers:
                gb = int(numbers[0])
                cost = gb * self.COST_ESTIMATES["ebs_gb"]
                estimates.append(f"{gb}GB EBS: ~${cost:.2f}/month")

        if "rds" in resource_lower:
            cost = self.COST_ESTIMATES["rds_small"]
            estimates.append(f"RDS instance: ~${cost:.2f}/month")

        if "alb" in resource_lower or "load balancer" in desc_lower:
            cost = self.COST_ESTIMATES["alb"]
            estimates.append(f"ALB: ~${cost:.2f}/month")

        if "nat" in resource_lower:
            cost = self.COST_ESTIMATES["nat_gateway"]
            estimates.append(f"NAT Gateway: ~${cost:.2f}/month")

        if estimates:
            return "Cost estimates:\n" + "\n".join(estimates)

        return "Unable to estimate costs for this change type"


def get_review_tools() -> list[BaseTool]:
    """Get all tools available to the Review Agent."""
    return [
        CfnLintTool(),
        CfnGuardTool(),
        KubeLinterTool(),
        KubeconformTool(),
        SecretsScanTool(),
        CostEstimateTool(),
    ]
