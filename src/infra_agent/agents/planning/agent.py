"""Planning Agent - Analyzes requests and generates requirements.

The Planning Agent is the first agent in the 4-agent pipeline. It receives
user requests from the Orchestrator (Chat Agent) and produces:
- Requirements derived from the user request
- Testable acceptance criteria for each requirement
- Identification of files to modify
- Impact assessment and approval requirements
"""

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_settings
from infra_agent.core.contracts import (
    AcceptanceCriteria,
    ChangeType,
    FileToModify,
    PlanningOutput,
    Priority,
    Requirement,
    RequirementType,
    UserRequest,
)
from infra_agent.core.state import AgentType, InfraAgentState
from infra_agent.agents.planning.tools import FileSearchTool


class PlanningAgent(BaseAgent):
    """
    Planning Agent - First stage of the 4-agent pipeline.

    Responsibilities:
    - Analyze user requests for infrastructure changes
    - Generate clear requirements from user intent
    - Create testable acceptance criteria
    - Identify files that need modification
    - Assess impact and determine if approval is required
    """

    def __init__(self, **kwargs):
        """Initialize the Planning Agent."""
        super().__init__(agent_type=AgentType.PLANNING, **kwargs)
        self._project_root = Path(__file__).parent.parent.parent.parent.parent
        self._infra_path = self._project_root / "infra"

        # Register tools for agentic execution
        from infra_agent.agents.planning.tools import get_planning_tools
        self.register_tools(get_planning_tools())

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

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph as the planning node.
        Analyzes the user request and generates requirements + acceptance criteria.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with planning_output
        """
        messages = state.get("messages", [])
        if not messages:
            return {"last_error": "No messages in state"}

        # Find the original user request (first HumanMessage)
        user_input = None
        for msg in messages:
            if hasattr(msg, "content") and isinstance(msg, HumanMessage):
                user_input = msg.content
                break

        if not user_input:
            # Try to get from last message
            last_msg = messages[-1]
            user_input = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        # Generate request ID
        request_id = f"req-{uuid.uuid4().hex[:8]}"

        # Create UserRequest
        settings = get_settings()
        user_request = UserRequest(
            request_id=request_id,
            user_prompt=user_input,
            environment=settings.environment.value,
            operator_id="pipeline",
        )

        try:
            # Use direct LLM analysis (more reliable than invoke_with_tools)
            # First, gather context using tools directly
            context = self._build_analysis_context(user_request, None)

            # Search for relevant files if specific services are mentioned
            tool_context_parts = []
            user_lower = user_input.lower()

            # Check for known services and gather file info
            service_keywords = ["gitlab", "signoz", "istio", "headlamp", "kubecost", "velero", "kiali"]
            for service in service_keywords:
                if service in user_lower:
                    file_search = FileSearchTool()
                    result = file_search._run(service, "yaml")
                    if "Found files" in result:
                        tool_context_parts.append(f"\n{service.upper()} files:\n{result}")

            # Add tool results to context
            if tool_context_parts:
                context += "\n\nDiscovered files:" + "".join(tool_context_parts)

            # Build analysis prompt for direct LLM call
            analysis_prompt = f"""Analyze this infrastructure change request and generate a structured plan with CONTEXT-AWARE validation tests.

User Request: {user_input}
Environment: {user_request.environment}

Context:
{context}

## CRITICAL: Context-Aware Test Generation

You MUST generate acceptance criteria with appropriate tests based on the RESOURCE TYPE being created/modified:

### For Helm Chart Installations (Kubernetes workloads):
- Pod health: `kubectl get pods -n <namespace> -l <label> -o jsonpath='{{.items[*].status.phase}}'` → All "Running"
- Container readiness: `kubectl get pods -n <namespace> -l <label> -o jsonpath='{{.items[*].status.containerStatuses[*].ready}}'` → All "true"
- PVC status (if stateful): `kubectl get pvc -n <namespace> -o jsonpath='{{.items[*].status.phase}}'` → All "Bound"
- Service endpoints: `kubectl get endpoints -n <namespace> <service-name> -o jsonpath='{{.subsets[*].addresses}}'` → Non-empty
- Health endpoint (if exposed): `kubectl exec -n <namespace> <pod> -- curl -s localhost:<port>/health` → 200 or healthy response

