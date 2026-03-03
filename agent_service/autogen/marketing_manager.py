"""
MarketingManager agent using AutoGen.

Capabilities:
- Web browsing and research (via shared browser tools)
- Social media content creation
- Brand monitoring
- Competitive analysis
"""

import asyncio
import os
from typing import Any

from agent_service.config import MARKETING_MANAGER_CONFIG, AgentConfig
from agent_service.sessions import get_or_create_session, get_session_store

# Import shared browser tools
from agent_service.shared.browser_tools import (
    analyze_competitor_page,
    extract_links,
    fetch_webpage,
    take_screenshot,
    web_search,
)
from agent_service.shared.agents_md_loader import load_shared_instructions
from agent_service.shared.slack_tools import (
    send_message,
)

# AutoGen imports - will fail gracefully if not installed
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_core.models import ModelFamily
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False
    AssistantAgent = None
    TaskResult = None
    AzureOpenAIChatCompletionClient = None
    ModelFamily = None

# Model info for custom Azure deployments
AZURE_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",
    "structured_output": True,
}


SHARED_INSTRUCTIONS = load_shared_instructions().strip()

MARKETING_MANAGER_SYSTEM_PROMPT = f"""You are Ada, the Marketing Manager for VibeTeam.

## CRITICAL: How to Respond

You MUST use `send_message()` to post your response to Slack. Never just return text.
Always call `send_message(message="your response here")` to communicate your findings, updates, and results.

Example:
```
send_message("Campaign analysis complete. /ProductManager please review the metrics before we proceed.")
```

Your responsibilities:
1. **Content Creation**: Write blog posts, social media content, and announcements
2. **Brand Monitoring**: Track mentions and sentiment across platforms
3. **Competitive Analysis**: Research competitor products and features
4. **Web Research**: Gather market insights and trends

## Platforms
- Twitter/X: @VibeTechnologies
- LinkedIn: Vibe Technologies
- Blog: blog.vibetechnologies.com

## Content Guidelines
- Keep social posts concise and engaging
- Use relevant hashtags for visibility
- Include calls to action when appropriate
- Maintain consistent brand voice

{SHARED_INSTRUCTIONS}

When you complete a task, summarize the content created and any scheduled posts.
"""


# Tool functions for MarketingManager
# NOTE: web_search, fetch_webpage, take_screenshot, extract_links, and analyze_competitor_page
# are imported from agent_service.shared.browser_tools above


async def create_social_post(platform: str, content: str, hashtags: str = "") -> str:
    """Create a social media post draft.

    Args:
        platform: The platform (twitter, linkedin, etc.)
        content: The post content
        hashtags: Optional hashtags to include

    Returns:
        Formatted post draft
    """
    platform = platform.lower()

    # Platform-specific formatting
    if platform == "twitter" or platform == "x":
        max_length = 280
        formatted = content
        if hashtags:
            formatted += f"\n\n{hashtags}"
        if len(formatted) > max_length:
            return f"Error: Tweet exceeds {max_length} characters ({len(formatted)} chars)"
        return f"""
=== Twitter/X Post Draft ===
{formatted}

Character count: {len(formatted)}/280
Hashtags: {hashtags or "None"}
Status: Ready for review
"""

    elif platform == "linkedin":
        formatted = content
        if hashtags:
            formatted += f"\n\n{hashtags}"
        return f"""
=== LinkedIn Post Draft ===
{formatted}

Character count: {len(formatted)}
Hashtags: {hashtags or "None"}
Status: Ready for review
"""

    else:
        return f"""
=== {platform.title()} Post Draft ===
{content}

Hashtags: {hashtags or "None"}
Status: Ready for review
"""


