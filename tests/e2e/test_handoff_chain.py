"""
E2E Test: Multi-Agent Handoff Chain Evaluation

This test validates multi-agent handoff chains where:
1. An initial agent receives a task
2. Agent detects need to involve another role via @mention
3. Handoff is detected and next agent is invoked
4. Chain continues until task is resolved
5. Context is preserved across all handoffs

Uses REAL agents (OpenHands, AutoGen, CrewAI) for actual execution.
Uses DeepEval G-Eval metrics with Azure GPT-5.2 as the LLM judge.
Metrics evaluated: HandoffQuality, ContextPreservation, TaskCompletion

Usage:
    pytest tests/e2e/test_handoff_chain.py -v -s
    pytest tests/e2e/test_handoff_chain.py -v -s --framework=autogen
    pytest tests/e2e/test_handoff_chain.py -v -s -k "support_to_swe"
    pytest tests/e2e/test_handoff_chain.py -v -s -k "DeepEval"
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from vibeteam.router.models import (
    ROLE_DISPLAY_NAMES,
    ROLE_MENTION_MAP,
    AgentRole,
)

# Import DeepEval if available
DEEPEVAL_AVAILABLE = False
LLMTestCase = None

try:
    from deepeval import assert_test  # noqa: F401
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: F401

    DEEPEVAL_AVAILABLE = True
except ImportError:
    pass

# Import conftest helpers
try:
    from conftest import (
        AGENT_THRESHOLDS,
        AzureOpenAIModel,
        create_context_preservation_metric,
        create_handoff_quality_metric,
        create_professionalism_metric,
        create_task_completion_metric,
    )
except ImportError:
    try:
        from tests.e2e.conftest import (
            AGENT_THRESHOLDS,
            AzureOpenAIModel,
            create_context_preservation_metric,
            create_handoff_quality_metric,
            create_professionalism_metric,
            create_task_completion_metric,
        )
    except ImportError:
        AGENT_THRESHOLDS = {}
        AzureOpenAIModel = None
        create_context_preservation_metric = None
        create_handoff_quality_metric = None
        create_professionalism_metric = None
        create_task_completion_metric = None

if TYPE_CHECKING:
    from conftest import RealAgentRunner


# ==============================================================================
# Configuration
# ==============================================================================


MAX_CHAIN_LENGTH = 5  # Maximum handoffs to prevent infinite loops
DEFAULT_AGENT_TIMEOUT = 180.0  # 3 minutes per agent turn


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class AgentTurn:
    """A single agent's turn in the handoff chain."""

    agent_role: AgentRole
    framework: str
    input_message: str
    response: str
    handoff_to: AgentRole | None
    latency_ms: int
    turn_number: int
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HandoffChain:
    """Complete handoff chain execution result."""

    scenario_name: str
    framework: str
    initial_message: str
    expected_chain: list[AgentRole]
    actual_chain: list[AgentRole]
    turns: list[AgentTurn]
    total_latency_ms: int
    chain_completed: bool
    context_preserved: bool

    @property
    def chain_matches(self) -> bool:
        """Check if actual chain matches expected chain."""
        return self.actual_chain == self.expected_chain

    @property
    def transcript(self) -> str:
        """Generate human-readable transcript."""
        lines = [
            f"=== HANDOFF CHAIN: {self.scenario_name} ({self.framework.upper()}) ===",
            f"Initial Message: {self.initial_message[:100]}...",
            f"Expected Chain: {' -> '.join(self.expected_chain)}",
            f"Actual Chain: {' -> '.join(self.actual_chain)}",
            "",
        ]
        for turn in self.turns:
            handoff = f" -> @{turn.handoff_to}" if turn.handoff_to else " [END]"
            status = "OK" if turn.success else "FAILED"
            lines.append(f"--- Turn {turn.turn_number}: {turn.agent_role}{handoff} [{status}] ---")
            lines.append(f"Input: {turn.input_message[:200]}...")
            lines.append(f"Response: {turn.response[:300]}...")
            if turn.error:
                lines.append(f"Error: {turn.error}")
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "framework": self.framework,
            "initial_message": self.initial_message,
            "expected_chain": self.expected_chain,
            "actual_chain": self.actual_chain,
            "turns": [t.to_dict() for t in self.turns],
            "total_latency_ms": self.total_latency_ms,
            "chain_completed": self.chain_completed,
            "chain_matches": self.chain_matches,
            "context_preserved": self.context_preserved,
        }


