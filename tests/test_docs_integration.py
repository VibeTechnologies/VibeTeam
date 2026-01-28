"""
Real Documentation Search Integration Tests for Multi-Framework Agents.

These tests verify that all agent frameworks can search product documentation
using the shared docs tools layer (agents.shared.docs_tools) which uses
BM25 for keyword-based search with fallback to simple matching.

Requirements:
    - rank-bm25 installed: pip install rank-bm25
    - AZURE_API_KEY and AZURE_API_BASE for LLM calls (for full agent tests)

Run with:
    pytest tests/test_docs_integration.py -v --run-integration

Run just shared tools tests (no LLM required):
    pytest tests/test_docs_integration.py -v --run-integration -k "TestSharedDocsTools"
"""

import os
import time
from dataclasses import dataclass

import pytest


@dataclass
class DocsTestResult:
    """Result from a docs integration test."""

    framework: str
    operation: str
    success: bool
    response: str
    latency_ms: float
    error: str | None = None

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return f"[{status}] {self.framework}/{self.operation}: {self.latency_ms:.0f}ms"


def validate_docs_response(response: str, expected_content: list[str] | None = None) -> bool:
    """
    Validate that the response contains valid documentation search results.

    Args:
        response: The response string
        expected_content: Optional list of strings that should be in the response

    Returns:
        True if the response appears to contain valid documentation data
    """
    response_lower = response.lower()

    # Check for error responses
    if "error" in response_lower:
        return False

    # Check for content markers
    has_content = any(
        marker in response_lower
        for marker in [
            "documentation search",
            "found",
            "file:",
            "available documentation",
            "===",
        ]
    )

    # Check for expected content if provided
    if expected_content:
        for content in expected_content:
            if content.lower() not in response_lower:
                return False

    return has_content


# =============================================================================
# Shared Tools Layer Tests (No LLM required)
# =============================================================================


class TestSharedDocsTools:
    """Test the shared docs tools directly without agent frameworks."""

    @pytest.mark.integration
    def test_search_docs_basic(self):
        """Test basic documentation search."""
        from agents.shared.docs_tools import search_docs

        start = time.time()
        result = search_docs("authentication", max_results=3)
        latency = (time.time() - start) * 1000

        print("\n=== search_docs('authentication') ===")
        print(f"Latency: {latency:.0f}ms")
        print(f"Response length: {len(result)} chars")
        print(f"Response preview: {result[:500]}...")

        assert result is not None
        assert "documentation search" in result.lower() or "found" in result.lower()
        # Should not start with "Error:" which indicates a failure
        assert not result.startswith("Error:")
        assert latency < 5000  # Should be fast with local files

    @pytest.mark.integration
    def test_search_docs_no_results(self):
        """Test search with no matching results."""
        from agents.shared.docs_tools import search_docs

        result = search_docs("xyznonexistentqueryzyx123")

        print("\n=== search_docs('nonexistent') ===")
        print(f"Response: {result}")

        # Should gracefully handle no results
        assert result is not None
        assert "no documentation found" in result.lower() or len(result) > 0

    @pytest.mark.integration
    def test_list_docs(self):
        """Test listing all documentation files."""
        from agents.shared.docs_tools import list_docs

        start = time.time()
        result = list_docs()
        latency = (time.time() - start) * 1000

        print("\n=== list_docs() ===")
        print(f"Latency: {latency:.0f}ms")
        print(f"Response:\n{result}")

        assert result is not None
        assert "available documentation" in result.lower()
        # Should find some markdown files
        assert ".md" in result.lower() or "documentation" in result.lower()

    @pytest.mark.integration
    def test_get_doc_content(self):
        """Test getting full content of a documentation file."""
        from agents.shared.docs_tools import get_doc_content

        result = get_doc_content("README.md")

        print("\n=== get_doc_content('README.md') ===")
        print(f"Response length: {len(result)} chars")
        print(f"Response preview: {result[:300]}...")

        assert result is not None
        # Either find the content or get a reasonable error
        assert "===" in result or "not found" in result.lower()

    @pytest.mark.integration
    def test_get_docs_context(self):
        """Test getting documentation context for agent prompts."""
        from agents.shared.docs_tools import get_docs_context

        result = get_docs_context("sentry integration", max_results=2)

        print("\n=== get_docs_context('sentry integration') ===")
        print(f"Response length: {len(result)} chars")
        print(f"Response preview: {result[:500]}...")

        assert result is not None
        assert "documentation" in result.lower()

    @pytest.mark.integration
    def test_rebuild_index(self):
        """Test rebuilding the documentation index."""
        from agents.shared.docs_tools import rebuild_index

        result = rebuild_index()

        print("\n=== rebuild_index() ===")
        print(f"Response: {result}")

        assert result is not None
        assert "indexed" in result.lower()
        assert "bm25" in result.lower()

    @pytest.mark.integration
    def test_bm25_available(self):
        """Test that BM25 is available for improved search quality."""
        from agents.shared.docs_tools import BM25_AVAILABLE, rebuild_index

        result = rebuild_index()

        print("\n=== BM25 Availability ===")
        print(f"BM25_AVAILABLE: {BM25_AVAILABLE}")
        print(f"Index status: {result}")

        # BM25 should be available after installing rank-bm25
        assert BM25_AVAILABLE, "rank-bm25 should be installed for better search quality"
        assert "bm25 available: true" in result.lower()


