"""
Test for Product Manager processing feature requests.

Tests the full flow:
1. Load feature request from JSON file (or use default)
2. PM analyzes the request
3. PM updates GitHub Customer Requests issue
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# Check if vibeteam.roles exists
def _roles_available():
    try:
        from vibeteam import roles  # noqa: F401

        return True
    except ImportError:
        return False


ROLES_AVAILABLE = _roles_available()


@pytest.fixture
def sample_request() -> dict:
    """Sample feature request for testing."""
    return {
        "request": "I want to integrate with Notion.so to sync my browser automation tasks",
        "source": "docs-chat",
    }


@pytest.mark.e2e
@pytest.mark.skipif(
    not ROLES_AVAILABLE,
    reason="vibeteam.roles module not implemented yet",
)
@pytest.mark.skipif(
    not os.getenv("AZURE_API_KEY"),
    reason="AZURE_API_KEY not set",
)
class TestPMFeatureRequest:
    """Test Product Manager feature request processing."""

    @pytest.mark.asyncio
    async def test_process_feature_request_action(self, sample_request: dict) -> None:
        """Test the ProcessFeatureRequest action directly."""
        from vibeteam.roles.product_manager import ProcessFeatureRequest

        action = ProcessFeatureRequest()
        result = await action.run(
            request=sample_request["request"],
            source=sample_request["source"],
        )

        # Verify result structure
        assert "priority" in result
        assert result["priority"] in ["P0", "P1", "P2", "P3"]
        assert "summary" in result
        assert len(result["summary"]) <= 60  # Should be concise
        assert "analysis" in result
        assert "status" in result

        print(f"\nPriority: {result['priority']}")
        print(f"Summary: {result['summary']}")
        print(f"Analysis: {result['analysis']}")

    @pytest.mark.asyncio
    async def test_pm_process_and_update_github(self, sample_request: dict) -> None:
        """Test PM processing with GitHub update."""
        if not os.getenv("GITHUB_TOKEN"):
            pytest.skip("GITHUB_TOKEN not set")

        from vibeteam.roles import ProductManager

        pm = ProductManager()
        result = await pm.process_feature_request(
            request=sample_request["request"],
            source=sample_request["source"],
            update_github=True,
        )

        # Verify analysis
        assert "priority" in result
        assert "summary" in result
        assert "analysis" in result

        # Verify GitHub was updated
        assert "github_updated" in result
        if result.get("github_updated"):
            print("\nGitHub Customer Requests issue updated!")
            print("Check: https://github.com/VibeTechnologies/VibeWebAgent/issues/322")
        else:
            print(
                f"\nGitHub update failed: {result.get('github_error', 'Unknown error')}"
            )

        print(f"\nResult: {json.dumps(result, indent=2)}")


@pytest.mark.unit
class TestGitHubConnector:
    """Test GitHub connector operations."""

    @pytest.mark.skipif(
        not os.getenv("GITHUB_TOKEN"),
        reason="GITHUB_TOKEN not set",
    )
    def test_get_customer_requests_table(self) -> None:
        """Test reading the Customer Requests table."""
        from vibeteam.connectors.github import GitHubConnector

        gh = GitHubConnector()
        body, requests = gh.get_customer_requests_table()

        assert "Customer Requests" in body
        assert "| Date |" in body
        print(f"\nFound {len(requests)} existing requests")
        for req in requests:
            print(f"  - {req.get('date')}: {req.get('request')[:40]}...")

    @pytest.mark.skipif(
        not os.getenv("GITHUB_TOKEN"),
        reason="GITHUB_TOKEN not set",
    )
    def test_add_customer_request(self) -> None:
        """Test adding a request to the table."""
        from vibeteam.connectors.github import GitHubConnector

        gh = GitHubConnector()

        # Add a test request
        issue = gh.add_customer_request(
            request="Test: Notion.so integration",
            source="test",
            priority="P2",
            status="New",
            analysis="Test entry from automated tests",
        )

        assert issue.number == 322
        assert "Test: Notion.so integration" in issue.body

        print(f"\nAdded test request to issue #{issue.number}")
        print(f"URL: {issue.html_url}")


if __name__ == "__main__":
    # Run a quick manual test
    import asyncio

    async def manual_test():
        request = (
            "I want to integrate with Notion.so to sync my browser automation tasks"
        )
        source = "docs-chat"

        print(f"Testing feature request: {request}")
        print(f"Source: {source}")
        print()

        if os.getenv("AZURE_API_KEY"):
            from vibeteam.roles.product_manager import ProcessFeatureRequest

            action = ProcessFeatureRequest()
            result = await action.run(request=request, source=source)
            print(f"Result: {json.dumps(result, indent=2)}")
        else:
            print("Set AZURE_API_KEY to test LLM analysis")

        if os.getenv("GITHUB_TOKEN"):
            from vibeteam.connectors.github import GitHubConnector

            gh = GitHubConnector()
            body, requests = gh.get_customer_requests_table()
            print(f"\nCustomer Requests table has {len(requests)} entries")
        else:
            print("\nSet GITHUB_TOKEN to test GitHub operations")

    asyncio.run(manual_test())
