"""
VibeTeam CLI - Command line interface for the autonomous team.
"""

import asyncio
from typing import Optional

import click
from rich.console import Console

from vibeteam import VibeTeam, __version__

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """VibeTeam - MetaGPT-based autonomous AI team for SaaS development."""
    pass


@main.command()
@click.argument("requirement")
@click.option(
    "--roles",
    "-r",
    multiple=True,
    help="Roles to include (pm, swe, marketer, support, sre, release)",
)
@click.option("--rounds", "-n", default=5, help="Number of communication rounds")
@click.option("--investment", "-i", default=10.0, help="Budget for LLM calls")
def run(
    requirement: str,
    roles: tuple[str, ...],
    rounds: int,
    investment: float,
) -> None:
    """Run the team on a requirement."""
    console.print(f"[bold blue]VibeTeam v{__version__}[/bold blue]")
    
    include_roles = list(roles) if roles else None
    team = VibeTeam(investment=investment, include_roles=include_roles)
    
    result = asyncio.run(team.run_project(requirement, n_round=rounds))
    console.print("\n[bold green]Project completed![/bold green]")
    console.print(result)


@main.command()
@click.option(
    "--roles",
    "-r",
    multiple=True,
    help="Roles to include",
)
def status(roles: tuple[str, ...]) -> None:
    """Show team status."""
    include_roles = list(roles) if roles else None
    team = VibeTeam(include_roles=include_roles)
    
    status = team.get_team_status()
    console.print("\n[bold]Team Status:[/bold]")
    for profile, info in status.items():
        console.print(f"\n[cyan]{profile}[/cyan] ({info['name']})")
        console.print(f"  Goal: {info['goal']}")
        console.print(f"  Actions: {', '.join(info['actions'])}")


@main.command()
def roles() -> None:
    """List available roles."""
    console.print("\n[bold]Available Roles:[/bold]\n")
    
    role_info = {
        "pm": ("Product Manager", "Requirements, roadmap, user stories"),
        "swe": ("Software Engineer", "Implementation, testing, code review"),
        "marketer": ("Marketer", "Content, social media, announcements"),
        "support": ("Support Engineer", "User issues, documentation, FAQ"),
        "sre": ("Reliability Engineer", "Production health, incidents, runbooks"),
        "release": ("Release Engineer", "Deployments, versioning, releases"),
    }
    
    for key, (name, desc) in role_info.items():
        console.print(f"  [cyan]{key:10}[/cyan] {name:20} - {desc}")


if __name__ == "__main__":
    main()
