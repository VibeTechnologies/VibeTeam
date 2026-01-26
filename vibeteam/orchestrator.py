"""
VibeTeam Orchestrator - OpenHands-based team orchestrator replacing MetaGPT Team.

This orchestrator manages multiple specialized agents and routes tasks to the
appropriate agent based on the task type and agent capabilities.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rich.console import Console

from vibeteam.agents import (
    BaseVibeAgent,
    MarketerAgent,
    ProductManagerAgent,
    ReleaseEngineerAgent,
    ReliabilityEngineerAgent,
    SoftwareEngineerAgent,
    SupportEngineerAgent,
)


class AgentType(Enum):
    """Available agent types in VibeTeam."""

    PM = "pm"
    SWE = "swe"
    MARKETER = "marketer"
    SUPPORT = "support"
    SRE = "sre"
    RELEASE = "release"


# Mapping from agent type to agent class
AGENT_REGISTRY: dict[AgentType, type[BaseVibeAgent]] = {
    AgentType.PM: ProductManagerAgent,
    AgentType.SWE: SoftwareEngineerAgent,
    AgentType.MARKETER: MarketerAgent,
    AgentType.SUPPORT: SupportEngineerAgent,
    AgentType.SRE: ReliabilityEngineerAgent,
    AgentType.RELEASE: ReleaseEngineerAgent,
}

# Keywords for automatic task routing
ROUTING_KEYWORDS: dict[AgentType, list[str]] = {
    AgentType.PM: [
        "requirement",
        "roadmap",
        "feature",
        "prioritize",
        "user story",
        "conversation",
        "langfuse",
        "analyze feedback",
        "product",
    ],
    AgentType.SWE: [
        "implement",
        "code",
        "bug",
        "fix",
        "test",
        "refactor",
        "pull request",
        "pr",
        "commit",
        "github issue",
    ],
    AgentType.MARKETER: [
        "social media",
        "twitter",
        "linkedin",
        "reddit",
        "post",
        "announce",
        "content",
        "marketing",
    ],
    AgentType.SUPPORT: [
        "customer",
        "support",
        "ticket",
        "help",
        "documentation",
        "faq",
        "user issue",
    ],
    AgentType.SRE: [
        "monitor",
        "alert",
        "incident",
        "sentry",
        "error",
        "health",
        "production",
        "observability",
    ],
    AgentType.RELEASE: [
        "release",
        "deploy",
        "version",
        "changelog",
        "tag",
        "publish",
        "cluster",
        "kubernetes",
        "k8s",
        "k3s",
        "pod",
        "infrastructure",
        "service status",
        "what is",
        "how does",
        "architecture",
        "system design",
    ],
}


@dataclass
class TaskResult:
    """Result from an agent task execution."""

    agent_type: AgentType
    task: str
    success: bool
    response: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VibeTeam:
    """
    VibeTeam - Autonomous AI team orchestrator using OpenHands-based agents.

    Replaces the MetaGPT-based Team with a simpler, more flexible architecture.
    Each agent operates independently with LiteLLM for model-agnostic LLM calls.

    Features:
    - Automatic task routing based on keywords
    - Manual agent selection
    - Parallel task execution (planned)
    - Shared context between agents (planned)

    Example:
        team = VibeTeam()
        result = await team.run("Implement the login feature from GitHub issue #123")
        # Routes to SoftwareEngineerAgent automatically

        # Or explicitly select an agent:
        result = await team.run("Create a release", agent_type=AgentType.RELEASE)
    """

    model: str = "openai/gpt-5-mini"
    include_agents: list[AgentType] | None = None
    console: Console = field(default_factory=Console)
    _agents: dict[AgentType, BaseVibeAgent] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        """Initialize agents after dataclass construction."""
        self._initialize_agents()

    def _initialize_agents(self) -> None:
        """Initialize all included agents."""
        agent_types = self.include_agents or list(AgentType)

        for agent_type in agent_types:
            if agent_type in AGENT_REGISTRY:
                agent_class = AGENT_REGISTRY[agent_type]
                self._agents[agent_type] = agent_class(model=self.model)
                self.console.print(f"[green]Initialized: {agent_class.__name__}[/green]")

        self.console.print(f"[bold blue]VibeTeam ready with {len(self._agents)} agents[/bold blue]")

    def get_agent(self, agent_type: AgentType) -> BaseVibeAgent | None:
        """Get a specific agent by type."""
        return self._agents.get(agent_type)

    def list_agents(self) -> list[tuple[AgentType, str]]:
        """List all available agents with their names."""
        return [(t, a.name) for t, a in self._agents.items()]

    def route_task(self, task: str) -> AgentType:
        """
        Automatically route a task to the most appropriate agent.

        Uses keyword matching to determine the best agent for the task.
        Falls back to SWE if no match is found.

        Args:
            task: The task description

        Returns:
            The most appropriate AgentType for the task
        """
        task_lower = task.lower()
        scores: dict[AgentType, int] = {}

        for agent_type, keywords in ROUTING_KEYWORDS.items():
            if agent_type not in self._agents:
                continue
            score = sum(1 for kw in keywords if kw in task_lower)
            if score > 0:
                scores[agent_type] = score

        if scores:
            return max(scores, key=lambda x: scores[x])

        # Default to SWE if available, otherwise first available agent
        if AgentType.SWE in self._agents:
            return AgentType.SWE
        return next(iter(self._agents.keys()))

    async def run(
        self,
        task: str,
        agent_type: AgentType | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskResult:
        """
        Run a task using the specified or auto-routed agent.

        Args:
            task: The task to execute
            agent_type: Specific agent to use (auto-routes if None)
            context: Optional context to pass to the agent

        Returns:
            TaskResult with the agent's response
        """
        # Route to appropriate agent
        selected_type = agent_type or self.route_task(task)
        agent = self._agents.get(selected_type)

        if not agent:
            return TaskResult(
                agent_type=selected_type,
                task=task,
                success=False,
                response="",
                error=f"Agent {selected_type.value} not available",
            )

        self.console.print(f"[cyan]Routing to: {agent.name}[/cyan]")

        # Prepare the task with context
        full_task = task
        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            full_task = f"Context:\n{context_str}\n\nTask: {task}"

        try:
            response = await agent.run(full_task)
            return TaskResult(
                agent_type=selected_type,
                task=task,
                success=True,
                response=response,
                metadata={"agent_name": agent.name, "model": agent.model},
            )
        except Exception as e:
            return TaskResult(
                agent_type=selected_type,
                task=task,
                success=False,
                response="",
                error=str(e),
            )

    async def run_with_agent(
        self,
        agent_key: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> TaskResult:
        """
        Run a task with a specific agent by string key.

        Convenience method for CLI usage.

        Args:
            agent_key: Agent key (pm, swe, marketer, support, sre, release)
            task: The task to execute
            context: Optional context

        Returns:
            TaskResult with the agent's response
        """
        try:
            agent_type = AgentType(agent_key.lower())
        except ValueError:
            return TaskResult(
                agent_type=AgentType.SWE,  # placeholder
                task=task,
                success=False,
                response="",
                error=f"Unknown agent: {agent_key}. Valid options: {[a.value for a in AgentType]}",
            )

        return await self.run(task, agent_type=agent_type, context=context)

    def get_team_status(self) -> dict[str, Any]:
        """Get current status of all team members."""
        status = {}
        for agent_type, agent in self._agents.items():
            status[agent_type.value] = {
                "name": agent.name,
                "profile": agent.profile,
                "goal": agent.goal,
                "tools": [t.name for t in agent.tools],
                "model": agent.model,
            }
        return status

    def reset_all(self) -> None:
        """Reset all agents' conversation history."""
        for agent in self._agents.values():
            agent.reset()
        self.console.print("[yellow]All agents reset[/yellow]")
