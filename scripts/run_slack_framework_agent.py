#!/usr/bin/env python3
"""
Run a VibeTeam agent as a Slack listener.

This script runs any framework's agent (AutoGen, CrewAI, OpenHands) as a
Slack listener that responds to @mentions in a channel.

Usage:
    python scripts/run_slack_framework_agent.py --framework autogen --agent support
    python scripts/run_slack_framework_agent.py --framework crewai --agent swe
    python scripts/run_slack_framework_agent.py --framework openhands --agent release

The agent will:
1. Subscribe to the configured Slack channel
2. Listen for @mentions directed at its role
3. Process tasks and respond in Slack
4. Use transfer tools to hand off to other agents (who also run as listeners)
"""

import argparse
import asyncio
import os
import re
import signal
import sys
from datetime import datetime, timedelta
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


# Agent key mappings
AGENT_ALIASES = {
    # Short names
    "swe": "software_engineer",
    "release": "release_engineer",
    "support": "support_engineer",
    "pm": "product_manager",
    "marketer": "marketing_manager",
    # Full names
    "software_engineer": "software_engineer",
    "release_engineer": "release_engineer",
    "support_engineer": "support_engineer",
    "product_manager": "product_manager",
    "marketing_manager": "marketing_manager",
}

# Slack @mention keywords to agent mapping
MENTION_KEYWORDS = {
    "swe": "software_engineer",
    "software": "software_engineer",
    "alan": "software_engineer",
    "release": "release_engineer",
    "einstein": "release_engineer",
    "support": "support_engineer",
    "grace": "support_engineer",
    "pm": "product_manager",
    "maya": "product_manager",
    "product": "product_manager",
    "marketer": "marketing_manager",
    "marketing": "marketing_manager",
}


def get_agent_class(framework: str, agent_key: str) -> type:
    """Get the agent class for a framework and agent key."""
    agent_name = AGENT_ALIASES.get(agent_key, agent_key)

    if framework == "autogen":
        if agent_name == "software_engineer":
            from agents.agent_service.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
        elif agent_name == "release_engineer":
            from agents.agent_service.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
        elif agent_name == "support_engineer":
            from agents.agent_service.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif agent_name == "product_manager":
            from agents.agent_service.autogen.product_manager import AutoGenProductManager

            return AutoGenProductManager
        else:
            raise ValueError(f"Unknown agent: {agent_key}")

    elif framework == "crewai":
        if agent_name == "software_engineer":
            from agents.agent_service.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
        elif agent_name == "release_engineer":
            from agents.agent_service.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
        elif agent_name == "support_engineer":
            from agents.agent_service.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif agent_name == "product_manager":
            from agents.agent_service.crewai.product_manager import CrewAIProductManager

            return CrewAIProductManager
        else:
            raise ValueError(f"Unknown agent: {agent_key}")

    elif framework == "openhands":
        if agent_name == "software_engineer":
            from agents.agent_service.openhands.software_engineer import OpenHandsSoftwareEngineer

            return OpenHandsSoftwareEngineer
        elif agent_name == "release_engineer":
            from agents.agent_service.openhands.release_engineer import OpenHandsReleaseEngineer

            return OpenHandsReleaseEngineer
        elif agent_name == "support_engineer":
            from agents.agent_service.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif agent_name == "product_manager":
            from agents.agent_service.openhands.product_manager import OpenHandsProductManager

            return OpenHandsProductManager
        else:
            raise ValueError(f"Unknown agent: {agent_key}")

    else:
        raise ValueError(f"Unknown framework: {framework}")


def is_mention_for_agent(text: str, agent_key: str) -> bool:
    """Check if a message text contains an @mention for the agent."""
    agent_name = AGENT_ALIASES.get(agent_key, agent_key)
    text_lower = text.lower()

    # Check for direct agent key mentions
    if f"@{agent_key}" in text_lower:
        return True

    # Check for keyword mentions
    for keyword, target_agent in MENTION_KEYWORDS.items():
        if target_agent == agent_name and f"@{keyword}" in text_lower:
            return True

    return False


def extract_task_from_mention(text: str, agent_key: str) -> str:
    """Extract the task description from a message with @mention."""
    # Remove all @mentions from the text
    task = re.sub(r"@\w+", "", text).strip()
    # Clean up extra whitespace
    task = re.sub(r"\s+", " ", task)
    return task