async def analyze_sentiment(text: str) -> str:
    """Analyze the sentiment of text.

    Args:
        text: The text to analyze

    Returns:
        Sentiment analysis result
    """
    # Simple keyword-based sentiment (in production, use ML model)
    text_lower = text.lower()

    positive_words = [
        "great",
        "excellent",
        "love",
        "amazing",
        "fantastic",
        "good",
        "happy",
        "wonderful",
    ]
    negative_words = [
        "bad",
        "terrible",
        "hate",
        "awful",
        "poor",
        "disappointed",
        "frustrated",
        "angry",
    ]

    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)

    if positive_count > negative_count:
        sentiment = "Positive"
        score = min(0.5 + (positive_count * 0.1), 1.0)
    elif negative_count > positive_count:
        sentiment = "Negative"
        score = max(0.5 - (negative_count * 0.1), 0.0)
    else:
        sentiment = "Neutral"
        score = 0.5

    return f"""
Sentiment Analysis:
- Text: "{text[:100]}{"..." if len(text) > 100 else ""}"
- Sentiment: {sentiment}
- Confidence: {score:.2f}
- Positive signals: {positive_count}
- Negative signals: {negative_count}
"""


class AutoGenMarketingManager:
    """Marketing Manager agent using AutoGen."""

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or MARKETING_MANAGER_CONFIG
        self.model_client = self._create_model_client()
        self.agent = self._create_agent()

    def _create_model_client(self) -> "AzureOpenAIChatCompletionClient":
        """Create Azure OpenAI model client."""
        model_name = self.config.llm.model or "gpt-5.2"
        if model_name.startswith("azure/"):
            model_name = model_name[6:]

        return AzureOpenAIChatCompletionClient(
            azure_deployment=model_name,
            model=model_name,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=self.config.llm.api_base or "",
            api_key=self.config.llm.api_key or "",
            model_info=AZURE_MODEL_INFO,
        )

    def _create_agent(self) -> "AssistantAgent":
        """Create AutoGen AssistantAgent with tools."""
        return AssistantAgent(
            name="MarketingManager",
            model_client=self.model_client,
            tools=[
                # Slack communication (send_message is PRIMARY for responses)
                send_message,
                # Browser tools from shared layer
                web_search,
                fetch_webpage,
                take_screenshot,
                extract_links,
                analyze_competitor_page,
                # Content tools
                create_social_post,
                analyze_sentiment,
            ],
            system_message=MARKETING_MANAGER_SYSTEM_PROMPT,
            description="Marketing Manager for content creation, brand monitoring, and market research.",
        )

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Marketing Manager agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="autogen",
            role="marketing_manager",
            context_type=context_type,
            context_id=context_id,
        )

        # Run the agent
        result: TaskResult = await self.agent.run(task=task)

        # Extract response from result
        # Priority: 1) send_message tool call content, 2) non-empty TextMessage
        response = ""
        if result.messages:
            import json

            from autogen_agentchat.messages import TextMessage, ToolCallRequestEvent

            # First, look for send_message tool calls - this is the actual response
            for msg in reversed(result.messages):
                if isinstance(msg, ToolCallRequestEvent) and msg.source == "MarketingManager":
                    for call in msg.content:
                        if hasattr(call, "name") and call.name == "send_message":
                            try:
                                args = json.loads(call.arguments)
                                if args.get("message"):
                                    response = args["message"]
                                    break
                            except (json.JSONDecodeError, AttributeError):
                                pass
                    if response:
                        break

            # Fallback: get the last non-empty TextMessage from the assistant
            if not response:
                for msg in reversed(result.messages):
                    if isinstance(msg, TextMessage) and msg.source == "MarketingManager":
                        if msg.content and str(msg.content).strip():
                            response = str(msg.content)
                            break

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "autogen",
            "agent": "marketing_manager",
        }

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync version of run_async."""
        return asyncio.run(self.run_async(task, context_type, context_id, **kwargs))

    async def close(self) -> None:
        """Close the model client connection."""
        if self.model_client:
            await self.model_client.close()


def create_marketing_manager(
    config: AgentConfig | None = None,
) -> AutoGenMarketingManager:
    """Factory function to create Marketing Manager agent."""
    return AutoGenMarketingManager(config)
