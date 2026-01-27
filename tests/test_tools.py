"""
Tests for VibeTeam OpenHands tools.

These tests verify the tool wrappers work correctly with mocked connectors.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibeteam.tools.docs import DocsTool
from vibeteam.tools.github import GitHubTool
from vibeteam.tools.health import HealthCheckTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.sentry import SentryTool


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


class TestDocsTool:
    """Test DocsTool functionality."""

    @pytest.fixture
    def temp_docs_dir(self) -> Path:
        """Create a temporary directory with test documentation files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)

            # Create test markdown files
            (docs_dir / "deployment.md").write_text(
                """# Deployment Guide

## Kubernetes Cluster

We use k3s for our kubernetes cluster.

### Pods
- api-server: Main API server
- worker: Background job processor

### Services
- api.vibebrowser.app: Public API endpoint
- portal.vibebrowser.app: User portal
"""
            )

            (docs_dir / "auth.md").write_text(
                """# Authentication

## OAuth Integration

We use Google OAuth for authentication.

### Setup
1. Create OAuth credentials
2. Configure redirect URIs
3. Set environment variables
"""
            )

            (docs_dir / "subscription.md").write_text(
                """# Subscription Tiers

| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | Basic features |
| Pro | $25/mo | All features |
| Max | $99/mo | Priority support |
"""
            )

            yield docs_dir

    def test_schema_structure(self, temp_docs_dir: Path) -> None:
        """Test tool schema is correctly structured."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "docs"
        assert "action" in schema["function"]["parameters"]["properties"]

    def test_schema_actions(self, temp_docs_dir: Path) -> None:
        """Test all expected actions are in schema."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        schema = tool.get_schema()
        actions = schema["function"]["parameters"]["properties"]["action"]["enum"]

        expected_actions = [
            "search",
            "get_file",
            "list_files",
            "get_summary",
            "search_topic",
            "sync",
        ]
        for action in expected_actions:
            assert action in actions

    @pytest.mark.asyncio
    async def test_search(self, temp_docs_dir: Path) -> None:
        """Test search action finds relevant documentation."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="search", query="kubernetes cluster")

        assert result.success is True
        assert "deployment.md" in result.output
        assert "k3s" in result.output

    @pytest.mark.asyncio
    async def test_search_no_results(self, temp_docs_dir: Path) -> None:
        """Test search returns appropriate message when no results."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="search", query="nonexistent_xyz_123")

        assert result.success is True
        assert "No documentation found" in result.output

    @pytest.mark.asyncio
    async def test_get_file(self, temp_docs_dir: Path) -> None:
        """Test get_file action retrieves file content."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="get_file", path="auth.md")

        assert result.success is True
        assert "OAuth Integration" in result.output
        assert "Google OAuth" in result.output

    @pytest.mark.asyncio
    async def test_get_file_not_found(self, temp_docs_dir: Path) -> None:
        """Test get_file returns error for missing file."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="get_file", path="nonexistent.md")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_files(self, temp_docs_dir: Path) -> None:
        """Test list_files action lists available documentation."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="list_files")

        assert result.success is True
        assert "deployment.md" in result.output
        assert "auth.md" in result.output
        assert "subscription.md" in result.output

    @pytest.mark.asyncio
    async def test_list_files_with_pattern(self, temp_docs_dir: Path) -> None:
        """Test list_files with pattern filter."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="list_files", pattern="*deploy*")

        assert result.success is True
        assert "deployment.md" in result.output
        assert "auth.md" not in result.output

    @pytest.mark.asyncio
    async def test_get_summary(self, temp_docs_dir: Path) -> None:
        """Test get_summary action returns knowledge base summary."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="get_summary")

        assert result.success is True
        assert "Total files:" in result.output
        assert "3" in result.output  # 3 test files

    @pytest.mark.asyncio
    async def test_search_topic(self, temp_docs_dir: Path) -> None:
        """Test search_topic action with topic expansion."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="search_topic", topic="auth")

        assert result.success is True
        assert "auth.md" in result.output

    @pytest.mark.asyncio
    async def test_search_missing_query(self, temp_docs_dir: Path) -> None:
        """Test search returns error when query is missing."""
        from vibeteam.connectors.docs import DocsSource

        tool = DocsTool(sources=[DocsSource(path=str(temp_docs_dir))], auto_sync=False)
        result = await tool.execute(action="search")

        assert result.success is False
        assert result.error is not None
        assert "query required" in result.error
