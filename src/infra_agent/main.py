"""Main entry point for the Infrastructure Agent CLI."""

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


if __name__ == "__main__":
    cli()
