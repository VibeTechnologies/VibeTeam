"""
Integration tests for webhook routing to agents.

Tests the complete flow from webhook event to agent response.
"""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    """Create test client for the gateway server."""
    from vibeteam.gateway.server import app

    return TestClient(app)


@pytest.fixture
def github_webhook_secret():
    """GitHub webhook secret for testing."""
    return "test_webhook_secret"


@pytest.fixture
def sentry_client_secret():
    """Sentry client secret for testing."""
    return "test_sentry_secret"


def generate_github_signature(payload: str, secret: str) -> str:
    """Generate GitHub webhook signature."""
    return (
        "sha256="
        + hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
    )


def generate_sentry_signature(payload: str, secret: str) -> str:
    """Generate Sentry webhook signature."""
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


class TestGitHubWebhookRouting:
    """Test GitHub webhook routing to agents."""

    def test_issue_assigned_to_bot(self, test_client, github_webhook_secret, monkeypatch):
        """Test that issue assignment to bot triggers SWE agent."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github_webhook_secret)
        monkeypatch.setenv("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")
        monkeypatch.setenv("GITHUB_APP_ID", "")  # Disable App auth for test

        payload = {
            "action": "assigned",
            "issue": {
                "number": 123,
                "title": "Test Issue",
                "body": "This is a test issue",
                "html_url": "https://github.com/owner/repo/issues/123",
            },
            "assignee": {
                "login": "vibeteam-bot[bot]",
                "id": 12345,
            },
            "repository": {
                "full_name": "owner/repo",
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_github_signature(payload_str, github_webhook_secret)

        with patch("vibeteam.gateway.routes.github.call_agent_service") as mock_agent:
            mock_agent.return_value = asyncio.Future()
            mock_agent.return_value.set_result({"response": "Task completed"})

            response = test_client.post(
                "/webhook",
                content=payload_str,
                headers={
                    "X-GitHub-Event": "issues",
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "123" in data["message"]

    def test_issue_comment_with_role_mention(self, test_client, github_webhook_secret, monkeypatch):
        """Test that issue comment with /RoleName triggers appropriate agent."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github_webhook_secret)
        monkeypatch.setenv("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")

        payload = {
            "action": "created",
            "issue": {
                "number": 123,
                "title": "Test Issue",
                "body": "Original issue body",
            },
            "comment": {
                "body": "This needs deployment help\n/ReleaseEngineer",
                "user": {"login": "testuser"},
            },
            "repository": {
                "full_name": "owner/repo",
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_github_signature(payload_str, github_webhook_secret)

        with patch("vibeteam.gateway.routes.github.call_agent_service") as mock_agent:
            mock_agent.return_value = asyncio.Future()
            mock_agent.return_value.set_result({"response": "Deployment handled"})

            response = test_client.post(
                "/webhook",
                content=payload_str,
                headers={
                    "X-GitHub-Event": "issue_comment",
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "release_engineer" in data["message"].lower()

    def test_invalid_signature_rejected(self, test_client, monkeypatch):
        """Test that webhooks with invalid signatures are rejected."""
        # Patch the config directly since FastAPI loads it at import time
        from vibeteam.gateway.routes import github

        original_secret = github.config.GITHUB_WEBHOOK_SECRET
        github.config.GITHUB_WEBHOOK_SECRET = "test_secret"

        try:
            payload = {"action": "opened", "issue": {"number": 1}}
            payload_str = json.dumps(payload)

            response = test_client.post(
                "/webhook",
                content=payload_str,
                headers={
                    "X-GitHub-Event": "issues",
                    "X-Hub-Signature-256": "sha256=invalid_signature",
                    "Content-Type": "application/json",
                },
            )

            assert response.status_code == 401
            assert "Invalid signature" in response.text
        finally:
            github.config.GITHUB_WEBHOOK_SECRET = original_secret


class TestSentryWebhookRouting:
    """Test Sentry webhook routing to agents."""

    def test_valid_bug_routed_to_agent(self, test_client, sentry_client_secret, monkeypatch):
        """Test that valid bugs are routed to Release Engineer agent."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "123456",
                    "shortId": "VIBETEAM-123",
                    "title": "TypeError: Cannot read property 'user' of undefined",
                    "culprit": "app/routes/auth.js in authenticate",
                    "count": 150,
                    "userCount": 45,
                    "firstSeen": "2024-02-10T00:00:00Z",
                    "lastSeen": "2024-02-10T03:00:00Z",
                    "level": "error",
                    "status": "unresolved",
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        # Mock the CLI command execution
        with patch("vibeteam.webhook.server.asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"Success", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            response = test_client.post(
                "/webhook/sentry",
                content=payload_str,
                headers={
                    "Sentry-Hook-Signature": signature,
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["classification"] in ["VALID_BUG", "NEEDS_INVESTIGATION"]
        assert data["short_id"] == "VIBETEAM-123"

    def test_noise_issue_skipped(self, test_client, sentry_client_secret, monkeypatch):
        """Test that noise issues are not routed to agents."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "789",
                    "shortId": "VIBETEAM-789",
                    "title": "Failed to fetch",
                    "count": 5,
                    "userCount": 2,
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        response = test_client.post(
            "/webhook/sentry",
            content=payload_str,
            headers={
                "Sentry-Hook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["reason"] == "noise"

    def test_invalid_sentry_signature_rejected(self, test_client):
        """Test that Sentry webhooks with invalid signatures are rejected."""
        # Patch the gateway config directly
        from vibeteam.gateway import server

        original_secret = server.config.SENTRY_CLIENT_SECRET
        server.config.SENTRY_CLIENT_SECRET = "test_secret"

        try:
            payload = {"action": "created", "data": {"issue": {"id": "123"}}}
            payload_str = json.dumps(payload)

            response = test_client.post(
                "/webhook/sentry",
                content=payload_str,
                headers={
                    "Sentry-Hook-Signature": "invalid_signature",
                    "Content-Type": "application/json",
                },
            )

            assert response.status_code == 401
        finally:
            server.config.SENTRY_CLIENT_SECRET = original_secret


class TestWebhookGitHubAppAuth:
    """Test webhook handlers use GitHub App authentication."""

    @pytest.mark.skip("Complex async mocking - covered by other tests")
    def test_acknowledgment_uses_app_token(self, test_client, github_webhook_secret, monkeypatch):
        """Test that acknowledgment comments use GitHub App token."""
        # This test is complex due to async mocking - the functionality is
        # covered by unit tests in test_github_app_auth.py
        pass


@pytest.mark.integration
class TestEndToEndWebhookFlow:
    """End-to-end tests requiring full agent services (marked for integration testing)."""

    def test_github_issue_assignment_creates_pr(self):
        """Test that assigning an issue to the bot creates a PR (requires agent services)."""
        pytest.skip("Requires running agent services and GitHub credentials")

    def test_sentry_issue_creates_github_issue(self):
        """Test that Sentry error creates GitHub issue (requires agent services)."""
        pytest.skip("Requires running agent services and Sentry/GitHub credentials")
