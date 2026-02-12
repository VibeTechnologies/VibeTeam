from __future__ import annotations

"""
MarketingManager agent using OpenHands.

Capabilities:
- Chrome DevTools via MCP for browser automation
- Browser context injection using shared browser tools
- Social media post creation
- Web research and analysis
- Screenshot and content capture

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import tempfile
from typing import Any

from agents.config import (
    MARKETING_MANAGER_CONFIG,
    AgentConfig,
    get_mcp_config_dict,
)
from agents.sessions import get_or_create_session, get_session_store

# Import shared browser tools for context injection
from agents.shared.browser_tools import (
    get_browser_context,
    web_search_sync,
)

try:
    from openhands.sdk import Agent, LocalConversation

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    Agent = None
    LocalConversation = None

from agents.shared.agents_md_loader import compose_agent_context
from agents.shared.llm import LLM, AzureLLM

from .utils import get_prompt_path

# Fallback context if AGENTS.md files not found
MARKETING_MANAGER_CONTEXT_FALLBACK = """You are Sam, the Marketing Manager for VibeTeam.

## CRITICAL: Agent Identity and Handoffs
You are the **MarketingManager**.
- **DO NOT** tag @MarketingManager in your response. You ARE the MarketingManager.
- If you need to hand off, tag the *other* specific role (e.g., @ProductManager).
- If you have completed the task, simply state that. Do not tag yourself.

Your responsibilities:
1. **Social Media**: Create and schedule posts on Twitter/X, LinkedIn
2. **Content Creation**: Write blog posts, announcements, release notes
3. **Web Research**: Analyze competitors, trends, and market opportunities
4. **Brand Management**: Ensure consistent messaging and brand voice

## Brand Guidelines
- Voice: Professional but approachable, technical but accessible
- Hashtags: #AI #DevTools #Automation #VibeTeam
- Always include relevant links and CTAs

## TEAM COLLABORATION

When you complete a task or need help from another team member, @mention them in your response:
- @SoftwareEngineer - for technical content review
- @ReleaseEngineer - for release announcements and changelogs
- @SupportEngineer - for customer testimonials and feedback
- @ProductManager - for product positioning decisions

Example: "Blog post draft ready for v1.2.0 release. @ProductManager please review before publishing."

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

    def _create_llm(self) -> AzureLLM:
        """Create AzureLLM with Azure configuration.

        Uses AzureLLM (not base LLM) because Azure OpenAI doesn't support the
        Responses API. AzureLLM overrides uses_responses_api() to return False.
        """
        model_name = self.config.llm.model or "gpt-5.2"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return AzureLLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,
            timeout=300,  # 5 min per LLM call — prevents infinite hangs
            num_retries=3,  # Retry transient failures (overall timeout is the safety net)
        )

    def _create_agent(self, llm: LLM, *, use_tools: bool = True) -> Agent:
        """Create Agent with MCP config if available.

        Args:
            llm: The LLM to use.
            use_tools: When False, skip MCP configuration (useful for
                lightweight/test invocations that don't need browser tools).
        """
        # Load agent context from AGENTS.md hierarchy
        # Falls back to hardcoded context if files not found
        agent_context = compose_agent_context(
            "marketing_manager", fallback_context=MARKETING_MANAGER_CONTEXT_FALLBACK
        )

        # Build common kwargs; only include mcp_config when servers are
        # actually configured.  Passing None crashes the OpenHands SDK
        # (pydantic expects a dict, not NoneType).
        agent_kwargs: dict[str, Any] = {
            "llm": llm,
            "system_prompt_filename": get_prompt_path(),
            "system_prompt_kwargs": {
                "agent_context": agent_context,
            },
        }

        if use_tools:
            mcp_config = get_mcp_config_dict(self.config.mcp_servers)
            if mcp_config.get("mcpServers"):
                agent_kwargs["mcp_config"] = mcp_config

        return Agent(**agent_kwargs)

    def _inject_browser_context(self, task: str) -> str:
        """Inject browser context based on task keywords.

        Automatically fetches web content when task mentions URLs or search-related keywords.

        Args:
            task: The task description

        Returns:
            Additional context string to prepend to the task
        """
        context_parts = []
        task_lower = task.lower()

        # Check for URL patterns
        import re

        urls = re.findall(r"https?://[^\s]+", task)
        for url in urls[:3]:  # Limit to 3 URLs
            try:
                content = get_browser_context(url.rstrip(".,;:)"))
                context_parts.append(content)
            except Exception as e:
                context_parts.append(f"## Error fetching {url}\n{e}")

        # Check for search-related keywords
        search_keywords = [
            "search for",
            "find information",
            "research",
            "look up",
            "competitor",
            "market analysis",
        ]
        if any(kw in task_lower for kw in search_keywords):
            # Extract search terms (simple heuristic)
            if "competitor" in task_lower or "market analysis" in task_lower:
                # Try to extract company/product name
                words = task.split()
                for i, word in enumerate(words):
                    if word.lower() in ["competitor", "analyze", "research"]:
                        if i + 1 < len(words):
                            search_term = words[i + 1].strip(".,;:)")
                            if len(search_term) > 2:
                                try:
                                    results = web_search_sync(f"{search_term} product features")
                                    context_parts.append(f"## Search Results\n{results}")
                                except Exception as e:
                                    context_parts.append(f"## Search Error\n{e}")
                                break

        if context_parts:
            return "\n\n".join(context_parts) + "\n\n"
        return ""

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
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

        use_tools = kwargs.get("use_tools", True)
        llm = self._create_llm()
        agent = self._create_agent(llm, use_tools=use_tools)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            # Inject browser context based on task keywords
            browser_context = self._inject_browser_context(task)

            full_task = f"{MARKETING_MANAGER_CONTEXT_FALLBACK}\n\n{browser_context}Task: {task}"
            response = conversation.ask_agent(full_task)

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

        finally:
            if temp_dir:
                try:
                    conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run, task, context_type, context_id, workspace, **kwargs
        )


def create_marketing_manager(
    config: AgentConfig | None = None,
) -> OpenHandsMarketingManager:
    """Factory function to create Marketing Manager agent."""
    return OpenHandsMarketingManager(config)