class SlackAgentRunner:
    """Run an agent as a Slack listener."""

    def __init__(
        self,
        framework: str,
        agent_key: str,
        channel: str | None = None,
        poll_interval: int = 5,
    ):
        self.framework = framework
        self.agent_key = agent_key
        self.agent_name = AGENT_ALIASES.get(agent_key, agent_key)
        self.channel = channel or os.getenv("SLACK_CHANNEL", "#ai-team")
        self.poll_interval = poll_interval
        self.running = False
        self.last_processed_ts = None
        self.agent = None
        self.connector = None

    def setup(self):
        """Set up the agent and Slack connector."""
        from vibeteam.connectors.slack import SlackConnector
        from agents.shared.slack_tools import set_slack_context

        # Create agent
        AgentClass = get_agent_class(self.framework, self.agent_key)
        self.agent = AgentClass()

        # Create Slack connector
        self.connector = SlackConnector()

        # Set Slack context for handoffs
        set_slack_context(
            connector=self.connector,
            channel=self.channel,
            from_agent=self.agent_name.replace("_", " ").title(),
        )

        print(f"[{self.framework}] {self.agent_name} listening on {self.channel}")

    async def process_message(self, message: dict[str, Any]) -> str | None:
        """Process a Slack message and return response."""
        text = message.get("text", "")
        thread_ts = message.get("thread_ts") or message.get("ts")
        user = message.get("user", "unknown")

        # Extract task from message
        task = extract_task_from_mention(text, self.agent_key)
        if not task:
            return None

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processing: {task[:100]}...")

        # Update Slack context with thread
        from agents.shared.slack_tools import set_slack_context

        set_slack_context(
            connector=self.connector,
            channel=self.channel,
            thread_ts=thread_ts,
            from_agent=self.agent_name.replace("_", " ").title(),
        )

        try:
            # Run agent (async if available)
            if hasattr(self.agent, "run_async"):
                result = await self.agent.run_async(
                    task=task,
                    context_type="slack",
                    context_id=thread_ts,
                )
            else:
                result = self.agent.run(
                    task=task,
                    context_type="slack",
                    context_id=thread_ts,
                )

            response = result.get("response", "")

            # Post response to Slack
            if response:
                self.connector.post_message(
                    channel=self.channel,
                    text=response,
                    thread_ts=thread_ts,
                )

            return response

        except Exception as e:
            error_msg = f"Error processing task: {e}"
            print(f"[ERROR] {error_msg}")
            self.connector.post_message(
                channel=self.channel,
                text=f"Sorry, I encountered an error: {e}",
                thread_ts=thread_ts,
            )
            return None

    async def poll_messages(self):
        """Poll Slack for new messages."""
        try:
            messages = self.connector.get_channel_history(
                channel=self.channel,
                limit=20,
            )

            # Filter to messages newer than last processed
            if self.last_processed_ts:
                # Parse ts to compare
                last_ts = float(self.last_processed_ts)
                messages = [m for m in messages if float(m.ts) > last_ts]

            # Process messages that mention this agent
            for msg in messages:
                # Skip bot messages
                if msg.bot_id or msg.user == self.connector.bot_user_id:
                    continue

                # Check if message is for this agent
                if is_mention_for_agent(msg.text, self.agent_key):
                    message_dict = {
                        "text": msg.text,
                        "ts": msg.ts,
                        "thread_ts": msg.thread_ts,
                        "user": msg.user,
                    }
                    await self.process_message(message_dict)
                    self.last_processed_ts = msg.ts

        except Exception as e:
            print(f"[ERROR] Polling failed: {e}")

    async def run(self):
        """Run the polling loop."""
        self.running = True

        # Set initial timestamp to now (don't process old messages)
        self.last_processed_ts = str(datetime.now().timestamp())

        print(f"Started polling (interval: {self.poll_interval}s)")

        while self.running:
            await self.poll_messages()
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop the polling loop."""
        self.running = False
        print("Stopping...")


def main():
    parser = argparse.ArgumentParser(description="Run a VibeTeam agent as a Slack listener")
    parser.add_argument(
        "--framework",
        "-f",
        choices=["autogen", "crewai", "openhands"],
        required=True,
        help="Agent framework to use",
    )
    parser.add_argument(
        "--agent",
        "-a",
        choices=list(AGENT_ALIASES.keys()),
        required=True,
        help="Agent to run",
    )
    parser.add_argument(
        "--channel",
        "-c",
        default=None,
        help="Slack channel to listen on (default: SLACK_CHANNEL env var or #ai-team)",
    )
    parser.add_argument(
        "--poll-interval",
        "-p",
        type=int,
        default=5,
        help="Polling interval in seconds (default: 5)",
    )

    args = parser.parse_args()

    runner = SlackAgentRunner(
        framework=args.framework,
        agent_key=args.agent,
        channel=args.channel,
        poll_interval=args.poll_interval,
    )

    # Handle signals
    def signal_handler(sig, frame):
        runner.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Setup and run
    runner.setup()
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