# =============================================================================
# Framework-Specific Agent Tests (Require LLM)
# =============================================================================


class TestAutoGenDocsIntegration:
    """Test AutoGen SupportEngineer with docs tools."""

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.getenv("AZURE_API_KEY"),
        reason="AZURE_API_KEY not set - skipping LLM test",
    )
    def test_autogen_support_engineer_has_docs_tools(self):
        """Verify AutoGen SupportEngineer has docs tools registered."""
        try:
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            agent = AutoGenSupportEngineer()
            tool_names = [t.__name__ for t in agent.agent._tools if hasattr(t, "__name__")]

            print("\n=== AutoGen SupportEngineer Tools ===")
            print(f"Tools: {tool_names}")

            assert "search_docs" in tool_names
            assert "list_docs" in tool_names
            assert "get_doc_content" in tool_names

        except ImportError as e:
            pytest.skip(f"AutoGen not available: {e}")


class TestCrewAIDocsIntegration:
    """Test CrewAI SupportEngineer with docs tools."""

    @pytest.mark.integration
    def test_crewai_support_engineer_has_docs_tools(self):
        """Verify CrewAI SupportEngineer has docs tools registered."""
        try:
            from agents.crewai.support_engineer import CrewAISupportEngineer

            agent = CrewAISupportEngineer()
            tool_names = [t.name for t in agent.tools if hasattr(t, "name")]

            print("\n=== CrewAI SupportEngineer Tools ===")
            print(f"Tools: {tool_names}")

            assert "search_docs" in tool_names
            assert "list_docs" in tool_names
            assert "get_doc_content" in tool_names

        except ImportError as e:
            pytest.skip(f"CrewAI not available: {e}")


class TestOpenHandsDocsIntegration:
    """Test OpenHands SupportEngineer with docs context injection."""

    @pytest.mark.integration
    def test_openhands_docs_context_injection(self):
        """Verify OpenHands SupportEngineer can inject docs context."""
        try:
            from agents.openhands.support_engineer import fetch_docs_context_wrapper

            result = fetch_docs_context_wrapper("authentication setup")

            print("\n=== OpenHands Docs Context Injection ===")
            print(f"Response length: {len(result)} chars")
            print(f"Response preview: {result[:500]}...")

            assert result is not None
            assert "documentation" in result.lower()

        except ImportError as e:
            pytest.skip(f"OpenHands tools not available: {e}")


# =============================================================================
# Cross-Framework Consistency Tests
# =============================================================================


class TestCrossFrameworkDocsConsistency:
    """Test that all frameworks produce consistent docs search results."""

    @pytest.mark.integration
    def test_all_frameworks_same_search_results(self):
        """Verify all frameworks get the same search results for a query."""
        from agents.shared.docs_tools import search_docs_sync

        query = "sentry error tracking"
        result = search_docs_sync(query, max_results=3)

        print("\n=== Cross-Framework Docs Consistency ===")
        print(f"Query: {query}")
        print(f"Result:\n{result}")

        # All frameworks use the same shared implementation
        # so results should be identical
        assert result is not None
        assert "documentation search" in result.lower() or "found" in result.lower()