### For RDS Database:
- Instance status: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].DBInstanceStatus'` → "available"
- Connectivity test: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].Endpoint.Address'` → Returns endpoint
- Security group: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].VpcSecurityGroups[*].Status'` → All "active"
- Encryption: `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].StorageEncrypted'` → true

### For S3 Bucket:
- Bucket exists: `aws s3api head-bucket --bucket <bucket-name>` → Exit code 0
- Encryption: `aws s3api get-bucket-encryption --bucket <bucket-name>` → Returns encryption config
- Public access block: `aws s3api get-public-access-block --bucket <bucket-name>` → All true
- Versioning: `aws s3api get-bucket-versioning --bucket <bucket-name> --query 'Status'` → "Enabled"

### For EKS Node Group:
- Node status: `kubectl get nodes -l eks.amazonaws.com/nodegroup=<name> -o jsonpath='{{.items[*].status.conditions[-1].type}}'` → "Ready"
- Node count: `kubectl get nodes -l eks.amazonaws.com/nodegroup=<name> --no-headers | wc -l` → Expected count
- ASG health: `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names <asg-name> --query 'AutoScalingGroups[0].Instances[*].HealthStatus'` → All "Healthy"

### For IAM Role/Policy:
- Role exists: `aws iam get-role --role-name <role-name> --query 'Role.RoleName'` → Returns role name
- Policy attached: `aws iam list-attached-role-policies --role-name <role-name> --query 'AttachedPolicies[*].PolicyName'` → Contains expected policies
- Trust relationship: `aws iam get-role --role-name <role-name> --query 'Role.AssumeRolePolicyDocument'` → Correct principal

### For CloudFormation Stack:
- Stack status: `aws cloudformation describe-stacks --stack-name <name> --query 'Stacks[0].StackStatus'` → "CREATE_COMPLETE" or "UPDATE_COMPLETE"
- Outputs exist: `aws cloudformation describe-stacks --stack-name <name> --query 'Stacks[0].Outputs'` → Non-empty
- No drift: `aws cloudformation detect-stack-drift --stack-name <name>` then check status

### For Lambda Function:
- Function exists: `aws lambda get-function --function-name <name> --query 'Configuration.FunctionName'` → Returns name
- State active: `aws lambda get-function --function-name <name> --query 'Configuration.State'` → "Active"
- Can invoke: `aws lambda invoke --function-name <name> --payload '{{}}' /tmp/response.json` → StatusCode 200

## Cost Estimation Guidelines

Estimate monthly cost impact based on:
- **Compute**: EC2/EKS nodes ~$70-150/month per node, Fargate ~$40/vCPU/month
- **Storage**: EBS gp3 ~$0.08/GB/month, S3 ~$0.023/GB/month
- **Database**: RDS db.t3.medium ~$50/month, db.r5.large ~$200/month
- **Network**: NAT Gateway ~$45/month + data, ALB ~$25/month + LCU

Generate a JSON response with the following structure:
{{
    "summary": "1-2 sentence summary of what will be done",
    "resource_types": ["helm", "rds", "s3", "eks", "iam", "cloudformation", "lambda"],
    "requirements": [
        {{
            "id": "REQ-001",
            "description": "What needs to be achieved",
            "type": "functional|non-functional|security|compliance",
            "priority": "low|medium|high|critical",
            "nist_controls": ["CM-3", "CP-10"]
        }}
    ],
    "acceptance_criteria": [
        {{
            "id": "AC-001",
            "requirement_id": "REQ-001",
            "description": "How to verify the requirement is met",
            "test_command": "REAL executable command based on resource type above",
            "expected_result": "specific expected output"
        }}
    ],
    "files_to_modify": [
        {{
            "path": "infra/helm/values/... or infra/cloudformation/stacks/...",
            "change_type": "cloudformation|helm|kubernetes",
            "description": "what change is needed"
        }}
    ],
    "estimated_impact": "low|medium|high",
    "estimated_monthly_cost": 0.00,
    "cost_breakdown": "e.g., '2 pods x $20/month = $40/month'",
    "requires_approval": false,
    "planning_notes": "any additional context for the IaC agent"
}}

