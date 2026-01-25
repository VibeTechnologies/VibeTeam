"""
VibeTeam CLI - Command line interface for the autonomous team.
"""

import asyncio

import click
from rich.console import Console
from rich.table import Table

from vibeteam import __version__
from vibeteam.orchestrator import AgentType, VibeTeam

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """VibeTeam - OpenHands-based autonomous AI team for SaaS development."""
    pass


@main.command()
@click.argument("task")
@click.option(
    "--agent",
    "-a",
    type=click.Choice(["pm", "swe", "marketer", "support", "sre", "release"]),
    help="Specific agent to use (auto-routes if not specified)",
)
@click.option(
    "--model",
    "-m",
    default="openai/gpt-5-mini",
    help="LLM model to use (LiteLLM format)",
)
def run(task: str, agent: str | None, model: str) -> None:
    """Run a task with the team."""
    console.print(f"[bold blue]VibeTeam v{__version__}[/bold blue]")

    team = VibeTeam(model=model)

    if agent:
        result = asyncio.run(team.run_with_agent(agent, task))
    else:
        result = asyncio.run(team.run(task))

    if result.success:
        console.print("\n[bold green]Task completed![/bold green]")
        console.print(f"[cyan]Agent: {result.metadata.get('agent_name', 'Unknown')}[/cyan]")
        console.print("\n" + result.response)
    else:
        console.print(f"\n[bold red]Task failed: {result.error}[/bold red]")


@main.command()
@click.option(
    "--model",
    "-m",
    default="openai/gpt-5-mini",
    help="LLM model to use",
)
def status(model: str) -> None:
    """Show team status."""
    team = VibeTeam(model=model)
    status = team.get_team_status()

    table = Table(title="VibeTeam Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Model")
    table.add_column("Tools", style="yellow")

    for agent_key, info in status.items():
        tools = ", ".join(info["tools"]) if info["tools"] else "None"
        table.add_row(agent_key, info["name"], info["model"], tools)

    console.print(table)


@main.command()
def agents() -> None:
    """List available agents."""
    console.print("\n[bold]Available Agents:[/bold]\n")

    agent_info = {
        "pm": ("Product Manager", "Requirements, roadmap, Langfuse analysis"),
        "swe": ("Software Engineer", "Implementation, testing, Torvalds Protocol"),
        "marketer": ("Marketer", "Social media, content, announcements"),
        "support": ("Support Engineer", "Customer issues, documentation, FAQ"),
        "sre": ("Reliability Engineer", "Monitoring, incidents, Sentry"),
        "release": ("Release Engineer", "Deployments, versioning, changelogs"),
    }

    for key, (name, desc) in agent_info.items():
        console.print(f"  [cyan]{key:10}[/cyan] {name:20} - {desc}")


@main.command()
@click.argument("agent_key", type=click.Choice(["pm", "swe", "marketer", "support", "sre", "release"]))
@click.option(
    "--model",
    "-m",
    default="openai/gpt-5-mini",
    help="LLM model to use",
)
def info(agent_key: str, model: str) -> None:
    """Show detailed info about a specific agent."""
    team = VibeTeam(model=model)
    agent_type = AgentType(agent_key)
    agent = team.get_agent(agent_type)

    if not agent:
        console.print(f"[red]Agent {agent_key} not found[/red]")
        return

    console.print(f"\n[bold cyan]{agent.name}[/bold cyan]")
    console.print(f"[dim]Model: {agent.model}[/dim]\n")

    console.print("[bold]Protocol:[/bold]")
    # Show first 500 chars of protocol
    protocol_preview = agent.protocol[:500] + "..." if len(agent.protocol) > 500 else agent.protocol
    console.print(f"[dim]{protocol_preview}[/dim]\n")

    if agent.tools:
        console.print("[bold]Tools:[/bold]")
        for tool in agent.tools:
            console.print(f"  - [yellow]{tool.name}[/yellow]: {tool.description[:60]}...")


# Legacy command for backwards compatibility
@main.command(name="run-project", hidden=True)
@click.argument("requirement")
@click.option("--rounds", "-n", default=5, help="(Deprecated) Number of rounds")
@click.option("--investment", "-i", default=10.0, help="(Deprecated) Budget")
def run_project(requirement: str, rounds: int, investment: float) -> None:
    """[Deprecated] Use 'run' instead."""
    console.print("[yellow]Warning: run-project is deprecated, use 'run' instead[/yellow]")
    console.print("[dim]--rounds and --investment options are no longer used[/dim]\n")

    team = VibeTeam()
    result = asyncio.run(team.run(requirement))

    if result.success:
        console.print("\n[bold green]Task completed![/bold green]")
        console.print(result.response)
    else:
        console.print(f"\n[bold red]Task failed: {result.error}[/bold red]")


if __name__ == "__main__":
    main()
