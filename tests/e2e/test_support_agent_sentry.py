"""
E2E Integration Test: SupportAgent Sentry Weekly Summary via REST API.

This test calls the VibeTeam Gateway REST API to invoke SupportAgent implementations
across all three frameworks (AutoGen, CrewAI, OpenHands) and asks each to provide
a summary of Sentry issues for this week.

Uses LLM-as-judge (Azure GPT-5) for objective evaluation of response quality.

Requirements:
    - kubectl access to vibeteam namespace
    - Services running: vibeteam-gateway, autogen-svc, crewai-svc, openhands-svc
    - Azure OpenAI credentials configured in cluster
    - Sentry auth token configured in cluster

Run with:
    pytest tests/e2e/test_support_agent_sentry.py -v -s

Run specific framework:
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "autogen"
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "crewai"
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "openhands"

Run all frameworks comparison:
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "compare_all"
"""

import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

# Add project root to path for import
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

# Skip this test module until benchmark module is restored
pytest.skip(
    "agents.benchmark module not yet migrated to new architecture",
    allow_module_level=True,
)

# This import would fail without the skip above
# from agents.benchmark import ComparativeEvaluator  # noqa: E402
ComparativeEvaluator = None  # Stub for type hints

# ==============================================================================
# Configuration
# ==============================================================================

GATEWAY_PORT = 19080  # Local port for kubectl port-forward
GATEWAY_SERVICE = "vibeteam-gateway"
NAMESPACE = "vibeteam"
REQUEST_TIMEOUT = 180.0  # 3 minutes for LLM responses

# The task to send to each SupportAgent
SENTRY_WEEKLY_SUMMARY_TASK = """
Provide a summary of Sentry issues for this week.

Include:
1. Total number of unresolved issues
2. Most frequent error types
3. Critical/high priority issues that need immediate attention
4. Any patterns or trends you notice

Format the response as a clear, actionable report.
"""


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class FrameworkResult:
    """Result from a framework test."""

    framework: str
    success: bool
    response: str
    latency_ms: float
    session_id: str
    error: str | None = None

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return f"[{status}] {self.framework}: {self.latency_ms:.0f}ms"


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def gateway_port_forward():
    """
    Start kubectl port-forward for the gateway service.

    Yields the local URL for the gateway.
    """
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{GATEWAY_SERVICE}",
            f"{GATEWAY_PORT}:8080",
            "-n",
            NAMESPACE,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for port-forward to establish
    time.sleep(3)

    # Verify the port-forward is working
    try:
        response = httpx.get(
            f"http://localhost:{GATEWAY_PORT}/health",
            timeout=10.0,
        )
        if response.status_code != 200:
            proc.terminate()
            pytest.skip(f"Gateway health check failed: {response.status_code}")
    except Exception as e:
        proc.terminate()
        pytest.skip(f"Cannot connect to gateway: {e}")

    yield f"http://localhost:{GATEWAY_PORT}"

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def http_client():
    """Provide an HTTP client with appropriate timeout."""
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        yield client


# ==============================================================================
# Helper Functions
# ==============================================================================


def call_gateway_run(
    client: httpx.Client,
    gateway_url: str,
    task: str,
    framework: str,
    role: str = "support_engineer",
    context_type: str = "sentry",
) -> dict[str, Any]:
    """
    Call the gateway /api/run endpoint.

    Args:
        client: HTTP client
        gateway_url: Base URL of the gateway
        task: Task description
        framework: Agent framework (autogen, crewai, openhands)
        role: Agent role
        context_type: Context type for session tracking

    Returns:
        Response dict from the gateway
    """
    response = client.post(
        f"{gateway_url}/api/run",
        json={
            "task": task,
            "framework": framework,
            "role": role,
            "context_type": context_type,
            "context_id": f"e2e-sentry-{framework}",
        },
    )
    response.raise_for_status()
    return response.json()


