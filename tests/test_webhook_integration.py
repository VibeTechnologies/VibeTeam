"""
Integration tests for webhook routing to agents.

Tests the complete flow from webhook event to agent response.
"""

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

        with patch(
            "vibeteam.gateway.routes.github.call_agent_service",
            new_callable=AsyncMock,
            return_value={"response": "Task completed"},
        ) as mock_agent:
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

        with patch(
            "vibeteam.gateway.routes.github.call_agent_service",
            new_callable=AsyncMock,
            return_value={"response": "Deployment handled"},
        ) as mock_agent:
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

        # Mock call_agent_service on the gateway route (not the legacy webhook server)
        with patch(
            "vibeteam.gateway.routes.sentry.call_agent_service",
            new_callable=AsyncMock,
            return_value={"response": "Issue triaged"},
        ) as mock_agent:
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


class TestSentryClassification:
    """Test classify_sentry_issue() edge cases."""

    def test_noise_pattern_low_impact(self):
        """Low-impact noise patterns are classified as NOISE."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "Failed to fetch", "count": 5, "userCount": 2}
        assert classify_sentry_issue(issue) == "NOISE"

    def test_noise_pattern_high_impact_count(self):
        """Noise patterns with count >= 100 become NEEDS_INVESTIGATION."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "NetworkError when loading chunk", "count": 100, "userCount": 5}
        assert classify_sentry_issue(issue) == "NEEDS_INVESTIGATION"

    def test_noise_pattern_high_impact_users(self):
        """Noise patterns with userCount >= 20 become NEEDS_INVESTIGATION."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "ResizeObserver loop limit exceeded", "count": 10, "userCount": 20}
        assert classify_sentry_issue(issue) == "NEEDS_INVESTIGATION"

    def test_chrome_extension_not_ours(self):
        """Chrome extension errors from third-party extensions are NOISE."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {
            "title": "Error in chrome-extension://abcdef123456/content.js",
            "count": 50,
            "userCount": 10,
        }
        assert classify_sentry_issue(issue) == "NOISE"

    def test_chrome_extension_ours(self):
        """Chrome extension errors from our extension are NOT noise."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        # Our extension ID: ajfjlohdpfgngdjfafhhcnpmijbbdgln
        issue = {
            "title": "Error in chrome-extension://ajfjlohdpfgngdjfafhhcnpmijbbdgln/bg.js",
            "count": 50,
            "userCount": 10,
        }
        # Should be classified by bug patterns or impact, NOT as NOISE
        assert classify_sentry_issue(issue) != "NOISE"

    def test_bug_pattern_typeerror(self):
        """TypeError titles are classified as VALID_BUG."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {
            "title": "TypeError: Cannot read property 'user' of undefined",
            "count": 3,
            "userCount": 1,
        }
        assert classify_sentry_issue(issue) == "VALID_BUG"

    def test_bug_pattern_reference_error(self):
        """ReferenceError titles are classified as VALID_BUG."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {
            "title": "ReferenceError: myVariable is not defined",
            "count": 1,
            "userCount": 1,
        }
        assert classify_sentry_issue(issue) == "VALID_BUG"

    def test_high_impact_unknown_is_valid_bug(self):
        """Unknown errors with high impact (count >= 50) are VALID_BUG."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "Something unexpected happened", "count": 50, "userCount": 5}
        assert classify_sentry_issue(issue) == "VALID_BUG"

    def test_low_impact_unknown_is_noise(self):
        """Unknown errors with low impact (count < 5, users < 3) are NOISE."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "Something unexpected happened", "count": 2, "userCount": 1}
        assert classify_sentry_issue(issue) == "NOISE"

    def test_medium_impact_unknown_needs_investigation(self):
        """Unknown errors with medium impact are NEEDS_INVESTIGATION."""
        from vibeteam.gateway.routes.sentry import classify_sentry_issue

        issue = {"title": "Something unexpected happened", "count": 10, "userCount": 5}
        assert classify_sentry_issue(issue) == "NEEDS_INVESTIGATION"


class TestSentryAgentRouting:
    """Test that Sentry webhook correctly routes to release_engineer agent."""

    def test_valid_bug_calls_agent_service(self, test_client, sentry_client_secret, monkeypatch):
        """Test that VALID_BUG triggers call_agent_service with role=release_engineer."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "999",
                    "shortId": "VIBETEAM-999",
                    "title": "TypeError: x is not a function",
                    "culprit": "app/utils.js in doStuff",
                    "count": 10,
                    "userCount": 3,
                    "firstSeen": "2024-02-10T00:00:00Z",
                    "lastSeen": "2024-02-10T01:00:00Z",
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        with patch(
            "vibeteam.gateway.routes.sentry.call_agent_service",
            new_callable=AsyncMock,
            return_value={"response": "Triaged successfully"},
        ) as mock_agent:
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
            assert data["classification"] == "VALID_BUG"

            # Verify the agent was called with correct parameters
            mock_agent.assert_called_once()
            call_kwargs = mock_agent.call_args[1]
            assert call_kwargs["role"] == "release_engineer"
            assert call_kwargs["context_type"] == "sentry"
            assert call_kwargs["context_id"] == "VIBETEAM-999"
            assert "TypeError: x is not a function" in call_kwargs["task"]
            assert "VIBETEAM-999" in call_kwargs["task"]

    def test_task_prompt_contains_issue_details(
        self, test_client, sentry_client_secret, monkeypatch
    ):
        """Test that the task prompt sent to agent contains full issue details."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "555",
                    "shortId": "VIBETEAM-555",
                    "title": "Unhandled Promise rejection",
                    "culprit": "src/api/client.ts in fetchData",
                    "count": 200,
                    "userCount": 80,
                    "firstSeen": "2024-02-09T12:00:00Z",
                    "lastSeen": "2024-02-10T12:00:00Z",
                    "level": "error",
                    "status": "unresolved",
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        with patch(
            "vibeteam.gateway.routes.sentry.call_agent_service",
            new_callable=AsyncMock,
            return_value={"response": "Triaged"},
        ) as mock_agent:
            test_client.post(
                "/webhook/sentry",
                content=payload_str,
                headers={
                    "Sentry-Hook-Signature": signature,
                    "Content-Type": "application/json",
                },
            )

            mock_agent.assert_called_once()
            task = mock_agent.call_args[1]["task"]
            # Verify task prompt contains all critical details
            assert "Sentry Error Triage" in task
            assert "VIBETEAM-555" in task
            assert "Unhandled Promise rejection" in task
            assert "src/api/client.ts in fetchData" in task
            assert "200" in task  # event count
            assert "80" in task  # user count


class TestGitHubHandoff:
    """Test SWE agent response handoff detection in GitHub webhook."""

    def test_swe_agent_response_triggers_handoff(
        self, test_client, github_webhook_secret, monkeypatch
    ):
        """When SWE agent response contains /RoleName, a second agent is invoked."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github_webhook_secret)
        monkeypatch.setenv("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")
        monkeypatch.setenv("GITHUB_APP_ID", "")

        payload = {
            "action": "assigned",
            "issue": {
                "number": 42,
                "title": "Deploy new release",
                "body": "Need a deployment to production",
                "html_url": "https://github.com/owner/repo/issues/42",
            },
            "assignee": {"login": "vibeteam-bot[bot]", "id": 12345},
            "repository": {"full_name": "owner/repo"},
        }

        payload_str = json.dumps(payload)
        signature = generate_github_signature(payload_str, github_webhook_secret)

        # First call (SWE agent) returns a handoff mention.
        # Second call (handoff target) returns a normal response.
        agent_responses = [
            {"response": "I've analyzed the code. /ReleaseEngineer please deploy to prod."},
            {"response": "Deployment initiated to production cluster."},
        ]

        with (
            patch(
                "vibeteam.gateway.routes.github.call_agent_service",
                new_callable=AsyncMock,
                side_effect=agent_responses,
            ) as mock_agent,
            patch(
                "vibeteam.gateway.routes.github.post_acknowledgment",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.github.post_github_comment",
                new_callable=AsyncMock,
            ) as mock_comment,
        ):
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

        # Verify two calls to call_agent_service:
        # 1st call: software_engineer for the original issue
        # 2nd call: release_engineer for the handoff
        assert mock_agent.call_count == 2

        first_call = mock_agent.call_args_list[0]
        assert first_call[1]["role"] == "software_engineer"

        second_call = mock_agent.call_args_list[1]
        assert second_call[1]["role"] == "release_engineer"
        assert "Handoff from SoftwareEngineer" in second_call[1]["task"]

        # Both agents should have posted comments
        assert mock_comment.call_count >= 2

    def test_swe_agent_error_posts_error_comment(
        self, test_client, github_webhook_secret, monkeypatch
    ):
        """When SWE agent returns an error, an error comment is posted and no handoff occurs."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github_webhook_secret)
        monkeypatch.setenv("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")
        monkeypatch.setenv("GITHUB_APP_ID", "")

        payload = {
            "action": "assigned",
            "issue": {
                "number": 77,
                "title": "Fix flaky test",
                "body": "The CI test is flaky",
                "html_url": "https://github.com/owner/repo/issues/77",
            },
            "assignee": {"login": "vibeteam-bot[bot]", "id": 12345},
            "repository": {"full_name": "owner/repo"},
        }

        payload_str = json.dumps(payload)
        signature = generate_github_signature(payload_str, github_webhook_secret)

        with (
            patch(
                "vibeteam.gateway.routes.github.call_agent_service",
                new_callable=AsyncMock,
                return_value={"error": "Agent service timed out after 600s"},
            ) as mock_agent,
            patch(
                "vibeteam.gateway.routes.github.post_acknowledgment",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.github.post_github_comment",
                new_callable=AsyncMock,
            ) as mock_comment,
        ):
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

        # Agent was called once (SWE agent only, no handoff)
        mock_agent.assert_called_once()
        assert mock_agent.call_args[1]["role"] == "software_engineer"

        # Error comment was posted containing the error message
        mock_comment.assert_called_once()
        comment_body = mock_comment.call_args[0][2]
        assert "error" in comment_body.lower()
        assert "Agent service timed out after 600s" in comment_body

    def test_handoff_comment_contains_agent_responses(
        self, test_client, github_webhook_secret, monkeypatch
    ):
        """Verify first comment has SWE response and second has [Release Engineer] prefix."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", github_webhook_secret)
        monkeypatch.setenv("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")
        monkeypatch.setenv("GITHUB_APP_ID", "")

        payload = {
            "action": "assigned",
            "issue": {
                "number": 88,
                "title": "Scale up deployment",
                "body": "We need more replicas",
                "html_url": "https://github.com/owner/repo/issues/88",
            },
            "assignee": {"login": "vibeteam-bot[bot]", "id": 12345},
            "repository": {"full_name": "owner/repo"},
        }

        payload_str = json.dumps(payload)
        signature = generate_github_signature(payload_str, github_webhook_secret)

        swe_response = "Analysis complete. /ReleaseEngineer please scale the deployment."
        handoff_response = "Scaled deployment to 5 replicas successfully."

        with (
            patch(
                "vibeteam.gateway.routes.github.call_agent_service",
                new_callable=AsyncMock,
                side_effect=[
                    {"response": swe_response},
                    {"response": handoff_response},
                ],
            ),
            patch(
                "vibeteam.gateway.routes.github.post_acknowledgment",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.github.post_github_comment",
                new_callable=AsyncMock,
            ) as mock_comment,
        ):
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
        assert mock_comment.call_count == 2

        # First comment: SWE agent's raw response
        first_comment = mock_comment.call_args_list[0]
        assert first_comment[0][0] == "owner/repo"  # repo
        assert first_comment[0][1] == 88  # issue number
        assert first_comment[0][2] == swe_response

        # Second comment: prefixed with [ReleaseEngineer] and contains handoff response
        second_comment = mock_comment.call_args_list[1]
        assert second_comment[0][0] == "owner/repo"
        assert second_comment[0][1] == 88
        assert second_comment[0][2].startswith("[ReleaseEngineer]")
        assert handoff_response in second_comment[0][2]


