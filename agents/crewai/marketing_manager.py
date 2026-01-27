"""
MarketingManager agent using CrewAI.

Capabilities:
- Web browsing via BrowserbaseTool or custom browser tool
- Content creation and social media posting
- Research and analysis
"""

import os
from typing import Any

from agents.config import AgentConfig, MARKETING_MANAGER_CONFIG
from agents.sessions import get_or_create_session, get_session_store

try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import BaseTool

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    Agent = None
    Task = None
    Crew = None


MARKETING_MANAGER_BACKSTORY = """You are Ada, the Marketing Manager for VibeTeam.
You have deep expertise in:
- Social media marketing (Twitter/X, LinkedIn)
- Content creation and copywriting
- Brand management and messaging
- Market research and competitive analysis

You are creative, data-driven, and always on-brand.
You craft compelling narratives that resonate with technical audiences.
"""

MARKETING_MANAGER_GOAL = """Create engaging content, manage social media presence,
and build brand awareness for VibeTeam."""


class WebSearchTool(BaseTool if CREWAI_AVAILABLE else object):
    """Search the web for information."""

    name: str = "web_search"
    description: str = "Search the web for information. Input: search query."

    def _run(self, query: str) -> str:
        """Perform web search (mock implementation)."""
        # In production, use a real search API
        return f"Web search results for: {query}\n[Mock results - integrate with actual search API]"


class ContentDraftTool(BaseTool if CREWAI_AVAILABLE else object):
    """Draft social media content."""

    name: str = "draft_content"
    description: str = "Draft social media content. Input: JSON with 'platform' and 'topic' keys."

    def _run(self, input_data: str) -> str:
        """Draft content."""
        import json

        try:
            data = json.loads(input_data)
            platform = data.get("platform", "twitter")
            topic = data.get("topic", "")

            # Character limits by platform
            limits = {"twitter": 280, "linkedin": 3000}
            limit = limits.get(platform.lower(), 280)

            return f"Draft for {platform} (max {limit} chars):\n[Content about: {topic}]"
        except Exception as e:
            return f"Error drafting content: {e}"


class CrewAIMarketingManager:
    """Marketing Manager agent using CrewAI."""

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or MARKETING_MANAGER_CONFIG
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _create_tools(self) -> list:
        """Create tools for the agent."""
        return [
            WebSearchTool(),
            ContentDraftTool(),
        ]

    def _create_agent(self) -> "Agent":
        """Create CrewAI Agent."""
        return Agent(
            role="Marketing Manager",
            goal=MARKETING_MANAGER_GOAL,
            backstory=MARKETING_MANAGER_BACKSTORY,
            tools=self.tools,
            verbose=self.config.verbose,
            llm=self.config.llm.model,
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a task with the Marketing Manager agent."""
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="crewai",
            role="marketing_manager",
            context_type=context_type,
            context_id=context_id,
        )

        crew_task = Task(
            description=task,
            agent=self.agent,
            expected_output="Content draft or research findings with recommendations.",
        )

        crew = Crew(
            agents=[self.agent],
            tasks=[crew_task],
            process=Process.sequential,
            verbose=self.config.verbose,
        )

        result = crew.kickoff()

        session.add_message("user", task)
        session.add_message("assistant", str(result))
        get_session_store().save(session)

        return {
            "response": str(result),
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "crewai",
            "agent": "marketing_manager",
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, **kwargs)


def create_marketing_manager(config: AgentConfig | None = None) -> CrewAIMarketingManager:
    """Factory function to create Marketing Manager agent."""
    return CrewAIMarketingManager(config)
