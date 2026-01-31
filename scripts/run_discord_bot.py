#!/usr/bin/env python3
"""
Run the VibeTeam Discord bot with multi-session routing.

This bot:
1. Monitors a Discord channel for messages mentioning @VibeTeam
2. Routes messages to appropriate agents based on /RoleName mentions
3. Tracks thread subscriptions so agents see follow-up messages
4. Handles handoffs when agents mention other roles in responses

Usage:
    python scripts/run_discord_bot.py
    python scripts/run_discord_bot.py --channel 1234567890
    python scripts/run_discord_bot.py --poll-interval 10 --debug

Message Format:
    User: "@VibeTeam /SoftwareEngineer fix the login bug"
    Bot:  "[SoftwareEngineer] I'll investigate the login issue..."
    Bot:  "[SoftwareEngineer] Fixed in PR #457. /ReleaseEngineer ready for staging."
    Bot:  "[ReleaseEngineer] Deploying to staging now..."

Environment Variables:
    DISCORD_BOT_TOKEN: Discord bot token (required)
    DISCORD_CHANNEL_ID: Default channel to monitor
    AZURE_API_KEY: Azure OpenAI API key
    AZURE_API_BASE: Azure OpenAI endpoint
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibeteam.connectors.discord import DiscordConnector, DiscordMessage
from vibeteam.router import Router, UnifiedMessage
from vibeteam.router.models import AgentRole, ROLE_DISPLAY_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("discord_bot")

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

        # Create agent based on role and framework
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
            # Default to vibeteam agents
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
            "marketing_manager": ProductManagerAgent,  # Fallback
        }
        agent_class = agents.get(role)
        if agent_class:
            return agent_class()
        raise ValueError(f"No agent class for role: {role}")

    def _create_crewai_agent(self, role: AgentRole):
        """Create a CrewAI agent."""
        try:
            from agents.crewai import (
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
            from agents.autogen import (
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
            from agents.openhands import (
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


class VibeTeamBot:
    """
    Multi-session Discord bot with message routing.

    Routes messages to appropriate agents based on /RoleName mentions
    and tracks thread subscriptions for follow-up messages.
    """

    def __init__(
        self,
        discord: DiscordConnector,
        router: Router,
        session_manager: AgentSessionManager,
        channel_id: str,
    ):
        self.discord = discord
        self.router = router
        self.session_manager = session_manager
        self.channel_id = channel_id
        self.processed_ids: set[str] = set()
        self.last_seen_id: str | None = None
        self.our_bot_id = os.environ.get("DISCORD_BOT_ID", "")

    def _to_unified_message(self, msg: DiscordMessage) -> UnifiedMessage:
        """Convert Discord message to unified message format."""
        # Discord thread_id is the parent message ID for threads
        # For non-threaded messages, use the message ID itself
        thread_id = msg.id  # TODO: Handle Discord threads properly

        return UnifiedMessage(
            source="discord",
            thread_id=thread_id,
            channel_id=self.channel_id,
            content=msg.content,
            author_id=msg.author_id,
            author_name=msg.author_name,
            is_bot=msg.is_bot,
            message_id=msg.id,
        )

    async def process_message(self, msg: DiscordMessage) -> None:
        """Process a single Discord message."""
        unified = self._to_unified_message(msg)

        # Route the message
        if msg.is_bot:
            # Check for handoffs in bot messages
            result = await self.router.handle_bot_message(unified)
            if not result.mentioned_roles:
                return  # No handoff, nothing to do
            logger.info(f"Detected handoff to: {result.mentioned_roles}")
        else:
            # Regular user message
            result = await self.router.route_message(unified)

        # Process for each mentioned role
        for role in result.mentioned_roles:
            await self._run_agent_for_role(role, unified)

    async def _run_agent_for_role(
        self, role: AgentRole, message: UnifiedMessage
    ) -> None:
        """Run an agent for a specific role and post response."""
        display_name = ROLE_DISPLAY_NAMES.get(role, role)
        logger.info(f"Running {display_name} agent for message: {message.content[:50]}...")

        try:
            # Get or create agent for this role
            agent = self.session_manager.get_agent(role)

            # Strip mentions from content to get the actual task
            task = self.discord.strip_mentions(message.content)
            if not task:
                logger.warning(f"Empty task after stripping mentions")
                return

            # Run the agent
            response = await self._run_agent(agent, task)

            if response:
                # Format with role prefix
                formatted = f"[{display_name}] {response}"

                # Post response
                self.discord.post_message(
                    channel_id=self.channel_id,
                    content=formatted,
                    reply_to=message.message_id,
                )
                logger.info(f"Posted {display_name} response")

        except Exception as e:
            logger.exception(f"Error running {display_name} agent: {e}")
            # Post error message
            error_msg = f"[{display_name}] Error: {str(e)}"
            self.discord.post_message(
                channel_id=self.channel_id,
                content=error_msg,
                reply_to=message.message_id,
            )

    async def _run_agent(self, agent, task: str) -> str | None:
        """Run an agent and return the response."""
        # Handle different agent interfaces
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
        """Poll for new messages once. Returns count of messages processed."""
        messages = self.discord.get_channel_history(
            channel_id=self.channel_id,
            limit=20,
            after=self.last_seen_id,
        )

        count = 0
        # Process oldest first
        for msg in reversed(messages):
            # Update last seen
            if not self.last_seen_id or msg.id > self.last_seen_id:
                self.last_seen_id = msg.id

            # Skip already processed
            if msg.id in self.processed_ids:
                continue

            # Check if message contains our bot mention or role mention
            has_role_mention = bool(self.router.parse_role_mentions(msg.content))

            if msg.is_bot:
                # Only process our own bot messages for handoffs
                if has_role_mention:
                    await self.process_message(msg)
                    count += 1
            else:
                # User message - check for @VibeTeam or role mentions
                if has_role_mention or "@VibeTeam" in msg.content:
                    # React with eyes emoji to acknowledge
                    try:
                        self.discord.add_reaction(msg.id, self.channel_id, "👀")
                    except Exception as e:
                        logger.debug(f"Could not add reaction: {e}")

                    await self.process_message(msg)
                    count += 1

            self.processed_ids.add(msg.id)

        return count


async def run_bot_loop(
    channel_id: str | None = None,
    poll_interval: int = 5,
    framework: str = "crewai",
    once: bool = False,
) -> None:
    """Run the bot polling loop."""
    global shutdown_requested

    # Initialize components
    discord = DiscordConnector()
    router = Router()
    session_manager = AgentSessionManager(framework=framework)

    channel_id = channel_id or discord.default_channel_id
    if not channel_id:
        logger.error("Channel ID required. Set DISCORD_CHANNEL_ID or use --channel")
        return

    bot = VibeTeamBot(
        discord=discord,
        router=router,
        session_manager=session_manager,
        channel_id=channel_id,
    )

    logger.info(f"Starting VibeTeam bot on channel {channel_id}")
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

    discord.close()
    logger.info("Bot stopped")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run the VibeTeam Discord bot with multi-session routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/run_discord_bot.py
    python scripts/run_discord_bot.py --channel 1234567890
    python scripts/run_discord_bot.py --framework openhands --debug

The bot routes messages based on /RoleName mentions:
    /SoftwareEngineer, /ReleaseEngineer, /SupportEngineer,
    /ProductManager, /MarketingManager

Or @RoleName mentions work too.
        """,
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Discord channel ID (default: DISCORD_CHANNEL_ID env var)",
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

    # Validate environment
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        logger.error("DISCORD_BOT_TOKEN required")
        return 1

    if not os.environ.get("AZURE_API_KEY"):
        logger.error("AZURE_API_KEY required")
        return 1

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await run_bot_loop(
        channel_id=args.channel,
        poll_interval=args.poll_interval,
        framework=args.framework,
        once=args.once,
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