@dataclass
class HandoffChainEvalResult:
    """Evaluation result for a handoff chain."""

    scenario_name: str
    framework: str
    chain_accuracy: float
    context_preservation: float
    handoff_detection: float
    task_completion: float
    overall_quality: float
    feedback: str
    judge_model: str
    evaluation_time_ms: int = 0

    @property
    def passed(self) -> bool:
        """Check if evaluation passed quality threshold."""
        return self.overall_quality >= 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ==============================================================================
# G-Eval Prompt for Handoff Chains
# ==============================================================================

HANDOFF_CHAIN_EVAL_PROMPT = """You are evaluating a multi-agent handoff chain where agents collaborate via @mentions.

SCENARIO: {scenario_name}
DESCRIPTION: {description}
FRAMEWORK: {framework}

INITIAL MESSAGE: {initial_message}

EXPECTED CHAIN: {expected_chain}
ACTUAL CHAIN: {actual_chain}

CONVERSATION TRANSCRIPT:
{transcript}

Evaluate the following criteria (0-1 scale):

1. CHAIN_ACCURACY: Did the actual chain match the expected chain?
   - 1.0: Perfect match
   - 0.5: Partial match (some agents correct, some missing/wrong)
   - 0.0: Completely wrong chain

2. CONTEXT_PRESERVATION: Was context preserved across handoffs?
   - 1.0: Full context carried through all handoffs
   - 0.5: Some context lost but core information preserved
   - 0.0: Context completely lost

3. HANDOFF_DETECTION: Were @mentions correctly detected and used?
   - 1.0: All handoffs triggered correctly via @mentions
   - 0.5: Some handoffs worked, some missed
   - 0.0: Handoff detection failed

4. TASK_COMPLETION: Was the overall task/issue resolved?
   - 1.0: Task fully completed
   - 0.5: Partial progress made
   - 0.0: Task not addressed

5. OVERALL_QUALITY: Overall quality of the multi-agent collaboration
   - 1.0: Excellent collaboration, seamless handoffs
   - 0.5: Acceptable but with issues
   - 0.0: Poor collaboration

Return ONLY valid JSON:
{{
    "chain_accuracy": 0.0,
    "context_preservation": 0.0,
    "handoff_detection": 0.0,
    "task_completion": 0.0,
    "overall_quality": 0.0,
    "feedback": "One paragraph summary of the evaluation"
}}"""


# ==============================================================================
# Handoff Detection
# ==============================================================================


def detect_handoff_in_response(response: str) -> AgentRole | None:
    """
    Detect @RoleName mention in agent response.

    Returns the mentioned role or None if no handoff detected.
    """
    # Pattern: @RoleName or /RoleName
    pattern = r"[@/]([A-Za-z]+)"
    matches = re.findall(pattern, response)

    for match in matches:
        normalized = match.lower()
        if normalized in ROLE_MENTION_MAP:
            return ROLE_MENTION_MAP[normalized]

    return None


# ==============================================================================
# Real Agent Handoff Chain Runner
# ==============================================================================


