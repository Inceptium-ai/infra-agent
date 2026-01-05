"""IaC Agent - CloudFormation management and NIST compliance validation."""

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_aws_settings, get_settings
from infra_agent.core.state import AgentType, InfraAgentState, OperationType


class IaCAgent(BaseAgent):
    """
    IaC Agent - Manages CloudFormation infrastructure.

    Responsibilities:
    - Validate CloudFormation templates with cfn-lint
    - Check NIST compliance with cfn-guard
    - Create and execute change sets
    - Track stack status and drift
    """

    def __init__(self, **kwargs):
        """Initialize the IaC Agent."""
        super().__init__(agent_type=AgentType.IAC, **kwargs)
        self._cfn_client = None
        self._templates_path = Path(__file__).parent.parent.parent.parent.parent / "infra" / "cloudformation"
        self._guard_rules_path = self._templates_path / "cfn-guard-rules" / "nist-800-53"

    @property
    def cfn_client(self):
        """Get CloudFormation client (lazy initialization)."""
        if self._cfn_client is None:
            import boto3
            aws_settings = get_aws_settings()
            self._cfn_client = boto3.client(
                "cloudformation",
                region_name=aws_settings.aws_region,
                aws_access_key_id=aws_settings.aws_access_key_id,
                aws_secret_access_key=aws_settings.aws_secret_access_key,
            )
        return self._cfn_client

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process IaC-related operations.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content.lower()

        # Route to appropriate handler
        if "validate" in user_input:
            response = await self._handle_validate(user_input, state)
        elif "deploy" in user_input or "create" in user_input:
            response = await self._handle_deploy(user_input, state)
        elif "status" in user_input:
            response = await self._handle_status(user_input, state)
        elif "drift" in user_input:
            response = await self._handle_drift(user_input, state)
        elif "delete" in user_input or "destroy" in user_input:
            response = await self._handle_delete(user_input, state)
        else:
            response = await self.invoke_llm(last_message.content, state)

        state.messages.append(AIMessage(content=response))
        return state

    async def _handle_validate(self, user_input: str, state: InfraAgentState) -> str:
        """Handle template validation requests."""
        settings = get_settings()

        # Determine which template to validate
        template_name = self._extract_template_name(user_input)
        if not template_name:
            return "Please specify which template to validate (e.g., 'validate vpc template')"

        template_path = self._find_template(template_name)
        if not template_path:
            return f"Template '{template_name}' not found in {self._templates_path}"

        results = []

        # Run cfn-lint
        lint_result = self.validate_with_cfn_lint(template_path)
        results.append(f"**cfn-lint validation:**\n{lint_result}")

        # Run cfn-guard
        guard_result = self.validate_with_cfn_guard(template_path)
        results.append(f"**cfn-guard NIST compliance:**\n{guard_result}")

        self.log_action(
            state=state,
            action="validate_template",
            success=True,
            resource_type="cloudformation_template",
            resource_id=str(template_path),
            details={"template": template_name},
        )

        return "\n\n".join(results)

    async def _handle_deploy(self, user_input: str, state: InfraAgentState) -> str:
        """Handle stack deployment requests."""
        settings = get_settings()

        # Check MFA for production
        if settings.is_production and not state.mfa_verified:
            return "Production deployment requires MFA verification. Please verify MFA first."

        template_name = self._extract_template_name(user_input)
        if not template_name:
            return "Please specify which stack to deploy (e.g., 'deploy vpc stack')"

        template_path = self._find_template(template_name)
        if not template_path:
            return f"Template '{template_name}' not found"

        # Validate before deploying
        lint_result = self.validate_with_cfn_lint(template_path)
        if "error" in lint_result.lower():
            return f"Template validation failed:\n{lint_result}\n\nPlease fix errors before deploying."

        guard_result = self.validate_with_cfn_guard(template_path)
        if "fail" in guard_result.lower():
            return f"NIST compliance check failed:\n{guard_result}\n\nPlease fix compliance issues before deploying."

        # Create change set
        stack_name = f"{settings.resource_prefix}-{template_name}"
        change_set_result = self.create_change_set(
            stack_name=stack_name,
            template_path=template_path,
            parameters=self._get_stack_parameters(template_name, state),
        )

        self.log_action(
            state=state,
            action="create_change_set",
            success="error" not in change_set_result.lower(),
            resource_type="cloudformation_stack",
            resource_id=stack_name,
            details={"template": template_name},
        )

        return change_set_result

    async def _handle_status(self, user_input: str, state: InfraAgentState) -> str:
        """Handle stack status requests."""
        settings = get_settings()

        try:
            stacks = self.cfn_client.describe_stacks()
            prefix = settings.resource_prefix

            relevant_stacks = [
                s for s in stacks.get("Stacks", [])
                if s["StackName"].startswith(prefix)
            ]

            if not relevant_stacks:
                return f"No stacks found with prefix '{prefix}'"

            lines = ["**CloudFormation Stack Status:**\n"]
            lines.append(f"{'Stack Name':<45} {'Status':<25} {'Last Updated'}")
            lines.append("-" * 90)

            for stack in relevant_stacks:
                name = stack["StackName"]
                status = stack["StackStatus"]
                updated = stack.get("LastUpdatedTime", stack.get("CreationTime", "N/A"))
                if hasattr(updated, "strftime"):
                    updated = updated.strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"{name:<45} {status:<25} {updated}")

            return "\n".join(lines)

        except Exception as e:
            return f"Error fetching stack status: {str(e)}"

    async def _handle_drift(self, user_input: str, state: InfraAgentState) -> str:
        """Handle drift detection requests."""
        settings = get_settings()
        template_name = self._extract_template_name(user_input)

        if template_name:
            stack_name = f"{settings.resource_prefix}-{template_name}"
        else:
            return "Please specify which stack to check for drift (e.g., 'check drift on vpc stack')"

        try:
            # Initiate drift detection
            response = self.cfn_client.detect_stack_drift(StackName=stack_name)
            drift_id = response["StackDriftDetectionId"]

            self.log_action(
                state=state,
                action="detect_drift",
                success=True,
                resource_type="cloudformation_stack",
                resource_id=stack_name,
                details={"drift_detection_id": drift_id},
            )

            return f"Drift detection initiated for stack '{stack_name}'.\nDetection ID: {drift_id}\n\nRun 'drift status {stack_name}' to check results."

        except Exception as e:
            return f"Error initiating drift detection: {str(e)}"

    async def _handle_delete(self, user_input: str, state: InfraAgentState) -> str:
        """Handle stack deletion requests."""
        settings = get_settings()

        # Check MFA for production
        if settings.is_production and not state.mfa_verified:
            return "Production stack deletion requires MFA verification."

        template_name = self._extract_template_name(user_input)
        if not template_name:
            return "Please specify which stack to delete (e.g., 'delete vpc stack')"

        stack_name = f"{settings.resource_prefix}-{template_name}"

        return f"**WARNING:** You are about to delete stack '{stack_name}'.\n\nThis action is irreversible and will destroy all resources in the stack.\n\nTo confirm, please type: 'confirm delete {stack_name}'"

    def validate_with_cfn_lint(self, template_path: Path) -> str:
        """
        Validate CloudFormation template with cfn-lint.

        Args:
            template_path: Path to the template file

        Returns:
            Validation results
        """
        try:
            result = subprocess.run(
                ["cfn-lint", str(template_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return "✓ Template passed cfn-lint validation (no errors)"
            else:
                output = result.stdout + result.stderr
                return f"Validation issues found:\n{output}"

        except FileNotFoundError:
            return "⚠ cfn-lint not installed. Install with: pip install cfn-lint"
        except subprocess.TimeoutExpired:
            return "⚠ Validation timed out"
        except Exception as e:
            return f"⚠ Validation error: {str(e)}"

    def validate_with_cfn_guard(self, template_path: Path) -> str:
        """
        Validate CloudFormation template with cfn-guard for NIST compliance.

        Args:
            template_path: Path to the template file

        Returns:
            Compliance check results
        """
        if not self._guard_rules_path.exists():
            return "⚠ cfn-guard rules not found"

        try:
            result = subprocess.run(
                [
                    "cfn-guard",
                    "validate",
                    "--data", str(template_path),
                    "--rules", str(self._guard_rules_path),
                    "--output-format", "single-line-summary",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout + result.stderr
            if result.returncode == 0:
                return f"✓ All NIST 800-53 controls passed\n{output}"
            else:
                return f"NIST compliance issues:\n{output}"

        except FileNotFoundError:
            return "⚠ cfn-guard not installed. Install from: https://github.com/aws-cloudformation/cloudformation-guard"
        except subprocess.TimeoutExpired:
            return "⚠ Compliance check timed out"
        except Exception as e:
            return f"⚠ Compliance check error: {str(e)}"

    def create_change_set(
        self,
        stack_name: str,
        template_path: Path,
        parameters: Optional[list[dict]] = None,
    ) -> str:
        """
        Create a CloudFormation change set.

        Args:
            stack_name: Name of the stack
            template_path: Path to the template file
            parameters: Stack parameters

        Returns:
            Change set creation result
        """
        import time
        settings = get_settings()

        try:
            with open(template_path) as f:
                template_body = f.read()

            # Check if stack exists
            try:
                self.cfn_client.describe_stacks(StackName=stack_name)
                change_set_type = "UPDATE"
            except self.cfn_client.exceptions.ClientError:
                change_set_type = "CREATE"

            change_set_name = f"{stack_name}-{int(time.time())}"

            # Create change set
            create_params = {
                "StackName": stack_name,
                "TemplateBody": template_body,
                "ChangeSetName": change_set_name,
                "ChangeSetType": change_set_type,
                "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
                "Tags": [
                    {"Key": "Environment", "Value": settings.environment.value},
                    {"Key": "Owner", "Value": settings.owner},
                    {"Key": "SecurityLevel", "Value": "internal"},
                    {"Key": "IaC_Version", "Value": settings.iac_version},
                    {"Key": "Project", "Value": settings.project_name},
                ],
            }

            if parameters:
                create_params["Parameters"] = parameters

            self.cfn_client.create_change_set(**create_params)

            # Wait for change set to be created
            waiter = self.cfn_client.get_waiter("change_set_create_complete")
            waiter.wait(
                StackName=stack_name,
                ChangeSetName=change_set_name,
                WaiterConfig={"Delay": 5, "MaxAttempts": 60},
            )

            # Describe the change set
            change_set = self.cfn_client.describe_change_set(
                StackName=stack_name,
                ChangeSetName=change_set_name,
            )

            changes = change_set.get("Changes", [])
            if not changes:
                return f"No changes detected for stack '{stack_name}'"

            lines = [f"**Change Set Created:** {change_set_name}\n"]
            lines.append(f"Stack: {stack_name}")
            lines.append(f"Type: {change_set_type}")
            lines.append(f"\n**Changes to be applied:**\n")

            for change in changes:
                rc = change.get("ResourceChange", {})
                action = rc.get("Action", "Unknown")
                resource_type = rc.get("ResourceType", "Unknown")
                logical_id = rc.get("LogicalResourceId", "Unknown")
                lines.append(f"  - {action} {resource_type} ({logical_id})")

            lines.append(f"\nTo execute this change set, run: 'execute changeset {change_set_name}'")

            return "\n".join(lines)

        except Exception as e:
            return f"Error creating change set: {str(e)}"

    def execute_change_set(self, stack_name: str, change_set_name: str) -> str:
        """
        Execute a CloudFormation change set.

        Args:
            stack_name: Name of the stack
            change_set_name: Name of the change set

        Returns:
            Execution result
        """
        try:
            self.cfn_client.execute_change_set(
                StackName=stack_name,
                ChangeSetName=change_set_name,
            )

            return f"Change set '{change_set_name}' is being executed.\n\nRun 'stack status' to monitor progress."

        except Exception as e:
            return f"Error executing change set: {str(e)}"

    def delete_stack(self, stack_name: str) -> str:
        """
        Delete a CloudFormation stack.

        Args:
            stack_name: Name of the stack to delete

        Returns:
            Deletion result
        """
        try:
            self.cfn_client.delete_stack(StackName=stack_name)
            return f"Stack '{stack_name}' deletion initiated.\n\nRun 'stack status' to monitor progress."

        except Exception as e:
            return f"Error deleting stack: {str(e)}"

    def _extract_template_name(self, user_input: str) -> Optional[str]:
        """Extract template name from user input."""
        templates = ["vpc", "security-groups", "iam-roles", "eks-cluster", "node-groups", "addons"]

        for template in templates:
            if template.replace("-", " ") in user_input or template in user_input:
                return template

        # Also check for partial matches
        if "security" in user_input or "sg" in user_input:
            return "security-groups"
        if "iam" in user_input or "role" in user_input:
            return "iam-roles"
        if "eks" in user_input and "cluster" in user_input:
            return "eks-cluster"
        if "node" in user_input:
            return "node-groups"
        if "addon" in user_input:
            return "addons"

        return None

    def _find_template(self, template_name: str) -> Optional[Path]:
        """Find template file by name."""
        template_mapping = {
            "vpc": "stacks/00-foundation/vpc.yaml",
            "security-groups": "stacks/00-foundation/security-groups.yaml",
            "iam-roles": "stacks/00-foundation/iam-roles.yaml",
            "eks-cluster": "stacks/03-eks/cluster.yaml",
            "node-groups": "stacks/03-eks/node-groups.yaml",
            "addons": "stacks/03-eks/addons.yaml",
        }

        relative_path = template_mapping.get(template_name)
        if relative_path:
            full_path = self._templates_path / relative_path
            if full_path.exists():
                return full_path

        return None

    def _get_stack_parameters(
        self, template_name: str, state: InfraAgentState
    ) -> list[dict]:
        """Get parameters for a stack deployment."""
        settings = get_settings()
        aws_settings = get_aws_settings()

        base_params = [
            {"ParameterKey": "ProjectName", "ParameterValue": settings.project_name},
            {"ParameterKey": "Environment", "ParameterValue": settings.environment.value},
            {"ParameterKey": "Owner", "ParameterValue": settings.owner},
            {"ParameterKey": "IaCVersion", "ParameterValue": settings.iac_version},
        ]

        # Add template-specific parameters
        if template_name == "security-groups":
            # VPC ID would come from state or be looked up
            if state.cloudformation_state.get("vpc_id"):
                base_params.append({
                    "ParameterKey": "VpcId",
                    "ParameterValue": state.cloudformation_state["vpc_id"],
                })

        return base_params
