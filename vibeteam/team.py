"""
VibeTeam - Main team orchestrator based on MetaGPT Team pattern.
"""

from typing import Any

from metagpt.context import Context
from metagpt.team import Team
from pydantic import Field
from rich.console import Console

from vibeteam.roles import (
    Marketer,
    ProductManager,
    ReleaseEngineer,
    ReliabilityEngineer,
    SoftwareEngineer,
    SupportEngineer,
)


class VibeTeam(Team):
    """
    VibeTeam - Autonomous AI team for SaaS development.

    Based on MetaGPT Team pattern with specialized roles:
    - ProductManager: Requirements, roadmap, user stories
    - SoftwareEngineer: Implementation, testing, reviews
    - Marketer: Content, social media, announcements
    - SupportEngineer: User issues, documentation
    - ReliabilityEngineer: Production health, incidents
    - ReleaseEngineer: Deployments, versioning

    The team operates autonomously with:
    - Message-based communication between roles
    - Shared memory and context
    - Automatic task routing based on capabilities
    """

    name: str = Field(default="VibeTeam")
    console: Console = Field(default_factory=Console, exclude=True)

    def __init__(
        self,
        context: Context | None = None,
        investment: float = 10.0,
        include_roles: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize VibeTeam with specified roles.

        Args:
            context: MetaGPT context for shared state
            investment: Budget for LLM calls
            include_roles: List of role names to include.
                          If None, includes all roles.
                          Options: ["pm", "swe", "marketer", "support", "sre", "release"]
        """
        super().__init__(context=context, investment=investment, **kwargs)

        # Role registry
        role_map = {
            "pm": ProductManager,
            "swe": SoftwareEngineer,
            "marketer": Marketer,
            "support": SupportEngineer,
            "sre": ReliabilityEngineer,
            "release": ReleaseEngineer,
        }

        # Determine which roles to include
        if include_roles is None:
            include_roles = list(role_map.keys())

        # Initialize roles
        roles = []
        for role_key in include_roles:
            if role_key in role_map:
                role_class = role_map[role_key]
                roles.append(role_class())
                self.console.print(f"[green]Added role: {role_class.__name__}[/green]")

        self.hire(roles)
        self.console.print(f"[bold blue]VibeTeam initialized with {len(roles)} roles[/bold blue]")

    async def run_project(self, requirement: str, n_round: int = 5) -> str:
        """
        Run the team on a project requirement.

        Args:
            requirement: High-level project requirement
            n_round: Number of communication rounds

        Returns:
            Final project output
        """
        self.console.print(f"[bold]Starting project: {requirement[:100]}...[/bold]")
        result = await self.run(n_round=n_round, idea=requirement)
        return result

    def get_team_status(self) -> dict[str, Any]:
        """Get current status of all team members."""
        status = {}
        for role in self.env.roles.values():
            status[role.profile] = {
                "name": role.name,
                "goal": role.goal,
                "actions": [a.name for a in role.actions],
            }
        return status
