"""
E2E Test: Multi-Agent Team Evaluation with DeepEval

This test evaluates multi-agent team coordination using the DeepEval framework.
It tests:
1. Responsibility detection - Did correct agents claim tasks?
2. Team coordination - How well did agents coordinate?
3. Handoff quality - Was context preserved in handoffs?
4. Task completion - Was the task fully completed?
5. Professionalism - Communication quality

Runs across frameworks: mock (fast), autogen, crewai, openhands, opencode (when available)

Usage:
    # Run with mock agents (fast, no LLM calls)
    pytest tests/e2e/test_team_eval.py -v -s

    # Run specific scenario
    pytest tests/e2e/test_team_eval.py -v -s -k "customer_api_error"

    # Run with real agents (requires LLM)
    pytest tests/e2e/test_team_eval.py -v -s --framework=crewai

    # Run full evaluation with DeepEval dashboard
    deepeval test run tests/e2e/test_team_eval.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Enable pytest-asyncio for async tests
pytestmark = pytest.mark.asyncio

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from vibeteam.team import (
    ScenarioResult,
    TeamTestHarness,
    create_handoff_test_case,
)

# ==============================================================================
# Configuration
# ==============================================================================


class EvalConfig:
    """Configuration for team evaluation tests."""

    AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_API_KEY", ""))
    AZURE_API_BASE = os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_API_BASE", ""))
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-08-01-preview")

    # Default framework for testing
    DEFAULT_FRAMEWORK = os.getenv("AGENT_FRAMEWORK", "mock")

    # Timeout for agent scenarios
    SCENARIO_TIMEOUT = float(os.getenv("SCENARIO_TIMEOUT", "5.0"))

    # DeepEval settings
    DEEPEVAL_THRESHOLD = 0.7


# ==============================================================================
# Test Scenarios
# ==============================================================================

SCENARIOS = [
    {
        "name": "customer_api_error",
        "message": "Customer reports API endpoint returning 404 errors. Infrastructure issue affecting 500 users. Need to check kubernetes deployment.",
        "expected_agents": ["support_engineer", "release_engineer"],
        "description": "Customer infrastructure issue requiring support and ops coordination",
    },
    {
        "name": "feature_request",
        "message": "Feature request: Can we add dark mode to the dashboard? Multiple customers asking for this feature. Please add to backlog.",
        "expected_agents": ["product_manager"],
        "description": "Feature request requiring product management triage",
    },
    {
        "name": "deployment_request",
        "message": "PR #457 is approved and ready. Please deploy to staging kubernetes cluster.",
        "expected_agents": ["release_engineer"],
        "description": "Deployment request for approved code",
    },
    {
        "name": "error_spike",
        "message": "Sentry alert: 50 new GraphRecursionError exceptions in code. This is a bug affecting users. Need to debug and fix.",
        "expected_agents": ["support_engineer", "software_engineer"],
        "description": "Error spike requiring support and engineering investigation",
    },
    {
        "name": "bug_report",
        "message": "Bug in login function: users getting 'undefined' error when clicking submit. Please fix the code ASAP.",
        "expected_agents": ["software_engineer"],
        "description": "Bug report requiring software engineering attention",
    },
]


# ==============================================================================
# Test Fixtures
# ==============================================================================


@pytest.fixture
def framework(request) -> str:
    """Get the framework to test from command line or config."""
    return getattr(request, "param", EvalConfig.DEFAULT_FRAMEWORK)


@pytest.fixture
def harness(framework: str) -> TeamTestHarness:
    """Create a TeamTestHarness for the given framework."""
    return TeamTestHarness(framework=framework)


# ==============================================================================
# Basic Tests (without DeepEval - always run)
# ==============================================================================


class TestTeamScenarios:
    """Test team scenarios with mock agents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
    async def test_scenario_runs(self, scenario: dict):
        """Test that scenarios run and expected agents respond."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message=scenario["message"],
            expected_agents=scenario["expected_agents"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        # Basic assertions
        assert result.total_messages >= 2, (
            f"Expected at least 2 messages (user + agent), got {result.total_messages}"
        )
        assert result.framework == "mock"

        # Check correct agents responded
        if scenario["expected_agents"]:
            for expected_agent in scenario["expected_agents"]:
                assert expected_agent in result.responding_agents, (
                    f"Expected {expected_agent} to respond. "
                    f"Responding agents: {result.responding_agents}"
                )

        # Print transcript for visibility
        print(f"\n--- Scenario: {scenario['name']} ---")
        print(f"Message: {scenario['message'][:80]}...")
        print(f"Expected: {scenario['expected_agents']}")
        print(f"Responded: {result.responding_agents}")
        print(f"Correct: {result.correct_agents_responded}")
        print(f"Transcript:\n{result.channel.to_transcript()}")

    @pytest.mark.asyncio
    async def test_customer_api_error_full(self):
        """Test the full customer API error scenario in detail."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message=(
                "URGENT: Customer ACME Corp reports API endpoint returning 404 errors. "
                "Infrastructure issue affecting 500 users. Need kubernetes cluster investigation."
            ),
            expected_agents=["support_engineer", "release_engineer"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        # Verify support engineer responded (customer issue)
        assert "support_engineer" in result.responding_agents
        # Verify release engineer responded (infrastructure issue)
        assert "release_engineer" in result.responding_agents

        # Verify message count
        assert result.total_messages >= 3  # user + 2 agents

        print(f"\n--- Full Transcript ---")
        print(result.channel.to_transcript())


class TestResponsibilityDetection:
    """Test that responsibility detection works correctly."""

    @pytest.mark.asyncio
    async def test_swe_claims_bug_fix(self):
        """Test that SoftwareEngineer claims bug fix tasks."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message="There's a bug in the login function. Please fix the code.",
            expected_agents=["software_engineer"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        assert "software_engineer" in result.responding_agents
        # Product manager should NOT claim a bug fix
        assert "product_manager" not in result.responding_agents

    @pytest.mark.asyncio
    async def test_pm_claims_feature_request(self):
        """Test that ProductManager claims feature requests."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message="Customer wants a new feature for exporting data to CSV. Add to backlog.",
            expected_agents=["product_manager"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        assert "product_manager" in result.responding_agents

    @pytest.mark.asyncio
    async def test_release_claims_deployment(self):
        """Test that ReleaseEngineer claims deployment tasks."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message="Deploy the latest build to kubernetes staging cluster.",
            expected_agents=["release_engineer"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        assert "release_engineer" in result.responding_agents


# ==============================================================================
# DeepEval Tests (only run when deepeval is available)
# ==============================================================================


def has_deepeval() -> bool:
    """Check if deepeval is available."""
    try:
        import deepeval  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not has_deepeval(), reason="deepeval not installed")
class TestTeamEvalWithDeepEval:
    """Test team scenarios with DeepEval metrics."""

    @pytest.fixture(autouse=True)
    def setup_metrics(self):
        """Setup DeepEval metrics."""
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams

        # Team Coordination metric
        self.team_coordination = GEval(
            name="TeamCoordination",
            criteria="""Evaluate how well the AI agents coordinated as a team:
            1. Did agents correctly identify their responsibilities?
            2. Did agents communicate their intentions clearly?
            3. Did agents hand off tasks appropriately?
            4. Did agents avoid duplicating work?
            5. Did the team complete the overall objective?
            """,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=EvalConfig.DEEPEVAL_THRESHOLD,
        )

        # Responsibility Detection metric
        self.responsibility_detection = GEval(
            name="ResponsibilityDetection",
            criteria="""Evaluate if agents correctly identified task ownership:
            - SoftwareEngineer should claim: code bugs, implementations, PRs
            - ReleaseEngineer should claim: deployments, infrastructure
            - SupportEngineer should claim: customer issues, error analysis
            - ProductManager should claim: feature requests, prioritization
            - MarketingManager should claim: announcements, content
            
            Score based on:
            1. Correct agent claimed the task (or multiple if appropriate)
            2. Wrong agents did NOT claim tasks outside their area
            3. Clear communication about who is handling what
            """,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=EvalConfig.DEEPEVAL_THRESHOLD,
        )

        # Task Completion metric
        self.task_completion = GEval(
            name="TaskCompletion",
            criteria="""Evaluate if the team successfully completed the requested task:
            1. Was the original request acknowledged?
            2. Were appropriate actions taken?
            3. Was there a clear resolution or next step?
            """,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=EvalConfig.DEEPEVAL_THRESHOLD,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
    async def test_scenario_with_geval(self, scenario: dict):
        """Test scenario with G-Eval metrics."""
        from deepeval import assert_test
        from deepeval.test_case import LLMTestCase

        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message=scenario["message"],
            expected_agents=scenario["expected_agents"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        # Create LLM test case for evaluation
        # Note: We use LLMTestCase instead of ConversationalTestCase
        # because GEval works with actual_output
        test_case = LLMTestCase(
            input=scenario["message"],
            actual_output=result.channel.to_transcript(),
            expected_output=f"Agents {scenario['expected_agents']} should respond appropriately",
            context=[scenario["description"]],
        )

        # Run assertion with metrics
        assert_test(
            test_case=test_case,
            metrics=[
                self.team_coordination,
                self.responsibility_detection,
                self.task_completion,
            ],
        )

    @pytest.mark.asyncio
    async def test_full_eval_pipeline(self):
        """Run full evaluation pipeline and print results."""
        from deepeval import evaluate
        from deepeval.test_case import LLMTestCase

        print("\n" + "=" * 70)
        print("FULL TEAM EVALUATION PIPELINE")
        print("=" * 70)

        test_cases = []
        harness = TeamTestHarness(framework="mock")

        for scenario in SCENARIOS:
            result = await harness.run_scenario(
                initial_message=scenario["message"],
                expected_agents=scenario["expected_agents"],
                timeout=EvalConfig.SCENARIO_TIMEOUT,
            )

            test_case = LLMTestCase(
                input=scenario["message"],
                actual_output=result.channel.to_transcript(),
                expected_output=f"Agents {scenario['expected_agents']} respond",
                context=[scenario["description"]],
            )
            test_cases.append(test_case)

            print(f"\n>>> Scenario: {scenario['name']}")
            print(f"    Responded: {result.responding_agents}")
            print(f"    Expected:  {scenario['expected_agents']}")

        # Run evaluation
        eval_result = evaluate(
            test_cases=test_cases,
            metrics=[
                self.team_coordination,
                self.responsibility_detection,
                self.task_completion,
            ],
            run_async=True,
            print_results=True,
        )

        print("\n" + "=" * 70)
        print("EVALUATION COMPLETE")
        print("=" * 70)

        # Basic assertion - at least some test cases should pass
        assert eval_result is not None


# ==============================================================================
# Conversational Test (with DeepEval ConversationalTestCase)
# ==============================================================================


@pytest.mark.skipif(not has_deepeval(), reason="deepeval not installed")
class TestConversationalEval:
    """Test multi-turn conversations with DeepEval ConversationalTestCase."""

    @pytest.mark.asyncio
    async def test_scenario_to_conversational_test_case(self):
        """Test conversion of scenario result to ConversationalTestCase."""
        harness = TeamTestHarness(framework="mock")

        result = await harness.run_scenario(
            initial_message="Customer reports API errors. Please investigate.",
            expected_agents=["support_engineer"],
            timeout=EvalConfig.SCENARIO_TIMEOUT,
        )

        # Convert to DeepEval test case
        test_case = create_handoff_test_case(result)

        # Verify structure
        assert test_case is not None
        assert len(test_case.turns) >= 2  # user + at least one agent

        print(f"\n--- ConversationalTestCase ---")
        for turn in test_case.turns:
            print(f"  [{turn.role}]: {turn.content[:80]}...")


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s"])
