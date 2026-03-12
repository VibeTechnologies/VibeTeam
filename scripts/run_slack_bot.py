#!/usr/bin/env python3
"""
Run the VibeTeam Slack bot with multi-session routing.

NOTE: from __future__ import annotations enables Python 3.10+ type syntax on 3.9+

This bot:
1. Monitors a Slack channel for messages mentioning role apps directly
   (e.g. @SupportEngineer, @ReleaseEngineer) or @VibeTeam for general routing
2. Routes messages to appropriate agents based on role app @mentions
3. Tracks thread subscriptions so agents see follow-up messages
4. Handles handoffs when agents mention other roles in responses

Usage:
    python scripts/run_slack_bot.py
    python scripts/run_slack_bot.py --channel "#ai-team"
    python scripts/run_slack_bot.py --framework openhands --debug

Message Format (per-agent Slack app identity):
    User: "@SupportEngineer investigate the login errors"
    SupportEngineer (app): "I'll investigate the login issue..."
    SupportEngineer (app): "Fixed in PR #457. @ReleaseEngineer ready for staging."
    ReleaseEngineer (app): "Deploying to staging now..."

Each agent responds via its own Slack app (not the ingress app).
Responses are attributed by Slack app identity, not text prefixes.

Environment Variables:
    SLACK_BOT_TOKEN: Ingress app token for receiving events (required)
    SLACK_BOT_TOKEN_<ROLE>: Per-role bot tokens (e.g. SLACK_BOT_TOKEN_SUPPORT_ENGINEER)
    SLACK_CHANNEL: Default channel to monitor
    AZURE_API_KEY: Azure OpenAI API key
    AZURE_API_BASE: Azure OpenAI endpoint
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import signal
import sys
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibeteam.connectors.slack import SlackConnector, SlackMessage
from vibeteam.router import Router, UnifiedMessage
from vibeteam.agents_config import get_slack_handle
from vibeteam.router.models import AgentRole

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("slack_bot")

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_requested = True


class AgentSessionManager:
    """Manages agent sessions for each role."""

    def __init__(self, framework: str = "crewai"):
        self.framework = framework
        self._sessions: dict[str, Any] = {}  # role -> agent instance

    def get_agent(self, role: AgentRole):
        """Get or create an agent for a role."""
        if role in self._sessions:
            return self._sessions[role]

        agent = self._create_agent(role)
        self._sessions[role] = agent
        return agent

    def _create_agent(self, role: AgentRole):
        """Create an agent instance for a role."""
        if self.framework == "crewai":
            return self._create_crewai_agent(role)
        elif self.framework == "autogen":
            return self._create_autogen_agent(role)
        elif self.framework == "openhands":
            return self._create_openhands_agent(role)
        else:
            return self._create_vibeteam_agent(role)

    def _create_vibeteam_agent(self, role: AgentRole):
        """Create a vibeteam agent."""
        from vibeteam.agents import (
            ProductManagerAgent,
            ReleaseEngineerAgent,
            SoftwareEngineerAgent,
            SupportEngineerAgent,
        )

        agents = {
            "software_engineer": SoftwareEngineerAgent,
            "release_engineer": ReleaseEngineerAgent,
            "support_engineer": SupportEngineerAgent,
            "product_manager": ProductManagerAgent,
            "marketing_manager": ProductManagerAgent,
        }
        agent_class = agents.get(role)
        if agent_class:
            return agent_class()
        raise ValueError(f"No agent class for role: {role}")

    def _create_crewai_agent(self, role: AgentRole):
        """Create a CrewAI agent."""
        try:
            from agent_service.crewai import (
                create_software_engineer,
                create_release_engineer,
                create_support_engineer,
                create_product_manager,
                create_marketing_manager,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning(f"CrewAI not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)

    def _create_autogen_agent(self, role: AgentRole):
        """Create an AutoGen agent."""
        try:
            from agent_service.autogen import (
                create_software_engineer,
                create_release_engineer,
                create_support_engineer,
                create_product_manager,
                create_marketing_manager,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning(f"AutoGen not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)

    def _create_openhands_agent(self, role: AgentRole):
        """Create an OpenHands agent."""
        try:
            from agent_service.openhands import (
                create_software_engineer,
                create_release_engineer,
                create_support_engineer,
                create_product_manager,
                create_marketing_manager,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning(f"OpenHands not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)


class VibeTeamSlackBot:
    """
    Multi-session Slack bot with message routing.

    Routes messages to appropriate agents based on /RoleName mentions
    and tracks thread subscriptions for follow-up messages.
    """

    def __init__(
        self,
        slack: SlackConnector,
        router: Router,
        session_manager: AgentSessionManager,
        channel: str,
    ):
        self.slack = slack
        self.router = router
        self.session_manager = session_manager
        self.channel = channel
        self.processed_ts: set[str] = set()
        self.our_bot_id = os.environ.get("SLACK_BOT_ID", "")

    def _to_unified_message(self, msg: SlackMessage) -> UnifiedMessage:
        """Convert Slack message to unified message format."""
        # Slack uses thread_ts for threading
        thread_id = msg.thread_ts or msg.ts

        return UnifiedMessage(
            source="slack",
            thread_id=thread_id,
            channel_id=self.channel,
            content=msg.text,
            author_id=msg.user,
            author_name=msg.user,  # Could look up display name
            is_bot=msg.is_bot,
            message_id=msg.ts,
            reply_to=msg.thread_ts if msg.thread_ts != msg.ts else None,
        )

    def _strip_slack_mentions(self, text: str) -> str:
        """Strip Slack user mentions from text."""
        return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    async def process_message(self, msg: SlackMessage) -> None:
        """Process a single Slack message."""
        unified = self._to_unified_message(msg)

        if msg.is_bot:
            result = await self.router.handle_bot_message(unified)
            if not result.mentioned_roles:
                return
            logger.info(f"Detected handoff to: {result.mentioned_roles}")
        else:
            result = await self.router.route_message(unified)

        for role in result.mentioned_roles:
            await self._run_agent_for_role(role, unified, msg)

    async def _run_agent_for_role(
        self, role: AgentRole, message: UnifiedMessage, original_msg: SlackMessage
    ) -> None:
        """Run an agent for a specific role and post response."""
        display_name = get_slack_handle(role) or role
        logger.info(f"Running {display_name} agent for: {message.content[:50]}...")

        try:
            agent = self.session_manager.get_agent(role)
            task = self._strip_slack_mentions(message.content)
            if not task:
                logger.warning(f"Empty task after stripping mentions")
                return

            response = await self._run_agent(agent, task)

            if response:
                formatted = f"[{display_name}] {response}"
                thread_ts = original_msg.thread_ts or original_msg.ts
                self.slack.post_message(
                    channel=self.channel,
                    text=formatted,
                    thread_ts=thread_ts,
                )
                logger.info(f"Posted {display_name} response in thread {thread_ts}")

        except Exception as e:
            logger.exception(f"Error running {display_name} agent: {e}")
            error_msg = f"[{display_name}] Error: {str(e)}"
            thread_ts = original_msg.thread_ts or original_msg.ts
            self.slack.post_message(
                channel=self.channel,
                text=error_msg,
                thread_ts=thread_ts,
            )

    async def _run_agent(self, agent, task: str) -> str | None:
        """Run an agent and return the response."""
        if hasattr(agent, "run_async"):
            result = await agent.run_async(task)
            if isinstance(result, dict):
                return result.get("response", "")
            return str(result) if result else None
        elif hasattr(agent, "run"):
            if asyncio.iscoroutinefunction(agent.run):
                result = await agent.run(task)
            else:
                result = await asyncio.to_thread(agent.run, task)
            if isinstance(result, dict):
                return result.get("response", "")
            return str(result) if result else None
        else:
            raise ValueError(f"Agent has no run method: {type(agent)}")

    async def poll_once(self) -> int:
        """Poll for new messages. Returns count processed."""
        messages = self.slack.get_channel_history(
            channel=self.channel,
            limit=20,
        )

        # Also get thread replies for threaded messages
        all_messages: list[SlackMessage] = []
        for msg in messages:
            all_messages.append(msg)
            if msg.thread_ts and msg.thread_ts == msg.ts:
                try:
                    replies = self.slack.get_thread_replies(self.channel, msg.ts)
                    for reply in replies:
                        if reply.ts != msg.ts:
                            all_messages.append(reply)
                except Exception as e:
                    logger.debug(f"Could not get thread replies: {e}")

        count = 0
        for msg in reversed(all_messages):
            if msg.ts in self.processed_ts:
                continue

            has_role_mention = bool(self.router.parse_role_mentions(msg.text))

            # Skip our own responses (messages starting with [RoleName])
            # UNLESS they contain a handoff mention to another agent
            if msg.is_bot and msg.text.startswith("["):
                if not has_role_mention:
                    self.processed_ts.add(msg.ts)
                    continue
                # Fall through to process handoff mentions in bot responses
                logger.info(f"Detected handoff in bot response: {msg.text[:80]}...")

            if msg.is_bot:
                # Process bot messages with /RoleName mentions (could be from eval script or handoffs)
                if has_role_mention:
                    logger.info(f"Processing bot message with role mention: {msg.text[:50]}...")
                    await self.process_message(msg)
                    count += 1
            else:
                if has_role_mention or "VibeTeam" in msg.text:
                    # Add eyes reaction
                    try:
                        self.slack.add_reaction(self.channel, msg.ts, "eyes")
                    except Exception as e:
                        logger.debug(f"Could not add reaction: {e}")

                    await self.process_message(msg)
                    count += 1

            self.processed_ts.add(msg.ts)

        return count


async def run_bot_loop(
    channel: str = "#ai-team",
    poll_interval: int = 5,
    framework: str = "crewai",
    once: bool = False,
) -> None:
    """Run the bot polling loop."""
    global shutdown_requested

    slack = SlackConnector()
    router = Router()
    session_manager = AgentSessionManager(framework=framework)

    bot = VibeTeamSlackBot(
        slack=slack,
        router=router,
        session_manager=session_manager,
        channel=channel,
    )

    logger.info(f"Starting VibeTeam Slack bot on {channel}")
    logger.info(f"Framework: {framework}, Poll interval: {poll_interval}s")

    while not shutdown_requested:
        try:
            count = await bot.poll_once()
            if count > 0:
                logger.info(f"Processed {count} message(s)")
        except Exception as e:
            logger.exception(f"Error in poll loop: {e}")

        if once:
            logger.info("Single poll complete, exiting")
            break

        await asyncio.sleep(poll_interval)

    logger.info("Bot stopped")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run the VibeTeam Slack bot with multi-session routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/run_slack_bot.py
    python scripts/run_slack_bot.py --channel "#engineering"
    python scripts/run_slack_bot.py --framework openhands --debug

The bot routes messages based on /RoleName mentions:
    /SoftwareEngineer, /ReleaseEngineer, /SupportEngineer,
    /ProductManager, /MarketingManager
        """,
    )
    parser.add_argument(
        "--channel",
        default="#ai-team",
        help="Slack channel to monitor (default: #ai-team)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between polls (default: 5)",
    )
    parser.add_argument(
        "--framework",
        choices=["crewai", "autogen", "openhands", "vibeteam"],
        default="crewai",
        help="Agent framework to use (default: crewai)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single poll and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.environ.get("SLACK_BOT_TOKEN"):
        logger.error("SLACK_BOT_TOKEN required")
        return 1

    if not os.environ.get("AZURE_API_KEY"):
        logger.error("AZURE_API_KEY required")
        return 1

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await run_bot_loop(
        channel=args.channel,
        poll_interval=args.poll_interval,
        framework=args.framework,
        once=args.once,
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