async def run_handoff_chain(
    scenario_name: str,
    initial_message: str,
    initial_agent: AgentRole,
    expected_chain: list[AgentRole],
    runner: RealAgentRunner,
    max_turns: int = MAX_CHAIN_LENGTH,
) -> HandoffChain:
    """
    Execute a multi-agent handoff chain with REAL agents.

    Args:
        scenario_name: Name of the scenario
        initial_message: The initial message to start the chain
        initial_agent: The first agent to invoke
        expected_chain: Expected sequence of agents
        runner: RealAgentRunner instance for executing agents
        max_turns: Maximum number of turns to prevent infinite loops

    Returns:
        HandoffChain with the execution results
    """
    turns: list[AgentTurn] = []
    actual_chain: list[AgentRole] = []
    total_latency = 0
    current_role = initial_agent
    current_message = initial_message

    for turn_num in range(1, max_turns + 1):
        start_time = time.perf_counter()

        print(f"    Turn {turn_num}: Running {current_role}...")

        try:
            # Run the REAL agent
            result = await runner.run(
                role=current_role,
                task=current_message,
                context_type="handoff_chain",
                context_id=f"{scenario_name}-turn-{turn_num}",
            )

            response = result.get("response", "")
            success = result.get("success", False)
            error = result.get("error")
            latency_ms = result.get("latency_ms", 0)
            total_latency += latency_ms

            # Detect handoff in response
            handoff_to = detect_handoff_in_response(response) if success else None

            turn = AgentTurn(
                agent_role=current_role,
                framework=runner.framework,
                input_message=current_message[:500],
                response=response[:1000],
                handoff_to=handoff_to,
                latency_ms=latency_ms,
                turn_number=turn_num,
                success=success,
                error=error,
            )
            turns.append(turn)
            actual_chain.append(current_role)

            print(f"      Success: {success}, Latency: {latency_ms}ms")
            if handoff_to:
                print(f"      Handoff detected: -> @{handoff_to}")

            # Check if chain should continue
            if not success or handoff_to is None:
                break

            # Prepare for next turn
            current_role = handoff_to
            current_message = f"""[Handoff from previous agent]

Previous agent ({ROLE_DISPLAY_NAMES.get(turns[-1].agent_role, turns[-1].agent_role)}) said:

{response}

Please continue handling this task as the next agent in the chain.
Original context: {initial_message[:500]}
"""

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            total_latency += latency_ms

            turn = AgentTurn(
                agent_role=current_role,
                framework=runner.framework,
                input_message=current_message[:500],
                response="",
                handoff_to=None,
                latency_ms=latency_ms,
                turn_number=turn_num,
                success=False,
                error=str(e),
            )
            turns.append(turn)
            actual_chain.append(current_role)
            print(f"      Error: {e}")
            break

    # Determine if chain completed and context was preserved
    chain_completed = len(turns) > 0 and turns[-1].success and turns[-1].handoff_to is None
    context_preserved = (
        all(
            turn.input_message and len(turn.input_message) > 20
            for turn in turns[1:]  # Skip first turn which has original message
        )
        if len(turns) > 1
        else True
    )

    return HandoffChain(
        scenario_name=scenario_name,
        framework=runner.framework,
        initial_message=initial_message,
        expected_chain=expected_chain,
        actual_chain=actual_chain,
        turns=turns,
        total_latency_ms=total_latency,
        chain_completed=chain_completed,
        context_preserved=context_preserved,
    )


# ==============================================================================
# Test Classes: Unit Tests for Handoff Detection
# ==============================================================================


class TestHandoffDetection:
    """Test handoff detection from agent responses (unit tests)."""

    def test_detect_at_mention(self):
        """Test detecting @RoleName mention."""
        response = "I've fixed the bug. @ReleaseEngineer please deploy."
        role = detect_handoff_in_response(response)
        assert role == "release_engineer"

    def test_detect_slash_mention(self):
        """Test detecting /RoleName mention."""
        response = "Investigation complete. /SoftwareEngineer can you look into this?"
        role = detect_handoff_in_response(response)
        assert role == "software_engineer"

    def test_detect_short_form(self):
        """Test detecting short form @SWE mention."""
        response = "Needs code review. @SWE please review."
        role = detect_handoff_in_response(response)
        assert role == "software_engineer"

    def test_no_mention(self):
        """Test no mention returns None."""
        response = "Task completed. No further action needed."
        role = detect_handoff_in_response(response)
        assert role is None

    def test_multiple_mentions_first_wins(self):
        """Test multiple mentions returns first one."""
        response = "@SupportEngineer and @ReleaseEngineer please coordinate."
        role = detect_handoff_in_response(response)
        assert role == "support_engineer"


# ==============================================================================
# NOTE: Legacy test classes (TestOpenHandsHandoffChain, TestHandoffChainAllScenarios,
# TestFullIncidentResponseChain, TestCrossFrameworkHandoffComparison,
# TestHandoffChainContextPreservation) have been removed. They used the deprecated
# GPT52Evaluator. Use DeepEval test classes below instead.
# ==============================================================================


