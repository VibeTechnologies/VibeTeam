"""
Slack Bot - Event-driven bot that routes messages to VibeTeam agents.

Uses Slack Bolt for Python to handle:
- App mentions (@vibeteam or @agent-name)
- Direct messages to the bot
- Scheduled monitoring tasks

This is the entry point for Slack-based agent communication.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from vibeteam.agents import (
    BaseVibeAgent,
    MarketerAgent,
    ProductManagerAgent,
    ReleaseEngineerAgent,
    ReliabilityEngineerAgent,
    SoftwareEngineerAgent,
    SupportEngineerAgent,
)
from vibeteam.connectors.slack import SlackConnector
from vibeteam.tools.slack import SlackTool

logger = logging.getLogger(__name__)


# Agent registry - maps keys to agent classes
AGENT_REGISTRY: dict[str, type[BaseVibeAgent]] = {
    "pm": ProductManagerAgent,
    "swe": SoftwareEngineerAgent,
    "release": ReleaseEngineerAgent,
    "support": SupportEngineerAgent,
    "sre": ReliabilityEngineerAgent,
    "marketer": MarketerAgent,
}

# Agent display names for Slack formatting
AGENT_NAMES: dict[str, str] = {
    "pm": "Curie",
    "swe": "Turing",
    "release": "Einstein",
    "support": "Darwin",
    "sre": "Newton",
    "marketer": "Ada",
}

# Keywords that route to specific agents
ROUTING_KEYWORDS: dict[str, list[str]] = {
    "pm": ["feature", "requirement", "roadmap", "prioritize", "prd", "customer request"],
    "swe": ["implement", "code", "bug", "fix", "pr", "pull request", "review"],
    "release": ["deploy", "release", "sentry", "error", "production", "version"],
    "support": ["customer", "email", "ticket", "help", "documentation"],
    "sre": ["health", "monitor", "incident", "uptime", "alert"],
    "marketer": ["announce", "social", "twitter", "linkedin", "content"],
}


@dataclass
class AgentResponse:
    """Response from an agent."""

    agent_key: str
    agent_name: str
    message: str
    success: bool
    metadata: dict[str, Any] | None = None


class SlackBot:
    """
    Slack bot that routes messages to VibeTeam agents.

    Architecture:
    1. Receives Slack events (mentions, DMs)
    2. Parses message to identify target agent
    3. Routes to appropriate agent
    4. Posts agent response back to Slack

    Usage:
        bot = SlackBot()
        bot.start()  # Blocking - runs the event loop
    """

    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
        model: str = "azure/gpt-4.1",
        default_channel: str = "#ai-team",
    ):
        """
        Initialize Slack bot.

        Args:
            bot_token: Slack bot token (or SLACK_BOT_TOKEN env)
            app_token: Slack app token for Socket Mode (or SLACK_APP_TOKEN env)
            model: LLM model for agents
            default_channel: Default channel for responses
        """
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
        self.model = model
        self.default_channel = default_channel

        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN required")

        # Initialize Slack Bolt app
        self.app = App(token=self.bot_token)

        # Initialize connector for posting
        self.connector = SlackConnector(token=self.bot_token, default_channel=default_channel)

        # Initialize agents (lazy loaded)
        self._agents: dict[str, BaseVibeAgent] = {}

        # Register event handlers
        self._register_handlers()

    def _get_agent(self, key: str) -> BaseVibeAgent:
        """Get or create an agent by key."""
        if key not in self._agents:
            if key not in AGENT_REGISTRY:
                raise ValueError(f"Unknown agent: {key}")

            agent_class = AGENT_REGISTRY[key]
            agent = agent_class(model=self.model)

            # Add Slack tool to agent
            slack_tool = SlackTool(
                token=self.bot_token,
                default_channel=self.default_channel,
                agent_name=AGENT_NAMES.get(key, key),
            )
            agent.add_tool(slack_tool)

            self._agents[key] = agent
            logger.info(f"Initialized agent: {key} ({agent.name})")

        return self._agents[key]

    def _parse_target_agent(self, text: str) -> str | None:
        """
        Parse message text to identify target agent.

        Checks for:
        1. Explicit @agent mentions (@pm, @swe, etc.)
        2. Keyword matching
        """
        text_lower = text.lower()

        # Check for explicit agent mentions
        for agent_key in AGENT_REGISTRY.keys():
            patterns = [
                f"@{agent_key}",
                f"<@{agent_key}>",
                f"@{AGENT_NAMES.get(agent_key, '').lower()}",
            ]
            for pattern in patterns:
                if pattern in text_lower:
                    return agent_key

        # Check for keyword-based routing
        scores: dict[str, int] = {}
        for agent_key, keywords in ROUTING_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[agent_key] = score

        if scores:
            return max(scores, key=lambda x: scores[x])

        # Default to PM for general questions
        return "pm"

    def _register_handlers(self) -> None:
        """Register Slack event handlers."""

        @self.app.event("app_mention")
        def handle_app_mention(event: dict, say: Callable) -> None:
            """Handle @vibeteam mentions."""
            asyncio.run(self._handle_mention_async(event, say))

        @self.app.event("message")
        def handle_direct_message(event: dict, say: Callable) -> None:
            """Handle direct messages to the bot."""
            # Only handle DMs (channel type 'im')
            if event.get("channel_type") == "im":
                asyncio.run(self._handle_mention_async(event, say))

    async def _handle_mention_async(self, event: dict, say: Callable) -> None:
        """Async handler for mentions."""
        try:
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts") or event.get("ts")

            logger.info(f"Received message from {user} in {channel}: {text[:100]}")

            # Parse target agent
            target_agent = self._parse_target_agent(text)
            if not target_agent:
                say(
                    text="I'm not sure which team member should handle this. "
                    "Try mentioning @pm, @swe, @release, @support, @sre, or @marketer.",
                    thread_ts=thread_ts,
                )
                return

            # Get the agent
            agent = self._get_agent(target_agent)

            # Acknowledge receipt
            agent_name = AGENT_NAMES.get(target_agent, target_agent)
            say(
                text=f":hourglass: Routing to *{agent_name}*...",
                thread_ts=thread_ts,
            )

            # Run the agent
            response = await agent.run(text)

            # Format and post response
            formatted = self.connector.format_agent_message(agent_name, response)
            say(text=formatted, thread_ts=thread_ts)

            logger.info(f"Agent {target_agent} responded successfully")

        except Exception as e:
            logger.exception(f"Error handling mention: {e}")
            say(
                text=f":warning: Sorry, I encountered an error: {str(e)[:200]}",
                thread_ts=event.get("ts"),
            )

    async def route_to_agent(
        self,
        agent_key: str,
        message: str,
        channel: str | None = None,
        thread_ts: str | None = None,
    ) -> AgentResponse:
        """
        Programmatically route a message to an agent.

        Args:
            agent_key: Agent to route to (pm, swe, etc.)
            message: Message/task for the agent
            channel: Channel to post response (optional)
            thread_ts: Thread to reply in (optional)

        Returns:
            AgentResponse with the result
        """
        try:
            agent = self._get_agent(agent_key)
            response = await agent.run(message)

            # Post to Slack if channel specified
            if channel:
                agent_name = AGENT_NAMES.get(agent_key, agent_key)
                formatted = self.connector.format_agent_message(agent_name, response)
                self.connector.post_message(channel, formatted, thread_ts=thread_ts)

            return AgentResponse(
                agent_key=agent_key,
                agent_name=AGENT_NAMES.get(agent_key, agent_key),
                message=response,
                success=True,
            )

        except Exception as e:
            logger.exception(f"Error routing to agent {agent_key}")
            return AgentResponse(
                agent_key=agent_key,
                agent_name=AGENT_NAMES.get(agent_key, agent_key),
                message=str(e),
                success=False,
            )

    def start(self) -> None:
        """Start the bot in Socket Mode (blocking)."""
        if not self.app_token:
            raise ValueError(
                "SLACK_APP_TOKEN required for Socket Mode. "
                "Generate one at api.slack.com/apps > Socket Mode."
            )

        logger.info("Starting SlackBot in Socket Mode...")
        handler = SocketModeHandler(self.app, self.app_token)
        handler.start()

    def start_async(self) -> None:
        """Start the bot asynchronously (non-blocking)."""
        import threading

        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        logger.info("SlackBot started in background thread")


class SlackAgentRouter:
    """
    Lightweight router for directing Slack messages to agents.

    Use this when you want more control over the routing logic
    or when integrating with existing event systems.
    """

    def __init__(self, model: str = "azure/gpt-4.1"):
        """Initialize router with agents."""
        self.model = model
        self._agents: dict[str, BaseVibeAgent] = {}

    def get_agent(self, key: str) -> BaseVibeAgent:
        """Get or create an agent."""
        if key not in self._agents:
            if key not in AGENT_REGISTRY:
                raise ValueError(f"Unknown agent: {key}")
            self._agents[key] = AGENT_REGISTRY[key](model=self.model)
        return self._agents[key]

    def parse_mentions(self, text: str) -> list[str]:
        """
        Extract agent mentions from message text.

        Returns list of agent keys that were mentioned.
        """
        mentioned = []
        text_lower = text.lower()

        for agent_key in AGENT_REGISTRY.keys():
            if f"@{agent_key}" in text_lower:
                mentioned.append(agent_key)

        return mentioned

    async def route(
        self,
        message: str,
        target: str | None = None,
    ) -> dict[str, str]:
        """
        Route message to agent(s).

        Args:
            message: The message to process
            target: Specific agent to route to (auto-routes if None)

        Returns:
            Dict of agent_key -> response
        """
        if target:
            targets = [target]
        else:
            targets = self.parse_mentions(message) or ["pm"]

        responses = {}
        for agent_key in targets:
            agent = self.get_agent(agent_key)
            responses[agent_key] = await agent.run(message)

        return responses


def create_slack_bot(
    model: str = "azure/gpt-4.1",
    default_channel: str = "#ai-team",
) -> SlackBot:
    """
    Factory function to create a configured SlackBot.

    Requires environment variables:
    - SLACK_BOT_TOKEN: Bot User OAuth Token
    - SLACK_APP_TOKEN: App-Level Token (for Socket Mode)
    """
    return SlackBot(model=model, default_channel=default_channel)


def cli_start_bot() -> None:
    """CLI entry point to start the Slack bot."""
    import argparse

    parser = argparse.ArgumentParser(description="Start VibeTeam Slack Bot")
    parser.add_argument(
        "--model",
        default="azure/gpt-4.1",
        help="LLM model for agents",
    )
    parser.add_argument(
        "--channel",
        default="#ai-team",
        help="Default channel for responses",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        bot = create_slack_bot(model=args.model, default_channel=args.channel)
        print(f"Starting VibeTeam Slack Bot...")
        print(f"  Model: {args.model}")
        print(f"  Channel: {args.channel}")
        print(f"  Agents: {', '.join(AGENT_REGISTRY.keys())}")
        print("\nBot is running. Press Ctrl+C to stop.")
        bot.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except ValueError as e:
        print(f"Error: {e}")
        print("\nRequired environment variables:")
        print("  SLACK_BOT_TOKEN - Bot User OAuth Token")
        print("  SLACK_APP_TOKEN - App-Level Token (Socket Mode)")


if __name__ == "__main__":
    cli_start_bot()