class TestSentryErrorHandling:
    """Test Sentry webhook error and edge-case paths."""

    def test_sentry_no_issue_data_ignored(self, test_client, sentry_client_secret, monkeypatch):
        """Payload with no issue data returns ignored status."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {},
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
        assert data["status"] == "ignored"
        assert data["reason"] == "no_issue_data"

    def test_sentry_agent_error_still_accepted(
        self, test_client, sentry_client_secret, monkeypatch
    ):
        """When agent returns an error, the webhook still returns accepted."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "err-1",
                    "shortId": "VIBETEAM-ERR1",
                    "title": "TypeError: boom",
                    "count": 10,
                    "userCount": 5,
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        with patch(
            "vibeteam.gateway.routes.sentry.call_agent_service",
            new_callable=AsyncMock,
            return_value={"error": "Agent service unavailable"},
        ):
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

    def test_sentry_agent_exception_handled(self, test_client, sentry_client_secret, monkeypatch):
        """When call_agent_service raises an exception, webhook still returns accepted."""
        monkeypatch.setenv("SENTRY_CLIENT_SECRET", sentry_client_secret)

        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "err-2",
                    "shortId": "VIBETEAM-ERR2",
                    "title": "ReferenceError: x is not defined",
                    "count": 20,
                    "userCount": 8,
                }
            },
        }

        payload_str = json.dumps(payload)
        signature = generate_sentry_signature(payload_str, sentry_client_secret)

        with patch(
            "vibeteam.gateway.routes.sentry.call_agent_service",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            response = test_client.post(
                "/webhook/sentry",
                content=payload_str,
                headers={
                    "Sentry-Hook-Signature": signature,
                    "Content-Type": "application/json",
                },
            )

        # The webhook returns accepted because the agent runs in a background task.
        # The exception is caught by the try/except in run_release_engineer_agent.
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"


@pytest.mark.integration
class TestEndToEndWebhookFlow:
    """End-to-end tests requiring full agent services (marked for integration testing)."""

    def test_github_issue_assignment_creates_pr(self):
        """Test that assigning an issue to the bot creates a PR (requires agent services)."""
        pytest.skip("Requires running agent services and GitHub credentials")

    def test_sentry_issue_creates_github_issue(self):
        """Test that Sentry error creates GitHub issue (requires agent services)."""
        pytest.skip("Requires running agent services and Sentry/GitHub credentials")
