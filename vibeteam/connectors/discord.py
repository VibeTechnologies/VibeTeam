"""
Discord Connector - API integration for Discord messaging.

Provides functionality to:
- Post messages to channels
- Read channel history
- Handle @role mentions for agent routing
- Send responses via webhooks (for custom agent identities)
- Thread-style replies

Uses discord.py for bot functionality and httpx for webhook posting.

Key difference from Slack: Discord uses role-based mentions. A single bot
can have multiple roles assigned, and we route messages to the appropriate
agent based on which role is mentioned.

API Docs: https://discord.com/developers/docs/reference
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DiscordMessage:
    """Represents a Discord message."""

    id: str  # Message ID
    channel_id: str
    author_id: str
    author_name: str
    content: str
    timestamp: datetime | None
    is_bot: bool
    role_mentions: list[str]  # Role IDs mentioned
    user_mentions: list[str]  # User IDs mentioned
    reference_id: str | None = None  # Reply reference message ID

    @property
    def permalink(self) -> str:
        """Generate a message reference."""
        return f"{self.channel_id}/{self.id}"


@dataclass
class DiscordRole:
    """Represents a Discord role."""

    id: str
    name: str
    mentionable: bool
    color: int


# Agent key to Discord role ID mapping
# Populated from environment variables: DISCORD_ROLE_SWE, DISCORD_ROLE_PM, etc.
AGENT_ROLE_MAP: dict[str, str] = {}

# Agent key to webhook URL mapping
# For posting responses with custom agent identity
AGENT_WEBHOOK_MAP: dict[str, str] = {}

# Agent display names and avatars
AGENT_DISPLAY_INFO: dict[str, dict[str, str]] = {
    "swe": {
        "name": "SoftwareEngineer",
        "emoji": ":computer:",
    },
    "release": {
        "name": "ReleaseEngineer",
        "emoji": ":rocket:",
    },
    "support": {
        "name": "SupportEngineer",
        "emoji": ":headphones:",
    },
    "pm": {
        "name": "ProductManager",
        "emoji": ":chart_with_upwards_trend:",
    },
    "marketing": {
        "name": "MarketingManager",
        "emoji": ":mega:",
    },
    "supervisor": {
        "name": "ProductManager",
        "emoji": ":chart_with_upwards_trend:",
    },
    "sre": {
        "name": "SiteReliabilityEngineer",
        "emoji": ":shield:",
    },
}


class DiscordConnector:
    """
    Discord API connector for messaging.

    Supports two modes of operation:
    1. Bot API: For reading messages and receiving events
    2. Webhooks: For posting messages with custom identities per agent

    Usage:
        connector = DiscordConnector()

        # Post message via webhook (custom identity)
        connector.post_webhook_message("swe", "I'll fix that bug!")

        # Check if a message mentions a specific agent role
        if connector.is_mention_for_agent(message, "swe"):
            # Process with SWE agent

        # Mention another agent (for handoffs)
        connector.mention_agent("release", "Ready for deployment!")
    """

    def __init__(
        self,
        bot_token: str | None = None,
        guild_id: str | None = None,
        channel_id: str | None = None,
    ):
        """
        Initialize Discord connector.

        Args:
            bot_token: Discord bot token (or from DISCORD_BOT_TOKEN env)
            guild_id: Discord server/guild ID (or from DISCORD_GUILD_ID env)
            channel_id: Default channel ID (or from DISCORD_CHANNEL_ID env)
        """
        self.bot_token = bot_token or os.environ.get("DISCORD_BOT_TOKEN")
        self.guild_id = guild_id or os.environ.get("DISCORD_GUILD_ID")
        self.default_channel_id = channel_id or os.environ.get("DISCORD_CHANNEL_ID")

        # Bot token is optional - webhooks can work without it
        self._bot_user_id: str | None = None

        # HTTP client for API calls
        self._http_client: httpx.Client | None = None

        # Load agent role and webhook mappings from environment
        self._load_agent_mappings()

    def _load_agent_mappings(self) -> None:
        """Load agent-to-role and agent-to-webhook mappings from environment."""
        global AGENT_ROLE_MAP, AGENT_WEBHOOK_MAP

        # Role mappings: DISCORD_ROLE_SWE=123456789
        role_prefixes = {
            "DISCORD_ROLE_SWE": "swe",
            "DISCORD_ROLE_RELEASE": "release",
            "DISCORD_ROLE_SUPPORT": "support",
            "DISCORD_ROLE_PM": "pm",
            "DISCORD_ROLE_MARKETING": "marketing",
            "DISCORD_ROLE_SUPERVISOR": "supervisor",
            "DISCORD_ROLE_SRE": "sre",
        }
        for env_key, agent_key in role_prefixes.items():
            value = os.environ.get(env_key)
            if value:
                AGENT_ROLE_MAP[agent_key] = value

        # Webhook mappings: DISCORD_WEBHOOK_SWE=https://discord.com/api/webhooks/...
        webhook_prefixes = {
            "DISCORD_WEBHOOK_SWE": "swe",
            "DISCORD_WEBHOOK_RELEASE": "release",
            "DISCORD_WEBHOOK_SUPPORT": "support",
            "DISCORD_WEBHOOK_PM": "pm",
            "DISCORD_WEBHOOK_MARKETING": "marketing",
            "DISCORD_WEBHOOK_SUPERVISOR": "supervisor",
            "DISCORD_WEBHOOK_SRE": "sre",
        }
        for env_key, agent_key in webhook_prefixes.items():
            value = os.environ.get(env_key)
            if value:
                AGENT_WEBHOOK_MAP[agent_key] = value

        logger.debug(f"Loaded {len(AGENT_ROLE_MAP)} role mappings, {len(AGENT_WEBHOOK_MAP)} webhook mappings")

    @property
    def http_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._http_client is None:
            headers = {}
            if self.bot_token:
                headers["Authorization"] = f"Bot {self.bot_token}"
            self._http_client = httpx.Client(
                base_url="https://discord.com/api/v10",
                headers=headers,
                timeout=30.0,
            )
        return self._http_client

    def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    @property
    def bot_user_id(self) -> str | None:
        """Get the bot's user ID (requires bot token)."""
        if self._bot_user_id is None and self.bot_token:
            try:
                response = self.http_client.get("/users/@me")
                response.raise_for_status()
                self._bot_user_id = response.json()["id"]
            except Exception as e:
                logger.warning(f"Failed to get bot user ID: {e}")
        return self._bot_user_id

    def _parse_message(self, data: dict) -> DiscordMessage:
        """Parse API response into DiscordMessage."""
        # Parse timestamp
        timestamp = None
        if ts_str := data.get("timestamp"):
            try:
                # Discord uses ISO 8601 format
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Extract role mentions
        role_mentions = [role["id"] for role in data.get("mention_roles", [])]
        # Also check raw mentions in content
        role_mentions.extend(re.findall(r"<@&(\d+)>", data.get("content", "")))
        role_mentions = list(set(role_mentions))

        # Extract user mentions
        user_mentions = [user["id"] for user in data.get("mentions", [])]

        author = data.get("author", {})

        return DiscordMessage(
            id=data.get("id", ""),
            channel_id=data.get("channel_id", ""),
            author_id=author.get("id", ""),
            author_name=author.get("username", "Unknown"),
            content=data.get("content", ""),
            timestamp=timestamp,
            is_bot=author.get("bot", False),
            role_mentions=role_mentions,
            user_mentions=user_mentions,
            reference_id=data.get("message_reference", {}).get("message_id"),
        )

    # =====================
    # Message Operations (Bot API)
    # =====================

    def get_channel_history(
        self,
        channel_id: str | None = None,
        limit: int = 20,
        before: str | None = None,
        after: str | None = None,
    ) -> list[DiscordMessage]:
        """
        Get channel message history.

        Requires bot token and MESSAGE_CONTENT intent.

        Args:
            channel_id: Channel ID (uses default if None)
            limit: Maximum messages to return (max 100)
            before: Get messages before this message ID
            after: Get messages after this message ID

        Returns:
            List of messages (newest first)
        """
        if not self.bot_token:
            raise ValueError("Bot token required for reading messages")

        channel_id = channel_id or self.default_channel_id
        if not channel_id:
            raise ValueError("Channel ID required")

        params: dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        response = self.http_client.get(f"/channels/{channel_id}/messages", params=params)
        response.raise_for_status()

        return [self._parse_message(msg) for msg in response.json()]

    def post_message(
        self,
        channel_id: str | None = None,
        content: str = "",
        reply_to: str | None = None,
    ) -> DiscordMessage:
        """
        Post a message to a channel using bot API.

        Uses the bot's identity (not recommended for agents - use webhooks instead).

        Args:
            channel_id: Channel ID (uses default if None)
            content: Message content
            reply_to: Message ID to reply to

        Returns:
            The posted message
        """
        if not self.bot_token:
            raise ValueError("Bot token required for posting messages")

        channel_id = channel_id or self.default_channel_id
        if not channel_id:
            raise ValueError("Channel ID required")

        payload: dict[str, Any] = {"content": content}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}

        response = self.http_client.post(f"/channels/{channel_id}/messages", json=payload)
        response.raise_for_status()

        return self._parse_message(response.json())

    # =====================
    # Webhook Operations (Custom Identity)
    # =====================

    def post_webhook_message(
        self,
        agent_key: str,
        content: str,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> dict | None:
        """
        Post a message via webhook with agent identity.

        Webhooks allow custom username and avatar per message,
        enabling each agent to appear as a distinct identity.

        Args:
            agent_key: Agent key (swe, release, support, pm, marketing)
            content: Message content
            reply_to: Message ID to reply to (for context, not true threading)
            thread_id: Thread ID to post in (for forum/thread channels)

        Returns:
            Webhook response dict, or None if webhook not configured
        """
        webhook_url = AGENT_WEBHOOK_MAP.get(agent_key)
        if not webhook_url:
            logger.warning(f"No webhook configured for agent: {agent_key}")
            return None

        # Get agent display info
        display_info = AGENT_DISPLAY_INFO.get(agent_key, {"name": agent_key.upper()})
        username = display_info.get("name", agent_key.upper())

        payload: dict[str, Any] = {
            "content": content,
            "username": username,
        }

        # Add thread_id for posting in threads
        params = {}
        if thread_id:
            params["thread_id"] = thread_id

        try:
            # Webhook URLs are full URLs, not relative
            with httpx.Client(timeout=30.0) as client:
                response = client.post(webhook_url, json=payload, params=params)
                response.raise_for_status()

                # Discord may return empty body on success (204)
                if response.status_code == 204:
                    return {"success": True}
                return response.json() if response.text else {"success": True}

        except Exception as e:
            logger.error(f"Failed to post webhook message for {agent_key}: {e}")
            return None

    # =====================
    # Agent Mention Operations
    # =====================

    def mention_agent(
        self,
        agent_key: str,
        message: str,
        channel_id: str | None = None,
        from_agent: str | None = None,
        thread_id: str | None = None,
    ) -> dict | None:
        """
        Mention another agent in a message (for handoffs).

        Posts via the from_agent's webhook (if available) or the target agent's.

        Args:
            agent_key: Target agent key to mention
            message: Message content
            channel_id: Channel ID (for bot API fallback)
            from_agent: The agent sending the handoff (uses their webhook)
            thread_id: Thread ID for context continuity

        Returns:
            Response dict or None
        """
        role_id = AGENT_ROLE_MAP.get(agent_key)

        # Format message with role mention
        if role_id:
            content = f"<@&{role_id}> {message}"
        else:
            # Fallback to plain text mention
            display_name = AGENT_DISPLAY_INFO.get(agent_key, {}).get("name", agent_key.upper())
            content = f"@{display_name}: {message}"

        # Try to post via webhook (preferred for custom identity)
        webhook_agent = from_agent or agent_key
        result = self.post_webhook_message(
            agent_key=webhook_agent,
            content=content,
            thread_id=thread_id,
        )

        if result:
            return result

        # Fallback to bot API
        if self.bot_token:
            try:
                msg = self.post_message(
                    channel_id=channel_id or self.default_channel_id,
                    content=content,
                )
                return {"message_id": msg.id}
            except Exception as e:
                logger.error(f"Failed to post mention via bot API: {e}")

        return None

    def is_mention_for_agent(self, message: DiscordMessage, agent_key: str) -> bool:
        """
        Check if a message mentions a specific agent's role.

        Args:
            message: The message to check
            agent_key: Agent key to check for

        Returns:
            True if the agent's role is mentioned
        """
        role_id = AGENT_ROLE_MAP.get(agent_key)

        # Check role mentions
        if role_id and role_id in message.role_mentions:
            return True

        # Fallback: check for text-based mention (@SoftwareEngineer, @swe, etc.)
        display_name = AGENT_DISPLAY_INFO.get(agent_key, {}).get("name", "")
        content_lower = message.content.lower()

        if f"@{agent_key}" in content_lower:
            return True
        if display_name and f"@{display_name.lower()}" in content_lower:
            return True

        # If no role configured, check if bot itself is mentioned
        if not role_id and self.bot_user_id and self.bot_user_id in message.user_mentions:
            return True

        return False

    def extract_mentioned_agents(self, message: DiscordMessage) -> list[str]:
        """
        Extract all agent keys mentioned in a message.

        Args:
            message: The message to parse

        Returns:
            List of agent keys that were mentioned
        """
        mentioned = []

        # Check configured role mentions
        for agent_key, role_id in AGENT_ROLE_MAP.items():
            if role_id in message.role_mentions:
                mentioned.append(agent_key)

        # Also check for text-based mentions
        content_lower = message.content.lower()
        for agent_key, info in AGENT_DISPLAY_INFO.items():
            if agent_key in mentioned:
                continue
            if f"@{agent_key}" in content_lower:
                mentioned.append(agent_key)
            elif f"@{info['name'].lower()}" in content_lower:
                mentioned.append(agent_key)

        return mentioned

    def get_role_mention_string(self, agent_key: str) -> str:
        """
        Get the mention string for an agent's role.

        Args:
            agent_key: Agent key

        Returns:
            Role mention string (e.g., "<@&123456>") or fallback text
        """
        role_id = AGENT_ROLE_MAP.get(agent_key)
        if role_id:
            return f"<@&{role_id}>"

        # Fallback to text
        display_name = AGENT_DISPLAY_INFO.get(agent_key, {}).get("name", agent_key.upper())
        return f"@{display_name}"

    # =====================
    # Utility Methods
    # =====================

    def format_agent_message(
        self,
        agent_name: str,
        message: str,
        include_emoji: bool = True,
    ) -> str:
        """
        Format a message from an agent with consistent styling.

        Note: When using webhooks, the username is set separately.
        This is mainly for formatting the message content.

        Args:
            agent_name: Name of the agent
            message: Message content
            include_emoji: Include role-specific emoji

        Returns:
            Formatted message
        """
        # Find agent key from name
        agent_key = None
        for key, info in AGENT_DISPLAY_INFO.items():
            if info.get("name", "").lower() == agent_name.lower():
                agent_key = key
                break

        emoji = ""
        if include_emoji and agent_key:
            emoji = AGENT_DISPLAY_INFO.get(agent_key, {}).get("emoji", ":robot:") + " "

        return f"{emoji}**[{agent_name}]** {message}"

    def strip_mentions(self, content: str) -> str:
        """
        Remove role and user mentions from message content.

        Args:
            content: Message content

        Returns:
            Content with mentions stripped
        """
        # Remove role mentions <@&ID>
        content = re.sub(r"<@&\d+>\s*", "", content)
        # Remove user mentions <@ID>
        content = re.sub(r"<@!?\d+>\s*", "", content)
        return content.strip()


def cli_test_connection() -> None:
    """CLI helper to test Discord connection."""
    try:
        connector = DiscordConnector()

        print("Discord Connector Status")
        print("=" * 40)
        print(f"Guild ID: {connector.guild_id or 'NOT SET'}")
        print(f"Channel ID: {connector.default_channel_id or 'NOT SET'}")
        print(f"Bot Token: {'SET' if connector.bot_token else 'NOT SET'}")

        print(f"\nRole Mappings ({len(AGENT_ROLE_MAP)}):")
        for agent, role_id in AGENT_ROLE_MAP.items():
            print(f"  {agent}: {role_id}")

        print(f"\nWebhook Mappings ({len(AGENT_WEBHOOK_MAP)}):")
        for agent, url in AGENT_WEBHOOK_MAP.items():
            # Only show part of URL for security
            masked = url[:50] + "..." if len(url) > 50 else url
            print(f"  {agent}: {masked}")

        if connector.bot_token:
            print(f"\nBot User ID: {connector.bot_user_id or 'Failed to fetch'}")

            if connector.default_channel_id:
                print("\nRecent messages:")
                messages = connector.get_channel_history(limit=5)
                for msg in messages[:5]:
                    print(f"  [{msg.author_name}]: {msg.content[:50]}...")

        connector.close()

    except Exception as e:
        print(f"Error: {e}")
        print("\nEnsure Discord environment variables are set:")
        print("  DISCORD_BOT_TOKEN")
        print("  DISCORD_GUILD_ID")
        print("  DISCORD_CHANNEL_ID")


if __name__ == "__main__":
    cli_test_connection()
