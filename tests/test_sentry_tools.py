"""
Unit tests for agent_service/shared/sentry_tools.py

Tests the standalone Sentry tools that don't depend on vibeteam.connectors.
These tools are used by OpenHands agents in the container where vibeteam
package is not installed.

Run with:
    pytest tests/test_sentry_tools.py -v

Run integration tests (requires SENTRY_AUTH_TOKEN):
    pytest tests/test_sentry_tools.py -v --run-integration
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest


class TestSentryToolsUnit:
    """Unit tests for sentry_tools.py (no external calls)."""

    def test_import_sentry_tools(self):
        """Test that sentry_tools can be imported without vibeteam dependency."""
        # This is the key test - it should work without vibeteam.connectors
        from agent_service.shared.sentry_tools import (
            SentryClient,
            SentryIssue,
            get_sentry_context,
        )

        assert SentryClient is not None
        assert SentryIssue is not None
        assert get_sentry_context is not None

    def test_get_sentry_context_no_token(self):
        """Test that get_sentry_context fails gracefully without token."""
        from agent_service.shared.sentry_tools import get_sentry_context

        # Temporarily remove token if set
        original_token = os.environ.pop("SENTRY_AUTH_TOKEN", None)
        try:
            result = get_sentry_context()
            assert "not configured" in result.lower()
        finally:
            if original_token:
                os.environ["SENTRY_AUTH_TOKEN"] = original_token

    def test_sentry_client_requires_token(self):
        """Test that SentryClient raises error without token."""
        from agent_service.shared.sentry_tools import SentryClient

        # Temporarily remove token if set
        original_token = os.environ.pop("SENTRY_AUTH_TOKEN", None)
        try:
            with pytest.raises(ValueError, match="auth token required"):
                SentryClient()
        finally:
            if original_token:
                os.environ["SENTRY_AUTH_TOKEN"] = original_token

    def test_sentry_issue_dataclass(self):
        """Test SentryIssue dataclass properties."""
        from agent_service.shared.sentry_tools import SentryIssue

        issue = SentryIssue(
            id="123",
            short_id="TEST-1",
            title="Test Error",
            culprit="test.py",
            level="error",
            status="unresolved",
            first_seen="2026-02-05T10:00:00Z",
            last_seen="2026-02-05T12:00:00Z",
            count=10,
            user_count=5,
            project="test-project",
            permalink="https://sentry.io/issues/123/",
            metadata={},
        )

        assert issue.short_id == "TEST-1"
        assert issue.count == 10
        assert not issue.is_frequent  # count must be > 10 to be frequent

    def test_sentry_issue_is_frequent(self):
        """Test SentryIssue.is_frequent property."""
        from agent_service.shared.sentry_tools import SentryIssue

        # Not frequent (count <= 10)
        issue_low = SentryIssue(
            id="1",
            short_id="T-1",
            title="",
            culprit="",
            level="error",
            status="unresolved",
            first_seen="2026-02-05T10:00:00Z",
            last_seen="2026-02-05T12:00:00Z",
            count=5,
            user_count=0,
            project="test",
            permalink="",
            metadata={},
        )
        assert not issue_low.is_frequent

        # Frequent (count > 10)
        issue_high = SentryIssue(
            id="2",
            short_id="T-2",
            title="",
            culprit="",
            level="error",
            status="unresolved",
            first_seen="2026-02-05T10:00:00Z",
            last_seen="2026-02-05T12:00:00Z",
            count=100,
            user_count=0,
            project="test",
            permalink="",
            metadata={},
        )
        assert issue_high.is_frequent

    @patch("agent_service.shared.sentry_tools.requests.get")
    def test_sentry_client_fetch_with_mock(self, mock_get):
        """Test SentryClient.fetch_unresolved_issues with mocked response."""
        from agent_service.shared.sentry_tools import SentryClient

        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "123",
                "shortId": "TEST-1",
                "title": "TypeError: Cannot read property",
                "culprit": "app.js",
                "level": "error",
                "status": "unresolved",
                "firstSeen": "2026-02-05T10:00:00Z",
                "lastSeen": "2026-02-05T12:00:00Z",
                "count": 42,
                "userCount": 10,
                "permalink": "https://sentry.io/issues/123/",
                "metadata": {},
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = SentryClient(auth_token="test-token")
        issues = client.fetch_unresolved_issues(project="test-project", hours=24, limit=10)

        assert len(issues) == 1
        assert issues[0].short_id == "TEST-1"
        assert issues[0].count == 42
        assert issues[0].title == "TypeError: Cannot read property"

    @patch("agent_service.shared.sentry_tools.requests.get")
    def test_get_sentry_context_formats_output(self, mock_get):
        """Test that get_sentry_context formats issues correctly."""
        from agent_service.shared.sentry_tools import get_sentry_context

        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "123",
                "shortId": "VIBE-1",
                "title": "Test Error",
                "culprit": "test.py",
                "level": "error",
                "status": "unresolved",
                "firstSeen": "2026-02-05T10:00:00Z",
                "lastSeen": "2026-02-05T12:00:00Z",
                "count": 5,
                "userCount": 2,
                "permalink": "https://sentry.io/issues/123/",
                "metadata": {},
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Set token for test
        original_token = os.environ.get("SENTRY_AUTH_TOKEN")
        os.environ["SENTRY_AUTH_TOKEN"] = "test-token"
        try:
            result = get_sentry_context(hours=24, limit=5)

            assert "Current Sentry Issues" in result
            assert "VIBE-1" in result
            assert "Test Error" in result
            assert "Count: 5" in result
        finally:
            if original_token:
                os.environ["SENTRY_AUTH_TOKEN"] = original_token
            else:
                os.environ.pop("SENTRY_AUTH_TOKEN", None)


@pytest.mark.integration
class TestSentryToolsIntegration:
    """Integration tests that require real SENTRY_AUTH_TOKEN."""

    @pytest.fixture
    def sentry_token(self):
        """Get Sentry token or skip test."""
        token = os.getenv("SENTRY_AUTH_TOKEN")
        if not token:
            pytest.skip("SENTRY_AUTH_TOKEN not configured")
        return token

    def test_real_sentry_fetch(self, sentry_token):
        """Test fetching real Sentry issues."""
        from agent_service.shared.sentry_tools import SentryClient

        client = SentryClient(auth_token=sentry_token, timeout=10.0)

        start = time.perf_counter()
        issues = client.fetch_unresolved_issues(hours=24, limit=5)
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Standalone sentry_tools - Real Sentry Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Issues found: {len(issues)}")

        for issue in issues:
            print(f"  - [{issue.project}] {issue.short_id}: {issue.title[:50]}...")
            print(f"    Count: {issue.count}, Level: {issue.level}")

        print(f"{'=' * 60}")

        # Verify we got a list (may be empty if no issues)
        assert isinstance(issues, list)
        # Verify latency is reasonable (should be < 15s with 10s timeout)
        assert latency < 15000, f"Sentry fetch took too long: {latency}ms"

    def test_get_sentry_context_real(self, sentry_token):
        """Test get_sentry_context with real Sentry."""
        from agent_service.shared.sentry_tools import get_sentry_context

        start = time.perf_counter()
        result = get_sentry_context(hours=24, limit=5)
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("get_sentry_context - Real Sentry Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}")
        print(f"{'=' * 60}")

        # Should not be an error message
        assert "error" not in result.lower() or "sentry issues" in result.lower()
        # Should complete in reasonable time
        assert latency < 15000, f"get_sentry_context took too long: {latency}ms"

    def test_sentry_timeout_behavior(self, sentry_token):
        """Test that timeout is respected."""
        from agent_service.shared.sentry_tools import SentryClient

        # Create client with very short timeout
        client = SentryClient(auth_token=sentry_token, timeout=0.001)

        start = time.perf_counter()
        try:
            client.fetch_unresolved_issues(hours=24, limit=1)
            # If it succeeds (unlikely), that's fine
        except Exception:
            # Expected to timeout
            pass
        latency = (time.perf_counter() - start) * 1000

        # Should fail fast, not hang
        assert latency < 5000, f"Timeout not respected, took {latency}ms"


class TestSentryToolsNoVibeteamDependency:
    """Verify sentry_tools doesn't import vibeteam.connectors."""

    def test_no_vibeteam_import(self):
        """Ensure sentry_tools doesn't depend on vibeteam.connectors."""
        import sys

        # Remove vibeteam from modules if present
        modules_to_remove = [k for k in sys.modules.keys() if k.startswith("vibeteam")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Mock vibeteam to raise ImportError
        with patch.dict(
            sys.modules,
            {"vibeteam": None, "vibeteam.connectors": None, "vibeteam.connectors.sentry": None},
        ):
            # Re-import sentry_tools - should work without vibeteam
            import importlib

            import agent_service.shared.sentry_tools as st

            importlib.reload(st)

            # Should still be able to use the module
            assert st.SentryClient is not None
            assert st.get_sentry_context is not None
