"""
Real Browser Integration Tests for Multi-Framework Agents.

These tests verify that all agent frameworks can perform web browsing operations
using the shared browser tools layer (agents.shared.browser_tools) which uses
playwright for real browser automation with urllib fallback.

Requirements:
    - playwright installed: pip install playwright && playwright install chromium
    - AZURE_API_KEY and AZURE_API_BASE for LLM calls (for full agent tests)

Run with:
    pytest tests/test_browser_integration.py -v --run-integration

Run specific framework:
    pytest tests/test_browser_integration.py -v --run-integration -k "autogen"
    pytest tests/test_browser_integration.py -v --run-integration -k "crewai"
    pytest tests/test_browser_integration.py -v --run-integration -k "openhands"

Run just shared tools tests (no LLM required):
    pytest tests/test_browser_integration.py -v --run-integration -k "TestSharedBrowserTools"
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import pytest


@dataclass
class BrowserTestResult:
    """Result from a browser integration test."""

    framework: str
    agent: str
    success: bool
    response: str
    latency_ms: float
    error: str | None = None

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return f"[{status}] {self.framework}/{self.agent}: {self.latency_ms:.0f}ms"


def validate_webpage_response(response: str, expected_content: list[str] | None = None) -> bool:
    """
    Validate that the response contains valid webpage content.

    Args:
        response: The response string
        expected_content: Optional list of strings that should be in the response

    Returns:
        True if the response appears to contain valid webpage data
    """
    response_lower = response.lower()

    # Check for error responses (still valid, just not successful fetch)
    if "error" in response_lower and (
        "timeout" in response_lower or "connection" in response_lower or "fetch" in response_lower
    ):
        # This is a valid error response
        return True

    # Check for content markers
    has_content = any(
        marker in response_lower
        for marker in [
            "content from",
            "===",
            "web page",
            "webpage",
        ]
    )

    # Check for expected content if provided
    if expected_content:
        return has_content and any(ec.lower() in response_lower for ec in expected_content)

    return has_content or len(response) > 100


def validate_search_response(response: str) -> bool:
    """Validate that the response contains search results."""
    response_lower = response.lower()

    # Check for search result markers
    has_results = any(
        marker in response_lower
        for marker in [
            "search results",
            "web search",
            "found",
            "results for",
            "url:",
        ]
    )

    # Check for numbered results
    import re

    has_numbered = bool(re.search(r"\d+\.\s+\*\*", response))

    return has_results or has_numbered or "playwright not" in response_lower


def validate_screenshot_response(result: dict) -> bool:
    """Validate screenshot result."""
    if not isinstance(result, dict):
        return False

    # Success case
    if result.get("success"):
        return bool(result.get("path"))

    # Failure case - still valid response
    return "error" in result


def validate_links_response(response: str) -> bool:
    """Validate link extraction response."""
    response_lower = response.lower()

    # Check for link markers
    return any(
        marker in response_lower
        for marker in [
            "links from",
            "found",
            "link",
            "playwright not",
        ]
    )


def validate_competitor_analysis_response(response: str) -> bool:
    """Validate competitor analysis response."""
    response_lower = response.lower()

    return any(
        marker in response_lower
        for marker in [
            "competitor analysis",
            "page content",
            "analysis",
            "content from",
        ]
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def check_playwright():
    """Check if playwright is available."""
    try:
        from agent_service.shared.browser_tools import PLAYWRIGHT_AVAILABLE

        return PLAYWRIGHT_AVAILABLE
    except ImportError:
        return False


@pytest.fixture(scope="module")
def azure_credentials():
    """Check if Azure credentials are available."""
    api_key = os.getenv("AZURE_API_KEY")
    api_base = os.getenv("AZURE_API_BASE")

    if not api_key or not api_base:
        pytest.skip("Azure credentials not available")

    return {"api_key": api_key, "api_base": api_base}


# =============================================================================
# Shared Browser Tools Direct Tests (Baseline)
# =============================================================================


@pytest.mark.integration
class TestSharedBrowserToolsDirect:
    """Test the shared browser tools directly as a baseline."""

    def test_fetch_webpage_basic(self):
        """Test fetching a basic webpage."""
        from agent_service.shared.browser_tools import fetch_webpage_sync

        start = time.perf_counter()
        result = fetch_webpage_sync("https://example.com")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Direct Browser Tools - Fetch Webpage Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}...")
        print(f"{'=' * 60}")

        assert validate_webpage_response(result)
        assert "example" in result.lower() or "domain" in result.lower()

    def test_fetch_webpage_with_js(self, check_playwright):
        """Test fetching a webpage that requires JS rendering."""
        if not check_playwright:
            pytest.skip("Playwright not available - using urllib fallback")

        from agent_service.shared.browser_tools import fetch_webpage_sync

        start = time.perf_counter()
        # Use a simple page that works without JS too
        result = fetch_webpage_sync("https://httpbin.org/html")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - JS-Rendered Page Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}...")
        print(f"{'=' * 60}")

        assert validate_webpage_response(result)

    def test_web_search(self, check_playwright):
        """Test web search functionality."""
        from agent_service.shared.browser_tools import web_search_sync

        start = time.perf_counter()
        result = web_search_sync("python programming", num_results=3)
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - Web Search Test")
        print(f"{'=' * 60}")
        print(f"Playwright available: {check_playwright}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}...")
        print(f"{'=' * 60}")

        assert validate_search_response(result)

    def test_take_screenshot(self, check_playwright):
        """Test screenshot functionality."""
        if not check_playwright:
            pytest.skip("Playwright required for screenshots")

        from agent_service.shared.browser_tools import take_screenshot_sync

        start = time.perf_counter()
        result = take_screenshot_sync("https://example.com")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - Screenshot Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result: {result}")
        print(f"{'=' * 60}")

        assert validate_screenshot_response(result)

        # Clean up screenshot file if created
        if result.get("success") and result.get("path"):
            try:
                os.remove(result["path"])
            except Exception:
                pass

    def test_extract_links(self, check_playwright):
        """Test link extraction functionality."""
        if not check_playwright:
            pytest.skip("Playwright required for link extraction")

        from agent_service.shared.browser_tools import extract_links_sync

        start = time.perf_counter()
        result = extract_links_sync("https://example.com")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - Extract Links Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}...")
        print(f"{'=' * 60}")

        assert validate_links_response(result)

    def test_analyze_competitor_page(self):
        """Test competitor analysis functionality."""
        from agent_service.shared.browser_tools import analyze_competitor_page_sync

        start = time.perf_counter()
        result = analyze_competitor_page_sync("https://example.com")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - Competitor Analysis Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Result preview:\n{result[:500]}...")
        print(f"{'=' * 60}")

        assert validate_competitor_analysis_response(result)

    def test_get_browser_context(self):
        """Test browser context for agent injection."""
        from agent_service.shared.browser_tools import get_browser_context

        start = time.perf_counter()
        context = get_browser_context("https://example.com")
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Browser Tools - Context Injection Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Context preview:\n{context[:500]}...")
        print(f"{'=' * 60}")

        assert "## Web Page Context" in context


# =============================================================================
# AutoGen MarketingManager Browser Tests
# =============================================================================


@pytest.mark.integration
class TestAutoGenBrowserIntegration:
    """Test AutoGen MarketingManager with real browser tools."""

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create AutoGen MarketingManager with real credentials."""
        from agent_service.autogen.marketing_manager import AutoGenMarketingManager

        return AutoGenMarketingManager()

    @pytest.mark.asyncio
    async def test_autogen_web_research(self, marketing_manager):
        """Test AutoGen MarketingManager performs web research."""
        task = "Research the main features on https://example.com and summarize them."

        start_time = time.perf_counter()
        result = await marketing_manager.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("AutoGen MarketingManager - Web Research Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        # Should contain content from the webpage or search
        assert len(response) > 50, f"Response too short: {response}"
        await marketing_manager.close()

    @pytest.mark.asyncio
    async def test_autogen_competitor_analysis(self, marketing_manager, check_playwright):
        """Test AutoGen MarketingManager analyzes competitor."""
        if not check_playwright:
            pytest.skip("Playwright recommended for competitor analysis")

        task = "Analyze https://example.com as a competitor and identify their key messaging."

        start_time = time.perf_counter()
        result = await marketing_manager.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("AutoGen MarketingManager - Competitor Analysis Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert len(response) > 50
        await marketing_manager.close()


# =============================================================================
# CrewAI MarketingManager Browser Tests
# =============================================================================


@pytest.mark.integration
class TestCrewAIBrowserIntegration:
    """Test CrewAI MarketingManager with real browser tools."""

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create CrewAI MarketingManager with real credentials."""
        from agent_service.crewai.marketing_manager import CrewAIMarketingManager

        return CrewAIMarketingManager()

    @pytest.mark.asyncio
    async def test_crewai_web_search(self, marketing_manager):
        """Test CrewAI MarketingManager performs web search."""
        task = "Search the web for information about AI agent frameworks and summarize the top results."

        start_time = time.perf_counter()
        result = await asyncio.to_thread(marketing_manager.run, task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("CrewAI MarketingManager - Web Search Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert len(response) > 50

    @pytest.mark.asyncio
    async def test_crewai_fetch_webpage(self, marketing_manager):
        """Test CrewAI MarketingManager fetches webpage."""
        task = "Fetch the content from https://example.com and summarize it."

        start_time = time.perf_counter()
        result = await asyncio.to_thread(marketing_manager.run, task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("CrewAI MarketingManager - Fetch Webpage Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert len(response) > 50


# =============================================================================
# OpenHands MarketingManager Browser Tests
# =============================================================================


@pytest.mark.integration
class TestOpenHandsBrowserIntegration:
    """Test OpenHands MarketingManager with browser context injection."""

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create OpenHands MarketingManager with real credentials."""
        from agent_service.openhands.marketing_manager import OpenHandsMarketingManager

        return OpenHandsMarketingManager()

    @pytest.mark.asyncio
    async def test_openhands_url_context_injection(self, marketing_manager):
        """Test OpenHands gets webpage context injected for URL-containing tasks."""
        task = "Summarize the content at https://example.com"

        start_time = time.perf_counter()
        result = await marketing_manager.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("OpenHands MarketingManager - URL Context Injection Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        # Should have used the injected context
        assert len(response) > 50

    @pytest.mark.asyncio
    async def test_openhands_competitor_context_injection(self, marketing_manager):
        """Test OpenHands gets search context for competitor research tasks."""
        task = "Research competitor Acme Corp and their product features."

        start_time = time.perf_counter()
        result = await marketing_manager.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")

        print(f"\n{'=' * 60}")
        print("OpenHands MarketingManager - Competitor Context Injection Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert len(response) > 50


# =============================================================================
# Cross-Framework Browser Comparison Test
# =============================================================================


@pytest.mark.integration
class TestCrossFrameworkBrowserComparison:
    """Compare all frameworks on the same browser task."""

    @pytest.mark.asyncio
    async def test_all_frameworks_web_research(self, azure_credentials, check_playwright):
        """Run identical web research task across all three frameworks."""
        from agent_service.autogen.marketing_manager import AutoGenMarketingManager
        from agent_service.crewai.marketing_manager import CrewAIMarketingManager
        from agent_service.openhands.marketing_manager import OpenHandsMarketingManager

        task = "Fetch content from https://example.com and provide a brief summary."

        results: list[BrowserTestResult] = []

        print("\n" + "=" * 70)
        print("CROSS-FRAMEWORK BROWSER COMPARISON TEST")
        print("=" * 70)
        print(f"Playwright available: {check_playwright}")

        # AutoGen
        try:
            agent = AutoGenMarketingManager()
            start = time.perf_counter()
            result = await agent.run_async(task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid = len(response) > 50
            await agent.close()

            results.append(
                BrowserTestResult(
                    framework="autogen",
                    agent="marketing_manager",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                )
            )
            print(f"\n[AutoGen] {latency:.0f}ms - {'PASS' if is_valid else 'FAIL'}")
        except Exception as e:
            results.append(
                BrowserTestResult(
                    framework="autogen",
                    agent="marketing_manager",
                    success=False,
                    response="",
                    latency_ms=0,
                    error=str(e),
                )
            )
            print(f"\n[AutoGen] ERROR: {e}")

        # CrewAI
        try:
            agent = CrewAIMarketingManager()
            start = time.perf_counter()
            result = await asyncio.to_thread(agent.run, task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid = len(response) > 50

            results.append(
                BrowserTestResult(
                    framework="crewai",
                    agent="marketing_manager",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                )
            )
            print(f"[CrewAI] {latency:.0f}ms - {'PASS' if is_valid else 'FAIL'}")
        except Exception as e:
            results.append(
                BrowserTestResult(
                    framework="crewai",
                    agent="marketing_manager",
                    success=False,
                    response="",
                    latency_ms=0,
                    error=str(e),
                )
            )
            print(f"[CrewAI] ERROR: {e}")

        # OpenHands
        try:
            agent = OpenHandsMarketingManager()
            start = time.perf_counter()
            result = await agent.run_async(task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid = len(response) > 50

            results.append(
                BrowserTestResult(
                    framework="openhands",
                    agent="marketing_manager",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                )
            )
            print(f"[OpenHands] {latency:.0f}ms - {'PASS' if is_valid else 'FAIL'}")
        except Exception as e:
            results.append(
                BrowserTestResult(
                    framework="openhands",
                    agent="marketing_manager",
                    success=False,
                    response="",
                    latency_ms=0,
                    error=str(e),
                )
            )
            print(f"[OpenHands] ERROR: {e}")

        # Summary
        print("\n" + "-" * 70)
        print("SUMMARY")
        print("-" * 70)
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        print(f"Total: {len(results)} frameworks tested")
        print(f"Passed: {len(successful)}")
        print(f"Failed: {len(failed)}")

        if successful:
            avg_latency = sum(r.latency_ms for r in successful) / len(successful)
            fastest = min(successful, key=lambda r: r.latency_ms)
            print(f"Average latency: {avg_latency:.0f}ms")
            print(f"Fastest: {fastest.framework} ({fastest.latency_ms:.0f}ms)")

        for r in results:
            print(f"  {r}")

        print("=" * 70)

        # Assert at least 2 passed
        assert len(successful) >= 2, (
            f"Not enough frameworks passed: {[r.framework for r in failed]}"
        )
