"""
VibeTeam CLI - Command line interface for the autonomous team.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import click
from rich.console import Console
from rich.table import Table

from vibeteam import __version__
from vibeteam.orchestrator import AgentType, VibeTeam

console = Console()
logger = logging.getLogger(__name__)


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
    default="azure/gpt-4.1",
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
        sys.exit(1)


@main.command()
@click.option(
    "--model",
    "-m",
    default="azure/gpt-4.1",
    help="LLM model to use",
)
def status(model: str) -> None:
    """Show team status."""
    team = VibeTeam(model=model)
    team_status = team.get_team_status()

    table = Table(title="VibeTeam Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Model")
    table.add_column("Tools", style="yellow")

    for agent_key, info in team_status.items():
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
@click.argument(
    "agent_key", type=click.Choice(["pm", "swe", "marketer", "support", "sre", "release"])
)
@click.option(
    "--model",
    "-m",
    default="azure/gpt-4.1",
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
    console.print(f"[dim]Profile: {agent.profile}[/dim]")
    console.print(f"[dim]Model: {agent.model}[/dim]")
    console.print(f"[dim]Goal: {agent.goal}[/dim]\n")

    if agent.tools:
        console.print("[bold]Tools:[/bold]")
        for tool in agent.tools:
            console.print(f"  - [yellow]{tool.name}[/yellow]: {tool.description[:60]}...")


# =============================================================================
# Scheduled Task Commands (for k8s CronJobs)
# =============================================================================


@main.group()
def scheduled() -> None:
    """Scheduled task commands for k8s CronJobs."""
    pass


@scheduled.command(name="pm-analyze")
@click.option("--hours", default=2, help="Hours of conversations to analyze")
@click.option("--dry-run", is_flag=True, help="Don't create GitHub issues")
def pm_analyze(hours: int, dry_run: bool) -> None:
    """Product Manager: Analyze Langfuse conversations for feature requests."""
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    langfuse_public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.environ.get("LANGFUSE_SECRET_KEY")
    langfuse_url = os.environ.get("LANGFUSE_BASE_URL", "https://langfuse.vibebrowser.app")
    gh_token = os.environ.get("GITHUB_TOKEN")

    if not langfuse_public or not langfuse_secret:
        console.print("[red]LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY required[/red]")
        sys.exit(1)

    console.print("[bold]Product Manager - Langfuse Analysis[/bold]")
    console.print(f"Analyzing last {hours} hours of conversations...")

    # Fetch conversations
    url = f"{langfuse_url}/api/public/traces"
    from_time = datetime.utcnow() - timedelta(hours=hours)
    params = {
        "limit": 100,
        "orderBy": "timestamp.desc",
        "fromTimestamp": from_time.isoformat() + "Z",
        "name": "support-chat",
    }

    try:
        resp = requests.get(
            url, auth=(langfuse_public, langfuse_secret), params=params, timeout=30  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        traces = resp.json().get("data", [])
        console.print(f"Found {len(traces)} conversations")

        # Feature request patterns
        feature_patterns = [
            "can you add",
            "would be nice if",
            "feature request",
            "i wish",
            "please add",
            "need a way to",
            "any plans to",
            "does vibe support",
        ]

        feature_requests = []
        for trace in traces:
            input_text = str(trace.get("input", "")).lower()
            if any(p in input_text for p in feature_patterns):
                feature_requests.append(
                    {
                        "id": trace.get("id"),
                        "text": input_text[:200],
                        "timestamp": trace.get("timestamp"),
                    }
                )

        console.print(f"Found {len(feature_requests)} potential feature requests")

        if feature_requests and gh_token and not dry_run:
            # Update GitHub tracking issue
            console.print("[dim]Updating GitHub tracking issue...[/dim]")
            # Implementation would go here

        console.print("[green]Analysis complete[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@scheduled.command(name="support-emails")
@click.option("--max-emails", default=20, help="Maximum emails to process")
@click.option("--dry-run", is_flag=True, help="Don't send responses")
def support_emails(max_emails: int, dry_run: bool) -> None:
    """Support Engineer: Process support emails from Gmail."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    console.print("[bold]Support Engineer - Email Processing[/bold]")
    console.print(f"Processing up to {max_emails} emails...")

    try:
        from pathlib import Path

        from vibeteam.agents.support_engineer import SupportEngineerAgent
        from vibeteam.connectors.gmail import GmailConnector

        creds_path = Path(
            os.environ.get("GMAIL_CREDENTIALS_PATH", "/secrets/gmail-credentials.json")
        )
        token_path = Path(os.environ.get("GMAIL_TOKEN_PATH", "/secrets/gmail-token.json"))

        if not creds_path.exists():
            console.print(f"[red]Credentials not found: {creds_path}[/red]")
            sys.exit(1)

        gmail = GmailConnector(credentials_path=creds_path, token_path=token_path)
        gmail.authenticate(headless=True)

        emails = gmail.fetch_unread_emails(max_results=max_emails)
        console.print(f"Found {len(emails)} unread emails")

        # Initialize support agent
        support_agent = SupportEngineerAgent()

        processed = 0
        for email in emails:
            # Filter for support emails
            if "[Docs Support" not in email.subject:
                continue

            console.print(f"  Processing: {email.subject[:50]}...")

            # Format email for agent
            email_content = f"""From: {email.sender}
Subject: {email.subject}
Date: {email.date}

{email.body}"""

            # Analyze email
            analysis = asyncio.run(support_agent.analyze_email(email_content))
            console.print(f"    Analysis: {analysis[:100]}...")

            # Check if escalation needed
            if "ESCALATE: Yes" in analysis or "escalat" in analysis.lower():
                console.print("    [yellow]Flagged for escalation[/yellow]")
                escalation = asyncio.run(support_agent.flag_for_escalation(email_content, analysis))
                console.print("    Escalation ticket created")
                # Mark as read but don't respond
                if not dry_run:
                    gmail.mark_as_read(email.id)
                processed += 1
                continue

            # Generate response
            response_text = asyncio.run(support_agent.write_response(email_content, analysis))

            # Validate response security
            validation = asyncio.run(support_agent.validate_response_security(response_text))
            if "VALIDATION: FAIL" in validation:
                console.print("    [red]Response failed security validation[/red]")
                continue

            # Send response
            if not dry_run:
                # Extract just the response body (skip metadata)
                response_body = response_text
                if "---" in response_text:
                    response_body = response_text.split("---")[-1].strip()

                gmail.send_reply(
                    thread_id=email.thread_id,
                    to=email.sender_email,
                    subject=f"Re: {email.subject}",
                    body=response_body,
                )
                gmail.mark_as_read(email.id)
                console.print("    [green]Response sent[/green]")
            else:
                console.print("    [dim]Dry run - response not sent[/dim]")

            processed += 1
            support_agent.reset()  # Clear conversation for next email

        console.print(f"[green]Processed {processed} support emails[/green]")

    except ImportError as e:
        console.print(f"[yellow]Import error: {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@scheduled.command(name="sre-health")
@click.option("--endpoints", "-e", multiple=True, help="Endpoints to check")
def sre_health(endpoints: tuple) -> None:
    """Reliability Engineer: Run health checks on endpoints."""
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    console.print("[bold]Reliability Engineer - Health Checks[/bold]")

    default_endpoints = [
        "https://api.vibebrowser.app/health",
        "https://portal.vibebrowser.app",
        "https://docs.vibebrowser.app",
    ]

    check_endpoints = list(endpoints) if endpoints else default_endpoints
    console.print(f"Checking {len(check_endpoints)} endpoints...")

    results = []
    for endpoint in check_endpoints:
        try:
            resp = requests.get(endpoint, timeout=10)
            status = "OK" if resp.status_code == 200 else f"ERROR ({resp.status_code})"
            results.append((endpoint, status, resp.elapsed.total_seconds()))
            console.print(f"  {status}: {endpoint} ({resp.elapsed.total_seconds():.2f}s)")
        except Exception as e:
            results.append((endpoint, f"FAIL: {e}", 0))
            console.print(f"  [red]FAIL: {endpoint} - {e}[/red]")

    failed = sum(1 for _, s, _ in results if not s.startswith("OK"))
    if failed > 0:
        console.print(f"[red]{failed} endpoints failed[/red]")
        sys.exit(1)
    else:
        console.print(f"[green]All {len(results)} endpoints healthy[/green]")


@scheduled.command(name="release-check")
def release_check() -> None:
    """Release Engineer: Check for pending releases."""
    import subprocess

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    console.print("[bold]Release Engineer - Release Check[/bold]")

    gh_token = os.environ.get("GITHUB_TOKEN")
    if not gh_token:
        console.print("[red]GITHUB_TOKEN required[/red]")
        sys.exit(1)

    # Check for merged PRs since last release
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                "VibeTechnologies/VibeWebAgent",
                "--state",
                "merged",
                "--limit",
                "10",
                "--json",
                "number,title,mergedAt",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "GH_TOKEN": gh_token},
        )
        if result.returncode == 0:
            prs = json.loads(result.stdout)
            console.print(f"Found {len(prs)} recently merged PRs")
            for pr in prs[:5]:
                console.print(f"  #{pr['number']}: {pr['title'][:50]}")
        else:
            console.print(f"[yellow]Could not fetch PRs: {result.stderr}[/yellow]")

        console.print("[green]Release check complete[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


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
        sys.exit(1)


if __name__ == "__main__":
    main()
