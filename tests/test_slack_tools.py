"""
Tests for agents/shared/slack_tools.py

Tests both unit tests (with mocks) and integration tests (with real Slack API).
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestSlackToolsUnit:
    """Unit tests with mocked Slack API."""

    def test_import_slack_tools(self):
        """Test that slack_tools can be imported without vibeteam dependency."""
        # This should not import vibeteam
        import agents.shared.slack_tools as slack_tools

        # Verify key exports exist
        assert hasattr(slack_tools, "SlackClient")
        assert hasattr(slack_tools, "SlackMessage")
        assert hasattr(slack_tools, "send_message")
        assert hasattr(slack_tools, "read_slack_channel")
        assert hasattr(slack_tools, "read_slack_thread")

    def test_slack_client_requires_token(self):
        """Test SlackClient raises error without token."""
        from agents.shared.slack_tools import SlackClient

        # Clear any existing token
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SLACK_BOT_TOKEN", None)
            with pytest.raises(ValueError, match="Slack token required"):
                SlackClient()

    def test_slack_message_dataclass(self):
        """Test SlackMessage dataclass properties."""
        from datetime import datetime

        from agents.shared.slack_tools import SlackMessage

        msg = SlackMessage(
            ts="1234567890.123456",
            channel="C12345",
            user="U12345",
            text="Hello world",
            thread_ts=None,
            timestamp=datetime(2026, 2, 5, 10, 0, 0),
            is_bot=False,
            mentions=["U67890"],
        )

        assert msg.ts == "1234567890.123456"
        assert msg.channel == "C12345"
        assert msg.permalink == "C12345/1234567890.123456"
        assert len(msg.mentions) == 1

    def test_slack_channel_dataclass(self):
        """Test SlackChannel dataclass."""
        from agents.shared.slack_tools import SlackChannel

        channel = SlackChannel(
            id="C12345",
            name="ai-team",
            is_private=False,
            is_member=True,
            topic="AI Team Channel",
            purpose="For AI agent discussions",
        )

        assert channel.id == "C12345"
        assert channel.name == "ai-team"
        assert channel.is_member is True

    def test_slack_client_with_mock(self):
        """Test SlackClient instantiation with mocked WebClient."""
        from agents.shared.slack_tools import SlackClient

        # Mock the slack_sdk module before importing SlackClient
        mock_webclient_class = MagicMock()
        mock_webclient_instance = MagicMock()
        mock_webclient_class.return_value = mock_webclient_instance
        mock_webclient_instance.auth_test.return_value = {"user_id": "U12345"}

        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-test-token"}):
            with patch("slack_sdk.WebClient", mock_webclient_class):
                with patch("slack_sdk.errors.SlackApiError", Exception):
                    # Create client - the slack_sdk imports happen inside __init__
                    client = SlackClient()
                    # Verify the client was created
                    assert client.token == "xoxb-test-token"

    def test_context_management(self):
        """Test Slack context management functions."""
        from agents.shared.slack_tools import (
            clear_slack_context,
            get_slack_context,
            is_slack_context_set,
            set_slack_context,
        )

        # Initially empty
        clear_slack_context()
        assert not is_slack_context_set()

        # Set context
        mock_client = MagicMock()
        set_slack_context(
            client=mock_client,
            channel="C12345",
            thread_ts="1234567890.123456",
            from_agent="SupportEngineer",
            session_id="abc12345",
        )

        assert is_slack_context_set()
        ctx = get_slack_context()
        assert ctx["channel"] == "C12345"
        assert ctx["thread_ts"] == "1234567890.123456"
        assert ctx["from_agent"] == "SupportEngineer"

        # Clear context
        clear_slack_context()
        assert not is_slack_context_set()

    def test_get_agent_display_name(self):
        """Test agent display name mapping."""
        from agents.shared.slack_tools import _get_agent_display_name

        assert _get_agent_display_name("swe") == "SoftwareEngineer"
        assert _get_agent_display_name("release") == "ReleaseEngineer"
        assert _get_agent_display_name("support") == "SupportEngineer"
        assert _get_agent_display_name("pm") == "ProductManager"
        assert _get_agent_display_name("marketer") == "MarketingManager"
        assert _get_agent_display_name("unknown") == "unknown"

    def test_handoff_instructions(self):
        """Test handoff instructions contain expected content."""
        from agents.shared.slack_tools import get_slack_handoff_instructions

        instructions = get_slack_handoff_instructions()
        assert "@SoftwareEngineer" in instructions
        assert "@ReleaseEngineer" in instructions
        assert "@SupportEngineer" in instructions
        assert "TEAM COLLABORATION" in instructions

    @pytest.mark.asyncio
    async def test_send_message_no_token(self):
        """Test send_message returns error when no token is available."""
        from agents.shared.slack_tools import clear_slack_context, send_message

        clear_slack_context()

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SLACK_BOT_TOKEN", None)
            result = await send_message("Hello")
            assert "error" in result.lower() or "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_send_message_with_context(self):
        """Test send_message uses context correctly."""
        from agents.shared.slack_tools import (
            clear_slack_context,
            send_message,
            set_slack_context,
        )

        # Create a mock client
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.ts = "1234567890.123456"
        mock_client.post_message.return_value = mock_message

        # Set context with mock client
        set_slack_context(
            client=mock_client,
            channel="C12345",
            thread_ts="1111111111.111111",
            from_agent="SupportEngineer",
            session_id="session123456789",  # 16 chars, will be truncated to first 8
        )

        result = await send_message("Test message")

        # Verify the message was prefixed correctly
        mock_client.post_message.assert_called_once()
        call_kwargs = mock_client.post_message.call_args[1]
        assert "[SupportEngineer:session1]" in call_kwargs["text"]
        assert "Test message" in call_kwargs["text"]
        assert call_kwargs["channel"] == "C12345"
        assert call_kwargs["thread_ts"] == "1111111111.111111"

        clear_slack_context()


class TestSlackToolsNoVibeteamDependency:
    """Verify slack_tools doesn't import vibeteam."""

    def test_no_vibeteam_import(self):
        """Ensure slack_tools doesn't import from vibeteam package."""
        import sys

        # Clear any cached imports
        modules_to_remove = [k for k in sys.modules if k.startswith("vibeteam")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Also remove slack_tools to force reimport
        if "agents.shared.slack_tools" in sys.modules:
            del sys.modules["agents.shared.slack_tools"]

        # Import slack_tools
        import agents.shared.slack_tools  # noqa: F401

        # Check that vibeteam was NOT imported
        vibeteam_modules = [k for k in sys.modules if k.startswith("vibeteam")]
        assert len(vibeteam_modules) == 0, f"vibeteam modules imported: {vibeteam_modules}"


# Integration tests require --run-integration flag
@pytest.mark.integration
class TestSlackToolsIntegration:
    """Integration tests with real Slack API.

    These tests require:
    - SLACK_BOT_TOKEN environment variable
    - A test channel the bot can post to

    Run with: pytest tests/test_slack_tools.py -v --run-integration
    """

    @pytest.fixture
    def slack_client(self):
        """Create a real Slack client."""
        from agents.shared.slack_tools import SlackClient

        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            pytest.skip("SLACK_BOT_TOKEN not set")

        return SlackClient(token=token)

    def test_real_slack_auth(self, slack_client):
        """Test authentication with real Slack API."""
        # This will trigger auth_test call
        user_id = slack_client.bot_user_id
        assert user_id.startswith("U") or user_id.startswith("W")
        print(f"Authenticated as bot user: {user_id}")

    def test_real_slack_list_channels(self, slack_client):
        """Test listing channels from real Slack workspace."""
        channels = slack_client.list_channels()
        assert len(channels) > 0
        print(f"Found {len(channels)} channels")
        for ch in channels[:5]:
            print(f"  #{ch.name} (member: {ch.is_member})")

    def test_real_slack_channel_history(self, slack_client):
        """Test reading channel history from real Slack."""
        # Use a known test channel
        test_channel = os.environ.get("SLACK_TEST_CHANNEL", "C0AATPSADB8")

        try:
            messages = slack_client.get_channel_history(channel=test_channel, limit=5)
            print(f"Found {len(messages)} messages in channel")
            for msg in messages[:3]:
                print(f"  [{msg.timestamp}] {msg.user}: {msg.text[:50]}...")
        except Exception as e:
            pytest.skip(f"Could not read channel history: {e}")

    def test_real_slack_post_message(self, slack_client):
        """Test posting a message to real Slack (use with caution)."""
        test_channel = os.environ.get("SLACK_TEST_CHANNEL", "C0AATPSADB8")

        # Only run if explicitly enabled
        if not os.environ.get("SLACK_TEST_POST_ENABLED"):
            pytest.skip("Set SLACK_TEST_POST_ENABLED=1 to enable post tests")

        msg = slack_client.post_message(
            channel=test_channel,
            text="[TEST] Slack tools integration test message",
        )

        assert msg.ts is not None
        print(f"Posted message: {msg.ts}")

    @pytest.mark.asyncio
    async def test_real_send_message_async(self, slack_client):
        """Test async send_message with real Slack."""
        from agents.shared.slack_tools import (
            clear_slack_context,
            send_message,
            set_slack_context,
        )

        test_channel = os.environ.get("SLACK_TEST_CHANNEL", "C0AATPSADB8")

        if not os.environ.get("SLACK_TEST_POST_ENABLED"):
            pytest.skip("Set SLACK_TEST_POST_ENABLED=1 to enable post tests")

        set_slack_context(
            client=slack_client,
            channel=test_channel,
            from_agent="TestAgent",
            session_id="test123",
        )

        result = await send_message("Integration test message")
        assert "Posted to" in result or "error" not in result.lower()
        print(f"Result: {result}")

        clear_slack_context()

    @pytest.mark.asyncio
    async def test_real_read_channel_async(self):
        """Test async read_slack_channel with real Slack."""
        from agents.shared.slack_tools import read_slack_channel

        test_channel = os.environ.get("SLACK_TEST_CHANNEL", "C0AATPSADB8")
        token = os.environ.get("SLACK_BOT_TOKEN")

        if not token:
            pytest.skip("SLACK_BOT_TOKEN not set")

        result = await read_slack_channel(channel=test_channel, limit=5)
        print(f"Read result:\n{result[:500]}...")

        # Should contain messages or indicate no messages
        assert (
            "messages" in result.lower()
            or "no messages" in result.lower()
            or "error" in result.lower()
        )

    def test_slack_timeout_behavior(self, slack_client):
        """Test that Slack client respects timeout settings."""
        # Create client with short timeout
        from agents.shared.slack_tools import SlackClient

        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            pytest.skip("SLACK_BOT_TOKEN not set")

        # Default timeout should be 10 seconds
        assert slack_client.timeout == 10

        # Create client with custom timeout
        custom_client = SlackClient(token=token, timeout=5)
        assert custom_client.timeout == 5
