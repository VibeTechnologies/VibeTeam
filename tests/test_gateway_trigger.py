"""
Tests for /slack/trigger endpoint authentication and input validation.

Tests cover:
- Bearer token auth when SLACK_TRIGGER_SECRET is set
- 503 misconfiguration when SLACK_TRIGGER_SECRET is not set
- Input validation (missing channel, text, role mentions)
- Rate limiting
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def _patch_run_agent():
    """Patch run_agent_for_slack so it doesn't actually invoke agents."""
    with patch(
        "vibeteam.gateway.routes.slack.run_agent_for_slack",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def client(_patch_run_agent):
    """Create a test client for the gateway app."""
    from vibeteam.gateway.server import app

    return TestClient(app)


VALID_PAYLOAD = {
    "channel": "C0AATPSADB8",
    "thread_ts": "1234567890.123456",
    "text": "@SupportEngineer please investigate the issue",
    "user_id": "test_user",
}

AUTH_HEADERS = {"Authorization": "Bearer test-secret"}


class TestTriggerAuth:
    """Test /slack/trigger authentication."""

    def test_503_when_secret_unset(self, client: TestClient):
        """When SLACK_TRIGGER_SECRET is empty, endpoint rejects as misconfigured."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = ""
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post("/slack/trigger", json=VALID_PAYLOAD)
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_401_when_secret_set_and_no_header(self, client: TestClient):
        """When SLACK_TRIGGER_SECRET is set, missing Authorization returns 401."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret-value"
            response = client.post("/slack/trigger", json=VALID_PAYLOAD)
        assert response.status_code == 401
        assert "Bearer token required" in response.json()["detail"]

    def test_401_when_secret_set_and_wrong_scheme(self, client: TestClient):
        """When SLACK_TRIGGER_SECRET is set, non-Bearer auth returns 401."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret-value"
            response = client.post(
                "/slack/trigger",
                json=VALID_PAYLOAD,
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
        assert response.status_code == 401

    def test_403_when_secret_set_and_wrong_token(self, client: TestClient):
        """When SLACK_TRIGGER_SECRET is set, wrong Bearer token returns 403."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "correct-secret"
            response = client.post(
                "/slack/trigger",
                json=VALID_PAYLOAD,
                headers={"Authorization": "Bearer wrong-secret"},
            )
        assert response.status_code == 403
        assert "Invalid trigger secret" in response.json()["detail"]

    def test_200_when_secret_set_and_correct_token(self, client: TestClient):
        """When SLACK_TRIGGER_SECRET is set and correct Bearer token, returns 200."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "correct-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post(
                "/slack/trigger",
                json=VALID_PAYLOAD,
                headers={"Authorization": "Bearer correct-secret"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["channel"] == "C0AATPSADB8"


class TestTriggerValidation:
    """Test /slack/trigger input validation."""

    def test_400_missing_channel(self, client: TestClient):
        """Missing channel returns 400."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            response = client.post(
                "/slack/trigger",
                json={"text": "@SupportEngineer check this"},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 400
        assert "channel is required" in response.json()["detail"]

    def test_400_missing_text(self, client: TestClient):
        """Missing text returns 400."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            response = client.post(
                "/slack/trigger",
                json={"channel": "C0AATPSADB8"},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 400
        assert "text is required" in response.json()["detail"]

    def test_400_no_role_mention(self, client: TestClient):
        """Text without @RoleName mention returns 400."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            response = client.post(
                "/slack/trigger",
                json={
                    "channel": "C0AATPSADB8",
                    "text": "just a regular message with no mention",
                },
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 400
        assert "@RoleName mention" in response.json()["detail"]

    def test_short_form_mentions_accepted(self, client: TestClient):
        """Short-form mentions like @SWE and @PM are accepted."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post(
                "/slack/trigger",
                json={
                    "channel": "C0AATPSADB8",
                    "text": "@SWE please review this code",
                },
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 200
        assert "software_engineer" in response.json()["roles"]

    def test_multiple_role_mentions(self, client: TestClient):
        """Multiple @RoleName mentions are all returned."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post(
                "/slack/trigger",
                json={
                    "channel": "C0AATPSADB8",
                    "text": "@SupportEngineer and @ReleaseEngineer investigate this",
                },
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 200
        roles = response.json()["roles"]
        assert "support_engineer" in roles
        assert "release_engineer" in roles


class TestTriggerRateLimit:
    """Test /slack/trigger rate limiting."""

    def test_rate_limit_exceeded(self, client: TestClient):
        """Exceeding rate limit returns 429."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"

            # Reset both the per-endpoint trigger limiter and global middleware limiter
            from vibeteam.gateway.routes.slack import _trigger_rate_limiter

            _trigger_rate_limiter.reset()

            from vibeteam.gateway.middleware import get_endpoint_limiter

            get_endpoint_limiter().reset()

            # Fire requests up to the limit + 1
            for i in range(_trigger_rate_limiter.max_requests):
                resp = client.post("/slack/trigger", json=VALID_PAYLOAD, headers=AUTH_HEADERS)
                assert resp.status_code == 200, f"Request {i + 1} should succeed"

            # Next request should be rate limited
            response = client.post("/slack/trigger", json=VALID_PAYLOAD, headers=AUTH_HEADERS)
            assert response.status_code == 429
            assert "Rate limit exceeded" in response.json()["detail"]


class TestTriggerAsyncMode:
    """Test /slack/trigger use_async parameter."""

    @pytest.fixture(autouse=True)
    def _reset_rate_limiter(self):
        """Reset rate limiter before each test so prior tests don't cause 429s."""
        from vibeteam.gateway.routes.slack import _trigger_rate_limiter

        _trigger_rate_limiter.reset()

        # Also reset global middleware rate limiter
        from vibeteam.gateway.middleware import get_endpoint_limiter

        get_endpoint_limiter().reset()

    def test_default_mode_is_sync(self, client: TestClient, _patch_run_agent):
        """Without use_async, mode should be 'sync' and run_agent called with use_async=False."""
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post("/slack/trigger", json=VALID_PAYLOAD, headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "sync"
        # Verify run_agent_for_slack was called with use_async=False
        _patch_run_agent.assert_called_once()
        _, kwargs = _patch_run_agent.call_args
        assert kwargs.get("use_async") is False

    def test_async_mode_returns_async(self, client: TestClient, _patch_run_agent):
        """With use_async=true, mode should be 'async' and run_agent called with use_async=True."""
        payload = {**VALID_PAYLOAD, "use_async": True}
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post("/slack/trigger", json=payload, headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "async"
        # Verify run_agent_for_slack was called with use_async=True
        _patch_run_agent.assert_called_once()
        _, kwargs = _patch_run_agent.call_args
        assert kwargs.get("use_async") is True

    def test_async_false_explicit(self, client: TestClient, _patch_run_agent):
        """With use_async=false explicitly, mode should be 'sync'."""
        payload = {**VALID_PAYLOAD, "use_async": False}
        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_TRIGGER_SECRET = "test-secret"
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"
            response = client.post("/slack/trigger", json=payload, headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "sync"
        # Verify run_agent_for_slack was called with use_async=False
        _patch_run_agent.assert_called_once()
        _, kwargs = _patch_run_agent.call_args
        assert kwargs.get("use_async") is False
