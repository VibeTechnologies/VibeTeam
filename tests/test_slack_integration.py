"""
Slack Integration Tests.

Real integration tests for Slack messaging via SlackConnector.
These tests require valid SLACK_BOT_TOKEN to be set.

Run with:
    pytest tests/test_slack_integration.py -v --run-integration

Environment variables required:
    SLACK_BOT_TOKEN - Bot OAuth token (xoxb-...)
    SLACK_TEST_CHANNEL - Test channel name (default: #ai-team-test)
"""

import os
import time
import uuid

import pytest

from vibeteam.connectors.slack import SlackAPIError, SlackConnector


# Skip all tests if no Slack token
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def slack_connector():
    """Create a SlackConnector for the test module."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        pytest.skip("SLACK_BOT_TOKEN not set")
    connector = SlackConnector(bot_token=token)
    yield connector
    connector.close()


@pytest.fixture(scope="module")
def test_channel():
    """Get test channel name."""
    return os.environ.get("SLACK_TEST_CHANNEL", "#ai-team-test")


class TestSlackConnectorBasics:
    """Basic SlackConnector functionality tests."""

    def test_connector_initialization(self, slack_connector: SlackConnector):
        """Test connector initializes correctly."""
        assert slack_connector.bot_token
        assert slack_connector.client is not None

    def test_list_channels(self, slack_connector: SlackConnector):
        """Test listing available channels."""
        channels = slack_connector.list_channels()
        assert isinstance(channels, list)
        # Should have at least one channel
        assert len(channels) > 0
        # Each channel should have required fields
        for ch in channels[:3]:  # Check first 3
            assert ch.id
            assert ch.name
            print(f"  Found channel: #{ch.name} ({ch.id})")

    def test_get_channel_by_name(self, slack_connector: SlackConnector, test_channel: str):
        """Test getting channel by name."""
        channel = slack_connector.get_channel_by_name(test_channel)
        if channel:
            assert channel.name == test_channel.lstrip("#")
            print(f"  Found test channel: #{channel.name} ({channel.id})")
        else:
            pytest.skip(f"Test channel {test_channel} not found")


class TestSlackMessaging:
    """Test Slack message sending and receiving."""

    def test_send_message(self, slack_connector: SlackConnector, test_channel: str):
        """Test sending a message to a channel."""
        test_id = str(uuid.uuid4())[:8]
        text = f"[Test] Integration test message - {test_id}"

        message = slack_connector.send_message(test_channel, text)

        assert message.ts  # Has timestamp (message ID)
        assert message.text == text
        print(f"  Sent message: {message.ts}")

        # Cleanup
        slack_connector.delete_message(test_channel, message.ts)

    def test_send_and_read_message(self, slack_connector: SlackConnector, test_channel: str):
        """Test that sent messages appear in channel history."""
        test_id = str(uuid.uuid4())[:8]
        text = f"[Test] Read test - {test_id}"

        # Send message
        sent = slack_connector.send_message(test_channel, text)
        time.sleep(1)  # Allow propagation

        # Read history
        history = slack_connector.get_channel_history(test_channel, limit=10)
        assert len(history) > 0

        # Find our message
        found = False
        for msg in history:
            if test_id in msg.text:
                found = True
                assert msg.ts == sent.ts
                print(f"  Found message in history: {msg.text[:50]}")
                break

        assert found, f"Message with test_id {test_id} not found in history"

        # Cleanup
        slack_connector.delete_message(test_channel, sent.ts)

    def test_thread_reply(self, slack_connector: SlackConnector, test_channel: str):
        """Test sending a thread reply."""
        test_id = str(uuid.uuid4())[:8]

        # Send parent message
        parent = slack_connector.send_message(
            test_channel,
            f"[Test] Thread parent - {test_id}",
        )
        time.sleep(0.5)

        # Send thread reply
        reply = slack_connector.send_message(
            test_channel,
            f"[Test] Thread reply - {test_id}",
            thread_ts=parent.ts,
        )

        assert reply.thread_ts == parent.ts
        print(f"  Thread parent: {parent.ts}, Reply: {reply.ts}")

        # Get thread replies
        time.sleep(0.5)
        replies = slack_connector.get_thread_replies(test_channel, parent.ts)
        assert len(replies) >= 2  # Parent + reply

        # Cleanup
        slack_connector.delete_message(test_channel, reply.ts)
        slack_connector.delete_message(test_channel, parent.ts)

    def test_update_message(self, slack_connector: SlackConnector, test_channel: str):
        """Test updating an existing message."""
        test_id = str(uuid.uuid4())[:8]

        # Send original
        original = slack_connector.send_message(
            test_channel,
            f"[Test] Original message - {test_id}",
        )
        time.sleep(0.5)

        # Update
        updated_text = f"[Test] Updated message - {test_id}"
        updated = slack_connector.update_message(
            test_channel,
            original.ts,
            updated_text,
        )

        assert updated.ts == original.ts
        assert updated.text == updated_text
        print(f"  Updated message: {updated.ts}")

        # Cleanup
        slack_connector.delete_message(test_channel, original.ts)

    def test_add_reaction(self, slack_connector: SlackConnector, test_channel: str):
        """Test adding a reaction to a message."""
        test_id = str(uuid.uuid4())[:8]

        # Send message
        message = slack_connector.send_message(
            test_channel,
            f"[Test] React to this - {test_id}",
        )
        time.sleep(0.5)

        # Add reaction
        result = slack_connector.add_reaction(test_channel, message.ts, "thumbsup")
        assert result is True
        print(f"  Added reaction to: {message.ts}")

        # Cleanup
        slack_connector.delete_message(test_channel, message.ts)


class TestSlackAgentCommunication:
    """Test agent-style communication patterns."""

    def test_post_status_update(self, slack_connector: SlackConnector, test_channel: str):
        """Test posting a status update like an agent would."""
        test_id = str(uuid.uuid4())[:8]

        status = slack_connector.post_status_update(
            f":robot_face: Agent status update - {test_id}\n"
            f"• Task: Integration test\n"
            f"• Status: Running",
            channel=test_channel,
        )

        assert status.ts
        print(f"  Posted status: {status.ts}")

        # Cleanup
        slack_connector.delete_message(test_channel, status.ts)

    def test_agent_conversation_flow(self, slack_connector: SlackConnector, test_channel: str):
        """Test a complete agent conversation flow."""
        test_id = str(uuid.uuid4())[:8]

        # 1. Agent posts initial acknowledgment
        ack = slack_connector.send_message(
            test_channel,
            f":wave: Got your request! Working on it... ({test_id})",
        )
        time.sleep(0.5)

        # 2. Agent posts progress in thread
        progress = slack_connector.send_message(
            test_channel,
            ":hourglass: Analyzing the issue...",
            thread_ts=ack.ts,
        )
        time.sleep(0.5)

        # 3. Agent posts final response in thread
        final = slack_connector.send_message(
            test_channel,
            ":white_check_mark: Done! Here's what I found:\n• Issue analyzed\n• Solution proposed",
            thread_ts=ack.ts,
        )

        # 4. Update parent message with completion status
        slack_connector.update_message(
            test_channel,
            ack.ts,
            f":white_check_mark: Request completed! See thread for details. ({test_id})",
        )

        # Add reaction to indicate success
        slack_connector.add_reaction(test_channel, ack.ts, "white_check_mark")

        print(f"  Conversation thread: {ack.ts}")

        # Verify thread has all messages
        time.sleep(0.5)
        replies = slack_connector.get_thread_replies(test_channel, ack.ts)
        assert len(replies) >= 3  # ack + progress + final

        # Cleanup
        slack_connector.delete_message(test_channel, final.ts)
        slack_connector.delete_message(test_channel, progress.ts)
        slack_connector.delete_message(test_channel, ack.ts)


class TestSlackErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_channel(self, slack_connector: SlackConnector):
        """Test error when sending to invalid channel."""
        with pytest.raises(SlackAPIError):
            slack_connector.send_message("#nonexistent-channel-xyz-123", "test")

    def test_missing_token(self):
        """Test error when token is missing."""
        connector = SlackConnector(bot_token="")
        # Use a channel ID to skip resolution step
        with pytest.raises(SlackAPIError, match="not configured"):
            connector.send_message("C12345678", "test")


class TestSlackE2EWithGateway:
    """E2E tests for Slack integration with the gateway."""

    @pytest.mark.slow
    def test_full_slack_event_flow(
        self,
        slack_connector: SlackConnector,
        test_channel: str,
    ):
        """
        Test the full Slack event flow:
        1. Send a message to test channel (simulating @vibeteam mention)
        2. Verify agent would be triggered
        3. Check response appears in channel

        Note: This test validates the connector works correctly.
        Full gateway testing requires a running K8s cluster.
        """
        test_id = str(uuid.uuid4())[:8]

        # Simulate what an @vibeteam mention would look like
        mention_text = f"@vibeteam Please check the latest Sentry errors ({test_id})"

        # Send the simulated mention
        mention = slack_connector.send_message(test_channel, mention_text)
        print(f"  Simulated mention: {mention.ts}")

        # In a real scenario, the gateway would:
        # 1. Receive the app_mention event
        # 2. Route to appropriate agent
        # 3. Post response in thread

        # For now, simulate the expected agent response
        response = slack_connector.send_message(
            test_channel,
            ":robot_face: I checked Sentry and found 3 unresolved errors in the last 24 hours.\n"
            "• TypeError in auth.py:142\n"
            "• ValueError in api.py:89\n"
            "• ConnectionError in db.py:256",
            thread_ts=mention.ts,
        )
        print(f"  Agent response: {response.ts}")

        # Add reaction to indicate processing complete
        slack_connector.add_reaction(test_channel, mention.ts, "eyes")
        slack_connector.add_reaction(test_channel, mention.ts, "white_check_mark")

        # Verify the thread exists with both messages
        time.sleep(0.5)
        replies = slack_connector.get_thread_replies(test_channel, mention.ts)
        assert len(replies) >= 2

        # Cleanup
        slack_connector.delete_message(test_channel, response.ts)
        slack_connector.delete_message(test_channel, mention.ts)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--run-integration"])
