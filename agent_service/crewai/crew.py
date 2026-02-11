"""
CrewAI team orchestration for VibeTeam.

Coordinates multiple agents using CrewAI's Crew and Process system.
"""

from typing import Any

from agents.config import AgentConfig
from agents.sessions import get_or_create_session, get_session_store

from .marketing_manager import CrewAIMarketingManager
from .release_engineer import CrewAIReleaseEngineer
from .support_engineer import CrewAISupportEngineer

try:
    from crewai import Agent, Crew, Process, Task

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    Agent = None
    Task = None
    Crew = None
    Process = None


class CrewAITeam:
    """
    Team orchestration for CrewAI agents.

    Routes tasks to appropriate agents based on @mentions or keywords.
    Supports both single-agent and multi-agent (Crew) execution.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or AgentConfig()
        self._agent_wrappers: dict[str, Any] = {}
        self._agents: dict[str, Agent] = {}

    def _get_agent_wrapper(self, role: str) -> Any:
        """Lazy-load agent wrappers on demand."""
        if role not in self._agent_wrappers:
            if role == "release_engineer":
                self._agent_wrappers[role] = CrewAIReleaseEngineer(self.config)
            elif role == "marketing_manager":
                self._agent_wrappers[role] = CrewAIMarketingManager(self.config)
            elif role == "support_engineer":
                self._agent_wrappers[role] = CrewAISupportEngineer(self.config)
            else:
                raise ValueError(f"Unknown agent role: {role}")
        return self._agent_wrappers[role]

    def _get_agent(self, role: str) -> "Agent":
        """Get the underlying CrewAI Agent."""
        if role not in self._agents:
            wrapper = self._get_agent_wrapper(role)
            self._agents[role] = wrapper.agent
        return self._agents[role]

    def _get_all_agents(self) -> list["Agent"]:
        """Get all agents for multi-agent tasks."""
        roles = ["release_engineer", "marketing_manager", "support_engineer"]
        return [self._get_agent(role) for role in roles]

    def parse_mention(self, text: str) -> str | None:
        """
        Parse @mention from text to determine target agent.

        Supported mentions:
        - @ReleaseEngineer, @release, @einstein
        - @MarketingManager, @marketing, @ada
        - @SupportEngineer, @support, @grace
        """
        text_lower = text.lower()

        release_patterns = ["@releaseengineer", "@release", "@einstein"]
        marketing_patterns = ["@marketingmanager", "@marketing", "@ada"]
        support_patterns = ["@supportengineer", "@support", "@grace"]

        for pattern in release_patterns:
            if pattern in text_lower:
                return "release_engineer"

        for pattern in marketing_patterns:
            if pattern in text_lower:
                return "marketing_manager"

        for pattern in support_patterns:
            if pattern in text_lower:
                return "support_engineer"

        return None

    def route_by_keywords(self, text: str) -> str:
        """
        Route to agent based on keywords if no @mention found.
        """
        text_lower = text.lower()

        # Release Engineer keywords
        if any(
            kw in text_lower
            for kw in [
                "deploy",
                "release",
                "k8s",
                "kubernetes",
                "pipeline",
                "ci/cd",
                "build",
                "version",
                "tag",
                "infrastructure",
                "git",
                "commit",
            ]
        ):
            return "release_engineer"

        # Marketing Manager keywords
        if any(
            kw in text_lower
            for kw in [
                "post",
                "tweet",
                "linkedin",
                "social",
                "blog",
                "announcement",
                "marketing",
                "content",
                "brand",
                "research",
            ]
        ):
            return "marketing_manager"

        # Support Engineer keywords
        if any(
            kw in text_lower
            for kw in [
                "email",
                "customer",
                "support",
                "ticket",
                "calendar",
                "meeting",
                "sentry",
                "error",
                "langfuse",
                "schedule",
            ]
        ):
            return "support_engineer"

        # Default to support engineer for general queries
        return "support_engineer"

    def run_single_agent(
        self,
        task: str,
        role: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Run task with a single specific agent."""
        wrapper = self._get_agent_wrapper(role)
        return wrapper.run(task, context_type, context_id)

    def run_multi_agent(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        process: str = "sequential",
    ) -> dict[str, Any]:
        """
        Run task with multiple agents collaborating.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, etc.)
            context_id: ID for the context
            process: Process type (sequential, hierarchical)

        Returns:
            dict with response, agents used, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="crewai",
            role="team",
            context_type=context_type,
            context_id=context_id,
        )

        agents = self._get_all_agents()

        # Create tasks for each agent based on the main task
        crew_tasks = []

        # Analyze and plan task
        analyze_task = Task(
            description=f"""Analyze this task and determine what needs to be done:

{task}

Break down the work and identify which team members should be involved.""",
            agent=agents[2],  # Support Engineer as coordinator
            expected_output="Task analysis with action items for each team member.",
        )
        crew_tasks.append(analyze_task)

        # Execute task
        execute_task = Task(
            description=f"""Based on the analysis, execute the following task:

{task}

Coordinate with other team members as needed.""",
            agent=agents[0],  # Release Engineer for execution
            expected_output="Summary of actions taken and results.",
            context=[analyze_task],
        )
        crew_tasks.append(execute_task)

        # Review and summarize
        review_task = Task(
            description="""Review the work done and create a summary.
Include any follow-up items or recommendations.""",
            agent=agents[1],  # Marketing Manager for communication
            expected_output="Final summary with next steps.",
            context=[analyze_task, execute_task],
        )
        crew_tasks.append(review_task)

        # Create and run crew
        process_type = Process.hierarchical if process == "hierarchical" else Process.sequential
        crew = Crew(
            agents=agents,
            tasks=crew_tasks,
            process=process_type,
            verbose=self.config.verbose if hasattr(self.config, "verbose") else True,
        )

        result = crew.kickoff()

        # Update session
        session.add_message("user", task)
        session.add_message(
            "assistant",
            str(result),
            agents=["release_engineer", "marketing_manager", "support_engineer"],
        )
        get_session_store().save(session)

        return {
            "response": str(result),
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "crewai",
            "agents": ["release_engineer", "marketing_manager", "support_engineer"],
            "process": process,
        }

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        multi_agent: bool = False,
    ) -> dict[str, Any]:
        """
        Route and execute task with appropriate agent(s).

        Args:
            task: The task description (may contain @mentions)
            context_type: Type of context (issue, pr, slack, etc.)
            context_id: ID for the context
            multi_agent: Force multi-agent execution

        Returns:
            dict with response, agent(s) used, and metadata
        """
        # Check for @mention
        role = self.parse_mention(task)
        if role and not multi_agent:
            return self.run_single_agent(task, role, context_type, context_id)

        # If no mention, route by keywords
        if not multi_agent:
            role = self.route_by_keywords(task)
            return self.run_single_agent(task, role, context_type, context_id)

        # Multi-agent execution
        return self.run_multi_agent(task, context_type, context_id)

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        multi_agent: bool = False,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, multi_agent)


def create_team(config: AgentConfig | None = None) -> CrewAITeam:
    """Factory function to create CrewAI team."""
    return CrewAITeam(config)