Important:
- Generate acceptance criteria with REAL, EXECUTABLE test commands appropriate to the resource type
- Include at least 3-5 acceptance criteria covering: existence, health, configuration, connectivity
- Be specific about file paths (check infra/cloudformation/stacks/ and infra/helm/values/)
- Consider NIST 800-53 controls for security/compliance requirements
- Set requires_approval=true for PRD environment or destructive changes
- Estimate realistic costs based on the guidelines above
"""

            # Direct LLM invocation (more reliable)
            from langchain_core.messages import SystemMessage as SM, HumanMessage as HM

            llm_messages = [
                SM(content=self.system_prompt),
                HM(content=analysis_prompt),
            ]

            response = await self.llm.ainvoke(llm_messages)
            response_text = response.content

            # Extract JSON from response
            planning_data = self._extract_json(response_text)

            # Build PlanningOutput from LLM response
            planning_output = self._build_planning_output(request_id, planning_data)

        except Exception as e:
            # Fallback to basic planning
            planning_output = self._create_fallback_plan(user_request, str(e))

        # Format response
        response_text = self._format_planning_response(planning_output)

        return {
            "planning_output": planning_output.model_dump_json(),
            "messages": [AIMessage(content=response_text)],
        }

    async def _generate_structured_plan(
        self, user_request: UserRequest, analysis: str
    ) -> dict:
        """Generate structured plan from analysis text."""
        # Use LLM to structure the analysis
        structure_prompt = f"""Based on this analysis, create a structured JSON plan:

Analysis:
{analysis}

Original Request:
{user_request.user_prompt}

