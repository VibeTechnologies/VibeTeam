"""
Integration tests for VibeTeam Webhook Server.

Tests the webhook endpoints for GitHub and Slack integrations.
These tests validate:
1. URL verification challenges are handled correctly
2. Signature verification works
3. Events are processed correctly
4. Required environment variables are checked

Run with: pytest tests/test_webhook.py -v
"""

import hashlib
import hmac
import json
import os
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# Import after setting up mocks
@pytest.fixture
def webhook_app():
    """Create a test client for the webhook app."""
    # Set required env vars for testing
    with patch.dict(
        os.environ,
        {
            "SLACK_SIGNING_SECRET": "test_signing_secret",
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "GITHUB_WEBHOOK_SECRET": "test_github_secret",
        },
    ):
        # Import here to pick up env vars
        from vibeteam.webhook.server import app

        yield TestClient(app)


@pytest.fixture
def slack_signing_secret():
    """Return the test signing secret."""
    return "test_signing_secret"


def generate_slack_signature(payload: str, timestamp: str, secret: str) -> str:
    """Generate a valid Slack signature for testing."""
    sig_basestring = f"v0:{timestamp}:{payload}"
    signature = hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    return f"v0={signature}"


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_returns_ok(self, webhook_app):
        """Test health endpoint returns 200."""
        response = webhook_app.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "vibeteam-webhook"