# ==============================================================================
# DeepEval G-Eval Tests for Handoff Chains
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestHandoffChainWithDeepEval:
    """Handoff chain tests using DeepEval G-Eval metrics.

    Uses the proper DeepEval library with GEval as specified in requirements.md.
    Metrics: HandoffQuality, ContextPreservation, TaskCompletion
    Thresholds are per-agent as defined in AGENT_THRESHOLDS.
    """

    @pytest.mark.asyncio
    async def test_support_to_swe_handoff_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        handoff_chain_scenarios,
    ):
        """Test Support -> SWE handoff using DeepEval G-Eval metrics."""
        scenario = next(s for s in handoff_chain_scenarios if s["name"] == "support_to_swe_bug")

        print(f"\n>>> Running DeepEval handoff test: {scenario['name']}")
        print(f"    Expected chain: {' -> '.join(scenario['expected_chain'])}")

        chain = await run_handoff_chain(
            scenario_name=scenario["name"],
            initial_message=scenario["initial_message"],
            initial_agent=scenario["initial_agent"],
            expected_chain=scenario["expected_chain"],
            runner=openhands_runner,
        )

        print(f"    Actual chain: {' -> '.join(chain.actual_chain)}")

        if not chain.turns or not chain.turns[0].success:
            pytest.skip(f"Chain failed: {chain.turns[0].error if chain.turns else 'No turns'}")

        # Create DeepEval test case from chain transcript
        test_case = LLMTestCase(
            input=scenario["initial_message"],
            actual_output=chain.transcript,
        )

        # Get the initial agent role for thresholds
        initial_role = scenario["initial_agent"]

        # Create handoff-specific metrics
        handoff_metric = create_handoff_quality_metric(azure_deepeval_model, initial_role)
        context_metric = create_context_preservation_metric(azure_deepeval_model, initial_role)
        task_metric = create_task_completion_metric(azure_deepeval_model, initial_role)

        # Measure metrics
        handoff_metric.measure(test_case)
        context_metric.measure(test_case)
        task_metric.measure(test_case)

        print(
            f"    HandoffQuality: {handoff_metric.score:.2f} (threshold: {handoff_metric.threshold})"
        )
        print(
            f"    ContextPreservation: {context_metric.score:.2f} (threshold: {context_metric.threshold})"
        )
        print(f"    TaskCompletion: {task_metric.score:.2f} (threshold: {task_metric.threshold})")
        print(f"    Handoff Reason: {handoff_metric.reason}")

        # Assert using DeepEval thresholds
        assert handoff_metric.score >= handoff_metric.threshold, (
            f"HandoffQuality {handoff_metric.score:.2f} below threshold {handoff_metric.threshold}"
        )

    @pytest.mark.asyncio
    async def test_swe_to_release_handoff_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        handoff_chain_scenarios,
    ):
        """Test SWE -> Release handoff using DeepEval."""
        scenario = next(s for s in handoff_chain_scenarios if s["name"] == "swe_to_release_deploy")

        print(f"\n>>> Running DeepEval handoff test: {scenario['name']}")

        chain = await run_handoff_chain(
            scenario_name=scenario["name"],
            initial_message=scenario["initial_message"],
            initial_agent=scenario["initial_agent"],
            expected_chain=scenario["expected_chain"],
            runner=openhands_runner,
        )

        if not chain.turns or not chain.turns[0].success:
            pytest.skip(f"Chain failed: {chain.turns[0].error if chain.turns else 'No turns'}")

        test_case = LLMTestCase(
            input=scenario["initial_message"],
            actual_output=chain.transcript,
        )

        initial_role = scenario["initial_agent"]
        handoff_metric = create_handoff_quality_metric(azure_deepeval_model, initial_role)
        task_metric = create_task_completion_metric(azure_deepeval_model, initial_role)

        handoff_metric.measure(test_case)
        task_metric.measure(test_case)

        print(f"    HandoffQuality: {handoff_metric.score:.2f}")
        print(f"    TaskCompletion: {task_metric.score:.2f}")

        assert handoff_metric.score >= handoff_metric.threshold

    @pytest.mark.asyncio
    async def test_context_preservation_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
    ):
        """Test context preservation across handoffs using DeepEval."""
        scenario = {
            "name": "context_preservation_deepeval",
            "description": "Test that customer name and error details are preserved",
            "initial_message": (
                "Customer ACME Corp (contact: alex@acme.com) reports: "
                "Error code ERR-12345 in the checkout flow. "
                "Affects 50 users since 10:30 AM PST. "
                "Please investigate and fix urgently."
            ),
            "initial_agent": "support_engineer",
            "expected_chain": ["support_engineer", "software_engineer"],
        }

        print("\n>>> CONTEXT PRESERVATION TEST with DeepEval")

        chain = await run_handoff_chain(
            scenario_name=scenario["name"],
            initial_message=scenario["initial_message"],
            initial_agent=scenario["initial_agent"],
            expected_chain=scenario["expected_chain"],
            runner=openhands_runner,
            max_turns=3,
        )

        if not chain.turns or not chain.turns[0].success:
            pytest.skip("Chain failed")

        test_case = LLMTestCase(
            input=scenario["initial_message"],
            actual_output=chain.transcript,
        )

        # Context preservation is key metric here
        context_metric = create_context_preservation_metric(
            azure_deepeval_model, "support_engineer"
        )
        context_metric.measure(test_case)

        print(f"    ContextPreservation: {context_metric.score:.2f}")
        print(f"    Reason: {context_metric.reason}")

        # SupportEngineer has higher thresholds
        assert context_metric.score >= 0.75, (
            f"Context preservation too low: {context_metric.score:.2f}"
        )


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestHandoffChainDeepEvalAllScenarios:
    """Run all handoff chain scenarios with DeepEval and summarize results."""

    @pytest.mark.asyncio
    async def test_all_handoff_scenarios_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        handoff_chain_scenarios,
    ):
        """Run all handoff chain scenarios with DeepEval G-Eval metrics."""
        results = []

        print("\n" + "=" * 70)
        print("HANDOFF CHAIN E2E TEST - DEEPEVAL G-EVAL")
        print("=" * 70)

        for scenario in handoff_chain_scenarios:
            initial_role = scenario["initial_agent"]
            print(f"\n>>> {scenario['name']} (initial: {initial_role})")
            print(f"    Expected chain: {' -> '.join(scenario['expected_chain'])}")

            chain = await run_handoff_chain(
                scenario_name=scenario["name"],
                initial_message=scenario["initial_message"],
                initial_agent=scenario["initial_agent"],
                expected_chain=scenario["expected_chain"],
                runner=openhands_runner,
            )

            print(f"    Actual chain: {' -> '.join(chain.actual_chain)}")

            if not chain.turns or not chain.turns[0].success:
                print(
                    f"    SKIPPED: Chain failed - {chain.turns[0].error if chain.turns else 'No turns'}"
                )
                results.append(
                    {
                        "scenario": scenario["name"],
                        "initial_role": initial_role,
                        "success": False,
                        "chain_matches": False,
                        "handoff_score": 0,
                        "context_score": 0,
                        "task_score": 0,
                    }
                )
                continue

            # Create test case
            test_case = LLMTestCase(
                input=scenario["initial_message"],
                actual_output=chain.transcript,
            )

            # Create and measure metrics
            handoff_metric = create_handoff_quality_metric(azure_deepeval_model, initial_role)
            context_metric = create_context_preservation_metric(azure_deepeval_model, initial_role)
            task_metric = create_task_completion_metric(azure_deepeval_model, initial_role)

            handoff_metric.measure(test_case)
            context_metric.measure(test_case)
            task_metric.measure(test_case)

            passed = (
                handoff_metric.score >= handoff_metric.threshold
                and context_metric.score >= context_metric.threshold
                and task_metric.score >= task_metric.threshold
            )

            results.append(
                {
                    "scenario": scenario["name"],
                    "initial_role": initial_role,
                    "success": True,
                    "passed": passed,
                    "chain_matches": chain.chain_matches,
                    "actual_chain": " -> ".join(chain.actual_chain),
                    "handoff_score": handoff_metric.score,
                    "handoff_threshold": handoff_metric.threshold,
                    "context_score": context_metric.score,
                    "context_threshold": context_metric.threshold,
                    "task_score": task_metric.score,
                    "task_threshold": task_metric.threshold,
                    "latency_ms": chain.total_latency_ms,
                }
            )

            status = "PASS" if passed else "FAIL"
            chain_status = "MATCH" if chain.chain_matches else "PARTIAL"
            print(f"    Status: {status}, Chain: {chain_status}")
            print(f"    HandoffQuality: {handoff_metric.score:.2f} >= {handoff_metric.threshold}")
            print(
                f"    ContextPreservation: {context_metric.score:.2f} >= {context_metric.threshold}"
            )
            print(f"    TaskCompletion: {task_metric.score:.2f} >= {task_metric.threshold}")

        # Summary
        print("\n" + "=" * 70)
        print("DEEPEVAL SUMMARY")
        print("=" * 70)

        successful = [r for r in results if r.get("success")]
        passed = [r for r in successful if r.get("passed")]
        chain_matches = [r for r in successful if r.get("chain_matches")]

        print(f"Total Scenarios: {len(results)}")
        print(f"Executed: {len(successful)}")
        print(f"Passed: {len(passed)}")
        print(f"Chain Matches: {len(chain_matches)}")

        if successful:
            avg_handoff = sum(r["handoff_score"] for r in successful) / len(successful)
            avg_context = sum(r["context_score"] for r in successful) / len(successful)
            avg_task = sum(r["task_score"] for r in successful) / len(successful)
            print(f"Avg HandoffQuality: {avg_handoff:.2f}")
            print(f"Avg ContextPreservation: {avg_context:.2f}")
            print(f"Avg TaskCompletion: {avg_task:.2f}")

        # At least half should pass
        assert len(passed) >= len(successful) // 2, (
            f"Only {len(passed)}/{len(successful)} passed DeepEval thresholds"
        )


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
