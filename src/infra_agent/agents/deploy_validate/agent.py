"""Deploy & Validate Agent - Executes deployments and validates acceptance criteria.

The Deploy & Validate Agent is the fourth and final agent in the 4-agent pipeline.
It receives review-approved changes and:
- Executes CloudFormation deployments
- Runs Helm upgrades
- Validates acceptance criteria
- Performs rollback if validation fails

CRITICAL: This agent MUST verify all deployments via AWS API calls.
Never claim a deployment succeeded without verification.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_settings
from infra_agent.core.contracts import (
    AcceptanceCriteria,
    ChangeType,
    CostEstimate,
    DeploymentAction,
    DeploymentOutput,
    DeploymentStatus,
    ReviewOutput,
    ReviewStatus,
    RollbackInfo,
    ValidationResult,
)
from infra_agent.core.state import AgentType, InfraAgentState

logger = logging.getLogger(__name__)


class DeployValidateAgent(BaseAgent):
    """
    Deploy & Validate Agent - Fourth stage of the 4-agent pipeline.

    Responsibilities:
    - Execute CloudFormation deployments (change sets)
    - Run Helm upgrade commands
    - Validate acceptance criteria after deployment
    - Rollback on validation failure
    - Report deployment status and duration
    """

    def __init__(self, **kwargs):
        """Initialize the Deploy & Validate Agent."""
        super().__init__(agent_type=AgentType.DEPLOY_VALIDATE, **kwargs)
        self._project_root = Path(__file__).parent.parent.parent.parent.parent
        self._helm_path = self._project_root / "infra" / "helm" / "values"

        # Register tools for agentic execution
        from infra_agent.agents.deploy_validate.tools import get_deploy_validate_tools
        self.register_tools(get_deploy_validate_tools())

        # Register MCP tools for AWS and Git access
        self._register_mcp_tools()

    def _register_mcp_tools(self) -> None:
        """Register MCP tools for AWS API and Git repository access."""
        try:
            from infra_agent.mcp.client import get_aws_tools, get_git_tools
            self.register_tools(get_aws_tools())
            self.register_tools(get_git_tools())
        except Exception:
            pass  # MCP tools optional

    def _verify_cloudformation_deployment(self, stack_name: str) -> dict[str, Any]:
        """
        Verify a CloudFormation deployment by querying AWS directly.

        CRITICAL: This method MUST be called after any claimed CloudFormation deployment
        to confirm it actually happened. Never trust LLM-generated deployment outputs.

        Args:
            stack_name: Name of the CloudFormation stack

        Returns:
            Dict with verification results:
            - verified: bool - whether the stack exists and is in expected state
            - stack_status: str - actual stack status from AWS
            - error: str - error message if verification failed
        """
        settings = get_settings()
        try:
            cfn = boto3.client("cloudformation", region_name=settings.aws_region)
            response = cfn.describe_stacks(StackName=stack_name)

            if not response.get("Stacks"):
                return {
                    "verified": False,
                    "stack_status": "NOT_FOUND",
                    "error": f"Stack {stack_name} does not exist in AWS",
                }

            stack = response["Stacks"][0]
            stack_status = stack.get("StackStatus", "UNKNOWN")

            # Check if status indicates successful deployment
            success_statuses = [
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_COMPLETE",  # Previous update failed but stack is stable
            ]

            if stack_status in success_statuses:
                return {
                    "verified": True,
                    "stack_status": stack_status,
                    "stack_id": stack.get("StackId"),
                    "last_updated": str(stack.get("LastUpdatedTime", "N/A")),
                }
            else:
                return {
                    "verified": False,
                    "stack_status": stack_status,
                    "error": f"Stack is in unexpected state: {stack_status}",
                }

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "ValidationError":
                return {
                    "verified": False,
                    "stack_status": "NOT_FOUND",
                    "error": f"Stack {stack_name} does not exist",
                }
            return {
                "verified": False,
                "stack_status": "ERROR",
                "error": f"AWS API error: {e}",
            }
        except Exception as e:
            return {
                "verified": False,
                "stack_status": "ERROR",
                "error": f"Verification failed: {e}",
            }

    def _verify_helm_deployment(self, release_name: str, namespace: str) -> dict[str, Any]:
        """
        Verify a Helm deployment by checking actual K8s resources.

        Args:
            release_name: Name of the Helm release
            namespace: Kubernetes namespace

        Returns:
            Dict with verification results
        """
        try:
            # Check helm release status
            result = subprocess.run(
                ["helm", "status", release_name, "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return {
                    "verified": False,
                    "release_status": "NOT_FOUND",
                    "error": f"Helm release {release_name} not found in namespace {namespace}",
                }

            status_data = json.loads(result.stdout)
            release_status = status_data.get("info", {}).get("status", "unknown")

            if release_status == "deployed":
                return {
                    "verified": True,
                    "release_status": release_status,
                    "revision": status_data.get("version"),
                    "last_deployed": status_data.get("info", {}).get("last_deployed"),
                }
            else:
                return {
                    "verified": False,
                    "release_status": release_status,
                    "error": f"Release is in unexpected state: {release_status}",
                }

        except subprocess.TimeoutExpired:
            return {
                "verified": False,
                "release_status": "TIMEOUT",
                "error": "Helm status check timed out",
            }
        except json.JSONDecodeError:
            return {
                "verified": False,
                "release_status": "ERROR",
                "error": "Failed to parse helm status output",
            }
        except Exception as e:
            return {
                "verified": False,
                "release_status": "ERROR",
                "error": f"Verification failed: {e}",
            }

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph as the deploy/validate node.
        Executes deployments and validates acceptance criteria.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with deployment_output and deployment_status
        """
        review_output_json = state.get("review_output")
        if not review_output_json:
            return {
                "last_error": "No review output found",
                "deployment_status": "failed",
                "messages": [AIMessage(content="**Deploy Error:** No review output found")],
            }

        try:
            review_output = ReviewOutput.model_validate_json(review_output_json)
        except Exception as e:
            return {
                "last_error": str(e),
                "deployment_status": "failed",
                "messages": [AIMessage(content=f"**Deploy Error:** {e}")],
            }

        if review_output.status != ReviewStatus.PASSED:
            return {
                "last_error": "Review did not pass",
                "deployment_status": "failed",
                "messages": [AIMessage(content="**Deploy Error:** Review did not pass")],
            }

        # Execute deployment with tools
        deployment_output = await self._execute_deployment_with_tools(review_output, state)

        # Format response
        response = self._format_deployment_response(deployment_output)

        # Determine retry
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 3)
        new_retry_count = retry_count + 1 if deployment_output.should_retry_iac and retry_count < max_retries else retry_count

        return {
            "deployment_output": deployment_output.model_dump_json(),
            "deployment_status": deployment_output.status.value,
            "retry_count": new_retry_count,
            "messages": [AIMessage(content=response)],
        }

    async def _execute_deployment_with_tools(
        self, review_output: ReviewOutput, state: dict[str, Any]
    ) -> DeploymentOutput:
        """Execute deployment using tools."""
        start_time = time.time()
        deployment_actions: list[DeploymentAction] = []
        validation_results: list[ValidationResult] = []
        rollback_info: Optional[RollbackInfo] = None

        iac_output = review_output.iac_output
        planning_output = iac_output.planning_output

        # Execute deployments
        for change in iac_output.code_changes:
            action_start = time.time()

            if change.change_type == ChangeType.CLOUDFORMATION:
                action = await self._deploy_cloudformation(change.file_path, state)
            elif change.change_type in [ChangeType.HELM, ChangeType.KUBERNETES]:
                action = await self._deploy_helm(change.file_path, state)
            else:
                action = DeploymentAction(
                    action_type="unknown",
                    resource_name=change.file_path,
                    status="skipped",
                    duration_seconds=0,
                    output="Unknown change type",
                )

            action.duration_seconds = time.time() - action_start
            deployment_actions.append(action)

            if action.status == "failed":
                break

        # Check deployment status
        deployment_failed = any(a.status == "failed" for a in deployment_actions)

        if deployment_failed:
            rollback_info = await self._perform_rollback(deployment_actions, state)
            return DeploymentOutput(
                request_id=iac_output.request_id,
                status=DeploymentStatus.ROLLED_BACK if rollback_info and rollback_info.rollback_successful else DeploymentStatus.FAILED,
                deployment_actions=deployment_actions,
                validation_results=[],
                all_validations_passed=False,
                rollback_info=rollback_info,
                summary="Deployment failed",
                deployment_duration_seconds=time.time() - start_time,
                should_retry_iac=True,
                retry_guidance="Review deployment errors and fix IaC code",
            )

        # Run validations
        for ac in planning_output.acceptance_criteria:
            result = await self._validate_acceptance_criteria(ac, state)
            validation_results.append(result)

        all_passed = all(v.passed for v in validation_results)

        if not all_passed:
            rollback_info = await self._perform_rollback(deployment_actions, state)
            failed_validations = [v for v in validation_results if not v.passed]
            retry_guidance = self._generate_retry_guidance(failed_validations)

            return DeploymentOutput(
                request_id=iac_output.request_id,
                status=DeploymentStatus.ROLLED_BACK if rollback_info and rollback_info.rollback_successful else DeploymentStatus.FAILED,
                deployment_actions=deployment_actions,
                validation_results=validation_results,
                all_validations_passed=False,
                rollback_info=rollback_info,
                summary="Validation failed",
                deployment_duration_seconds=time.time() - start_time,
                should_retry_iac=True,
                retry_guidance=retry_guidance,
            )

        return DeploymentOutput(
            request_id=iac_output.request_id,
            status=DeploymentStatus.SUCCESS,
            deployment_actions=deployment_actions,
            validation_results=validation_results,
            all_validations_passed=True,
            summary=f"Successfully deployed: {planning_output.summary}",
            deployment_duration_seconds=time.time() - start_time,
        )

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Execute deployment and validate acceptance criteria.

        Args:
            state: Current agent state with ReviewOutput

        Returns:
            Updated state with DeploymentOutput
        """
        # Get review output from state
        if not state.review_output_json:
            error_msg = "No review output found in state. Review Agent must run first."
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**Deploy Error:** {error_msg}"))
            return state

        try:
            review_output = ReviewOutput.model_validate_json(state.review_output_json)
        except Exception as e:
            error_msg = f"Failed to parse review output: {e}"
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**Deploy Error:** {error_msg}"))
            return state

        # Verify review passed
        if review_output.status != ReviewStatus.PASSED:
            error_msg = "Cannot deploy: Review did not pass"
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**Deploy Error:** {error_msg}"))
            return state

        # Execute deployment and validation
        deployment_output = await self._execute_deployment(review_output, state)

        # Store in state
        state.deployment_output_json = deployment_output.model_dump_json()

        # Save artifacts for audit trail (both chat and pipeline modes)
        try:
            from infra_agent.core.artifacts import get_artifact_manager
            artifact_mgr = get_artifact_manager()
            artifact_mgr.save_deployment_output(deployment_output)
            # Regenerate summary with validation results
            artifact_mgr.generate_summary(deployment_output.request_id)
        except Exception as e:
            # Log but don't fail - artifacts are for audit, not critical path
            import logging
            logging.warning(f"Failed to save deployment artifacts: {e}")

        # Determine final pipeline state
        if deployment_output.status == DeploymentStatus.SUCCESS:
            state.complete_pipeline(success=True)
        elif deployment_output.should_retry_iac:
            # Go back to IaC for fixes
            state.advance_pipeline("iac")
            state.retry_pipeline()
        else:
            state.complete_pipeline(success=False)

        # Log action
        self.log_action(
            state=state,
            action="deploy_and_validate",
            success=deployment_output.status == DeploymentStatus.SUCCESS,
            resource_type="deployment_output",
            resource_id=review_output.request_id,
            details={
                "status": deployment_output.status.value,
                "actions_count": len(deployment_output.deployment_actions),
                "validations_passed": deployment_output.all_validations_passed,
            },
        )

        # Create response message
        response = self._format_deployment_response(deployment_output)
        state.messages.append(AIMessage(content=response))

        return state

    async def _execute_deployment(
        self, review_output: ReviewOutput, state: InfraAgentState
    ) -> DeploymentOutput:
        """
        Execute the deployment and run validation.

        Args:
            review_output: Output from Review Agent
            state: Current agent state

        Returns:
            DeploymentOutput with results
        """
        start_time = time.time()
        deployment_actions: list[DeploymentAction] = []
        validation_results: list[ValidationResult] = []
        rollback_info: Optional[RollbackInfo] = None

        iac_output = review_output.iac_output
        planning_output = iac_output.planning_output

        # Execute deployments for each code change
        for change in iac_output.code_changes:
            action_start = time.time()

            if change.change_type == ChangeType.CLOUDFORMATION:
                action = await self._deploy_cloudformation(change.file_path, state)
            elif change.change_type in [ChangeType.HELM, ChangeType.KUBERNETES]:
                action = await self._deploy_helm(change.file_path, state)
            else:
                action = DeploymentAction(
                    action_type="unknown",
                    resource_name=change.file_path,
                    status="skipped",
                    duration_seconds=0,
                    output="Unknown change type",
                )

            action.duration_seconds = time.time() - action_start
            deployment_actions.append(action)

            # Stop on failure
            if action.status == "failed":
                break

        # Check if any deployment failed
        deployment_failed = any(a.status == "failed" for a in deployment_actions)

        if deployment_failed:
            # Attempt rollback
            rollback_info = await self._perform_rollback(deployment_actions, state)

            return DeploymentOutput(
                request_id=iac_output.request_id,
                status=DeploymentStatus.ROLLED_BACK if rollback_info and rollback_info.rollback_successful else DeploymentStatus.FAILED,
                deployment_actions=deployment_actions,
                validation_results=[],
                all_validations_passed=False,
                rollback_info=rollback_info,
                summary="Deployment failed, rollback attempted" if rollback_info else "Deployment failed",
                deployment_duration_seconds=time.time() - start_time,
                should_retry_iac=True,
                retry_guidance="Review deployment errors and fix the IaC code",
            )

        # Run validation against acceptance criteria
        for ac in planning_output.acceptance_criteria:
            result = await self._validate_acceptance_criteria(ac, state)
            validation_results.append(result)

        all_passed = all(v.passed for v in validation_results)

        if not all_passed:
            # Validation failed - attempt rollback
            rollback_info = await self._perform_rollback(deployment_actions, state)

            # Generate retry guidance
            failed_validations = [v for v in validation_results if not v.passed]
            retry_guidance = self._generate_retry_guidance(failed_validations)

            return DeploymentOutput(
                request_id=iac_output.request_id,
                status=DeploymentStatus.ROLLED_BACK if rollback_info and rollback_info.rollback_successful else DeploymentStatus.FAILED,
                deployment_actions=deployment_actions,
                validation_results=validation_results,
                all_validations_passed=False,
                rollback_info=rollback_info,
                summary="Validation failed after deployment",
                deployment_duration_seconds=time.time() - start_time,
                should_retry_iac=True,
                retry_guidance=retry_guidance,
            )

        # Success!
        return DeploymentOutput(
            request_id=iac_output.request_id,
            status=DeploymentStatus.SUCCESS,
            deployment_actions=deployment_actions,
            validation_results=validation_results,
            all_validations_passed=True,
            summary=f"Successfully deployed and validated: {planning_output.summary}",
            deployment_duration_seconds=time.time() - start_time,
        )

    async def _deploy_cloudformation(
        self, file_path: str, state: InfraAgentState
    ) -> DeploymentAction:
        """Deploy a CloudFormation template."""
        settings = get_settings()
        full_path = self._project_root / file_path

        # Extract stack name from file path
        # e.g., infra/cloudformation/stacks/00-foundation/vpc.yaml -> vpc
        stack_suffix = Path(file_path).stem
        stack_name = f"{settings.resource_prefix}-{stack_suffix}"

        try:
            # Use AWS CLI for deployment
            cmd = [
                "aws", "cloudformation", "deploy",
                "--template-file", str(full_path),
                "--stack-name", stack_name,
                "--capabilities", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND",
                "--no-fail-on-empty-changeset",
                "--region", settings.aws_region,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
            )

            if result.returncode == 0:
                # CRITICAL: Verify deployment via AWS API - never trust CLI output alone
                verification = self._verify_cloudformation_deployment(stack_name)
                if verification["verified"]:
                    return DeploymentAction(
                        action_type="cloudformation_deploy",
                        resource_name=stack_name,
                        status="success",
                        duration_seconds=0,
                        output=f"VERIFIED: Stack {stack_name} is {verification['stack_status']}. "
                               f"Stack ID: {verification.get('stack_id', 'N/A')}",
                    )
                else:
                    # CLI said success but AWS verification failed - this is suspicious
                    logger.error(f"CloudFormation deployment verification failed: {verification}")
                    return DeploymentAction(
                        action_type="cloudformation_deploy",
                        resource_name=stack_name,
                        status="failed",
                        duration_seconds=0,
                        output=f"VERIFICATION FAILED: CLI reported success but AWS verification failed. "
                               f"Status: {verification.get('stack_status')}. Error: {verification.get('error')}",
                    )
            else:
                return DeploymentAction(
                    action_type="cloudformation_deploy",
                    resource_name=stack_name,
                    status="failed",
                    duration_seconds=0,
                    output=result.stderr[:500] if result.stderr else "Deployment failed",
                )

        except subprocess.TimeoutExpired:
            return DeploymentAction(
                action_type="cloudformation_deploy",
                resource_name=stack_name,
                status="failed",
                duration_seconds=0,
                output="Deployment timed out after 10 minutes",
            )
        except Exception as e:
            return DeploymentAction(
                action_type="cloudformation_deploy",
                resource_name=stack_name,
                status="failed",
                duration_seconds=0,
                output=str(e)[:500],
            )

    async def _deploy_helm(
        self, file_path: str, state: InfraAgentState
    ) -> DeploymentAction:
        """Deploy using Helm."""
        full_path = self._project_root / file_path

        # Parse file path to determine release and chart
        # e.g., infra/helm/values/signoz/values.yaml -> release=signoz
        path_parts = Path(file_path).parts
        try:
            values_idx = path_parts.index("values")
            release_name = path_parts[values_idx + 1]
        except (ValueError, IndexError):
            release_name = Path(file_path).stem

        # Determine namespace (usually same as release name for this project)
        namespace = release_name

        # Chart mapping
        chart_map = {
            "signoz": ("signoz", "https://charts.signoz.io"),
            "istio": ("base", "https://istio-release.storage.googleapis.com/charts"),
            "headlamp": ("headlamp", "https://headlamp-k8s.github.io/headlamp"),
            "kubecost": ("cost-analyzer", "https://kubecost.github.io/cost-analyzer"),
            "velero": ("velero", "https://vmware-tanzu.github.io/helm-charts"),
            "kiali": ("kiali-operator", "https://kiali.org/helm-charts"),
            "trivy": ("trivy-operator", "https://aquasecurity.github.io/helm-charts"),
        }

        chart_info = chart_map.get(release_name)
        if not chart_info:
            return DeploymentAction(
                action_type="helm_upgrade",
                resource_name=release_name,
                status="skipped",
                duration_seconds=0,
                output=f"Unknown chart for release: {release_name}",
            )

        chart_name, repo_url = chart_info

        try:
            cmd = [
                "helm", "upgrade", "--install",
                release_name, chart_name,
                "--repo", repo_url,
                "--namespace", namespace,
                "-f", str(full_path),
                "--wait", "--timeout", "10m",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=660,  # 11 minutes
            )

            if result.returncode == 0:
                # CRITICAL: Verify deployment via helm status - never trust CLI output alone
                verification = self._verify_helm_deployment(release_name, namespace)
                if verification["verified"]:
                    return DeploymentAction(
                        action_type="helm_upgrade",
                        resource_name=release_name,
                        status="success",
                        duration_seconds=0,
                        output=f"VERIFIED: Helm release {release_name} is {verification['release_status']}. "
                               f"Revision: {verification.get('revision', 'N/A')}",
                    )
                else:
                    # CLI said success but verification failed - this is suspicious
                    logger.error(f"Helm deployment verification failed: {verification}")
                    return DeploymentAction(
                        action_type="helm_upgrade",
                        resource_name=release_name,
                        status="failed",
                        duration_seconds=0,
                        output=f"VERIFICATION FAILED: CLI reported success but verification failed. "
                               f"Status: {verification.get('release_status')}. Error: {verification.get('error')}",
                    )
            else:
                return DeploymentAction(
                    action_type="helm_upgrade",
                    resource_name=release_name,
                    status="failed",
                    duration_seconds=0,
                    output=result.stderr[:500] if result.stderr else "Helm upgrade failed",
                )

        except subprocess.TimeoutExpired:
            return DeploymentAction(
                action_type="helm_upgrade",
                resource_name=release_name,
                status="failed",
                duration_seconds=0,
                output="Helm upgrade timed out",
            )
        except Exception as e:
            return DeploymentAction(
                action_type="helm_upgrade",
                resource_name=release_name,
                status="failed",
                duration_seconds=0,
                output=str(e)[:500],
            )

    async def _validate_acceptance_criteria(
        self, ac: AcceptanceCriteria, state: InfraAgentState
    ) -> ValidationResult:
        """Validate a single acceptance criterion."""
        try:
            # Execute the test command
            result = subprocess.run(
                ac.test_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            actual_result = result.stdout.strip()

            # Compare with expected result
            passed = self._compare_results(actual_result, ac.expected_result)

            return ValidationResult(
                acceptance_criteria_id=ac.id,
                passed=passed,
                actual_result=actual_result or "(empty)",
                expected_result=ac.expected_result,
                test_command=ac.test_command,
                error_message=result.stderr[:200] if result.returncode != 0 else None,
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                acceptance_criteria_id=ac.id,
                passed=False,
                actual_result="(timeout)",
                expected_result=ac.expected_result,
                test_command=ac.test_command,
                error_message="Test command timed out",
            )
        except Exception as e:
            return ValidationResult(
                acceptance_criteria_id=ac.id,
                passed=False,
                actual_result="(error)",
                expected_result=ac.expected_result,
                test_command=ac.test_command,
                error_message=str(e)[:200],
            )

    def _compare_results(self, actual: str, expected: str) -> bool:
        """Compare actual vs expected results."""
        # Exact match
        if actual == expected:
            return True

        # Numeric comparison
        try:
            actual_num = float(actual)
            expected_num = float(expected)
            return actual_num == expected_num
        except ValueError:
            pass

        # Contains check (for flexible matching)
        if expected.lower() in actual.lower():
            return True

        # "at least" pattern
        if expected.startswith(">="):
            try:
                actual_num = float(actual)
                expected_num = float(expected[2:])
                return actual_num >= expected_num
            except ValueError:
                pass

        return False

    async def _perform_rollback(
        self, actions: list[DeploymentAction], state: InfraAgentState
    ) -> RollbackInfo:
        """Attempt to rollback failed deployments."""
        rollback_details = []

        for action in reversed(actions):
            if action.status == "success":
                # Attempt rollback
                if action.action_type == "cloudformation_deploy":
                    # CloudFormation has automatic rollback on failure
                    rollback_details.append(
                        f"CloudFormation stack {action.resource_name}: automatic rollback"
                    )
                elif action.action_type == "helm_upgrade":
                    # Helm rollback
                    try:
                        result = subprocess.run(
                            ["helm", "rollback", action.resource_name, "1"],
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                        if result.returncode == 0:
                            rollback_details.append(
                                f"Helm release {action.resource_name}: rollback successful"
                            )
                        else:
                            rollback_details.append(
                                f"Helm release {action.resource_name}: rollback failed - {result.stderr[:100]}"
                            )
                    except Exception as e:
                        rollback_details.append(
                            f"Helm release {action.resource_name}: rollback error - {e}"
                        )

        return RollbackInfo(
            rollback_performed=bool(rollback_details),
            rollback_successful=all("failed" not in d and "error" not in d for d in rollback_details),
            rollback_details="\n".join(rollback_details) if rollback_details else "No rollback performed",
        )

    def _generate_retry_guidance(self, failed_validations: list[ValidationResult]) -> str:
        """Generate guidance for IaC agent to fix validation failures."""
        guidance_parts = ["Validation failed. Please address:\n"]

        for v in failed_validations:
            guidance_parts.append(
                f"- [{v.acceptance_criteria_id}] Expected '{v.expected_result}' but got '{v.actual_result}'"
            )
            if v.error_message:
                guidance_parts.append(f"  Error: {v.error_message}")

        return "\n".join(guidance_parts)

    def _format_deployment_response(self, output: DeploymentOutput) -> str:
        """Format deployment output as a user-friendly response."""
        status_emoji = {
            DeploymentStatus.SUCCESS: "SUCCESS",
            DeploymentStatus.FAILED: "FAILED",
            DeploymentStatus.ROLLED_BACK: "ROLLED BACK",
            DeploymentStatus.PENDING: "PENDING",
        }

        lines = [
            f"**Deployment Complete** (Request: {output.request_id})\n",
            f"**Status:** {status_emoji[output.status]}",
            f"**Duration:** {output.deployment_duration_seconds:.1f}s\n",
        ]

        # Deployment actions
        if output.deployment_actions:
            lines.append("**Actions:**")
            for action in output.deployment_actions:
                status_mark = "OK" if action.status == "success" else "FAIL" if action.status == "failed" else "SKIP"
                lines.append(f"  - [{status_mark}] {action.action_type}: {action.resource_name}")
                if action.status == "failed" and action.output:
                    lines.append(f"    Error: {action.output[:100]}")

        # Validation results
        if output.validation_results:
            lines.append("\n**Validations:**")
            for v in output.validation_results:
                status_mark = "PASS" if v.passed else "FAIL"
                lines.append(f"  - [{status_mark}] {v.acceptance_criteria_id}")
                if not v.passed:
                    lines.append(f"    Expected: {v.expected_result}")
                    lines.append(f"    Actual: {v.actual_result}")

        # Rollback info
        if output.rollback_info and output.rollback_info.rollback_performed:
            lines.append("\n**Rollback:**")
            lines.append(f"  Success: {'Yes' if output.rollback_info.rollback_successful else 'No'}")
            lines.append(f"  Details: {output.rollback_info.rollback_details[:200]}")

        # Summary
        lines.append(f"\n**Summary:** {output.summary}")

        # Next steps
        if output.status == DeploymentStatus.SUCCESS:
            lines.append("\n**Pipeline completed successfully!**")
        elif output.should_retry_iac:
            lines.append(f"\n**Next:** Returning to IaC Agent for fixes")
            if output.retry_guidance:
                lines.append(f"Guidance: {output.retry_guidance[:200]}")
        else:
            lines.append("\n**Pipeline stopped.** Manual intervention required.")

        return "\n".join(lines)
