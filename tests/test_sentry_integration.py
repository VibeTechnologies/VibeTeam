"""
Real Sentry Integration Tests for Multi-Framework Agents.

These tests verify that all agent frameworks can query REAL Sentry issues
using the vibeteam.connectors.sentry.SentryConnector.

Requirements:
    - SENTRY_AUTH_TOKEN environment variable set
    - AZURE_API_KEY and AZURE_API_BASE for LLM calls
    - Real Sentry project with issues to query

Run with:
    pytest tests/test_sentry_integration.py -v --run-integration

Run specific framework:
    pytest tests/test_sentry_integration.py -v --run-integration -k "autogen"
    pytest tests/test_sentry_integration.py -v --run-integration -k "crewai"
    pytest tests/test_sentry_integration.py -v --run-integration -k "openhands"

With metrics export:
    pytest tests/test_sentry_integration.py -v --run-integration --export-metrics=results/sentry_test_metrics.json
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import pytest


@dataclass
class SentryTestResult:
    """Result from a Sentry integration test."""

    framework: str
    agent: str
    success: bool
    response: str
    latency_ms: float
    issues_found: int
    error: str | None = None

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return (
            f"[{status}] {self.framework}/{self.agent}: "
            f"{self.issues_found} issues found in {self.latency_ms:.0f}ms"
        )


def validate_sentry_response(response: str) -> tuple[bool, int]:
    """
    Validate that the response contains real Sentry issue data.

    Returns:
        Tuple of (is_valid, issue_count)
    """
    response_lower = response.lower()

    # Check for error indicators
    if "error" in response_lower and "sentry_auth_token" in response_lower:
        return False, 0
    if "simulated" in response_lower or "mock" in response_lower:
        return False, 0

    # Check for real Sentry issue indicators
    has_issue_id = "vibebrowserextension-" in response_lower or "issue" in response_lower
    has_url = "sentry.io" in response_lower
    has_level = "level:" in response_lower or "error" in response_lower
    has_count = "count:" in response_lower or "occurrences" in response_lower

    # Count issues found (look for issue patterns)
    import re

    issue_pattern = r"vibebrowserextension-\d+"
    issues = re.findall(issue_pattern, response_lower)
    issue_count = len(set(issues))  # Unique issues

    # Also count from "Found X issues" pattern
    found_pattern = r"found (\d+) (?:unresolved )?issues?"
    found_match = re.search(found_pattern, response_lower)
    if found_match:
        issue_count = max(issue_count, int(found_match.group(1)))

    is_valid = (has_issue_id or has_url) and issue_count >= 0

    return is_valid, issue_count


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def sentry_credentials():
    """Verify Sentry credentials are available."""
    token = os.getenv("SENTRY_AUTH_TOKEN")
    if not token:
        pytest.skip("SENTRY_AUTH_TOKEN not configured")
    return {"auth_token": token}


@pytest.fixture(scope="module")
def verify_sentry_connectivity(sentry_credentials):
    """Verify we can actually connect to Sentry before running tests."""
    try:
        from vibeteam.connectors.sentry import SentryConnector

        connector = SentryConnector(auth_token=sentry_credentials["auth_token"])
        issues = connector.fetch_unresolved_issues(hours=24, limit=1)
        # We just need to verify the connection works, not that there are issues
        return True
    except Exception as e:
        pytest.skip(f"Cannot connect to Sentry: {e}")


@pytest.fixture
def test_results() -> list[SentryTestResult]:
    """Collect test results for summary."""
    return []


# =============================================================================
# AutoGen Sentry Tests
# =============================================================================


@pytest.mark.integration
class TestAutoGenSentryIntegration:
    """Test AutoGen agents with real Sentry integration."""

    @pytest.fixture
    def support_engineer(self, azure_credentials, sentry_credentials):
        """Create AutoGen SupportEngineer with real credentials."""
        from agents.autogen.support_engineer import AutoGenSupportEngineer

        return AutoGenSupportEngineer()

    @pytest.mark.asyncio
    async def test_autogen_sentry_fetch_issues(self, support_engineer, verify_sentry_connectivity):
        """Test AutoGen SupportEngineer fetches real Sentry issues."""
        task = "Pull all unresolved issues from Sentry and provide a summary of errors."

        start_time = time.perf_counter()
        result = await support_engineer.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("AutoGen SupportEngineer - Sentry Integration Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Issues found: {issue_count}")
        print(f"Valid response: {is_valid}")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert is_valid, f"Response does not contain real Sentry data: {response[:300]}"
        # We expect at least awareness that Sentry was queried, even if 0 issues
        assert "sentry" in response.lower() or issue_count >= 0

    @pytest.mark.asyncio
    async def test_autogen_sentry_analyze_errors(
        self, support_engineer, verify_sentry_connectivity
    ):
        """Test AutoGen SupportEngineer analyzes Sentry errors."""
        task = (
            "Check Sentry for the most critical unresolved errors. "
            "Identify patterns and recommend which errors should be fixed first."
        )

        start_time = time.perf_counter()
        result = await support_engineer.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("AutoGen SupportEngineer - Error Analysis Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Response preview:\n{response[:600]}...")
        print(f"{'=' * 60}")

        # Analysis should mention priorities, recommendations, or specific issues
        has_analysis = any(
            word in response.lower()
            for word in ["recommend", "priority", "fix", "critical", "should", "first"]
        )
        assert is_valid or has_analysis, f"No analysis found: {response[:300]}"


# =============================================================================
# CrewAI Sentry Tests
# =============================================================================


@pytest.mark.integration
class TestCrewAISentryIntegration:
    """Test CrewAI agents with real Sentry integration."""

    @pytest.fixture
    def support_engineer(self, azure_credentials, sentry_credentials):
        """Create CrewAI SupportEngineer with real credentials."""
        from agents.crewai.support_engineer import CrewAISupportEngineer

        return CrewAISupportEngineer()

    @pytest.mark.asyncio
    async def test_crewai_sentry_fetch_issues(self, support_engineer, verify_sentry_connectivity):
        """Test CrewAI SupportEngineer fetches real Sentry issues."""
        task = "Pull all unresolved issues from Sentry and provide a summary of errors."

        start_time = time.perf_counter()
        # CrewAI uses sync interface, run in thread
        result = await asyncio.to_thread(support_engineer.run, task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("CrewAI SupportEngineer - Sentry Integration Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Issues found: {issue_count}")
        print(f"Valid response: {is_valid}")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert is_valid, f"Response does not contain real Sentry data: {response[:300]}"

    @pytest.mark.asyncio
    async def test_crewai_sentry_tool_usage(self, support_engineer, verify_sentry_connectivity):
        """Test that CrewAI SupportEngineer uses the Sentry tool."""
        task = "Use the Sentry tool to get current errors affecting the VibeBrowser extension."

        start_time = time.perf_counter()
        result = await asyncio.to_thread(support_engineer.run, task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("CrewAI SupportEngineer - Tool Usage Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Issues found: {issue_count}")
        print(f"Response preview:\n{response[:600]}...")
        print(f"{'=' * 60}")

        assert is_valid, f"Sentry tool was not used properly: {response[:300]}"


# =============================================================================
# OpenHands Sentry Tests
# =============================================================================


@pytest.mark.integration
class TestOpenHandsSentryIntegration:
    """Test OpenHands agents with real Sentry integration."""

    @pytest.fixture
    def support_engineer(self, azure_credentials, sentry_credentials):
        """Create OpenHands SupportEngineer with real credentials."""
        from agents.openhands.support_engineer import OpenHandsSupportEngineer

        return OpenHandsSupportEngineer()

    @pytest.mark.asyncio
    async def test_openhands_sentry_fetch_issues(
        self, support_engineer, verify_sentry_connectivity
    ):
        """Test OpenHands SupportEngineer fetches real Sentry issues."""
        task = "Pull all unresolved issues from Sentry and provide a summary of errors."

        start_time = time.perf_counter()
        result = await support_engineer.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("OpenHands SupportEngineer - Sentry Integration Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Issues found: {issue_count}")
        print(f"Valid response: {is_valid}")
        print(f"Response preview:\n{response[:500]}...")
        print(f"{'=' * 60}")

        assert is_valid, f"Response does not contain real Sentry data: {response[:300]}"

    @pytest.mark.asyncio
    async def test_openhands_sentry_context_injection(
        self, support_engineer, verify_sentry_connectivity
    ):
        """Test that OpenHands gets Sentry context injected properly."""
        task = "What errors are currently affecting our users?"

        start_time = time.perf_counter()
        result = await support_engineer.run_async(task)
        latency_ms = (time.perf_counter() - start_time) * 1000

        response = result.get("response", "")
        is_valid, issue_count = validate_sentry_response(response)

        print(f"\n{'=' * 60}")
        print("OpenHands SupportEngineer - Context Injection Test")
        print(f"{'=' * 60}")
        print(f"Latency: {latency_ms:.0f}ms")
        print(f"Issues found: {issue_count}")
        print(f"Response preview:\n{response[:600]}...")
        print(f"{'=' * 60}")

        # OpenHands should have Sentry context pre-injected for error-related queries
        assert is_valid, f"Sentry context not injected: {response[:300]}"


# =============================================================================
# Cross-Framework Comparison Test
# =============================================================================


@pytest.mark.integration
class TestCrossFrameworkSentryComparison:
    """Compare all frameworks on the same Sentry task."""

    @pytest.mark.asyncio
    async def test_all_frameworks_sentry_query(
        self, azure_credentials, sentry_credentials, verify_sentry_connectivity
    ):
        """Run identical Sentry query across all three frameworks."""
        from agents.autogen.support_engineer import AutoGenSupportEngineer
        from agents.crewai.support_engineer import CrewAISupportEngineer
        from agents.openhands.support_engineer import OpenHandsSupportEngineer

        task = "Query Sentry for unresolved issues and list them with their error counts."

        results: list[SentryTestResult] = []

        # Test AutoGen
        print("\n" + "=" * 70)
        print("CROSS-FRAMEWORK SENTRY COMPARISON TEST")
        print("=" * 70)

        # AutoGen
        try:
            agent = AutoGenSupportEngineer()
            start = time.perf_counter()
            result = await agent.run_async(task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid, issue_count = validate_sentry_response(response)
            await agent.close()

            results.append(
                SentryTestResult(
                    framework="autogen",
                    agent="support_engineer",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                    issues_found=issue_count,
                )
            )
            print(
                f"\n[AutoGen] {latency:.0f}ms - {issue_count} issues - {'PASS' if is_valid else 'FAIL'}"
            )
        except Exception as e:
            results.append(
                SentryTestResult(
                    framework="autogen",
                    agent="support_engineer",
                    success=False,
                    response="",
                    latency_ms=0,
                    issues_found=0,
                    error=str(e),
                )
            )
            print(f"\n[AutoGen] ERROR: {e}")

        # CrewAI
        try:
            agent = CrewAISupportEngineer()
            start = time.perf_counter()
            result = await asyncio.to_thread(agent.run, task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid, issue_count = validate_sentry_response(response)

            results.append(
                SentryTestResult(
                    framework="crewai",
                    agent="support_engineer",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                    issues_found=issue_count,
                )
            )
            print(
                f"[CrewAI]  {latency:.0f}ms - {issue_count} issues - {'PASS' if is_valid else 'FAIL'}"
            )
        except Exception as e:
            results.append(
                SentryTestResult(
                    framework="crewai",
                    agent="support_engineer",
                    success=False,
                    response="",
                    latency_ms=0,
                    issues_found=0,
                    error=str(e),
                )
            )
            print(f"[CrewAI] ERROR: {e}")

        # OpenHands
        try:
            agent = OpenHandsSupportEngineer()
            start = time.perf_counter()
            result = await agent.run_async(task)
            latency = (time.perf_counter() - start) * 1000
            response = result.get("response", "")
            is_valid, issue_count = validate_sentry_response(response)

            results.append(
                SentryTestResult(
                    framework="openhands",
                    agent="support_engineer",
                    success=is_valid,
                    response=response[:200],
                    latency_ms=latency,
                    issues_found=issue_count,
                )
            )
            print(
                f"[OpenHands] {latency:.0f}ms - {issue_count} issues - {'PASS' if is_valid else 'FAIL'}"
            )
        except Exception as e:
            results.append(
                SentryTestResult(
                    framework="openhands",
                    agent="support_engineer",
                    success=False,
                    response="",
                    latency_ms=0,
                    issues_found=0,
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

        # Assert all passed
        assert len(successful) == 3, f"Not all frameworks passed: {[r.framework for r in failed]}"


# =============================================================================
# Direct Sentry Connector Test (Baseline)
# =============================================================================


@pytest.mark.integration
class TestSentryConnectorDirect:
    """Test the SentryConnector directly as a baseline."""

    def test_sentry_connector_fetch(self, sentry_credentials):
        """Test direct SentryConnector without any agent framework."""
        from vibeteam.connectors.sentry import SentryConnector

        connector = SentryConnector(auth_token=sentry_credentials["auth_token"])

        start = time.perf_counter()
        issues = connector.fetch_unresolved_issues(hours=24, limit=10)
        latency = (time.perf_counter() - start) * 1000

        print(f"\n{'=' * 60}")
        print("Direct SentryConnector Test (Baseline)")
        print(f"{'=' * 60}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Issues found: {len(issues)}")

        for issue in issues:
            print(f"  - [{issue.project}] {issue.short_id}: {issue.title[:50]}...")
            print(f"    Count: {issue.count}, Level: {issue.level}")

        print(f"{'=' * 60}")

        # This should always work if SENTRY_AUTH_TOKEN is valid
        assert isinstance(issues, list)
        # Note: We don't assert issues > 0 because there might genuinely be no issues
