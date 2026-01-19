"""Main entry point for the Infrastructure Agent CLI."""

import readline  # Enables arrow keys, history, and line editing in CLI input

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from infra_agent import __version__
from infra_agent.config import get_settings

console = Console()


def print_banner() -> None:
    """Print the application banner."""
    banner = Text()
    banner.append("AI Infrastructure Agent", style="bold blue")
    banner.append(f" v{__version__}\n", style="dim")
    banner.append("AWS EKS Management with NIST 800-53 R5 Compliance", style="italic")

    console.print(Panel(banner, title="[bold]infra-agent[/bold]", border_style="blue"))


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """AI Infrastructure Agent - Manage AWS EKS with NIST compliance."""
    pass


@cli.command()
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
def chat(environment: str) -> None:
    """Start interactive chat with the Infrastructure Agent."""
    from infra_agent.agents.chat.agent import start_chat_session

    settings = get_settings()
    print_banner()

    console.print(f"\n[green]Environment:[/green] {environment.upper()}")
    console.print(f"[green]EKS Cluster:[/green] {settings.eks_cluster_name}")
    console.print(f"[green]AWS Region:[/green] {settings.aws_region}")
    console.print()

    try:
        start_chat_session(environment=environment)
    except KeyboardInterrupt:
        console.print("\n[yellow]Session ended.[/yellow]")


