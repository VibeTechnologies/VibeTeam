"""
MarketingManager agent using OpenHands.

Capabilities:
- Chrome DevTools via MCP for browser automation
- Social media post creation
- Web research and analysis
- Screenshot and content capture
"""

import os
from typing import Any

from agents.config import (
    MARKETING_MANAGER_CONFIG,
    AgentConfig,
    get_mcp_config_dict,
)
from agents.sessions import get_or_create_session, get_session_store

try:
    from openhands.sdk import LLM, Agent, Conversation, Tool
    from openhands.tools.browser import BrowserTool

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    Agent = None
    Conversation = None


MARKETING_MANAGER_SYSTEM_PROMPT = """You are Ada, the Marketing Manager for VibeTeam.

Your responsibilities:
1. **Social Media**: Create and schedule posts on Twitter/X, LinkedIn
2. **Content Creation**: Write blog posts, announcements, release notes
3. **Web Research**: Analyze competitors, trends, and market opportunities
4. **Brand Management**: Ensure consistent messaging and brand voice

## Tools Available
- Chrome DevTools MCP: Control browser for social media and web research
- Screenshot capabilities for content capture
- Web navigation and form filling

## Brand Guidelines
- Voice: Professional but approachable, technical but accessible
- Hashtags: #AI #DevTools #Automation #VibeTeam
- Always include relevant links and CTAs

## Communication
- Post updates to Slack #marketing
- Coordinate with @ReleaseEngineer for release announcements
- Tag @SupportEngineer for customer testimonials

When posting to social media:
1. Draft the post content
2. Take a screenshot for approval (if needed)
3. Confirm before publishing
"""


class OpenHandsMarketingManager:
    """Marketing Manager agent using OpenHands SDK."""

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or MARKETING_MANAGER_CONFIG
        self.llm = self._create_llm()
        self.agent = self._create_agent()

    def _create_llm(self) -> "LLM":
        """Create OpenHands LLM instance."""
        return LLM(
            model=self.config.llm.model,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            temperature=self.config.llm.temperature,
        )

    def _create_agent(self) -> "Agent":
        """Create OpenHands Agent with Chrome DevTools MCP."""
        mcp_config = get_mcp_config_dict(self.config.mcp_servers)

        tools = []
        # Add browser tool if available
        try:
            tools.append(Tool(name=BrowserTool.name))
        except Exception:
            pass  # Browser tool may not be available

        return Agent(
            llm=self.llm,
            tools=tools,
            mcp_config=mcp_config if mcp_config["mcpServers"] else None,
            system_prompt=MARKETING_MANAGER_SYSTEM_PROMPT,
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """
        Run a task with the Marketing Manager agent.

        Args:
            task: The task description
            context_type: Type of context (campaign, post, slack, ephemeral)
            context_id: ID for the context
            workspace: Working directory for the agent

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="marketing_manager",
            context_type=context_type,
            context_id=context_id,
        )

        workspace = workspace or os.getcwd()
        conversation = Conversation(
            agent=self.agent,
            workspace=workspace,
            persistence_dir=self.config.session.storage_path,
            conversation_id=session.session_id,
        )

        conversation.send_message(task)
        conversation.run()

        response = conversation.get_last_assistant_message()

        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "openhands",
            "agent": "marketing_manager",
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, workspace)


def create_marketing_manager(config: AgentConfig | None = None) -> OpenHandsMarketingManager:
    """Factory function to create Marketing Manager agent."""
    return OpenHandsMarketingManager(config)
