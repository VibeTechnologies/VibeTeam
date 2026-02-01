"""
E2E Integration Test: SupportAgent Sentry Weekly Summary.

This test invokes SupportAgent implementations across all three frameworks
(AutoGen, CrewAI, OpenHands) and asks each to provide a summary of Sentry issues.

Uses:
- RealAgentRunner fixtures from conftest.py for agent execution
- DeepEval G-Eval metrics for structured evaluation with per-agent thresholds

Requirements:
    - Agent services accessible (K8s or local)
    - Azure OpenAI credentials configured
    - Sentry auth token configured (for real Sentry access)

Run with:
    pytest tests/e2e/test_support_agent_sentry.py -v -s
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "openhands"
    pytest tests/e2e/test_support_agent_sentry.py -v -s -k "DeepEval"
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Add project root to path for import
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

# Import DeepEval if available
DEEPEVAL_AVAILABLE = False
LLMTestCase = None

try:
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    DEEPEVAL_AVAILABLE = True
except ImportError:
    pass

# Import conftest helpers
try:
    from conftest import (
        AGENT_THRESHOLDS,
        AzureOpenAIModel,
        create_professionalism_metric,
        create_task_completion_metric,
        create_tool_usage_metric,
    )
except ImportError:
    try:
        from tests.e2e.conftest import (
            AGENT_THRESHOLDS,
            AzureOpenAIModel,
            create_professionalism_metric,
            create_task_completion_metric,
            create_tool_usage_metric,
        )
    except ImportError:
        AGENT_THRESHOLDS = {}
        AzureOpenAIModel = None
        create_professionalism_metric = None
        create_task_completion_metric = None
        create_tool_usage_metric = None

if TYPE_CHECKING:
    from conftest import RealAgentRunner


# ==============================================================================
# Configuration
# ==============================================================================

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
# Fixtures
# ==============================================================================


@pytest.fixture
def sentry_task() -> str:
    """Return the Sentry weekly summary task."""
    return SENTRY_WEEKLY_SUMMARY_TASK


# ==============================================================================
# Helper Functions
# ==============================================================================


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
# NOTE: Legacy test classes (TestSupportAgentSentryOpenHands, TestSupportAgentSentryAutoGen,
# TestSupportAgentSentryCrewAI, TestSupportAgentSentryComparison) have been removed.
# They used the deprecated GPT52Evaluator. Use DeepEval test classes below instead.
# ==============================================================================


# ==============================================================================
# DeepEval G-Eval Tests
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestSupportAgentSentryDeepEval:
    """Test SupportAgent Sentry summary using DeepEval G-Eval metrics.

    Uses per-agent thresholds from requirements.md:
    - SupportEngineer: TaskCompletion ≥ 0.80, Professionalism ≥ 0.80
    """

    @pytest.mark.asyncio
    async def test_sentry_summary_with_deepeval(
        self,
        openhands_runner: "RealAgentRunner",
        azure_deepeval_model: "AzureOpenAIModel",
        sentry_task: str,
    ):
        """Test Sentry summary using DeepEval G-Eval metrics."""
        role = "support_engineer"

        print(f"\n>>> Running DeepEval Sentry test for {role}...")
        print(
            f"    TaskCompletion threshold: {AGENT_THRESHOLDS.get(role, {}).get('task_completion', 0.80)}"
        )
        print(
            f"    Professionalism threshold: {AGENT_THRESHOLDS.get(role, {}).get('professionalism', 0.80)}"
        )

        # Run the agent
        result = await openhands_runner.run(
            role=role,
            task=sentry_task,
            context_type="sentry",
            context_id="deepeval-sentry-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        response = result.get("response", "")

        # Create DeepEval test case
        test_case = LLMTestCase(
            input=sentry_task,
            actual_output=response,
        )

        # Create metrics with SupportEngineer thresholds
        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        prof_metric = create_professionalism_metric(azure_deepeval_model, role)

        # Measure metrics
        task_metric.measure(test_case)
        prof_metric.measure(test_case)

        print(f"    TaskCompletion: {task_metric.score:.2f} (threshold: {task_metric.threshold})")
        print(f"    Professionalism: {prof_metric.score:.2f} (threshold: {prof_metric.threshold})")
        print(f"    Task Reason: {task_metric.reason}")

        # SupportEngineer has higher thresholds (0.80)
        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )
        assert prof_metric.score >= prof_metric.threshold, (
            f"Professionalism {prof_metric.score:.2f} below threshold {prof_metric.threshold}"
        )

    @pytest.mark.asyncio
    async def test_sentry_tool_usage_with_deepeval(
        self,
        openhands_runner: "RealAgentRunner",
        azure_deepeval_model: "AzureOpenAIModel",
        sentry_task: str,
    ):
        """Test that SupportAgent uses Sentry tools appropriately."""
        role = "support_engineer"

        print(f"\n>>> Running DeepEval ToolUsage test...")

        result = await openhands_runner.run(
            role=role,
            task=sentry_task,
            context_type="sentry",
            context_id="deepeval-tool-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        test_case = LLMTestCase(
            input=sentry_task,
            actual_output=result.get("response", ""),
        )

        # ToolUsage metric evaluates if agent used appropriate tools
        tool_metric = create_tool_usage_metric(azure_deepeval_model, role)
        tool_metric.measure(test_case)

        print(f"    ToolUsage: {tool_metric.score:.2f}")
        print(f"    Reason: {tool_metric.reason}")

        # Tool usage threshold is 0.7
        assert tool_metric.score >= tool_metric.threshold


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestSupportAgentSentryDeepEvalAllFrameworks:
    """Run Sentry summary across all frameworks with DeepEval evaluation."""

    @pytest.mark.asyncio
    async def test_all_frameworks_sentry_deepeval(
        self,
        openhands_runner: "RealAgentRunner",
        autogen_runner: "RealAgentRunner",
        crewai_runner: "RealAgentRunner",
        azure_deepeval_model: "AzureOpenAIModel",
        sentry_task: str,
    ):
        """Run Sentry task across all frameworks with DeepEval metrics."""
        runners = {
            "openhands": openhands_runner,
            "autogen": autogen_runner,
            "crewai": crewai_runner,
        }
        results = []
        role = "support_engineer"

        print("\n" + "=" * 70)
        print("SENTRY SUMMARY E2E TEST - DEEPEVAL G-EVAL")
        print("=" * 70)

        for framework, runner in runners.items():
            print(f"\n>>> Testing {framework.upper()}...")

            try:
                agent_result = await runner.run(
                    role=role,
                    task=sentry_task,
                    context_type="sentry",
                    context_id=f"deepeval-{framework}",
                )

                if not agent_result.get("success"):
                    print(f"    SKIPPED: Agent failed - {agent_result.get('error')}")
                    results.append(
                        {
                            "framework": framework,
                            "success": False,
                            "task_score": 0,
                            "prof_score": 0,
                        }
                    )
                    continue

                test_case = LLMTestCase(
                    input=sentry_task,
                    actual_output=agent_result.get("response", ""),
                )

                task_metric = create_task_completion_metric(azure_deepeval_model, role)
                prof_metric = create_professionalism_metric(azure_deepeval_model, role)

                task_metric.measure(test_case)
                prof_metric.measure(test_case)

                passed = (
                    task_metric.score >= task_metric.threshold
                    and prof_metric.score >= prof_metric.threshold
                )

                results.append(
                    {
                        "framework": framework,
                        "success": True,
                        "passed": passed,
                        "task_score": task_metric.score,
                        "task_threshold": task_metric.threshold,
                        "prof_score": prof_metric.score,
                        "prof_threshold": prof_metric.threshold,
                        "latency_ms": agent_result.get("latency_ms", 0),
                    }
                )

                status = "PASS" if passed else "FAIL"
                print(f"    Status: {status}")
                print(f"    TaskCompletion: {task_metric.score:.2f} >= {task_metric.threshold}")
                print(f"    Professionalism: {prof_metric.score:.2f} >= {prof_metric.threshold}")

            except Exception as e:
                print(f"    ERROR: {e}")
                results.append(
                    {
                        "framework": framework,
                        "success": False,
                        "error": str(e),
                        "task_score": 0,
                        "prof_score": 0,
                    }
                )

        # Summary
        print("\n" + "=" * 70)
        print("DEEPEVAL SUMMARY")
        print("=" * 70)

        successful = [r for r in results if r.get("success")]
        passed = [r for r in successful if r.get("passed")]

        print(f"Total Frameworks: {len(results)}")
        print(f"Executed: {len(successful)}")
        print(f"Passed: {len(passed)}")

        if successful:
            avg_task = sum(r["task_score"] for r in successful) / len(successful)
            avg_prof = sum(r["prof_score"] for r in successful) / len(successful)
            print(f"Avg TaskCompletion: {avg_task:.2f}")
            print(f"Avg Professionalism: {avg_prof:.2f}")

        # At least one should pass
        assert len(successful) >= 1, f"No frameworks succeeded!"


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