Return JSON with: summary, requirements, acceptance_criteria, files_to_modify, estimated_impact, requires_approval, planning_notes"""

        from langchain_core.messages import SystemMessage, HumanMessage as HM
        messages = [
            SystemMessage(content="You are a planning assistant. Return only valid JSON."),
            HM(content=structure_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json(response.content)

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process a user request and generate planning output.

        Args:
            state: Current agent state with user message

        Returns:
            Updated state with PlanningOutput
        """
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content

        # Create UserRequest
        request_id = state.active_request_id or f"req-{uuid.uuid4().hex[:8]}"
        user_request = UserRequest(
            request_id=request_id,
            user_prompt=user_input,
            environment=state.environment.value,
            operator_id=state.operator_id or "unknown",
        )

        # Generate planning output
        planning_output = await self._generate_planning_output(user_request, state)

        # Store in state
        state.planning_output_json = planning_output.model_dump_json()
        state.advance_pipeline("iac")

        # Save artifacts for audit trail (both chat and pipeline modes)
        try:
            from infra_agent.core.artifacts import get_artifact_manager
            artifact_mgr = get_artifact_manager()
            artifact_mgr.save_planning_output(planning_output)
        except Exception as e:
            # Log but don't fail - artifacts are for audit, not critical path
            import logging
            logging.warning(f"Failed to save planning artifacts: {e}")

        # Log action
        self.log_action(
            state=state,
            action="generate_plan",
            success=True,
            resource_type="planning_output",
            resource_id=request_id,
            details={
                "requirements_count": len(planning_output.requirements),
                "files_to_modify": len(planning_output.files_to_modify),
                "requires_approval": planning_output.requires_approval,
            },
        )

        # Create response message
        response = self._format_planning_response(planning_output)
        state.messages.append(AIMessage(content=response))

        return state

    async def _generate_planning_output(
        self, user_request: UserRequest, state: InfraAgentState
    ) -> PlanningOutput:
        """
        Generate planning output using LLM analysis.

        Args:
            user_request: The user's request
            state: Current agent state

        Returns:
            PlanningOutput with requirements and acceptance criteria
        """
        # Build context for LLM
        context = self._build_analysis_context(user_request, state)

        # Use LLM to analyze the request
        analysis_prompt = f"""Analyze this infrastructure change request and generate a structured plan.

User Request: {user_request.user_prompt}
Environment: {user_request.environment}

Context:
{context}

Generate a JSON response with the following structure:
{{
    "summary": "1-2 sentence summary of what will be done",
    "requirements": [
        {{
            "id": "REQ-001",
            "description": "What needs to be achieved",
            "type": "functional|non-functional|security|compliance",
            "priority": "low|medium|high|critical",
            "nist_controls": ["CM-3", "CP-10"]  // relevant NIST controls
        }}
    ],
    "acceptance_criteria": [
        {{
            "id": "AC-001",
            "requirement_id": "REQ-001",
            "description": "How to verify the requirement is met",
            "test_command": "kubectl or aws command to verify",
            "expected_result": "what the command should return"
        }}
    ],
    "files_to_modify": [
        {{
            "path": "infra/helm/values/...",
            "change_type": "cloudformation|helm|kubernetes",
            "description": "what change is needed"
        }}
    ],
    "estimated_impact": "low|medium|high",
    "requires_approval": false,
    "planning_notes": "any additional context for the IaC agent"
}}

Important:
- Be specific about file paths (check infra/cloudformation/stacks/ and infra/helm/values/)
- Test commands should be executable kubectl or AWS CLI commands
- Consider NIST 800-53 controls for security/compliance requirements
- Set requires_approval=true for PRD environment or destructive changes
"""

        try:
            llm_response = await self.invoke_llm(analysis_prompt, state)

            # Extract JSON from response
            planning_data = self._extract_json(llm_response)

            # Build PlanningOutput from LLM response
            return self._build_planning_output(user_request.request_id, planning_data)

        except Exception as e:
            # Fallback to basic planning if LLM fails
            return self._create_fallback_plan(user_request, str(e))

    def _build_analysis_context(
        self, user_request: UserRequest, state: Optional[InfraAgentState]
    ) -> str:
        """Build context string for LLM analysis."""
        context_parts = []

        # Add cluster context
        settings = get_settings()
        context_parts.append(f"EKS Cluster: {settings.eks_cluster_name}")
        context_parts.append(f"AWS Region: {settings.aws_region}")

        # Add relevant file structure
        context_parts.append("\nRelevant directories:")
        context_parts.append("- CloudFormation: infra/cloudformation/stacks/")
        context_parts.append("- Helm values: infra/helm/values/")

        # Check for known service names in the request
        user_input_lower = user_request.user_prompt.lower()

        service_dirs = {
            "signoz": "infra/helm/values/signoz/",
            "istio": "infra/helm/values/istio/",
            "headlamp": "infra/helm/values/headlamp/",
            "kubecost": "infra/helm/values/kubecost/",
            "velero": "infra/helm/values/velero/",
            "kiali": "infra/helm/values/kiali/",
            "trivy": "infra/helm/values/trivy/",
        }

        for service, path in service_dirs.items():
            if service in user_input_lower:
                service_path = self._infra_path / path.replace("infra/", "")
                if service_path.exists():
                    files = list(service_path.glob("*.yaml"))
                    context_parts.append(f"\n{service.upper()} files found:")
                    for f in files[:5]:  # Limit to 5 files
                        context_parts.append(f"  - {path}{f.name}")

        return "\n".join(context_parts)

    def _extract_json(self, response: str) -> dict:
        """Extract JSON from LLM response."""
        # Try to find JSON block
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "{" in response:
            # Try to extract raw JSON
            start = response.find("{")
            # Find matching closing brace
            depth = 0
            end = start
            for i, char in enumerate(response[start:], start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            json_str = response[start:end]
        else:
            raise ValueError("No JSON found in response")

        return json.loads(json_str)

    def _build_planning_output(self, request_id: str, data: dict) -> PlanningOutput:
        """Build PlanningOutput from parsed LLM response."""
        requirements = []
        for req_data in data.get("requirements", []):
            req_type = req_data.get("type", "functional")
            if req_type not in [t.value for t in RequirementType]:
                req_type = "functional"

            priority = req_data.get("priority", "medium")
            if priority not in [p.value for p in Priority]:
                priority = "medium"

            requirements.append(
                Requirement(
                    id=req_data.get("id", f"REQ-{len(requirements)+1:03d}"),
                    description=req_data.get("description", ""),
                    type=RequirementType(req_type),
                    priority=Priority(priority),
                    nist_controls=req_data.get("nist_controls", []),
                )
            )

        acceptance_criteria = []
        for ac_data in data.get("acceptance_criteria", []):
            acceptance_criteria.append(
                AcceptanceCriteria(
                    id=ac_data.get("id", f"AC-{len(acceptance_criteria)+1:03d}"),
                    requirement_id=ac_data.get("requirement_id", "REQ-001"),
                    description=ac_data.get("description", ""),
                    test_command=ac_data.get("test_command", ""),
                    expected_result=ac_data.get("expected_result", ""),
                )
            )

        files_to_modify = []
        for file_data in data.get("files_to_modify", []):
            change_type = file_data.get("change_type", "helm")
            if change_type not in [ct.value for ct in ChangeType]:
                change_type = "helm"

            files_to_modify.append(
                FileToModify(
                    path=file_data.get("path", ""),
                    change_type=ChangeType(change_type),
                    description=file_data.get("description", ""),
                )
            )

        return PlanningOutput(
            request_id=request_id,
            summary=data.get("summary", "Infrastructure change planned"),
            resource_types=data.get("resource_types", []),
            requirements=requirements,
            acceptance_criteria=acceptance_criteria,
            files_to_modify=files_to_modify,
            estimated_impact=data.get("estimated_impact", "low"),
            estimated_monthly_cost=float(data.get("estimated_monthly_cost", 0.0)),
            cost_breakdown=data.get("cost_breakdown", ""),
            requires_approval=data.get("requires_approval", False),
            planning_notes=data.get("planning_notes", ""),
        )

    def _create_fallback_plan(self, user_request: UserRequest, error: str) -> PlanningOutput:
        """Create a basic plan when LLM analysis fails."""
        return PlanningOutput(
            request_id=user_request.request_id,
            summary=f"Manual planning required: {user_request.user_prompt}",
            requirements=[
                Requirement(
                    id="REQ-001",
                    description=user_request.user_prompt,
                    type=RequirementType.FUNCTIONAL,
                    priority=Priority.MEDIUM,
                    nist_controls=["CM-3"],
                )
            ],
            acceptance_criteria=[
                AcceptanceCriteria(
                    id="AC-001",
                    requirement_id="REQ-001",
                    description="Verify the change was applied",
                    test_command="# Manual verification required",
                    expected_result="Change applied successfully",
                )
            ],
            files_to_modify=[],
            estimated_impact="medium",
            requires_approval=True,
            planning_notes=f"LLM analysis failed ({error}). Manual review required.",
        )

    def _format_planning_response(self, output: PlanningOutput) -> str:
        """Format planning output as a user-friendly response."""
        lines = [
            f"**Planning Complete** (Request: {output.request_id})\n",
            f"**Summary:** {output.summary}\n",
            f"**Impact:** {output.estimated_impact}",
        ]

        if output.requires_approval:
            lines.append("**Status:** Requires approval before proceeding\n")

        if output.requirements:
            lines.append("\n**Requirements:**")
            for req in output.requirements:
                nist = f" (NIST: {', '.join(req.nist_controls)})" if req.nist_controls else ""
                lines.append(f"  - [{req.id}] {req.description}{nist}")

        if output.files_to_modify:
            lines.append("\n**Files to Modify:**")
            for f in output.files_to_modify:
                lines.append(f"  - `{f.path}` ({f.change_type.value})")
                lines.append(f"    {f.description}")

        if output.acceptance_criteria:
            lines.append("\n**Acceptance Criteria:**")
            for ac in output.acceptance_criteria:
                lines.append(f"  - [{ac.id}] {ac.description}")

        if output.planning_notes:
            lines.append(f"\n**Notes:** {output.planning_notes}")

        return "\n".join(lines)

    async def analyze_request(
        self, user_prompt: str, state: InfraAgentState
    ) -> PlanningOutput:
        """
        Public method to analyze a request without full process flow.

        Useful for testing or direct invocation.

        Args:
            user_prompt: The user's request text
            state: Current agent state

        Returns:
            PlanningOutput with analysis results
        """
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        user_request = UserRequest(
            request_id=request_id,
            user_prompt=user_prompt,
            environment=state.environment.value,
            operator_id=state.operator_id or "unknown",
        )
        return await self._generate_planning_output(user_request, state)