def validate_sentry_summary(response: str) -> tuple[bool, list[str]]:
    """
    Validate that the response contains a valid Sentry summary.

    Returns:
        Tuple of (is_valid, list of validation notes)
    """
    response_lower = response.lower()
    notes: list[str] = []

    # Check for definitive error indicators (authentication/access issues)
    auth_error_patterns = [
        "sentry_auth_token",
        "authentication failed",
        "unauthorized",
        "403 forbidden",
        "401 unauthorized",
        "module not available",
        "please install",
        "not configured",
        "unable to fulfill",
        "i'm sorry",
        "i cannot",
    ]

    for pattern in auth_error_patterns:
        if pattern in response_lower:
            notes.append(f"Error pattern detected: '{pattern}'")
            return False, notes

    if "could not" in response_lower and "sentry" in response_lower:
        notes.append("Sentry access issue detected")
        return False, notes

    # Check for expected content in a Sentry summary
    has_issues = any(
        word in response_lower for word in ["issue", "error", "exception", "unresolved", "sentry"]
    )

    has_count = any(
        word in response_lower
        for word in ["total", "count", "found", "number", "0", "1", "2", "3", "4", "5"]
    )

    has_analysis = any(
        word in response_lower
        for word in ["summary", "report", "analysis", "priority", "critical", "pattern", "trend"]
    )

    if has_issues:
        notes.append("Contains issue/error references")
    if has_count:
        notes.append("Contains count/quantity information")
    if has_analysis:
        notes.append("Contains analysis/summary content")

    # Response must have at least issue references and some form of count/analysis
    is_valid = has_issues and (has_count or has_analysis)

    if not is_valid:
        notes.append("Missing expected Sentry summary content")

    return is_valid, notes


# ==============================================================================
# Tests - Individual Frameworks
# ==============================================================================