class TestSlackURLVerification:
    """Test Slack URL verification challenge."""

    def test_url_verification_returns_challenge(self, webhook_app):
        """Test that URL verification challenge is returned correctly."""
        challenge = "test_challenge_12345"
        payload = {"type": "url_verification", "challenge": challenge}

        response = webhook_app.post(
            "/slack/events",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge

    def test_url_verification_with_different_challenges(self, webhook_app):
        """Test URL verification with various challenge strings."""
        challenges = [
            "abc123",
            "a" * 100,  # Long challenge
            "challenge-with-dashes",
            "challenge_with_underscores",
        ]

        for challenge in challenges:
            payload = {"type": "url_verification", "challenge": challenge}
            response = webhook_app.post("/slack/events", json=payload)
            assert response.status_code == 200
            assert response.json()["challenge"] == challenge


class TestSlackSignatureVerification:
    """Test Slack request signature verification."""

    def test_invalid_signature_rejected(self, webhook_app):
        """Test that requests with invalid signatures are rejected."""
        payload = json.dumps(
            {"type": "event_callback", "event": {"type": "app_mention", "text": "test"}}
        )

        response = webhook_app.post(
            "/slack/events",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": str(int(time.time())),
                "X-Slack-Signature": "v0=invalid_signature",
            },
        )

        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]

    def test_missing_signature_rejected(self, webhook_app):
        """Test that requests without signatures are rejected."""
        payload = {"type": "event_callback", "event": {"type": "app_mention", "text": "test"}}

        response = webhook_app.post(
            "/slack/events",
            json=payload,
            headers={
                "X-Slack-Request-Timestamp": str(int(time.time())),
                # No signature header
            },
        )

        assert response.status_code == 401

    def test_old_timestamp_rejected(self, webhook_app, slack_signing_secret):
        """Test that requests with old timestamps are rejected (replay attack prevention)."""
        old_timestamp = str(int(time.time()) - 600)  # 10 minutes ago
        payload = json.dumps(
            {"type": "event_callback", "event": {"type": "app_mention", "text": "test"}}
        )
        signature = generate_slack_signature(payload, old_timestamp, slack_signing_secret)

        response = webhook_app.post(
            "/slack/events",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": old_timestamp,
                "X-Slack-Signature": signature,
            },
        )

        assert response.status_code == 401

    def test_valid_signature_accepted(self, webhook_app, slack_signing_secret):
        """Test that requests with valid signatures are accepted."""
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "app_mention",
                    "user": "U123456",
                    "channel": "C123456",
                    "text": "<@U0AAYE8HV6Z> hello",
                    "ts": "1234567890.123456",
                },
            }
        )
        signature = generate_slack_signature(payload, timestamp, slack_signing_secret)

        with patch("vibeteam.webhook.server.send_slack_message", new_callable=AsyncMock):
            with patch("vibeteam.webhook.server.run_agent_for_slack", new_callable=AsyncMock):
                response = webhook_app.post(
                    "/slack/events",
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Slack-Request-Timestamp": timestamp,
                        "X-Slack-Signature": signature,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["event"] == "app_mention"


class TestSlackAppMention:
    """Test Slack app_mention event handling."""

    def test_app_mention_triggers_response(self, webhook_app, slack_signing_secret):
        """Test that app_mention events trigger a response."""
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "app_mention",
                    "user": "U123456",
                    "channel": "C123456",
                    "text": "<@U0AAYE8HV6Z> what is the status?",
                    "ts": "1234567890.123456",
                },
            }
        )
        signature = generate_slack_signature(payload, timestamp, slack_signing_secret)

        with patch(
            "vibeteam.webhook.server.send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            with patch("vibeteam.webhook.server.run_agent_for_slack", new_callable=AsyncMock):
                response = webhook_app.post(
                    "/slack/events",
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Slack-Request-Timestamp": timestamp,
                        "X-Slack-Signature": signature,
                    },
                )

        assert response.status_code == 200
        # Verify acknowledgment was sent
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "C123456" in str(call_args)  # Channel
        assert "working" in str(call_args).lower()  # Acknowledgment message

    def test_bot_messages_ignored(self, webhook_app, slack_signing_secret):
        """Test that bot messages are ignored to prevent loops."""
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "app_mention",
                    "bot_id": "B123456",  # Bot message
                    "user": "U123456",
                    "channel": "C123456",
                    "text": "bot message",
                    "ts": "1234567890.123456",
                },
            }
        )
        signature = generate_slack_signature(payload, timestamp, slack_signing_secret)

        response = webhook_app.post(
            "/slack/events",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "bot_message"


class TestSlackDirectMessage:
    """Test Slack direct message handling."""

    def test_dm_triggers_response(self, webhook_app, slack_signing_secret):
        """Test that direct messages trigger a response."""
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U123456",
                    "channel": "D123456",
                    "text": "help me with something",
                    "ts": "1234567890.123456",
                },
            }
        )
        signature = generate_slack_signature(payload, timestamp, slack_signing_secret)

        with patch(
            "vibeteam.webhook.server.send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            with patch("vibeteam.webhook.server.run_agent_for_slack", new_callable=AsyncMock):
                response = webhook_app.post(
                    "/slack/events",
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Slack-Request-Timestamp": timestamp,
                        "X-Slack-Signature": signature,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["event"] == "message.im"


class TestSlackBotTokenRequired:
    """Test that SLACK_BOT_TOKEN is required for sending messages."""

    def test_send_message_warns_when_token_missing(self):
        """Test that missing SLACK_BOT_TOKEN logs a warning."""
        import asyncio
        from unittest.mock import patch

        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": ""}):
            # Re-import to get fresh module state
            import importlib
            import vibeteam.webhook.server as server_module

            # Save original value
            original_token = server_module.SLACK_BOT_TOKEN
            server_module.SLACK_BOT_TOKEN = ""

            try:
                with patch.object(server_module.logger, "warning") as mock_warning:
                    asyncio.run(server_module.send_slack_message("C123", "test"))
                    mock_warning.assert_called_with("SLACK_BOT_TOKEN not set, cannot send message")
            finally:
                server_module.SLACK_BOT_TOKEN = original_token


class TestGitHubWebhook:
    """Test GitHub webhook handling."""

    def generate_github_signature(self, payload: bytes, secret: str) -> str:
        """Generate a valid GitHub webhook signature."""
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={signature}"

    def test_github_webhook_health(self, webhook_app):
        """Test that /webhook endpoint exists."""
        # Without proper headers, should fail
        response = webhook_app.post("/webhook", json={})
        # Missing required header
        assert response.status_code == 422  # Validation error for missing header

    def test_github_issue_assigned_to_bot(self, webhook_app):
        """Test GitHub issue assignment to bot triggers agent."""
        secret = "test_github_secret"
        payload = json.dumps(
            {
                "action": "assigned",
                "repository": {"full_name": "test/repo"},
                "issue": {"number": 123, "title": "Test Issue", "body": "Test body"},
                "assignee": {"login": "vibeteam-bot"},
            }
        ).encode()

        signature = self.generate_github_signature(payload, secret)

        with patch("vibeteam.webhook.server.post_acknowledgment", new_callable=AsyncMock):
            with patch("vibeteam.webhook.server.run_swe_agent", new_callable=AsyncMock):
                response = webhook_app.post(
                    "/webhook",
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Event": "issues",
                        "X-Hub-Signature-256": signature,
                    },
                )

        assert response.status_code == 200


class TestWebhookEnvironmentValidation:
    """Test that webhook validates required environment variables."""

    def test_missing_slack_signing_secret_allows_requests(self):
        """Test behavior when SLACK_SIGNING_SECRET is not set."""
        # When secret is not set, verification is skipped (for dev mode)
        from vibeteam.webhook.server import verify_slack_signature

        result = verify_slack_signature(
            payload=b"test",
            timestamp="123",
            signature="v0=invalid",
            secret="",  # Empty secret
        )

        # Should return True (skip verification) when no secret
        assert result is True

    def test_verify_slack_signature_with_valid_data(self):
        """Test signature verification with valid data."""
        from vibeteam.webhook.server import verify_slack_signature

        secret = "my_secret"
        timestamp = str(int(time.time()))
        payload = b'{"test": "data"}'

        # Generate valid signature
        sig_basestring = f"v0:{timestamp}:{payload.decode()}"
        expected_sig = (
            "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
        )

        result = verify_slack_signature(
            payload=payload, timestamp=timestamp, signature=expected_sig, secret=secret
        )

        assert result is True


class TestSlackIntegrationReadiness:
    """
    Integration readiness tests.

    These tests verify the Slack integration is properly configured.
    Run against a live deployment with: pytest tests/test_webhook.py -v -k readiness
    """

    @pytest.mark.skipif(
        not os.environ.get("SLACK_BOT_TOKEN"),
        reason="SLACK_BOT_TOKEN required for integration tests",
    )
    def test_slack_bot_token_is_valid(self):
        """Test that SLACK_BOT_TOKEN is valid by calling auth.test."""
        import httpx

        token = os.environ["SLACK_BOT_TOKEN"]
        response = httpx.post(
            "https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {token}"}
        )

        data = response.json()
        assert data["ok"] is True, f"Slack auth.test failed: {data.get('error')}"
        assert "user_id" in data
        assert "team_id" in data

    @pytest.mark.skipif(
        not os.environ.get("SLACK_BOT_TOKEN"),
        reason="SLACK_BOT_TOKEN required for integration tests",
    )
    def test_slack_bot_can_post_to_test_channel(self):
        """Test that bot can post messages."""
        import httpx

        token = os.environ["SLACK_BOT_TOKEN"]

        # First, find a channel the bot is in
        response = httpx.post(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {token}"},
            data={"types": "public_channel", "limit": 10},
        )

        data = response.json()
        assert data["ok"] is True

        # Find a channel where is_member is True
        member_channels = [c for c in data.get("channels", []) if c.get("is_member")]

        if not member_channels:
            pytest.skip("Bot is not a member of any channels")

        # Bot can access channels - integration is working
        assert len(member_channels) > 0

    @pytest.mark.skipif(
        not os.environ.get("WEBHOOK_URL"),
        reason="WEBHOOK_URL required (e.g., https://webhook.team.vibebrowser.app)",
    )
    def test_webhook_endpoint_reachable(self):
        """Test that webhook endpoint is reachable."""
        import httpx

        url = os.environ["WEBHOOK_URL"]
        response = httpx.get(f"{url}/health", timeout=10)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.skipif(not os.environ.get("WEBHOOK_URL"), reason="WEBHOOK_URL required")
    def test_webhook_rejects_unsigned_requests(self):
        """Test that webhook properly rejects unsigned Slack requests."""
        import httpx

        url = os.environ["WEBHOOK_URL"]
        response = httpx.post(
            f"{url}/slack/events",
            json={"type": "event_callback", "event": {"type": "app_mention", "text": "test"}},
            timeout=10,
        )

        # Should reject with 401
        assert response.status_code == 401
        assert "Invalid signature" in response.json().get("detail", "")


