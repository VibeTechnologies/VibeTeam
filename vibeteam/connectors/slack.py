"""
Slack Connector for VibeTeam.

Provides methods to interact with Slack API for testing and validation.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class SlackAuthInfo:
    """Slack authentication info."""

    ok: bool
    user_id: str | None = None
    user: str | None = None
    team_id: str | None = None
    team: str | None = None
    error: str | None = None


class SlackConnector:
    """Connector for Slack API operations."""

    def __init__(
        self,
        bot_token: str | None = None,
        signing_secret: str | None = None,
    ):
        """
        Initialize Slack connector.

        Args:
            bot_token: Slack Bot User OAuth Token (xoxb-...). If not provided,
                      reads from SLACK_BOT_TOKEN env var or .secrets/slack.json.
            signing_secret: Slack Signing Secret for webhook verification.
        """
        self.bot_token = bot_token or self._get_token()
        self.signing_secret = signing_secret or os.environ.get("SLACK_SIGNING_SECRET", "")
        self.base_url = "https://slack.com/api"

    def _get_token(self) -> str:
        """Get bot token from environment or secrets file."""
        # Try environment variable first
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if token:
            return token

        # Try secrets file
        secrets_paths = [
            Path(".secrets/slack.json"),
            Path(os.path.expanduser("~/.secrets/slack.json")),
        ]

        for path in secrets_paths:
            if path.exists():
                try:
                    with open(path) as f:
                        data = json.load(f)
                        token = data.get("SLACK_BOT_TOKEN", "")
                        if token:
                            return token
                except (json.JSONDecodeError, OSError):
                    pass

        return ""

    def _request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        json_data: dict | None = None,
    ) -> dict:
        """Make authenticated request to Slack API."""
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }

        response = requests.request(
            method,
            url,
            headers=headers,
            data=data,
            json=json_data,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def auth_test(self) -> SlackAuthInfo:
        """
        Test authentication and get bot info.

        Returns:
            SlackAuthInfo with authentication details or error.
        """
        if not self.bot_token:
            return SlackAuthInfo(ok=False, error="SLACK_BOT_TOKEN not set")

        try:
            result = self._request("POST", "auth.test")
            if result.get("ok"):
                return SlackAuthInfo(
                    ok=True,
                    user_id=result.get("user_id"),
                    user=result.get("user"),
                    team_id=result.get("team_id"),
                    team=result.get("team"),
                )
            else:
                return SlackAuthInfo(ok=False, error=result.get("error", "Unknown error"))
        except requests.RequestException as e:
            return SlackAuthInfo(ok=False, error=str(e))

    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict:
        """
        Send a message to a channel.

        Args:
            channel: Channel ID or name
            text: Message text
            thread_ts: Optional thread timestamp to reply in thread

        Returns:
            API response dict
        """
        payload = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        return self._request("POST", "chat.postMessage", json_data=payload)

    def list_channels(self, limit: int = 100) -> list[dict]:
        """
        List channels the bot is a member of.

        Args:
            limit: Maximum number of channels to return

        Returns:
            List of channel dicts
        """
        result = self._request(
            "GET",
            f"conversations.list?types=public_channel,private_channel&limit={limit}",
        )
        if result.get("ok"):
            return result.get("channels", [])
        return []

    def health_check(self) -> bool:
        """
        Check if Slack integration is healthy.

        Returns:
            True if authenticated and working
        """
        auth = self.auth_test()
        return auth.ok
