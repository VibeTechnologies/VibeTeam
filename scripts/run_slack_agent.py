#!/usr/bin/env python3
"""
Run a VibeTeam agent in Slack polling mode.

This script runs an agent that:
1. Polls a Slack channel for new messages
2. Responds to @mentions directed at the agent
3. Posts responses in threads for context

Usage:
    python scripts/run_slack_agent.py --agent support --channel "#ai-team"
    python scripts/run_slack_agent.py --agent swe --poll-interval 10
    python scripts/run_slack_agent.py --agent release --once  # Single poll, then exit

Environment Variables:
    SLACK_BOT_TOKEN: Slack bot OAuth token (required)
    SLACK_AGENT_SWE: Slack user ID for SWE agent
    SLACK_AGENT_SUPPORT: Slack user ID for Support agent
    SLACK_AGENT_RELEASE: Slack user ID for Release agent
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
from vibeteam.connectors.slack import SlackConnector, SlackMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("slack_agent")

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
    slack: SlackConnector,
    message: SlackMessage,
    agent_key: str,
) -> str | None:
    """
    Process a single message and return the response.

    Args:
        agent: The agent instance
        slack: Slack connector
        message: The message to process
        agent_key: The agent's key (for formatting)

    Returns:
        The response text, or None if no response
    """
    # Extract the actual task from the message
    # Remove the @mention prefix if present
    task = message.text

    # Strip any <@USER_ID> mentions from the beginning
    import re

    task = re.sub(r"^<@[A-Z0-9]+>\s*", "", task).strip()

    if not task:
        logger.warning(f"Empty task after stripping mentions: {message.text}")
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
    channel: str,
    poll_interval: int = 5,
    lookback_minutes: int = 5,
    once: bool = False,
    allow_bot: bool = False,
) -> None:
    """
    Run the agent polling loop.

    Args:
        agent_key: Agent key (pm, swe, support, release, supervisor)
        channel: Slack channel to monitor
        poll_interval: Seconds between polls
        lookback_minutes: How far back to look for messages on startup
        once: If True, run once and exit
        allow_bot: If True, process bot messages (for testing only)
    """
    global shutdown_requested

    # Initialize
    slack = SlackConnector()
    agent = create_agent(agent_key)
    processed_ts: set[str] = set()

    # Calculate initial lookback timestamp
    lookback_time = datetime.now() - timedelta(minutes=lookback_minutes)
    oldest_ts = str(lookback_time.timestamp())

    logger.info(f"Starting {agent_key.upper()} agent on {channel}")
    logger.info(f"Poll interval: {poll_interval}s, Lookback: {lookback_minutes}min")
    logger.info(f"Agent model: {agent.model}")

    iteration = 0
    while not shutdown_requested:
        iteration += 1
        logger.debug(f"Poll iteration {iteration}")

        try:
            # Get recent messages
            messages = slack.get_channel_history(
                channel=channel,
                limit=20,
                oldest=oldest_ts if iteration == 1 else None,
            )

            # Process messages (newest first, so reverse for chronological order)
            for msg in reversed(messages):
                # Skip already processed
                if msg.ts in processed_ts:
                    continue

                # Skip bot messages (including our own) unless allow_bot is set
                if msg.is_bot and not allow_bot:
                    processed_ts.add(msg.ts)
                    continue

                # Check if this message is for us
                if not slack.is_mention_for_agent(msg, agent_key):
                    # Not for us, but still mark as seen
                    processed_ts.add(msg.ts)
                    continue

                logger.info(f"Found message for {agent_key}: {msg.text[:50]}...")

                # Process the message
                response = await process_message(agent, slack, msg, agent_key)

                if response:
                    # Format response with agent identity
                    formatted = slack.format_agent_message(
                        agent_name=agent.name,
                        message=response,
                    )

                    # Post in thread
                    thread_ts = msg.thread_ts or msg.ts
                    slack.post_message(
                        channel=channel,
                        text=formatted,
                        thread_ts=thread_ts,
                    )
                    logger.info(f"Posted response in thread {thread_ts}")

                # Mark as processed
                processed_ts.add(msg.ts)

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

    logger.info("Agent loop stopped")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run a VibeTeam agent in Slack polling mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run support agent on #ai-team
    python scripts/run_slack_agent.py --agent support --channel "#ai-team"

    # Run SWE agent with 10s poll interval
    python scripts/run_slack_agent.py --agent swe --poll-interval 10

    # Single poll for testing
    python scripts/run_slack_agent.py --agent pm --once

Available agents:
    pm        - Product Manager (Curie)
    swe       - Software Engineer (Turing)
    support   - Support Engineer (Darwin)
    release   - Release Engineer (Einstein)
    supervisor - Supervisor (Planck)
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
    if not os.environ.get("SLACK_BOT_TOKEN"):
        logger.error("SLACK_BOT_TOKEN environment variable required")
        return 1

    if not os.environ.get("AZURE_API_KEY"):
        logger.error("AZURE_API_KEY environment variable required")
        return 1

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the agent loop
    await run_agent_loop(
        agent_key=args.agent,
        channel=args.channel,
        poll_interval=args.poll_interval,
        lookback_minutes=args.lookback,
        once=args.once,
        allow_bot=args.allow_bot,
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