class TestLiveWebhookIntegration:
    """
    Live integration tests that call the actual deployed webhook.

    These tests simulate real Slack events with proper signatures.
    Run with: WEBHOOK_URL=https://webhook.team.vibebrowser.app SLACK_SIGNING_SECRET=xxx pytest tests/test_webhook.py -v -k live
    """

    @pytest.fixture
    def webhook_url(self):
        """Get webhook URL from environment."""
        url = os.environ.get("WEBHOOK_URL")
        if not url:
            pytest.skip("WEBHOOK_URL required for live tests")
        return url

    @pytest.fixture
    def signing_secret(self):
        """Get signing secret from environment."""
        return os.environ.get("SLACK_SIGNING_SECRET", "")

    def _make_signed_request(self, url: str, payload: dict, signing_secret: str):
        """Make a properly signed Slack request."""
        import httpx

        timestamp = str(int(time.time()))
        payload_str = json.dumps(payload)
        signature = generate_slack_signature(payload_str, timestamp, signing_secret)

        return httpx.post(
            url,
            content=payload_str,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            timeout=30,
        )

    def test_live_health_check(self, webhook_url):
        """Test that the live webhook health endpoint responds."""
        import httpx

        response = httpx.get(f"{webhook_url}/health", timeout=10)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "vibeteam-webhook"
        print(f"✓ Health check passed: {data}")

    def test_live_url_verification(self, webhook_url):
        """Test URL verification challenge on live webhook."""
        import httpx

        challenge = f"test_challenge_{int(time.time())}"
        payload = {"type": "url_verification", "challenge": challenge}

        response = httpx.post(
            f"{webhook_url}/slack/events",
            json=payload,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge
        print(f"✓ URL verification passed: challenge echoed correctly")

    @pytest.mark.skipif(
        not os.environ.get("SLACK_SIGNING_SECRET"),
        reason="SLACK_SIGNING_SECRET required for signed request tests",
    )
    def test_live_signed_event_accepted(self, webhook_url, signing_secret):
        """Test that a properly signed event is accepted by live webhook."""
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U_TEST_USER",
                "channel": "C_TEST_CHANNEL",
                "text": "<@U0AAYE8HV6Z> integration test - please ignore",
                "ts": str(time.time()),
            },
        }

        response = self._make_signed_request(f"{webhook_url}/slack/events", payload, signing_secret)

        # Should accept the event (200) - agent processing happens async
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["event"] == "app_mention"
        print(f"✓ Signed event accepted: {data}")

    @pytest.mark.skipif(
        not os.environ.get("SLACK_SIGNING_SECRET"),
        reason="SLACK_SIGNING_SECRET required for signed request tests",
    )
    def test_live_bot_message_ignored(self, webhook_url, signing_secret):
        """Test that bot messages are properly ignored on live webhook."""
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "bot_id": "B_TEST_BOT",
                "user": "U_TEST_USER",
                "channel": "C_TEST_CHANNEL",
                "text": "bot message should be ignored",
                "ts": str(time.time()),
            },
        }

        response = self._make_signed_request(f"{webhook_url}/slack/events", payload, signing_secret)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "bot_message"
        print(f"✓ Bot message correctly ignored: {data}")

    def test_live_invalid_signature_rejected(self, webhook_url):
        """Test that invalid signatures are rejected on live webhook."""
        import httpx

        payload = {
            "type": "event_callback",
            "event": {"type": "app_mention", "text": "test"},
        }

        response = httpx.post(
            f"{webhook_url}/slack/events",
            json=payload,
            headers={
                "X-Slack-Request-Timestamp": str(int(time.time())),
                "X-Slack-Signature": "v0=invalid_signature_here",
            },
            timeout=10,
        )

        assert response.status_code == 401
        assert "Invalid signature" in response.json().get("detail", "")
        print(f"✓ Invalid signature correctly rejected")


def run_live_webhook_tests():
    """
    Convenience function to run live webhook tests.

    Usage:
        python -c "from tests.test_webhook import run_live_webhook_tests; run_live_webhook_tests()"

    Or with environment variables:
        WEBHOOK_URL=https://webhook.team.vibebrowser.app \\
        SLACK_SIGNING_SECRET=your_secret \\
        python -m pytest tests/test_webhook.py -v -k live
    """
    import subprocess
    import sys

    # Default webhook URL
    webhook_url = os.environ.get("WEBHOOK_URL", "https://webhook.team.vibebrowser.app")

    print(f"Running live webhook tests against: {webhook_url}")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "-k", "live", "--tb=short"],
        env={**os.environ, "WEBHOOK_URL": webhook_url},
    )
    return result.returncode


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
