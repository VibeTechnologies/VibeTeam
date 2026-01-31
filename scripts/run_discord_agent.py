#!/usr/bin/env python3
"""
Run a VibeTeam agent in Discord polling mode.

This script runs an agent that:
1. Polls a Discord channel for new messages
2. Responds to @role mentions directed at the agent
3. Posts responses via webhooks for custom agent identity

Key difference from Slack: Discord uses role-based mentions. A single bot
can have multiple roles assigned. Users mention @SoftwareEngineer (role),
and the bot routes to the appropriate agent logic.

Usage:
    python scripts/run_discord_agent.py --agent swe
    python scripts/run_discord_agent.py --agent support --poll-interval 10
    python scripts/run_discord_agent.py --agent release --once  # Single poll, then exit

Environment Variables:
    DISCORD_BOT_TOKEN: Discord bot token (required for reading messages)
    DISCORD_GUILD_ID: Discord server/guild ID
    DISCORD_CHANNEL_ID: Default channel ID to monitor

    # Role IDs (created in server, assigned to bot)
    DISCORD_ROLE_SWE: Role ID for SoftwareEngineer
    DISCORD_ROLE_RELEASE: Role ID for ReleaseEngineer
    DISCORD_ROLE_SUPPORT: Role ID for SupportEngineer
    DISCORD_ROLE_PM: Role ID for ProductManager
    DISCORD_ROLE_MARKETING: Role ID for MarketingManager

    # Webhook URLs (for custom agent identities)
    DISCORD_WEBHOOK_SWE: Webhook URL for SWE responses
    DISCORD_WEBHOOK_RELEASE: Webhook URL for Release responses
    DISCORD_WEBHOOK_SUPPORT: Webhook URL for Support responses
    DISCORD_WEBHOOK_PM: Webhook URL for PM responses
    DISCORD_WEBHOOK_MARKETING: Webhook URL for Marketing responses

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

# Load environment variables from .env file
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibeteam.agents import (
    ProductManagerAgent,
    ReleaseEngineerAgent,
    SoftwareEngineerAgent,
    SupportEngineerAgent,
    SupervisorAgent,
)
from vibeteam.connectors.discord import DiscordConnector, DiscordMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("discord_agent")

# Agent key to class mapping
AGENT_CLASSES = {
    "pm": ProductManagerAgent,
    "swe": SoftwareEngineerAgent,
    "support": SupportEngineerAgent,
    "release": ReleaseEngineerAgent,
    "supervisor": SupervisorAgent,
}

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_requested = True


def create_agent(agent_key: str):
    """Create an agent instance by key."""
    agent_class = AGENT_CLASSES.get(agent_key.lower())
    if not agent_class:
        raise ValueError(
            f"Unknown agent key: {agent_key}. Valid options: {', '.join(AGENT_CLASSES.keys())}"
        )
    return agent_class()


async def process_message(
    agent,
    discord: DiscordConnector,
    message: DiscordMessage,
    agent_key: str,
) -> str | None:
    """
    Process a single message and return the response.

    Args:
        agent: The agent instance
        discord: Discord connector
        message: The message to process
        agent_key: The agent's key (for formatting and webhook)

    Returns:
        The response text, or None if no response
    """
    # Extract the actual task from the message
    # Remove role and user mentions from the beginning
    task = discord.strip_mentions(message.content)

    if not task:
        logger.warning(f"Empty task after stripping mentions: {message.content}")
        return None

    logger.info(f"Processing task: {task[:100]}...")

    try:
        response = await agent.run(task)
        return response
    except Exception as e:
        logger.exception(f"Error processing message: {e}")
        return f"Error processing request: {str(e)}"


async def run_agent_loop(
    agent_key: str,
    channel_id: str | None = None,
    poll_interval: int = 5,
    lookback_minutes: int = 5,
    once: bool = False,
    allow_bot: bool = False,
) -> None:
    """
    Run the agent polling loop.

    Args:
        agent_key: Agent key (pm, swe, support, release, supervisor)
        channel_id: Discord channel ID to monitor (uses default if None)
        poll_interval: Seconds between polls
        lookback_minutes: How far back to look for messages on startup
        once: If True, run once and exit
        allow_bot: If True, process bot messages (for testing only)
    """
    global shutdown_requested

    # Initialize
    discord = DiscordConnector()
    agent = create_agent(agent_key)
    processed_ids: set[str] = set()

    # Use default channel if not specified
    channel_id = channel_id or discord.default_channel_id
    if not channel_id:
        logger.error("Channel ID required. Set DISCORD_CHANNEL_ID or use --channel")
        return

    logger.info(f"Starting {agent_key.upper()} agent on channel {channel_id}")
    logger.info(f"Poll interval: {poll_interval}s, Lookback: {lookback_minutes}min")
    logger.info(f"Agent model: {agent.model}")

    # Track the last message ID we've seen for pagination
    last_seen_id: str | None = None

    iteration = 0
    while not shutdown_requested:
        iteration += 1
        logger.debug(f"Poll iteration {iteration}")

        try:
            # Get recent messages
            # On first iteration, get all recent messages
            # On subsequent iterations, only get messages after the last one we processed
            messages = discord.get_channel_history(
                channel_id=channel_id,
                limit=20,
                after=last_seen_id if iteration > 1 else None,
            )

            # Process messages (oldest first for chronological order)
            for msg in reversed(messages):
                # Update last seen ID
                if not last_seen_id or msg.id > last_seen_id:
                    last_seen_id = msg.id

                # Skip already processed
                if msg.id in processed_ids:
                    continue

                # Skip bot messages (including our own) unless allow_bot is set
                if msg.is_bot and not allow_bot:
                    processed_ids.add(msg.id)
                    continue

                # Check if this message is for us (mentions our role)
                if not discord.is_mention_for_agent(msg, agent_key):
                    # Not for us, but still mark as seen
                    processed_ids.add(msg.id)
                    continue

                logger.info(f"Found message for {agent_key}: {msg.content[:50]}...")

                # Process the message
                response = await process_message(agent, discord, msg, agent_key)

                if response:
                    # Format response with agent identity
                    formatted = discord.format_agent_message(
                        agent_name=agent.name,
                        message=response,
                    )

                    # Post via webhook (preferred for custom identity)
                    result = discord.post_webhook_message(
                        agent_key=agent_key,
                        content=formatted,
                    )

                    if result:
                        logger.info(f"Posted response via webhook for {agent_key}")
                    else:
                        # Fallback to bot API
                        discord.post_message(
                            channel_id=channel_id,
                            content=formatted,
                            reply_to=msg.id,
                        )
                        logger.info(f"Posted response via bot API (webhook not configured)")

                # Mark as processed
                processed_ids.add(msg.id)

                # Reset agent for next task
                agent.reset()

        except Exception as e:
            logger.exception(f"Error in poll loop: {e}")

        # Exit if running in once mode
        if once:
            logger.info("Single poll complete, exiting")
            break

        # Wait before next poll
        await asyncio.sleep(poll_interval)

    # Cleanup
    discord.close()
    logger.info("Agent loop stopped")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run a VibeTeam agent in Discord polling mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run support agent on default channel
    python scripts/run_discord_agent.py --agent support

    # Run SWE agent with 10s poll interval
    python scripts/run_discord_agent.py --agent swe --poll-interval 10

    # Run on specific channel
    python scripts/run_discord_agent.py --agent pm --channel 1234567890

    # Single poll for testing
    python scripts/run_discord_agent.py --agent release --once

Available agents:
    pm        - Product Manager (Curie)
    swe       - Software Engineer (Turing)
    support   - Support Engineer (Darwin)
    release   - Release Engineer (Einstein)
    supervisor - Supervisor (Planck)

Required Environment Variables:
    DISCORD_BOT_TOKEN    - Bot token from Developer Portal
    DISCORD_CHANNEL_ID   - Default channel to monitor
    DISCORD_ROLE_<AGENT> - Role IDs for each agent (e.g., DISCORD_ROLE_SWE)
    DISCORD_WEBHOOK_<AGENT> - Webhook URLs for responses (e.g., DISCORD_WEBHOOK_SWE)
        """,
    )
    parser.add_argument(
        "--agent",
        choices=list(AGENT_CLASSES.keys()),
        required=True,
        help="Agent to run",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Discord channel ID to monitor (default: DISCORD_CHANNEL_ID env var)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between polls (default: 5)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Minutes to look back for messages on startup (default: 5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single poll and exit (for testing)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--allow-bot",
        action="store_true",
        help="Process bot messages (for testing only)",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate environment
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        logger.error("DISCORD_BOT_TOKEN environment variable required")
        return 1

    if not os.environ.get("AZURE_API_KEY"):
        logger.error("AZURE_API_KEY environment variable required")
        return 1

    # Check for role and webhook config (warning only)
    agent_upper = args.agent.upper()
    if not os.environ.get(f"DISCORD_ROLE_{agent_upper}"):
        logger.warning(f"DISCORD_ROLE_{agent_upper} not set - text-based mentions will be used")
    if not os.environ.get(f"DISCORD_WEBHOOK_{agent_upper}"):
        logger.warning(f"DISCORD_WEBHOOK_{agent_upper} not set - bot API will be used for responses")

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the agent loop
    await run_agent_loop(
        agent_key=args.agent,
        channel_id=args.channel,
        poll_interval=args.poll_interval,
        lookback_minutes=args.lookback,
        once=args.once,
        allow_bot=args.allow_bot,
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