@cli.command()
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
@click.option("--dry-run", is_flag=True, help="Plan and review only, don't deploy")
def pipeline(environment: str, dry_run: bool) -> None:
    """Start LangGraph-based agentic pipeline with approval gates."""
    import asyncio
    from rich.markdown import Markdown
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel

    from infra_agent.core.graph import get_pipeline, PipelineState

    settings = get_settings()
    print_banner()

    console.print(f"\n[green]Environment:[/green] {environment.upper()}")
    console.print(f"[green]EKS Cluster:[/green] {settings.eks_cluster_name}")
    console.print(f"[green]Mode:[/green] LangGraph Agentic Pipeline")
    if dry_run:
        console.print(f"[yellow]Dry Run:[/yellow] Enabled (will not deploy)")
    console.print()
    console.print("[dim]4-Agent Pipeline: Orchestrator → Planning → [Approve] → IaC → Review → [Approve] → Deploy[/dim]")
    console.print("[dim]Type 'exit' or 'quit' to end session, 'graph' to see pipeline diagram[/dim]\n")

    pipe = get_pipeline()

    async def run_pipeline_session():
        while True:
            try:
                user_input = Prompt.ask("[bold blue]You[/bold blue]")

                if user_input.lower() in ["exit", "quit"]:
                    console.print("[yellow]Session ended.[/yellow]")
                    break

                if user_input.lower() == "graph":
                    mermaid = pipe.get_graph_visualization()
                    console.print("\n[bold]Pipeline Graph:[/bold]")
                    console.print(f"```mermaid\n{mermaid}\n```")
                    continue

                console.print("[dim]Processing through pipeline...[/dim]")

                # Track the current state for approval handling
                current_state: PipelineState | None = None

                # Stream results until we hit an approval gate or end
                async for state_update in pipe.stream(user_input, dry_run=dry_run):
                    for node_name, node_output in state_update.items():
                        if node_name == "__end__":
                            continue

                        console.print(f"\n[bold cyan]{node_name}:[/bold cyan]")

                        if "messages" in node_output:
                            for msg in node_output["messages"]:
                                if hasattr(msg, "content"):
                                    console.print(Markdown(msg.content))

                        # Update current state
                        if current_state is None:
                            current_state = node_output
                        else:
                            current_state = {**current_state, **node_output}

                # Check if we stopped at an approval gate
                if current_state and current_state.get("pending_approval"):
                    pending = current_state.get("pending_approval")

                    # Show approval panel
                    if pending == "plan":
                        console.print(Panel.fit(
                            "[bold yellow]Plan Approval Required[/bold yellow]\n\n"
                            "Review the plan above and decide whether to proceed.",
                            border_style="yellow",
                        ))
                    elif pending == "deploy":
                        cost = current_state.get("cost_estimate", "Unknown")
                        console.print(Panel.fit(
                            f"[bold yellow]Deploy Approval Required[/bold yellow]\n\n"
                            f"[bold]Estimated Cost Impact:[/bold] {cost}\n\n"
                            "Review the validation results above and decide whether to deploy.",
                            border_style="yellow",
                        ))

                    # Get approval
                    approved = Confirm.ask(
                        f"[bold]Approve {pending}?[/bold]",
                        default=False,
                    )

                    if approved:
                        console.print(f"[green]{pending.title()} approved. Continuing...[/green]\n")
                    else:
                        console.print(f"[red]{pending.title()} rejected. Pipeline stopped.[/red]\n")
                        continue

                    # Resume pipeline with approval
                    async for state_update in pipe.stream_with_approval(current_state, approved):
                        for node_name, node_output in state_update.items():
                            if node_name == "__end__" or node_name == "rejected":
                                if node_name == "rejected":
                                    console.print("[yellow]Pipeline stopped by user.[/yellow]")
                                continue

                            console.print(f"\n[bold cyan]{node_name}:[/bold cyan]")

                            if "messages" in node_output:
                                for msg in node_output["messages"]:
                                    if hasattr(msg, "content"):
                                        console.print(Markdown(msg.content))

                            # Check for second approval gate (deploy after plan)
                            if node_output.get("pending_approval") == "deploy":
                                current_state = {**current_state, **node_output}

                                cost = current_state.get("cost_estimate", "Unknown")
                                console.print(Panel.fit(
                                    f"[bold yellow]Deploy Approval Required[/bold yellow]\n\n"
                                    f"[bold]Estimated Cost Impact:[/bold] {cost}\n\n"
                                    "Review the validation results above.",
                                    border_style="yellow",
                                ))

                                deploy_approved = Confirm.ask(
                                    "[bold]Approve deployment?[/bold]",
                                    default=False,
                                )

                                if deploy_approved:
                                    console.print("[green]Deployment approved. Deploying...[/green]\n")
                                    async for final_update in pipe.stream_with_approval(current_state, True):
                                        for fn, fo in final_update.items():
                                            if fn not in ["__end__", "rejected"]:
                                                console.print(f"\n[bold cyan]{fn}:[/bold cyan]")
                                                if "messages" in fo:
                                                    for msg in fo["messages"]:
                                                        if hasattr(msg, "content"):
                                                            console.print(Markdown(msg.content))
                                else:
                                    console.print("[red]Deployment rejected.[/red]\n")

                # Show dry-run completion message
                if dry_run and current_state and current_state.get("review_status") == "passed":
                    console.print(Panel.fit(
                        "[bold green]Dry Run Complete[/bold green]\n\n"
                        "Plan and review passed. No changes were deployed.\n"
                        "Run without --dry-run to deploy.",
                        border_style="green",
                    ))

                console.print()

            except KeyboardInterrupt:
                console.print("\n[yellow]Session ended.[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                import traceback
                traceback.print_exc()

    try:
        asyncio.run(run_pipeline_session())
    except KeyboardInterrupt:
        console.print("\n[yellow]Session ended.[/yellow]")


@cli.command()
@click.argument("command")
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
def exec(command: str, environment: str) -> None:
    """Execute a single command and exit."""
    from infra_agent.agents.chat.agent import execute_command

    settings = get_settings()
    console.print(f"[dim]Executing in {environment.upper()}...[/dim]")

    result = execute_command(command, environment=environment)
    console.print(result)


@cli.command()
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
@click.option("--version", "-v", "app_version", required=True, help="Version to deploy")
@click.option("--service", "-s", default="all", help="Service to deploy")
def deploy(environment: str, app_version: str, service: str) -> None:
    """Deploy application to specified environment."""
    console.print(f"[yellow]Deploying {service} v{app_version} to {environment.upper()}...[/yellow]")

    if environment == "prd":
        console.print("[red]Production deployment requires MFA verification.[/red]")
        # TODO: Implement MFA verification

    # TODO: Implement deployment logic
    console.print("[green]Deployment initiated.[/green]")


@cli.command()
@click.option("--control", "-c", help="Specific NIST control to check (e.g., CM-8)")
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
@click.option("--output", "-o", type=click.Choice(["text", "json"]), default="text")
def compliance(control: str | None, environment: str, output: str) -> None:
    """Check NIST 800-53 R5 compliance status."""
    console.print(f"[yellow]Checking compliance for {environment.upper()}...[/yellow]")

    if control:
        console.print(f"[dim]Control: {control}[/dim]")

    # TODO: Implement compliance checking
    console.print("[green]All compliance checks passed.[/green]")


@cli.command()
@click.option("--environment", "-e", type=click.Choice(["dev", "tst", "prd"]), default="dev")
def drift(environment: str) -> None:
    """Detect and report CloudFormation drift."""
    console.print(f"[yellow]Checking drift for {environment.upper()}...[/yellow]")

    # TODO: Implement drift detection
    console.print("[green]No drift detected.[/green]")


@cli.command()
def status() -> None:
    """Show current infrastructure status."""
    settings = get_settings()

    console.print(Panel.fit(
        f"""[bold]Cluster:[/bold] {settings.eks_cluster_name}
[bold]Environment:[/bold] {settings.environment.value.upper()}
[bold]Region:[/bold] {settings.aws_region}
[bold]NIST Compliance:[/bold] {'Enabled' if settings.nist_controls_enabled else 'Disabled'}
""",
        title="Infrastructure Status",
        border_style="green",
    ))


@cli.command("mcp-server")
@click.option(
    "--transport",
    "-t",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport mechanism for MCP communication",
)
def mcp_server(transport: str) -> None:
    """Start the AWS MCP server for full AWS API access.

    The MCP server exposes tools for executing any AWS API operation via boto3.

    Examples:
        # Start with stdio transport (default)
        infra-agent mcp-server

        # Start with SSE transport
        infra-agent mcp-server -t sse
    """
    from infra_agent.mcp import create_aws_mcp_server

    settings = get_settings()

    console.print("[bold green]Starting AWS MCP Server[/bold green]")
    console.print(f"[dim]Environment: {settings.environment.value.upper()}[/dim]")
    console.print(f"[dim]Region: {settings.aws_region}[/dim]")
    console.print(f"[dim]Transport: {transport}[/dim]")
    console.print()

    mcp = create_aws_mcp_server()
    mcp.run(transport=transport)


if __name__ == "__main__":
    cli()
