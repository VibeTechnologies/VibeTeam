"""
Tests for VibeTeam OpenHands tools.

These tests verify the tool wrappers work correctly with mocked connectors.
"""

import pytest
from unittest.mock import MagicMock, patch

from vibeteam.tools.github import GitHubTool
from vibeteam.tools.sentry import SentryTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.health import HealthCheckTool


class TestGitHubTool:
    """Test GitHubTool functionality."""

    def test_schema_structure(self) -> None:
        """Test tool schema is correctly structured."""
        with patch("vibeteam.tools.github.GitHubConnector"):
            tool = GitHubTool(token="fake_token")
        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "github"
        assert "action" in schema["function"]["parameters"]["properties"]

    def test_schema_actions(self) -> None:
        """Test all expected actions are in schema."""
        with patch("vibeteam.tools.github.GitHubConnector"):
            tool = GitHubTool(token="fake_token")
        schema = tool.get_schema()
        actions = schema["function"]["parameters"]["properties"]["action"]["enum"]

        expected_actions = [
            "get_issue",
            "update_issue",
            "add_comment",
            "search_issues",
            "get_customer_requests",
            "add_customer_request",
            "get_pr",
            "list_prs",
            "create_review",
        ]
        for action in expected_actions:
            assert action in actions

    @pytest.mark.asyncio
    async def test_get_issue(self) -> None:
        """Test get_issue action."""
        from vibeteam.connectors.github import GitHubIssue

        with patch("vibeteam.tools.github.GitHubConnector") as MockConnector:
            mock_connector = MagicMock()
            MockConnector.return_value = mock_connector

            # Use actual dataclass instance
            mock_issue = GitHubIssue(
                number=123,
                title="Test Issue",
                body="Test body",
                state="open",
                labels=["bug"],
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-02T00:00:00Z",
                html_url="https://github.com/test",
                user="testuser",
            )
            mock_connector.get_issue.return_value = mock_issue

            tool = GitHubTool(token="fake_token")
            result = await tool.execute(action="get_issue", issue_number=123)

        assert result.success is True
        assert "123" in result.output

    @pytest.mark.asyncio
    async def test_missing_required_param(self) -> None:
        """Test error when required param is missing."""
        with patch("vibeteam.tools.github.GitHubConnector"):
            tool = GitHubTool(token="fake_token")
            result = await tool.execute(action="get_issue")  # Missing issue_number

        assert result.success is False
        assert "issue_number required" in result.error


class TestSentryTool:
    """Test SentryTool functionality."""

    def test_schema_structure(self) -> None:
        """Test tool schema is correctly structured."""
        with patch("vibeteam.tools.sentry.SentryConnector"):
            tool = SentryTool(auth_token="fake_token")
        schema = tool.get_schema()

        assert schema["function"]["name"] == "sentry"
        assert "action" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_fetch_issues(self) -> None:
        """Test fetch_issues action."""
        with patch("vibeteam.tools.sentry.SentryConnector") as MockConnector:
            mock_connector = MagicMock()
            MockConnector.return_value = mock_connector
            mock_connector.fetch_unresolved_issues.return_value = []

            tool = SentryTool(auth_token="fake_token")
            result = await tool.execute(action="fetch_issues", hours=24)

        assert result.success is True
        assert result.metadata["count"] == 0


class TestLangfuseTool:
    """Test LangfuseTool functionality."""

    def test_schema_structure(self) -> None:
        """Test tool schema is correctly structured."""
        with patch("vibeteam.tools.langfuse.LangfuseConnector"):
            tool = LangfuseTool(public_key="pk", secret_key="sk")
        schema = tool.get_schema()

        assert schema["function"]["name"] == "langfuse"
        actions = schema["function"]["parameters"]["properties"]["action"]["enum"]
        assert "get_traces" in actions
        assert "detect_anomalies" in actions

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        """Test health_check action."""
        with patch("vibeteam.tools.langfuse.LangfuseConnector") as MockConnector:
            mock_connector = MagicMock()
            MockConnector.return_value = mock_connector
            mock_connector.health_check.return_value = True

            tool = LangfuseTool(public_key="pk", secret_key="sk")
            result = await tool.execute(action="health_check")

        assert result.success is True
        assert result.metadata["healthy"] is True


class TestHealthCheckTool:
    """Test HealthCheckTool functionality."""

    def test_schema_structure(self) -> None:
        """Test tool schema is correctly structured."""
        tool = HealthCheckTool()
        schema = tool.get_schema()

        assert schema["function"]["name"] == "health_check"
        actions = schema["function"]["parameters"]["properties"]["action"]["enum"]
        assert "check_endpoint" in actions
        assert "check_all" in actions
        assert "get_alerts" in actions

    @pytest.mark.asyncio
    async def test_check_endpoint(self) -> None:
        """Test check_endpoint action."""
        from vibeteam.connectors.health import HealthCheckResult

        with patch("vibeteam.tools.health.HealthConnector") as MockConnector:
            mock_connector = MagicMock()
            MockConnector.return_value = mock_connector

            # Use actual dataclass instance
            mock_result = HealthCheckResult(
                url="https://example.com",
                status="healthy",
                status_code=200,
                latency_ms=100.0,
                error=None,
                timestamp="2024-01-01T00:00:00Z",
            )
            mock_connector.check_endpoint.return_value = mock_result

            tool = HealthCheckTool()
            result = await tool.execute(
                action="check_endpoint",
                url="https://example.com",
            )

        assert result.success is True
        assert result.metadata["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_check_endpoint_missing_url(self) -> None:
        """Test error when URL is missing."""
        tool = HealthCheckTool()
        result = await tool.execute(action="check_endpoint")

        assert result.success is False
        assert "url required" in result.error