class TestSupportAgentSentryAutoGen:
    """Test AutoGen SupportAgent Sentry summary via REST API."""

    @pytest.mark.xfail(reason="AutoGen container may not have Sentry connector installed")
    def test_autogen_sentry_weekly_summary(
        self,
        gateway_port_forward: str,
        http_client: httpx.Client,
    ):
        """Test AutoGen SupportAgent provides a Sentry weekly summary."""
        framework = "autogen"

        print(f"\n{'=' * 70}")
        print(f"Testing {framework.upper()} SupportAgent - Sentry Weekly Summary")
        print(f"{'=' * 70}")

        start_time = time.perf_counter()

        try:
            result = call_gateway_run(
                client=http_client,
                gateway_url=gateway_port_forward,
                task=SENTRY_WEEKLY_SUMMARY_TASK,
                framework=framework,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            response = result.get("response", "")
            session_id = result.get("session_id", "")

            is_valid, notes = validate_sentry_summary(response)

            print(f"\nFramework: {result.get('framework', framework)}")
            print(f"Session ID: {session_id}")
            print(f"Latency: {latency_ms:.0f}ms")
            print(f"Valid: {is_valid}")
            print(f"Validation notes: {', '.join(notes)}")
            print(f"\nResponse ({len(response)} chars):")
            print("-" * 40)
            print(response[:1500] if len(response) > 1500 else response)
            if len(response) > 1500:
                print(f"\n... (truncated, {len(response) - 1500} more chars)")
            print("-" * 40)

            assert is_valid, f"Invalid Sentry summary: {notes}"
            assert len(response) > 50, "Response too short"

        except httpx.HTTPStatusError as e:
            pytest.fail(f"HTTP error: {e.response.status_code} - {e.response.text}")


class TestSupportAgentSentryCrewAI:
    """Test CrewAI SupportAgent Sentry summary via REST API."""

    @pytest.mark.xfail(reason="CrewAI container may not have Sentry connector installed")
    def test_crewai_sentry_weekly_summary(
        self,
        gateway_port_forward: str,
        http_client: httpx.Client,
    ):
        """Test CrewAI SupportAgent provides a Sentry weekly summary."""
        framework = "crewai"

        print(f"\n{'=' * 70}")
        print(f"Testing {framework.upper()} SupportAgent - Sentry Weekly Summary")
        print(f"{'=' * 70}")

        start_time = time.perf_counter()

        try:
            result = call_gateway_run(
                client=http_client,
                gateway_url=gateway_port_forward,
                task=SENTRY_WEEKLY_SUMMARY_TASK,
                framework=framework,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            response = result.get("response", "")
            session_id = result.get("session_id", "")

            is_valid, notes = validate_sentry_summary(response)

            print(f"\nFramework: {result.get('framework', framework)}")
            print(f"Session ID: {session_id}")
            print(f"Latency: {latency_ms:.0f}ms")
            print(f"Valid: {is_valid}")
            print(f"Validation notes: {', '.join(notes)}")
            print(f"\nResponse ({len(response)} chars):")
            print("-" * 40)
            print(response[:1500] if len(response) > 1500 else response)
            if len(response) > 1500:
                print(f"\n... (truncated, {len(response) - 1500} more chars)")
            print("-" * 40)

            assert is_valid, f"Invalid Sentry summary: {notes}"
            assert len(response) > 50, "Response too short"

        except httpx.HTTPStatusError as e:
            pytest.fail(f"HTTP error: {e.response.status_code} - {e.response.text}")


class TestSupportAgentSentryOpenHands:
    """Test OpenHands SupportAgent Sentry summary via REST API."""

    def test_openhands_sentry_weekly_summary(
        self,
        gateway_port_forward: str,
        http_client: httpx.Client,
    ):
        """Test OpenHands SupportAgent provides a Sentry weekly summary."""
        framework = "openhands"

        print(f"\n{'=' * 70}")
        print(f"Testing {framework.upper()} SupportAgent - Sentry Weekly Summary")
        print(f"{'=' * 70}")

        start_time = time.perf_counter()

        try:
            result = call_gateway_run(
                client=http_client,
                gateway_url=gateway_port_forward,
                task=SENTRY_WEEKLY_SUMMARY_TASK,
                framework=framework,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            response = result.get("response", "")
            session_id = result.get("session_id", "")

            is_valid, notes = validate_sentry_summary(response)

            print(f"\nFramework: {result.get('framework', framework)}")
            print(f"Session ID: {session_id}")
            print(f"Latency: {latency_ms:.0f}ms")
            print(f"Valid: {is_valid}")
            print(f"Validation notes: {', '.join(notes)}")
            print(f"\nResponse ({len(response)} chars):")
            print("-" * 40)
            print(response[:1500] if len(response) > 1500 else response)
            if len(response) > 1500:
                print(f"\n... (truncated, {len(response) - 1500} more chars)")
            print("-" * 40)

            assert is_valid, f"Invalid Sentry summary: {notes}"
            assert len(response) > 50, "Response too short"

        except httpx.HTTPStatusError as e:
            pytest.fail(f"HTTP error: {e.response.status_code} - {e.response.text}")


# ==============================================================================
# Tests - Cross-Framework Comparison
# ==============================================================================


class TestSupportAgentSentryComparison:
    """Compare all three frameworks on the same Sentry summary task."""

    def test_compare_all_frameworks_sentry_summary(
        self,
        gateway_port_forward: str,
        http_client: httpx.Client,
    ):
        """
        Run the same Sentry weekly summary task across all three frameworks.

        Uses LLM-as-judge (GPT-5) to objectively score each response on a 0-5 scale.
        Winner is determined by the judge, not by response length or latency.
        """
        frameworks = ["autogen", "crewai", "openhands"]
        results: list[FrameworkResult] = []

        print("\n" + "=" * 70)
        print("CROSS-FRAMEWORK SENTRY SUMMARY COMPARISON")
        print("=" * 70)
        print(f"\nTask: {SENTRY_WEEKLY_SUMMARY_TASK[:100]}...")
        print("-" * 70)

        # Collect responses from all frameworks
        for framework in frameworks:
            print(f"\n>>> Testing {framework.upper()}...")

            start_time = time.perf_counter()

            try:
                result = call_gateway_run(
                    client=http_client,
                    gateway_url=gateway_port_forward,
                    task=SENTRY_WEEKLY_SUMMARY_TASK,
                    framework=framework,
                )
                latency_ms = (time.perf_counter() - start_time) * 1000

                response = result.get("response", "")
                session_id = result.get("session_id", "")

                is_valid, notes = validate_sentry_summary(response)

                results.append(
                    FrameworkResult(
                        framework=framework,
                        success=is_valid,
                        response=response,
                        latency_ms=latency_ms,
                        session_id=session_id,
                    )
                )

                print(f"    Status: {'PASS' if is_valid else 'FAIL'}")
                print(f"    Latency: {latency_ms:.0f}ms")
                print(f"    Response length: {len(response)} chars")
                print(f"    Validation: {', '.join(notes)}")

            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                results.append(
                    FrameworkResult(
                        framework=framework,
                        success=False,
                        response="",
                        latency_ms=latency_ms,
                        session_id="",
                        error=str(e),
                    )
                )
                print(f"    Status: ERROR - {e}")

        # Run LLM-as-judge evaluation
        print("\n" + "=" * 70)
        print("LLM-AS-JUDGE EVALUATION (GPT-5)")
        print("=" * 70)

        responses_for_judge = {r.framework: r.response for r in results}

        evaluator = ComparativeEvaluator()
        eval_result = asyncio.run(
            evaluator.evaluate(
                task=SENTRY_WEEKLY_SUMMARY_TASK,
                responses=responses_for_judge,
            )
        )

        # Print evaluation results
        print(f"\nJudge Model: {eval_result.judge_model}")
        print(f"Evaluation Time: {eval_result.evaluation_time_ms}ms")
        print("\nScores:")
        print("-" * 50)

        for framework in frameworks:
            score = eval_result.scores.get(framework)
            if score:
                status = "WINNER" if framework == eval_result.winner else ""
                print(f"  {framework.upper()}: {score.score}/5 {status}")
                print(f"    Feedback: {score.feedback}")
            else:
                print(f"  {framework.upper()}: No score")

        print("-" * 50)
        print(f"\nWINNER: {eval_result.winner.upper()}")
        print(f"Reasoning: {eval_result.reasoning}")

        # Print performance metrics
        print("\n" + "=" * 70)
        print("PERFORMANCE METRICS")
        print("=" * 70)

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        print(f"\nTotal frameworks tested: {len(results)}")
        print(f"Passed validation: {len(successful)}")
        print(f"Failed validation: {len(failed)}")

        if successful:
            avg_latency = sum(r.latency_ms for r in successful) / len(successful)
            fastest = min(successful, key=lambda r: r.latency_ms)

            print("\nLatency:")
            print(f"  Average: {avg_latency:.0f}ms")
            print(f"  Fastest: {fastest.framework} ({fastest.latency_ms:.0f}ms)")

        print("\nPer-Framework Results:")
        for r in results:
            score = eval_result.scores.get(r.framework)
            score_str = f"{score.score}/5" if score else "N/A"
            status = "PASS" if r.success else "FAIL"
            if r.error:
                print(f"  [{status}] {r.framework}: ERROR - {r.error}")
            else:
                print(
                    f"  [{status}] {r.framework}: {r.latency_ms:.0f}ms, {len(r.response)} chars, Score: {score_str}"
                )

        # Print sample responses
        print("\n" + "-" * 70)
        print("SAMPLE RESPONSES (first 500 chars)")
        print("-" * 70)

        for r in results:
            if r.response:
                score = eval_result.scores.get(r.framework)
                score_str = f"[Score: {score.score}/5]" if score else ""
                print(f"\n>>> {r.framework.upper()} {score_str}:")
                print(r.response[:500])
                if len(r.response) > 500:
                    print(f"... ({len(r.response) - 500} more chars)")

        print("\n" + "=" * 70)

        # Assertions
        assert len(results) == 3, f"Expected 3 frameworks, got {len(results)}"

        # At least 1 framework must succeed to validate the test works
        assert (
            len(successful) >= 1
        ), f"No frameworks succeeded! Results: {[f'{r.framework}: {r.response[:100]}' for r in results]}"

        # Winner must have a score > 0
        winner_score = eval_result.scores.get(eval_result.winner)
        assert winner_score is not None, "No winner determined"
        assert winner_score.score > 0, f"Winner {eval_result.winner} has score 0"

        # Print final verdict
        print("\n" + "=" * 70)
        print(f"FINAL VERDICT: {eval_result.winner.upper()} wins with score {winner_score.score}/5")
        print("=" * 70)


# ==============================================================================
# Tests - Gateway Health Check
# ==============================================================================


class TestGatewayServiceHealth:
    """Verify gateway can reach all agent services."""

    def test_gateway_health_shows_all_services(
        self,
        gateway_port_forward: str,
        http_client: httpx.Client,
    ):
        """Test that gateway health endpoint shows all three agent services."""
        response = http_client.get(f"{gateway_port_forward}/health")
        assert response.status_code == 200

        data = response.json()

        print("\n" + "=" * 70)
        print("GATEWAY HEALTH CHECK")
        print("=" * 70)
        print(f"\nStatus: {data.get('status')}")
        print(f"Service: {data.get('service')}")
        print(f"Timestamp: {data.get('timestamp')}")

        services = data.get("services", {})
        print("\nDownstream Services:")
        for service, status in services.items():
            print(f"  {service}: {status}")

        assert data["status"] == "healthy"
        assert "autogen-svc" in services
        assert "crewai-svc" in services
        assert "openhands-svc" in services

        # All services should be healthy for this test to be meaningful
        all_healthy = all(
            status == "healthy"
            for service, status in services.items()
            if service in ("autogen-svc", "crewai-svc", "openhands-svc")
        )

        if not all_healthy:
            unhealthy = [
                service
                for service, status in services.items()
                if status != "healthy" and service in ("autogen-svc", "crewai-svc", "openhands-svc")
            ]
            pytest.skip(f"Some services unhealthy: {unhealthy}")


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
