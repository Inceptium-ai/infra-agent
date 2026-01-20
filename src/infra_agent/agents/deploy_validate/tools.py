"""Tools for the Deploy & Validate Agent.

These tools help the Deploy & Validate Agent execute deployments
and validate acceptance criteria.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class CfnDeployInput(BaseModel):
    """Input for CloudFormation deploy tool."""

    stack_name: str = Field(description="Name of the CloudFormation stack")
    template_path: str = Field(description="Path to CloudFormation template")
    parameters: Optional[str] = Field(
        default=None, description="JSON string of parameters"
    )


class CfnDeployTool(BaseTool):
    """Tool to deploy CloudFormation stacks."""

    name: str = "cfn_deploy"
    description: str = """Deploy a CloudFormation stack using the AWS CLI.
    Creates or updates the stack with the specified template."""
    args_schema: type[BaseModel] = CfnDeployInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(
        self, stack_name: str, template_path: str, parameters: Optional[str] = None
    ) -> str:
        """Execute CloudFormation deployment."""
        full_path = self.project_root / template_path

        if not full_path.exists():
            return f"Template not found: {template_path}"

        cmd = [
            "aws", "cloudformation", "deploy",
            "--template-file", str(full_path),
            "--stack-name", stack_name,
            "--capabilities", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND",
            "--no-fail-on-empty-changeset",
        ]

        if parameters:
            try:
                params = json.loads(parameters)
                param_overrides = " ".join(
                    f"{k}={v}" for k, v in params.items()
                )
                cmd.extend(["--parameter-overrides", param_overrides])
            except json.JSONDecodeError:
                return f"Invalid parameters JSON: {parameters}"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0:
                return f"Stack {stack_name} deployed successfully\n{result.stdout}"
            else:
                return f"Deployment failed:\n{result.stderr}"

        except subprocess.TimeoutExpired:
            return f"Deployment timed out for stack {stack_name}"
        except Exception as e:
            return f"Deployment error: {e}"


class HelmUpgradeInput(BaseModel):
    """Input for Helm upgrade tool."""

    release_name: str = Field(description="Helm release name")
    chart: str = Field(description="Chart name or path")
    namespace: str = Field(description="Kubernetes namespace")
    values_file: Optional[str] = Field(
        default=None, description="Path to values file"
    )
    repo: Optional[str] = Field(
        default=None, description="Helm repository URL"
    )


class HelmUpgradeTool(BaseTool):
    """Tool to upgrade Helm releases."""

    name: str = "helm_upgrade"
    description: str = """Upgrade or install a Helm release.
    Deploys the specified chart with the given values."""
    args_schema: type[BaseModel] = HelmUpgradeInput

    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent.parent)

    def _run(
        self,
        release_name: str,
        chart: str,
        namespace: str,
        values_file: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> str:
        """Execute Helm upgrade."""
        cmd = [
            "helm", "upgrade", "--install",
            release_name, chart,
            "--namespace", namespace,
            "--create-namespace",
            "--wait", "--timeout", "10m",
        ]

        if repo:
            cmd.extend(["--repo", repo])

        if values_file:
            full_path = self.project_root / values_file
            if full_path.exists():
                cmd.extend(["-f", str(full_path)])
            else:
                return f"Values file not found: {values_file}"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=660,
            )

            if result.returncode == 0:
                return f"Release {release_name} deployed successfully\n{result.stdout}"
            else:
                return f"Helm upgrade failed:\n{result.stderr}"

        except subprocess.TimeoutExpired:
            return f"Helm upgrade timed out for release {release_name}"
        except FileNotFoundError:
            return "Helm not installed"
        except Exception as e:
            return f"Helm error: {e}"


class HelmRollbackInput(BaseModel):
    """Input for Helm rollback tool."""

    release_name: str = Field(description="Helm release name")
    revision: int = Field(default=0, description="Revision to rollback to (0 = previous)")


class HelmRollbackTool(BaseTool):
    """Tool to rollback Helm releases."""

    name: str = "helm_rollback"
    description: str = """Rollback a Helm release to a previous revision.
    Use revision 0 for the immediately previous version."""
    args_schema: type[BaseModel] = HelmRollbackInput

    def _run(self, release_name: str, revision: int = 0) -> str:
        """Execute Helm rollback."""
        cmd = ["helm", "rollback", release_name]

        if revision > 0:
            cmd.append(str(revision))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                return f"Release {release_name} rolled back successfully"
            else:
                return f"Rollback failed:\n{result.stderr}"

        except subprocess.TimeoutExpired:
            return f"Rollback timed out for release {release_name}"
        except FileNotFoundError:
            return "Helm not installed"
        except Exception as e:
            return f"Rollback error: {e}"


class KubectlExecInput(BaseModel):
    """Input for kubectl execution tool."""

    command: str = Field(description="kubectl command to execute (without 'kubectl' prefix)")


class KubectlExecTool(BaseTool):
    """Tool to execute kubectl commands."""

    name: str = "kubectl_exec"
    description: str = """Execute a kubectl command.
    Useful for validation, getting resources, checking status, etc.
    Do not include 'kubectl' prefix in the command."""
    args_schema: type[BaseModel] = KubectlExecInput

    def _run(self, command: str) -> str:
        """Execute kubectl command."""
        # Prepend kubectl if not present
        if not command.strip().startswith("kubectl"):
            cmd = f"kubectl {command}"
        else:
            cmd = command

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout if result.stdout else result.stderr
            return output[:2000]  # Limit output size

        except subprocess.TimeoutExpired:
            return "kubectl command timed out"
        except Exception as e:
            return f"kubectl error: {e}"


class ValidateCommandInput(BaseModel):
    """Input for validation command tool."""

    command: str = Field(description="Command to execute for validation")
    expected_result: str = Field(description="Expected output or pattern")


class ValidateCommandTool(BaseTool):
    """Tool to execute validation commands and check results."""

    name: str = "validate_command"
    description: str = """Execute a validation command and compare output with expected result.
    Returns whether the validation passed and the actual vs expected values."""
    args_schema: type[BaseModel] = ValidateCommandInput

    def _run(self, command: str, expected_result: str) -> str:
        """Execute validation and check result."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            actual = result.stdout.strip()

            # Simple comparison
            passed = (
                actual == expected_result
                or expected_result.lower() in actual.lower()
            )

            return json.dumps({
                "passed": passed,
                "actual": actual,
                "expected": expected_result,
                "error": result.stderr[:200] if result.returncode != 0 else None,
            })

        except subprocess.TimeoutExpired:
            return json.dumps({
                "passed": False,
                "actual": "(timeout)",
                "expected": expected_result,
                "error": "Command timed out",
            })
        except Exception as e:
            return json.dumps({
                "passed": False,
                "actual": "(error)",
                "expected": expected_result,
                "error": str(e),
            })


