"""IaC Agent - Infrastructure as Code management for CloudFormation and Helm.

The IaC Agent is the second agent in the 4-agent pipeline. It receives
planning output and implements the required infrastructure changes:
- Modifies CloudFormation templates
- Updates Helm values files
- Validates changes with cfn-lint and kube-linter
- Commits changes to git (optional)
- Handles retry loops with feedback from Review Agent
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console

# Console for progress output
_console = Console(stderr=True)

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_aws_settings, get_settings
from infra_agent.core.contracts import (
    ChangeType,
    CodeChange,
    GitBranchConfig,
    GitCommit,
    GitPlatform,
    IaCOutput,
    PlanningOutput,
    PullRequest,
    ReviewOutput,
)
from infra_agent.core.state import AgentType, InfraAgentState, OperationType


class IaCAgent(BaseAgent):
    """
    IaC Agent - Second stage of the 4-agent pipeline.

    Responsibilities:
    - Implement infrastructure changes based on planning output
    - Modify CloudFormation templates and Helm values
    - Validate changes with cfn-lint and kube-linter
    - Create git commits for changes
    - Handle retry loops with Review Agent feedback

    Also supports direct operations (outside pipeline):
    - Validate CloudFormation templates with cfn-lint
    - Check NIST compliance with cfn-guard
    - Create and execute change sets
    - Track stack status and drift
    """

    def __init__(self, **kwargs):
        """Initialize the IaC Agent."""
        super().__init__(agent_type=AgentType.IAC, **kwargs)
        self._cfn_client = None
        self._project_root = Path(__file__).parent.parent.parent.parent.parent
        self._templates_path = self._project_root / "infra" / "cloudformation"
        self._helm_path = self._project_root / "infra" / "helm" / "values"
        self._guard_rules_path = self._templates_path / "cfn-guard-rules" / "nist-800-53"

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

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph as the IaC node.
        Receives planning output and implements infrastructure changes.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with iac_output
        """
        from langchain_core.messages import AIMessage

        planning_output_json = state.get("planning_output")
        if not planning_output_json:
            return {
                "last_error": "No planning output found",
                "messages": [AIMessage(content="**IaC Error:** No planning output found")],
            }

        try:
            planning_output = PlanningOutput.model_validate_json(planning_output_json)
        except Exception as e:
            return {
                "last_error": str(e),
                "messages": [AIMessage(content=f"**IaC Error:** {e}")],
            }

        # Check for review feedback (retry scenario)
        review_notes = ""
        retry_count = state.get("retry_count", 0)
        review_output_json = state.get("review_output")
        if review_output_json:
            try:
                review_output = ReviewOutput.model_validate_json(review_output_json)
                review_notes = review_output.review_notes
            except Exception:
                pass

        # Implement the changes using tools
        iac_output = await self._implement_changes_with_tools(
            planning_output, review_notes, retry_count
        )

        # Format response
        response = self._format_iac_response(iac_output)

        return {
            "iac_output": iac_output.model_dump_json(),
            "retry_count": retry_count,
            "messages": [AIMessage(content=response)],
        }

    async def _implement_changes_with_tools(
        self,
        planning_output: PlanningOutput,
        review_notes: str,
        retry_count: int,
    ) -> IaCOutput:
        """Implement changes using LLM with tools."""
        code_changes: list[CodeChange] = []
        lint_warnings: list[str] = []
        self_lint_passed = True

        total_files = len(planning_output.files_to_modify)
        _console.print(f"\n[bold]IaC Agent: Processing {total_files} file(s)...[/bold]")

        # Build context for tool-based implementation
        context = f"""Planning Output:
Summary: {planning_output.summary}
Requirements: {[r.description for r in planning_output.requirements]}
Files to modify: {[f.path for f in planning_output.files_to_modify]}
{f"Review feedback: {review_notes}" if review_notes else ""}"""

        for idx, file_to_modify in enumerate(planning_output.files_to_modify, 1):
            file_path = self._project_root / file_to_modify.path

            _console.print(f"\n[bold cyan]({idx}/{total_files}) Processing: {file_to_modify.path}[/bold cyan]")

            # Generate the change using LLM with tools
            change_result = await self._generate_file_change_with_tools(
                file_to_modify, planning_output, review_notes
            )

            if change_result:
                code_changes.append(change_result)
                _console.print(f"[dim]  Running validation...[/dim]")

                # Run self-validation
                if file_to_modify.change_type == ChangeType.CLOUDFORMATION:
                    lint_result = self.validate_with_cfn_lint(file_path)
                    if "error" in lint_result.lower():
                        self_lint_passed = False
                        lint_warnings.append(f"{file_to_modify.path}: {lint_result[:200]}")
                        _console.print(f"[red]  Lint failed: {lint_result[:100]}[/red]")
                    else:
                        _console.print(f"[green]  cfn-lint passed[/green]")
                elif file_to_modify.change_type in [ChangeType.HELM, ChangeType.KUBERNETES]:
                    lint_result = self._validate_with_kube_linter(file_path)
                    if "error" in lint_result.lower():
                        self_lint_passed = False
                        lint_warnings.append(f"{file_to_modify.path}: {lint_result[:200]}")
                        _console.print(f"[red]  Lint failed: {lint_result[:100]}[/red]")
                    else:
                        _console.print(f"[green]  kube-linter passed[/green]")
            else:
                _console.print(f"[yellow]  Skipped (no changes generated)[/yellow]")

        return IaCOutput(
            request_id=planning_output.request_id,
            planning_output=planning_output,
            code_changes=code_changes,
            git_commit=None,  # Skip git in pipeline mode
            self_lint_passed=self_lint_passed,
            self_lint_warnings=lint_warnings,
            retry_count=retry_count,
            notes=f"Implemented {len(code_changes)} changes",
        )

    async def _generate_file_change_with_tools(
        self,
        file_to_modify,
        planning_output: PlanningOutput,
        review_notes: str,
    ) -> Optional[CodeChange]:
        """Generate file change using LLM assistance."""
        file_path = self._project_root / file_to_modify.path

        _console.print(f"[dim]  Reading {file_to_modify.path}...[/dim]")

        # Read current file content
        current_content = ""
        if file_path.exists():
            try:
                current_content = file_path.read_text()
            except Exception as e:
                _console.print(f"[yellow]  Warning: Could not read file: {e}[/yellow]")

        # Truncate large files to avoid timeout
        content_for_prompt = current_content[:2000] if len(current_content) > 2000 else current_content
        if len(current_content) > 2000:
            _console.print(f"[dim]  File truncated for prompt ({len(current_content)} -> 2000 chars)[/dim]")

        prompt = f"""Implement this infrastructure change:

Request: {planning_output.summary}
File: {file_to_modify.path}
Change Type: {file_to_modify.change_type.value}
Description: {file_to_modify.description}

Current content:
```
{content_for_prompt if content_for_prompt else "(new file)"}
```

{f"Review feedback: {review_notes}" if review_notes else ""}

Generate ONLY the updated file content. No explanations."""

        def progress_callback(event_type: str, message: str, details: Optional[dict]) -> None:
            """Show progress during LLM invocation."""
            if event_type == "llm_thinking":
                _console.print(f"[dim]  {message}[/dim]")
            elif event_type == "tool_call":
                _console.print(f"[cyan]  > {message}[/cyan]")
            elif event_type == "tool_result":
                _console.print(f"[green]  < {message}[/green]")
            elif event_type == "tool_error":
                _console.print(f"[red]  ! {message}[/red]")

        try:
            _console.print(f"[dim]  Generating changes with LLM...[/dim]")

            # Add timeout to prevent hanging
            response, tool_calls = await asyncio.wait_for(
                self.invoke_with_tools(
                    user_message=prompt,
                    max_iterations=3,
                    progress_callback=progress_callback,
                ),
                timeout=120.0,  # 2 minute timeout
            )

            new_content = self._clean_code_response(response)

            if not new_content or len(new_content) < 10:
                _console.print(f"[yellow]  Warning: LLM returned empty or minimal content[/yellow]")
                return None

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content)

            _console.print(f"[green]  Wrote {len(new_content)} chars to {file_to_modify.path}[/green]")

            return CodeChange(
                file_path=file_to_modify.path,
                change_type=file_to_modify.change_type,
                diff_summary=f"Updated {file_to_modify.description}",
                lines_added=len(new_content.split("\n")),
                lines_removed=len(current_content.split("\n")) if current_content else 0,
            )
        except asyncio.TimeoutError:
            _console.print(f"[red]  Error: LLM timed out after 120s for {file_to_modify.path}[/red]")
            return None
        except Exception as e:
            _console.print(f"[red]  Error generating change: {e}[/red]")
            return None

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process IaC-related operations.

        Handles two modes:
        1. Pipeline mode: Process PlanningOutput and generate IaCOutput
        2. Direct mode: Handle direct user commands (validate, deploy, etc.)

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        # Check if we're in pipeline mode
        if state.is_pipeline_active() and state.current_pipeline_stage == "iac":
            return await self._process_pipeline(state)

        # Direct mode: handle user commands
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

    async def _process_pipeline(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process pipeline mode: implement changes based on PlanningOutput.

        Args:
            state: Current agent state with PlanningOutput

        Returns:
            Updated state with IaCOutput
        """
        # Get planning output
        if not state.planning_output_json:
            error_msg = "No planning output found in state. Planning Agent must run first."
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**IaC Error:** {error_msg}"))
            return state

        try:
            planning_output = PlanningOutput.model_validate_json(state.planning_output_json)
        except Exception as e:
            error_msg = f"Failed to parse planning output: {e}"
            state.last_error = error_msg
            state.messages.append(AIMessage(content=f"**IaC Error:** {error_msg}"))
            return state

        # Check for review feedback (retry scenario)
        review_notes = ""
        retry_count = 0
        if state.review_output_json:
            try:
                review_output = ReviewOutput.model_validate_json(state.review_output_json)
                review_notes = review_output.review_notes
                retry_count = review_output.iac_output.retry_count + 1
            except Exception:
                pass

        # Implement the changes
        iac_output = await self._implement_changes(
            planning_output, state, review_notes, retry_count
        )

        # Store in state
        state.iac_output_json = iac_output.model_dump_json()
        state.advance_pipeline("review")

        # Log action
        self.log_action(
            state=state,
            action="implement_changes",
            success=True,
            resource_type="iac_output",
            resource_id=planning_output.request_id,
            details={
                "changes_count": len(iac_output.code_changes),
                "self_lint_passed": iac_output.self_lint_passed,
                "retry_count": iac_output.retry_count,
            },
        )

        # Create response message
        response = self._format_iac_response(iac_output)
        state.messages.append(AIMessage(content=response))

        return state

    async def _implement_changes(
        self,
        planning_output: PlanningOutput,
        state: InfraAgentState,
        review_notes: str = "",
        retry_count: int = 0,
    ) -> IaCOutput:
        """
        Implement the infrastructure changes specified in planning output.

        Args:
            planning_output: Output from Planning Agent
            state: Current agent state
            review_notes: Feedback from Review Agent (on retry)
            retry_count: Number of retries

        Returns:
            IaCOutput with code changes
        """
        code_changes: list[CodeChange] = []
        lint_warnings: list[str] = []
        self_lint_passed = True

        # Process each file to modify
        for file_to_modify in planning_output.files_to_modify:
            file_path = self._project_root / file_to_modify.path

            # Generate the change using LLM
            change_result = await self._generate_file_change(
                file_to_modify, planning_output, review_notes, state
            )

            if change_result:
                code_changes.append(change_result)

                # Run self-validation
                if file_to_modify.change_type == ChangeType.CLOUDFORMATION:
                    lint_result = self.validate_with_cfn_lint(file_path)
                    if "error" in lint_result.lower():
                        self_lint_passed = False
                        lint_warnings.append(f"{file_to_modify.path}: {lint_result[:200]}")
                elif file_to_modify.change_type in [ChangeType.HELM, ChangeType.KUBERNETES]:
                    lint_result = self._validate_with_kube_linter(file_path)
                    if "error" in lint_result.lower():
                        self_lint_passed = False
                        lint_warnings.append(f"{file_to_modify.path}: {lint_result[:200]}")

        # Create git commit and PR if changes were made
        git_commit = None
        pull_request = None
        if code_changes:
            environment = state.environment.value.lower()
            git_commit, pull_request = await self._create_git_commit(
                planning_output, code_changes, state, environment
            )

        return IaCOutput(
            request_id=planning_output.request_id,
            planning_output=planning_output,
            code_changes=code_changes,
            git_commit=git_commit,
            pull_request=pull_request,
            self_lint_passed=self_lint_passed,
            self_lint_warnings=lint_warnings,
            retry_count=retry_count,
            notes=f"Implemented {len(code_changes)} changes",
        )

    async def _generate_file_change(
        self,
        file_to_modify,
        planning_output: PlanningOutput,
        review_notes: str,
        state: InfraAgentState,
    ) -> Optional[CodeChange]:
        """
        Generate the actual file change using LLM assistance.

        Args:
            file_to_modify: FileToModify from planning output
            planning_output: Full planning output for context
            review_notes: Feedback from review agent
            state: Current agent state

        Returns:
            CodeChange if successful, None otherwise
        """
        file_path = self._project_root / file_to_modify.path

        # Read current file content if it exists
        current_content = ""
        if file_path.exists():
            try:
                current_content = file_path.read_text()
            except Exception:
                pass

        # Build prompt for LLM
        prompt = f"""You are implementing an infrastructure change.

Request: {planning_output.summary}
File: {file_to_modify.path}
Change Type: {file_to_modify.change_type.value}
Description: {file_to_modify.description}

Current file content:
```
{current_content[:3000] if current_content else "(new file)"}
```

{f"Review feedback to address: {review_notes}" if review_notes else ""}

Generate ONLY the updated file content. Do not include any explanation, just the raw file content.
If this is a YAML file, ensure proper indentation.
"""

        try:
            new_content = await self.invoke_llm(prompt, state)

            # Clean up LLM response (remove markdown code blocks if present)
            new_content = self._clean_code_response(new_content)

            # Write the file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content)

            # Calculate diff summary
            lines_added = len(new_content.split("\n"))
            lines_removed = len(current_content.split("\n")) if current_content else 0

            diff_summary = f"Updated {file_to_modify.description}"

            return CodeChange(
                file_path=file_to_modify.path,
                change_type=file_to_modify.change_type,
                diff_summary=diff_summary,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )

        except Exception as e:
            # Log error but continue with other files
            self.log_action(
                state=state,
                action="generate_file_change",
                success=False,
                resource_type="file",
                resource_id=file_to_modify.path,
                details={"error": str(e)[:200]},
            )
            return None

    def _clean_code_response(self, response: str) -> str:
        """Clean up LLM response to extract just the code.

        Handles various markdown formats:
        - ```yaml\ncontent\n```
        - ```\ncontent\n```
        - Content with no fences (raw YAML/JSON)
        - Content with only opening fence (strips it)
        """
        if not response:
            return ""

        # Check if response contains code fences
        has_fence = '```' in response

        if not has_fence:
            # No fences - return as-is (it's raw code)
            return response.strip()

        # Parse line-by-line to extract code from fences
        lines = response.split('\n')
        result_lines = []
        in_code_block = False

        for line in lines:
            stripped = line.strip()

            # Check for opening fence (```yaml, ```json, ```, etc.)
            if stripped.startswith('```') and not in_code_block:
                in_code_block = True
                continue

            # Check for closing fence
            if stripped == '```' and in_code_block:
                # We found the closing fence - we're done with this block
                # If there are more code blocks, we might want to continue
                # For now, break after first complete block
                break

            # Collect lines when inside code block
            if in_code_block:
                result_lines.append(line)

        # Return extracted content if we found any
        if result_lines:
            return '\n'.join(result_lines).strip()

        # Fallback: Strip fences manually if parsing failed
        cleaned = response.strip()

        # Remove opening fence at start
        if cleaned.startswith('```'):
            first_newline = cleaned.find('\n')
            if first_newline > 0:
                cleaned = cleaned[first_newline + 1:]

        # Remove closing fence at end
        if cleaned.rstrip().endswith('```'):
            last_newline = cleaned.rfind('\n```')
            if last_newline > 0:
                cleaned = cleaned[:last_newline]
            elif cleaned.endswith('```'):
                cleaned = cleaned[:-3]

        return cleaned.strip()

    async def _create_git_commit(
        self,
        planning_output: PlanningOutput,
        code_changes: list[CodeChange],
        state: InfraAgentState,
        environment: str = "dev",
    ) -> tuple[Optional[GitCommit], Optional[PullRequest]]:
        """
        Create a git commit with full GitFlow workflow.

        This method:
        1. Creates a feature branch based on environment
        2. Stages and commits changes
        3. Pushes to remote origin
        4. Creates a pull request

        Args:
            planning_output: Planning output for commit message
            code_changes: List of changes made
            state: Current agent state
            environment: Target environment (dev, tst, prd)

        Returns:
            Tuple of (GitCommit info, PullRequest info) - either may be None
        """
        try:
            # Step 1: Get original branch (to return to on failure)
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=10,
            )
            original_branch = result.stdout.strip() if result.returncode == 0 else "main"

            # Step 2: Generate feature branch name
            feature_branch = GitBranchConfig.get_feature_branch_name(
                planning_output.request_id, environment
            )

            # Step 3: Create and checkout feature branch
            result = subprocess.run(
                ["git", "checkout", "-b", feature_branch],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=10,
            )
            if result.returncode != 0:
                # Branch might already exist, try to checkout
                result = subprocess.run(
                    ["git", "checkout", feature_branch],
                    capture_output=True,
                    text=True,
                    cwd=self._project_root,
                    timeout=10,
                )
                if result.returncode != 0:
                    return None, None

            # Step 4: Stage files
            files_to_stage = [change.file_path for change in code_changes]
            for file_path in files_to_stage:
                subprocess.run(
                    ["git", "add", file_path],
                    cwd=self._project_root,
                    capture_output=True,
                    timeout=10,
                )

            # Step 5: Create commit message
            commit_message = f"""feat: {planning_output.summary}

Request ID: {planning_output.request_id}
Environment: {environment.upper()}

Changes:
{chr(10).join(f"- {c.file_path}: {c.diff_summary}" for c in code_changes)}

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
"""

            # Step 6: Commit
            result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=30,
            )

            if result.returncode != 0:
                # Commit might fail if nothing to commit
                # Return to original branch
                subprocess.run(
                    ["git", "checkout", original_branch],
                    cwd=self._project_root,
                    capture_output=True,
                    timeout=10,
                )
                return None, None

            # Step 7: Get commit SHA
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=10,
            )
            commit_sha = result.stdout.strip() if result.returncode == 0 else "unknown"

            # Step 8: Push to remote origin
            pushed = False
            result = subprocess.run(
                ["git", "push", "-u", "origin", feature_branch],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=60,
            )
            if result.returncode == 0:
                pushed = True

            git_commit = GitCommit(
                commit_sha=commit_sha,
                branch=feature_branch,
                message=commit_message[:200],
                files_changed=files_to_stage,
                pushed_to_remote=pushed,
            )

            # Step 9: Create pull request (only if pushed successfully)
            pull_request = None
            if pushed:
                pull_request = await self._create_pull_request(
                    planning_output=planning_output,
                    code_changes=code_changes,
                    source_branch=feature_branch,
                    environment=environment,
                )

            return git_commit, pull_request

        except Exception as e:
            # Git operations are optional, don't fail the pipeline
            return None, None

    async def _create_pull_request(
        self,
        planning_output: PlanningOutput,
        code_changes: list[CodeChange],
        source_branch: str,
        environment: str,
    ) -> Optional[PullRequest]:
        """
        Create a pull/merge request using the configured Git platform.

        Supports both GitHub (gh CLI) and GitLab (glab CLI).

        Args:
            planning_output: Planning output for PR/MR description
            code_changes: List of changes for PR/MR body
            source_branch: Source/head branch
            environment: Target environment (dev, tst, prd)

        Returns:
            PullRequest info if successful, None otherwise
        """
        settings = get_settings()
        platform = GitPlatform(settings.git_platform.lower())

        if platform == GitPlatform.GITLAB:
            return await self._create_gitlab_mr(
                planning_output, code_changes, source_branch, environment
            )
        else:
            return await self._create_github_pr(
                planning_output, code_changes, source_branch, environment
            )

    async def _create_github_pr(
        self,
        planning_output: PlanningOutput,
        code_changes: list[CodeChange],
        source_branch: str,
        environment: str,
    ) -> Optional[PullRequest]:
        """
        Create a pull request using GitHub REST API.

        API: POST /repos/{owner}/{repo}/pulls
        Docs: https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request

        Args:
            planning_output: Planning output for PR description
            code_changes: List of changes for PR body
            source_branch: Source/head branch
            environment: Target environment (dev, tst, prd)

        Returns:
            PullRequest info if successful, None otherwise
        """
        import httpx
        import os

        try:
            settings = get_settings()

            # Get token from environment
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                return None

            # Get org/repo from environment or settings
            org = os.environ.get("GITHUB_ORG", "")
            repo = os.environ.get("GITHUB_REPO", "")
            if not org or not repo:
                return None

            # Get target branch based on environment
            target_branch = GitBranchConfig.get_pr_target_branch(environment)

            # Build PR title and body
            pr_title = f"feat({environment}): {planning_output.summary}"
            pr_body = self._build_pr_body(planning_output, code_changes, environment)

            # GitHub API endpoint
            api_url = f"https://api.github.com/repos/{org}/{repo}/pulls"

            # Create PR via REST API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={
                        "title": pr_title,
                        "body": pr_body,
                        "head": source_branch,
                        "base": target_branch,
                    },
                    timeout=30.0,
                )

                if response.status_code not in [200, 201]:
                    # PR creation failed
                    return None

                data = response.json()

                return PullRequest(
                    number=data.get("number", 0),
                    url=data.get("html_url", ""),
                    title=pr_title,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    status="open",
                    platform=GitPlatform.GITHUB,
                )

        except Exception as e:
            # PR creation is optional, don't fail the pipeline
            return None

    async def _create_gitlab_mr(
        self,
        planning_output: PlanningOutput,
        code_changes: list[CodeChange],
        source_branch: str,
        environment: str,
    ) -> Optional[PullRequest]:
        """
        Create a merge request using GitLab REST API.

        API: POST /projects/{id}/merge_requests
        Docs: https://docs.gitlab.com/ee/api/merge_requests.html#create-mr

        Args:
            planning_output: Planning output for MR description
            code_changes: List of changes for MR body
            source_branch: Source/head branch
            environment: Target environment (dev, tst, prd)

        Returns:
            PullRequest info if successful, None otherwise
        """
        import httpx
        import os
        import urllib.parse

        try:
            settings = get_settings()

            # Get token from environment
            token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
            if not token:
                return None

            # Get GitLab URL (default to gitlab.com)
            gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")

            # Get org/repo (project path)
            org = os.environ.get("GITLAB_ORG") or os.environ.get("GITHUB_ORG", "")
            repo = os.environ.get("GITLAB_REPO") or os.environ.get("GITHUB_REPO", "")
            if not org or not repo:
                return None

            # URL-encode the project path (org/repo)
            project_path = urllib.parse.quote(f"{org}/{repo}", safe="")

            # Get target branch based on environment
            target_branch = GitBranchConfig.get_pr_target_branch(environment)

            # Build MR title and body
            mr_title = f"feat({environment}): {planning_output.summary}"
            mr_body = self._build_pr_body(planning_output, code_changes, environment)

            # GitLab API endpoint
            api_url = f"{gitlab_url}/api/v4/projects/{project_path}/merge_requests"

            # Create MR via REST API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    headers={
                        "PRIVATE-TOKEN": token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "title": mr_title,
                        "description": mr_body,
                        "source_branch": source_branch,
                        "target_branch": target_branch,
                        "remove_source_branch": True,
                    },
                    timeout=30.0,
                )

                if response.status_code not in [200, 201]:
                    # MR creation failed
                    return None

                data = response.json()

                return PullRequest(
                    number=data.get("iid", 0),  # GitLab uses 'iid' for project-level ID
                    url=data.get("web_url", ""),
                    title=mr_title,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    status="open",
                    platform=GitPlatform.GITLAB,
                )

        except Exception as e:
            # MR creation is optional, don't fail the pipeline
            return None

    def _build_pr_body(
        self,
        planning_output: PlanningOutput,
        code_changes: list[CodeChange],
        environment: str,
    ) -> str:
        """Build the PR/MR body content."""
        return f"""## Summary
{planning_output.summary}

## Request ID
`{planning_output.request_id}`

## Environment
**{environment.upper()}**

## Changes
{chr(10).join(f"- `{c.file_path}`: {c.diff_summary}" for c in code_changes)}

## Requirements
{chr(10).join(f"- [{r.id}] {r.description}" for r in planning_output.requirements)}

## Acceptance Criteria
{chr(10).join(f"- [{ac.id}] {ac.description}" for ac in planning_output.acceptance_criteria)}

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
"""

    def _validate_with_kube_linter(self, file_path: Path) -> str:
        """
        Validate Kubernetes/Helm manifest with kube-linter.

        Args:
            file_path: Path to the file

        Returns:
            Validation results
        """
        try:
            result = subprocess.run(
                ["kube-linter", "lint", str(file_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return "OK: kube-linter passed"

            output = result.stdout + result.stderr
            return f"kube-linter issues:\n{output[:500]}"

        except FileNotFoundError:
            return "OK: kube-linter not installed (skipped)"
        except subprocess.TimeoutExpired:
            return "Warning: kube-linter timed out"
        except Exception as e:
            return f"Warning: kube-linter error: {e}"

    def _format_iac_response(self, output: IaCOutput) -> str:
        """Format IaC output as a user-friendly response."""
        lines = [
            f"**IaC Implementation Complete** (Request: {output.request_id})\n",
            f"**Changes Made:** {len(output.code_changes)}",
            f"**Self-Validation:** {'PASSED' if output.self_lint_passed else 'ISSUES FOUND'}",
        ]

        if output.code_changes:
            lines.append("\n**Files Modified:**")
            for change in output.code_changes:
                lines.append(f"  - `{change.file_path}`")
                lines.append(f"    {change.diff_summary}")

        if output.git_commit:
            lines.append(f"\n**Git Commit:** {output.git_commit.commit_sha[:8]}")
            lines.append(f"  Branch: `{output.git_commit.branch}`")
            lines.append(f"  Pushed: {'Yes' if output.git_commit.pushed_to_remote else 'No'}")

        if output.pull_request:
            pr_label = output.pull_request.display_name  # "PR" for GitHub, "MR" for GitLab
            lines.append(f"\n**{pr_label}:** #{output.pull_request.number}")
            lines.append(f"  URL: {output.pull_request.url}")
            lines.append(f"  Target: `{output.pull_request.target_branch}`")

        if output.self_lint_warnings:
            lines.append("\n**Lint Warnings:**")
            for warning in output.self_lint_warnings[:3]:
                lines.append(f"  - {warning[:100]}")

        if output.retry_count > 0:
            lines.append(f"\n**Retry:** Attempt {output.retry_count}")

        lines.append("\n**Next:** Proceeding to Review Agent...")

        return "\n".join(lines)

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
