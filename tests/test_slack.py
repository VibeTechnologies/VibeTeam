"""
Tests for Slack-based agent communication.

Tests the SlackConnector, SlackTool, and SlackBot routing system.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSlackConnector:
    """Test SlackConnector functionality."""

    @pytest.fixture
    def mock_slack_client(self):
        """Create a mock Slack WebClient."""
        with patch("vibeteam.connectors.slack.WebClient") as mock:
            client = MagicMock()
            client.auth_test.return_value = {"user_id": "U12345BOT"}
            client.conversations_list.return_value = {
                "channels": [
                    {"id": "C12345", "name": "ai-team", "is_private": False, "is_member": True},
                    {"id": "C67890", "name": "general", "is_private": False, "is_member": True},
                ]
            }
            client.conversations_history.return_value = {
                "messages": [
                    {"ts": "1234567890.123", "user": "U11111", "text": "Hello @pm"},
                    {"ts": "1234567890.124", "user": "U22222", "text": "Test message"},
                ]
            }
            client.chat_postMessage.return_value = {"ts": "1234567890.999"}
            mock.return_value = client
            yield client

    @pytest.fixture
    def connector(self, mock_slack_client):
        """Create a SlackConnector with mocked client."""
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test-token"}):
            from vibeteam.connectors.slack import SlackConnector

            return SlackConnector()

    def test_initialization(self, connector):
        """Test connector initializes correctly."""
        assert connector.token == "xoxb-test-token"
        assert connector.default_channel == "#ai-team"

    def test_initialization_without_token_fails(self):
        """Test connector requires token."""
        with patch.dict("os.environ", {}, clear=True):
            from vibeteam.connectors.slack import SlackConnector

            with pytest.raises(ValueError, match="Slack token required"):
                SlackConnector()

    def test_bot_user_id(self, connector, mock_slack_client):
        """Test bot user ID is retrieved."""
        assert connector.bot_user_id == "U12345BOT"
        mock_slack_client.auth_test.assert_called_once()

    def test_resolve_channel_by_name(self, connector, mock_slack_client):
        """Test channel name resolves to ID."""
        channel_id = connector._resolve_channel("#ai-team")
        assert channel_id == "C12345"

    def test_resolve_channel_id_unchanged(self, connector):
        """Test channel ID passes through unchanged."""
        channel_id = connector._resolve_channel("C99999")
        assert channel_id == "C99999"

    def test_post_message(self, connector, mock_slack_client):
        """Test posting a message."""
        msg = connector.post_message("#ai-team", "Hello world!")

        mock_slack_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "C12345"
        assert call_kwargs["text"] == "Hello world!"
        assert msg.ts == "1234567890.999"

    def test_post_message_with_thread(self, connector, mock_slack_client):
        """Test posting a threaded reply."""
        connector.post_message("#ai-team", "Reply", thread_ts="1234567890.123")

        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["thread_ts"] == "1234567890.123"

    def test_get_channel_history(self, connector, mock_slack_client):
        """Test retrieving channel history."""
        messages = connector.get_channel_history("#ai-team", limit=10)

        assert len(messages) == 2
        assert messages[0].ts == "1234567890.123"
        assert messages[0].text == "Hello @pm"

    def test_mention_agent(self, connector, mock_slack_client):
        """Test mentioning another agent."""
        with patch.dict("vibeteam.connectors.slack.AGENT_USER_MAP", {"swe": "U99999"}):
            msg = connector.mention_agent("#ai-team", "swe", "Please review this")

        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert "<@U99999>" in call_kwargs["text"]
        assert "Please review this" in call_kwargs["text"]

    def test_is_mention_for_agent_with_user_id(self, connector):
        """Test detecting agent mention by user ID."""
        from vibeteam.connectors.slack import SlackMessage

        with patch.dict("vibeteam.connectors.slack.AGENT_USER_MAP", {"pm": "U99999"}):
            msg = SlackMessage(
                ts="123",
                channel="C123",
                user="U11111",
                text="Hey <@U99999> can you help?",
                thread_ts=None,
                timestamp=None,
                is_bot=False,
                mentions=["U99999"],
            )
            assert connector.is_mention_for_agent(msg, "pm") is True
            assert connector.is_mention_for_agent(msg, "swe") is False

    def test_is_mention_for_agent_with_text(self, connector):
        """Test detecting agent mention by @text."""
        from vibeteam.connectors.slack import SlackMessage

        msg = SlackMessage(
            ts="123",
            channel="C123",
            user="U11111",
            text="Hey @swe can you help?",
            thread_ts=None,
            timestamp=None,
            is_bot=False,
            mentions=[],
        )
        assert connector.is_mention_for_agent(msg, "swe") is True

    def test_extract_mentioned_agents(self, connector):
        """Test extracting all mentioned agents."""
        from vibeteam.connectors.slack import SlackMessage

        with patch.dict(
            "vibeteam.connectors.slack.AGENT_USER_MAP", {"pm": "U11111", "swe": "U22222"}
        ):
            msg = SlackMessage(
                ts="123",
                channel="C123",
                user="U00000",
                text="@release please check this too",
                thread_ts=None,
                timestamp=None,
                is_bot=False,
                mentions=["U11111", "U22222"],
            )
            mentioned = connector.extract_mentioned_agents(msg)
            assert "pm" in mentioned
            assert "swe" in mentioned
            assert "release" in mentioned

    def test_format_agent_message(self, connector):
        """Test formatting an agent message."""
        formatted = connector.format_agent_message("Curie", "Task completed!")
        assert "*[Curie]*" in formatted
        assert "Task completed!" in formatted
        assert ":chart_with_upwards_trend:" in formatted  # PM emoji


class TestSlackTool:
    """Test SlackTool for agent use."""

    @pytest.fixture
    def mock_connector(self):
        """Create a mock SlackConnector."""
        connector = MagicMock()
        connector.default_channel = "#ai-team"
        connector.post_message.return_value = MagicMock(ts="123", channel="C123")
        connector.get_channel_history.return_value = []
        connector.mention_agent.return_value = MagicMock(ts="124", channel="C123")
        connector.list_channels.return_value = []
        connector.format_agent_message.return_value = ":robot: *[Test]* Hello"
        connector.get_display_name.return_value = "Test User"
        return connector

    @pytest.fixture
    def slack_tool(self, mock_connector):
        """Create SlackTool with mocked connector."""
        with patch("vibeteam.tools.slack.SlackConnector", return_value=mock_connector):
            with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
                from vibeteam.tools.slack import SlackTool

                tool = SlackTool(agent_name="TestAgent")
                tool.connector = mock_connector
                return tool

    def test_tool_schema(self, slack_tool):
        """Test tool schema is valid."""
        schema = slack_tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "slack"
        assert "post_message" in schema["function"]["parameters"]["properties"]["action"]["enum"]

    @pytest.mark.asyncio
    async def test_post_message_action(self, slack_tool, mock_connector):
        """Test post_message action."""
        result = await slack_tool.execute(
            action="post_message",
            channel="#ai-team",
            message="Hello world!",
        )

        assert result.success is True
        assert "Posted to" in result.output
        mock_connector.post_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_message_requires_message(self, slack_tool):
        """Test post_message fails without message."""
        result = await slack_tool.execute(action="post_message")
        assert result.success is False
        assert "message required" in result.error

    @pytest.mark.asyncio
    async def test_read_channel_action(self, slack_tool, mock_connector):
        """Test read_channel action."""
        from datetime import datetime

        from vibeteam.connectors.slack import SlackMessage

        mock_connector.get_channel_history.return_value = [
            SlackMessage(
                ts="123",
                channel="C123",
                user="U111",
                text="Hello",
                thread_ts=None,
                timestamp=datetime.now(),
                is_bot=False,
                mentions=[],
            )
        ]

        result = await slack_tool.execute(action="read_channel", channel="#ai-team", limit=5)

        assert result.success is True
        messages = json.loads(result.output)
        assert len(messages) == 1
        assert messages[0]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_mention_agent_action(self, slack_tool, mock_connector):
        """Test mention_agent action."""
        result = await slack_tool.execute(
            action="mention_agent",
            agent="swe",
            message="Please review this PR",
        )

        assert result.success is True
        assert "Mentioned @swe" in result.output
        mock_connector.mention_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_mention_agent_requires_agent(self, slack_tool):
        """Test mention_agent fails without agent."""
        result = await slack_tool.execute(action="mention_agent", message="Hello")
        assert result.success is False
        assert "agent and message required" in result.error

    @pytest.mark.asyncio
    async def test_list_channels_action(self, slack_tool, mock_connector):
        """Test list_channels action."""
        from vibeteam.connectors.slack import SlackChannel

        mock_connector.list_channels.return_value = [
            SlackChannel(
                id="C123",
                name="ai-team",
                is_private=False,
                is_member=True,
                topic="Team discussion",
                purpose="AI team chat",
            )
        ]

        result = await slack_tool.execute(action="list_channels")

        assert result.success is True
        channels = json.loads(result.output)
        assert len(channels) == 1
        assert channels[0]["name"] == "ai-team"

    @pytest.mark.asyncio
    async def test_unknown_action(self, slack_tool):
        """Test unknown action returns error."""
        result = await slack_tool.execute(action="unknown_action")
        assert result.success is False
        assert "Unknown action" in result.error


class TestSlackAgentRouter:
    """Test SlackAgentRouter for message routing."""

    def test_parse_mentions_explicit(self):
        """Test parsing explicit @agent mentions."""
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
            from vibeteam.slack_bot import SlackAgentRouter

            router = SlackAgentRouter()

            mentions = router.parse_mentions("Hey @pm and @swe, please help")
            assert "pm" in mentions
            assert "swe" in mentions
            assert len(mentions) == 2

    def test_parse_mentions_none(self):
        """Test parsing message with no mentions."""
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
            from vibeteam.slack_bot import SlackAgentRouter

            router = SlackAgentRouter()

            mentions = router.parse_mentions("Just a regular message")
            assert len(mentions) == 0


class TestSlackBotRouting:
    """Test SlackBot routing logic."""

    def test_parse_target_agent_explicit_mention(self):
        """Test routing to explicitly mentioned agent."""
        with patch.dict(
            "os.environ", {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_APP_TOKEN": "xapp-test"}
        ):
            with patch("vibeteam.slack_bot.SlackConnector"):
                from vibeteam.slack_bot import SlackBot

                bot = SlackBot.__new__(SlackBot)
                bot._agents = {}

                # Test explicit mentions
                assert bot._parse_target_agent("@swe please fix the bug") == "swe"
                assert bot._parse_target_agent("@release deploy this") == "release"
                assert bot._parse_target_agent("@pm analyze this request") == "pm"

    def test_parse_target_agent_keyword_routing(self):
        """Test routing based on keywords."""
        with patch.dict(
            "os.environ", {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_APP_TOKEN": "xapp-test"}
        ):
            with patch("vibeteam.slack_bot.SlackConnector"):
                from vibeteam.slack_bot import SlackBot

                bot = SlackBot.__new__(SlackBot)
                bot._agents = {}

                # Test keyword routing - use unambiguous keywords
                assert bot._parse_target_agent("Please implement the code fix") == "swe"
                assert bot._parse_target_agent("Check sentry for errors") == "release"
                assert bot._parse_target_agent("Customer email about billing") == "support"
                assert bot._parse_target_agent("Monitor health endpoints") == "sre"

    def test_parse_target_agent_default_to_pm(self):
        """Test default routing to PM for generic messages."""
        with patch.dict(
            "os.environ", {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_APP_TOKEN": "xapp-test"}
        ):
            with patch("vibeteam.slack_bot.SlackConnector"):
                from vibeteam.slack_bot import SlackBot

                bot = SlackBot.__new__(SlackBot)
                bot._agents = {}

                # Generic messages should route to PM
                assert bot._parse_target_agent("What should we work on?") == "pm"


class TestSlackIntegration:
    """Integration tests for full Slack workflow."""

    @pytest.mark.asyncio
    async def test_agent_to_agent_communication_flow(self):
        """Test an agent mentioning another agent."""
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
            with patch("vibeteam.tools.slack.SlackConnector") as mock_connector_class:
                mock_connector = MagicMock()
                mock_connector.default_channel = "#ai-team"
                mock_connector.mention_agent.return_value = MagicMock(ts="123", channel="C123")
                mock_connector_class.return_value = mock_connector

                from vibeteam.tools.slack import SlackTool

                # PM agent creates a tool and mentions SWE
                pm_tool = SlackTool(agent_name="Curie")
                pm_tool.connector = mock_connector

                result = await pm_tool.execute(
                    action="mention_agent",
                    agent="swe",
                    message="New feature request analyzed. Please implement login with SSO.",
                )

                assert result.success is True
                mock_connector.mention_agent.assert_called_with(
                    channel="#ai-team",
                    agent_key="swe",
                    message="[From Curie] New feature request analyzed. Please implement login with SSO.",
                    thread_ts=None,
                )

    @pytest.mark.asyncio
    async def test_router_routes_to_correct_agent(self):
        """Test router correctly routes messages to agents."""
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
            with patch("vibeteam.slack_bot.AGENT_REGISTRY") as mock_registry:
                from vibeteam.slack_bot import SlackAgentRouter

                mock_agent = MagicMock()
                mock_agent.run = AsyncMock(return_value="Analyzed the request")

                mock_pm_class = MagicMock(return_value=mock_agent)
                mock_registry.__getitem__ = MagicMock(return_value=mock_pm_class)
                mock_registry.__contains__ = MagicMock(return_value=True)
                mock_registry.keys = MagicMock(return_value=["pm", "swe"])

                router = SlackAgentRouter()
                router._agents["pm"] = mock_agent  # Inject mock directly

                responses = await router.route(
                    message="Analyze this feature request for Notion integration",
                    target="pm",
                )

                assert "pm" in responses
                assert responses["pm"] == "Analyzed the request"
                mock_agent.run.assert_called_once()