class WaitForConditionInput(BaseModel):
    """Input for wait condition tool."""

    resource_type: str = Field(description="Kubernetes resource type (e.g., deployment, pod)")
    resource_name: str = Field(description="Name of the resource")
    namespace: str = Field(description="Kubernetes namespace")
    condition: str = Field(
        default="available",
        description="Condition to wait for (e.g., available, ready)"
    )
    timeout: int = Field(default=120, description="Timeout in seconds")


class WaitForConditionTool(BaseTool):
    """Tool to wait for a Kubernetes resource condition."""

    name: str = "wait_for_condition"
    description: str = """Wait for a Kubernetes resource to reach a specific condition.
    Commonly used to wait for deployments to be available or pods to be ready."""
    args_schema: type[BaseModel] = WaitForConditionInput

    def _run(
        self,
        resource_type: str,
        resource_name: str,
        namespace: str,
        condition: str = "available",
        timeout: int = 120,
    ) -> str:
        """Wait for condition."""
        cmd = [
            "kubectl", "wait",
            f"--for=condition={condition}",
            f"{resource_type}/{resource_name}",
            "-n", namespace,
            f"--timeout={timeout}s",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
            )

            if result.returncode == 0:
                return f"{resource_type}/{resource_name} is {condition}"
            else:
                return f"Condition not met: {result.stderr}"

        except subprocess.TimeoutExpired:
            return f"Timed out waiting for {resource_type}/{resource_name}"
        except Exception as e:
            return f"Wait error: {e}"


def get_deploy_validate_tools() -> list[BaseTool]:
    """Get all tools available to the Deploy & Validate Agent."""
    return [
        CfnDeployTool(),
        HelmUpgradeTool(),
        HelmRollbackTool(),
        KubectlExecTool(),
        ValidateCommandTool(),
        WaitForConditionTool(),
    ]
