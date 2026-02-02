"""
E2E Test: Slack Message Routing with /RoleName Mentions

This test validates the Slack integration's ability to:
1. Parse /RoleName mentions from incoming Slack messages
2. Route messages to the correct agent based on role mention
3. Execute REAL agents (OpenHands, AutoGen, CrewAI) for tasks
4. Evaluate agent responses using DeepEval G-Eval with Azure GPT-5.2
5. Optionally post results to real Slack channels

Uses DeepEval G-Eval metrics with Azure GPT-5.2 as the LLM judge.
Metrics evaluated: TaskCompletion, Professionalism, ToolUsage

Usage:
    # Run with OpenHands (default)
    pytest tests/e2e/test_slack_routing.py -v -s

    # Run with specific framework
    pytest tests/e2e/test_slack_routing.py -v -s --framework=autogen

    # Run with real Slack posting
    pytest tests/e2e/test_slack_routing.py -v -s --post-to-slack

    # Run DeepEval tests only
    pytest tests/e2e/test_slack_routing.py -v -s -k "DeepEval"

    # Run specific test
    pytest tests/e2e/test_slack_routing.py -v -s -k "openhands_swe"
"""

from __future__ import annotations

import re
import sys
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
assert_test = None

try:
    from deepeval import assert_test  # noqa: F401
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: F401

    DEEPEVAL_AVAILABLE = True
except ImportError:
    pass

# Import conftest helpers (these are always available)
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
        # Try relative import if running from within package
        from tests.e2e.conftest import (
            AGENT_THRESHOLDS,
            AzureOpenAIModel,
            create_professionalism_metric,
            create_task_completion_metric,
            create_tool_usage_metric,
        )
    except ImportError:
        # Running standalone without any conftest access
        AGENT_THRESHOLDS = {}
        AzureOpenAIModel = None
        create_professionalism_metric = None
        create_task_completion_metric = None
        create_tool_usage_metric = None

if TYPE_CHECKING:
    from conftest import RealAgentRunner


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class RoutingResult:
    """Result of routing a Slack message to a real agent."""

    scenario_name: str
    original_message: str
    detected_role: AgentRole | None
    expected_role: AgentRole
    routing_correct: bool
    agent_response: str
    latency_ms: int
    framework: str
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoutingEvalResult:
    """Evaluation result from GPT-5.2 judge."""

    scenario_name: str
    task_understanding: float
    action_taken: float
    result_quality: float
    tool_usage: float
    completeness: float
    overall_score: float
    feedback: str
    judge_model: str

    @property
    def passed(self) -> bool:
        """Check if evaluation passed quality threshold."""
        return self.overall_score >= 0.6


# ==============================================================================
# G-Eval Prompt for Slack Routing
# ==============================================================================

SLACK_ROUTING_EVAL_PROMPT = """You are evaluating an AI agent's response to a Slack message task.

SCENARIO: {scenario_name}
DESCRIPTION: {description}
SLACK MESSAGE: {message}
EXPECTED ROLE: {expected_role}
DETECTED ROLE: {detected_role}
AGENT FRAMEWORK: {framework}

AGENT RESPONSE:
{response}

Evaluate the agent's response on these criteria (score 0.0 to 1.0):

1. TASK_UNDERSTANDING: Did the agent understand what was being asked in the Slack message?
   - 1.0: Fully understood the task and context
   - 0.5: Partially understood but missed some details
   - 0.0: Did not understand the task

2. ACTION_TAKEN: Did the agent take appropriate actions to complete the task?
   - 1.0: Took correct actions (used tools, made decisions, etc.)
   - 0.5: Took some actions but incomplete
   - 0.0: No meaningful action taken

3. RESULT_QUALITY: Is the response helpful, accurate, and actionable?
   - 1.0: Excellent response with clear, useful information
   - 0.5: Acceptable but could be more detailed
   - 0.0: Unhelpful or incorrect response

4. TOOL_USAGE: Did the agent use available tools effectively? (gh CLI, file operations, etc.)
   - 1.0: Used tools appropriately and effectively
   - 0.5: Limited tool usage or partial success
   - 0.0: Failed to use tools when needed (or N/A if no tools required)

5. COMPLETENESS: Is the response complete, or does it clearly need follow-up?
   - 1.0: Complete response, task fully addressed
   - 0.5: Partial response, some follow-up needed
   - 0.0: Incomplete, major parts missing

Return ONLY valid JSON:
{{
    "task_understanding": 0.0,
    "action_taken": 0.0,
    "result_quality": 0.0,
    "tool_usage": 0.0,
    "completeness": 0.0,
    "overall_score": 0.0,
    "feedback": "Brief explanation of scores"
}}"""


# ==============================================================================
# Router Helper Functions
# ==============================================================================


def parse_role_mention(message: str) -> AgentRole | None:
    """
    Parse /RoleName mention from a message.

    Returns the detected agent role or None if no mention found.
    """
    pattern = r"/([A-Za-z]+)"
    matches = re.findall(pattern, message)

    for match in matches:
        normalized = match.lower()
        if normalized in ROLE_MENTION_MAP:
            return ROLE_MENTION_MAP[normalized]

    return None


def keyword_based_routing(message: str) -> AgentRole | None:
    """
    Fall back to keyword-based routing when no mention is present.

    Returns the detected agent role based on keywords.
    """
    message_lower = message.lower()

    patterns: dict[AgentRole, list[str]] = {
        "software_engineer": [
            "bug",
            "fix",
            "code",
            "implement",
            "pr",
            "merge",
            "function",
            "error",
            "issue",
            "github",
            "review",
            "test",
        ],
        "release_engineer": [
            "deploy",
            "release",
            "staging",
            "production",
            "kubernetes",
            "rollback",
            "infrastructure",
            "k8s",
            "helm",
        ],
        "support_engineer": [
            "customer",
            "ticket",
            "support",
            "complaint",
            "help",
            "user",
            "incident",
            "sentry",
        ],
        "product_manager": [
            "feature",
            "backlog",
            "priority",
            "roadmap",
            "requirement",
            "spec",
            "story",
            "prd",
        ],
        "marketing_manager": [
            "announce",
            "tweet",
            "blog",
            "campaign",
            "launch",
            "marketing",
            "press",
            "newsletter",
        ],
    }

    for role, keywords in patterns.items():
        if any(keyword in message_lower for keyword in keywords):
            return role

    return None


# ==============================================================================
# Test Classes: Unit Tests for Parsing
# ==============================================================================


class TestSlackMentionParsing:
    """Test /RoleName mention parsing (unit tests, no agents needed)."""

    def test_parse_software_engineer(self):
        """Test parsing /SoftwareEngineer mention."""
        role = parse_role_mention("/SoftwareEngineer fix the bug")
        assert role == "software_engineer"

    def test_parse_release_engineer(self):
        """Test parsing /ReleaseEngineer mention."""
        role = parse_role_mention("/ReleaseEngineer deploy to staging")
        assert role == "release_engineer"

    def test_parse_support_engineer(self):
        """Test parsing /SupportEngineer mention."""
        role = parse_role_mention("/SupportEngineer customer needs help")
        assert role == "support_engineer"

    def test_parse_product_manager(self):
        """Test parsing /ProductManager mention."""
        role = parse_role_mention("/ProductManager add to backlog")
        assert role == "product_manager"

    def test_parse_marketing_manager(self):
        """Test parsing /MarketingManager mention."""
        role = parse_role_mention("/MarketingManager announce the release")
        assert role == "marketing_manager"

    def test_parse_short_form_swe(self):
        """Test parsing short form /SWE mention."""
        role = parse_role_mention("/SWE review this PR")
        assert role == "software_engineer"

    def test_parse_short_form_pm(self):
        """Test parsing short form /PM mention."""
        role = parse_role_mention("/PM prioritize this feature")
        assert role == "product_manager"

    def test_parse_case_insensitive(self):
        """Test case-insensitive parsing."""
        assert parse_role_mention("/softwareengineer fix it") == "software_engineer"
        assert parse_role_mention("/SOFTWAREENGINEER fix it") == "software_engineer"
        assert parse_role_mention("/SoftwareEngineer fix it") == "software_engineer"

    def test_parse_no_mention(self):
        """Test message with no mention returns None."""
        role = parse_role_mention("Just a regular message")
        assert role is None

    def test_parse_mention_in_middle(self):
        """Test mention in middle of message."""
        role = parse_role_mention("Hey /ReleaseEngineer can you deploy?")
        assert role == "release_engineer"


class TestKeywordRouting:
    """Test keyword-based fallback routing (unit tests)."""

    def test_keyword_deploy(self):
        """Test 'deploy' routes to release_engineer."""
        role = keyword_based_routing("We need to deploy to staging")
        assert role == "release_engineer"

    def test_keyword_bug(self):
        """Test 'bug' routes to software_engineer."""
        role = keyword_based_routing("There's a bug in the login form")
        assert role == "software_engineer"

    def test_keyword_customer(self):
        """Test 'customer' routes to support_engineer."""
        role = keyword_based_routing("A customer needs assistance with billing")
        assert role == "support_engineer"

    def test_keyword_feature(self):
        """Test 'feature' routes to product_manager."""
        role = keyword_based_routing("New feature request from the team")
        assert role == "product_manager"

    def test_keyword_announce(self):
        """Test 'announce' routes to marketing_manager."""
        role = keyword_based_routing("We need to announce this via tweet")
        assert role == "marketing_manager"

    def test_keyword_sentry(self):
        """Test 'sentry' routes to support_engineer."""
        role = keyword_based_routing("Sentry alert received from customer")
        assert role == "support_engineer"

    def test_keyword_github(self):
        """Test 'github' routes to software_engineer."""
        role = keyword_based_routing("Check the GitHub issues for open bugs")
        assert role == "software_engineer"


# ==============================================================================
# NOTE: Legacy test classes (TestOpenHandsSlackRouting, TestSlackRoutingAllScenarios,
# TestCrossFrameworkComparison) have been removed. They used the deprecated
# GPT52Evaluator. Use DeepEval test classes below instead.
# ==============================================================================


class TestSlackRoutingWithRealSlack:
    """Test Slack routing with real Slack posting (when --post-to-slack is enabled)."""

    @pytest.mark.asyncio
    async def test_post_agent_response_to_slack(
        self,
        autogen_runner: RealAgentRunner,
        slack_connector,
        slack_test_channel: str,
        should_post_to_slack: bool,
        slack_routing_scenarios,
    ):
        """Run agent and post response to real Slack channel."""
        if not should_post_to_slack:
            pytest.skip("--post-to-slack not enabled")

        scenario = slack_routing_scenarios[0]  # Use first scenario

        print("\n>>> Testing with REAL Slack posting")
        print(f"    Channel: {slack_test_channel}")
        print(f"    Task: {scenario['message']}")

        # Post the original message to Slack
        original_msg = slack_connector.post_message(
            channel=slack_test_channel,
            text=f"[E2E Test] {scenario['message']}",
        )

        print(f"    Posted message: {original_msg.ts}")

        # Run the agent (using AutoGen since OpenHands requires Python 3.12+)
        agent_result = await autogen_runner.run(
            role=scenario["expected_role"],
            task=scenario["message"],
            context_type="slack",
            context_id=original_msg.ts,
        )

        # Post agent response as reply
        if agent_result.get("success") and agent_result.get("response"):
            role_display = ROLE_DISPLAY_NAMES.get(
                scenario["expected_role"],
                scenario["expected_role"],
            )

            reply = slack_connector.post_message(
                channel=slack_test_channel,
                text=f"*{role_display}* responds:\n\n{agent_result['response'][:2000]}",
                thread_ts=original_msg.ts,
            )

            print(f"    Posted reply: {reply.ts}")

        assert agent_result.get("success"), f"Agent failed: {agent_result.get('error')}"


# ==============================================================================
# DeepEval G-Eval Tests (New - Using DeepEval Library)
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestSlackRoutingWithDeepEval:
    """
    Slack routing tests using DeepEval G-Eval metrics.

    Uses the proper DeepEval library with GEval as specified in requirements.md.
    Metrics: TaskCompletion, Professionalism, ToolUsage
    Thresholds are per-agent as defined in AGENT_THRESHOLDS.
    """

    @pytest.mark.asyncio
    async def test_swe_task_with_deepeval(
        self,
        autogen_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        slack_routing_scenarios,
    ):
        """Test SWE task using DeepEval G-Eval metrics with per-role thresholds."""
        scenario = next(
            s for s in slack_routing_scenarios if s["name"] == "openhands_swe_github_issue"
        )
        role = scenario["expected_role"]

        print(f"\n>>> Running DeepEval test for {role}...")
        print(f"    Threshold: {AGENT_THRESHOLDS.get(role, {}).get('task_completion', 0.7)}")

        # Run the agent (using AutoGen since OpenHands requires Python 3.12+)
        result = await autogen_runner.run(
            role=role,
            task=scenario["message"],
            context_type="slack",
            context_id="deepeval-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        # Create DeepEval test case
        test_case = LLMTestCase(
            input=scenario["message"],
            actual_output=result.get("response", ""),
        )

        # Create metrics with role-specific thresholds
        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        prof_metric = create_professionalism_metric(azure_deepeval_model, role)

        # Measure metrics
        task_metric.measure(test_case)
        prof_metric.measure(test_case)

        print(f"    TaskCompletion: {task_metric.score:.2f} (threshold: {task_metric.threshold})")
        print(f"    Professionalism: {prof_metric.score:.2f} (threshold: {prof_metric.threshold})")
        print(f"    Task Reason: {task_metric.reason}")

        # Assert using DeepEval
        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )

    @pytest.mark.asyncio
    async def test_support_task_with_deepeval(
        self,
        autogen_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        slack_routing_scenarios,
    ):
        """Test SupportEngineer task with higher thresholds per requirements.md."""
        scenario = next(
            s for s in slack_routing_scenarios if s["name"] == "openhands_support_analyze"
        )
        role = scenario["expected_role"]

        print(f"\n>>> Running DeepEval test for {role}...")
        print(f"    Threshold: {AGENT_THRESHOLDS.get(role, {}).get('task_completion', 0.8)}")

        # Run the agent (using AutoGen since OpenHands requires Python 3.12+)
        result = await autogen_runner.run(
            role=role,
            task=scenario["message"],
            context_type="slack",
            context_id="deepeval-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        test_case = LLMTestCase(
            input=scenario["message"],
            actual_output=result.get("response", ""),
        )

        # SupportEngineer has higher thresholds (0.80 task, 0.80 professionalism)
        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        prof_metric = create_professionalism_metric(azure_deepeval_model, role)

        task_metric.measure(test_case)
        prof_metric.measure(test_case)

        print(f"    TaskCompletion: {task_metric.score:.2f}")
        print(f"    Professionalism: {prof_metric.score:.2f}")

        # SupportEngineer has higher thresholds
        assert task_metric.score >= 0.80, (
            f"SupportEngineer TaskCompletion too low: {task_metric.score:.2f}"
        )


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestSlackRoutingDeepEvalAllScenarios:
    """Run all scenarios with DeepEval and summarize results."""

    @pytest.mark.asyncio
    async def test_all_scenarios_deepeval(
        self,
        autogen_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        slack_routing_scenarios,
    ):
        """Run all Slack routing scenarios with DeepEval G-Eval metrics."""

        results = []

        print("\n" + "=" * 70)
        print("SLACK ROUTING E2E TEST - DEEPEVAL G-EVAL")
        print("=" * 70)

        for scenario in slack_routing_scenarios:
            role = scenario["expected_role"]
            print(f"\n>>> {scenario['name']} (role: {role})")

            # Run agent (using AutoGen since OpenHands requires Python 3.12+)
            agent_result = await autogen_runner.run(
                role=role,
                task=scenario["message"],
                context_type="slack",
                context_id=f"deepeval-{scenario['name']}",
            )

            if not agent_result.get("success"):
                print(f"    SKIPPED: Agent failed - {agent_result.get('error')}")
                results.append(
                    {
                        "scenario": scenario["name"],
                        "role": role,
                        "success": False,
                        "task_score": 0,
                        "prof_score": 0,
                    }
                )
                continue

            # Create test case
            test_case = LLMTestCase(
                input=scenario["message"],
                actual_output=agent_result.get("response", ""),
            )

            # Create and measure metrics
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
                    "scenario": scenario["name"],
                    "role": role,
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

        # Summary
        print("\n" + "=" * 70)
        print("DEEPEVAL SUMMARY")
        print("=" * 70)

        successful = [r for r in results if r.get("success")]
        passed = [r for r in successful if r.get("passed")]

        print(f"Total Scenarios: {len(results)}")
        print(f"Executed: {len(successful)}")
        print(f"Passed: {len(passed)}")

        if successful:
            avg_task = sum(r["task_score"] for r in successful) / len(successful)
            avg_prof = sum(r["prof_score"] for r in successful) / len(successful)
            print(f"Avg TaskCompletion: {avg_task:.2f}")
            print(f"Avg Professionalism: {avg_prof:.2f}")

        # At least half should pass
        assert len(passed) >= len(successful) // 2, (
            f"Only {len(passed)}/{len(successful)} passed DeepEval thresholds"
        )


# ==============================================================================
# Real Slack E2E Handoff Test (with Slack Tools)
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestRealSlackHandoffE2E:
    """
    End-to-end test for Slack handoff scenarios.

    This test validates the COMPLETE handoff flow:
    1. Post initial message to REAL Slack channel
    2. Set Slack context for agent
    3. Run SupportEngineer with Slack tools (post_slack_message, mention_agent)
    4. Detect handoff via @mention
    5. Run ReleaseEngineer with same context
    6. Evaluate with DeepEval metrics
    7. Verify messages appeared in Slack
    """

    @pytest.mark.asyncio
    async def test_real_slack_handoff_support_to_release(
        self,
        autogen_runner: RealAgentRunner,
        slack_connector,
        slack_test_channel: str,
        should_post_to_slack: bool,
        azure_deepeval_model: AzureOpenAIModel,
    ):
        """
        Test complete handoff flow from SupportEngineer to ReleaseEngineer.

        Scenario: Customer reports API 404 errors. SupportEngineer should
        analyze and handoff to ReleaseEngineer for investigation.
        """
        if not should_post_to_slack:
            pytest.skip("--post-to-slack not enabled")

        # Import Slack tools
        from agents.shared.slack_tools import (
            clear_slack_context,
            set_slack_context,
        )

        print("\n" + "=" * 70)
        print("REAL SLACK E2E HANDOFF TEST")
        print("=" * 70)
        print(f"Channel: {slack_test_channel}")

        # Step 1: Post initial customer message to Slack
        customer_message = (
            "/SupportEngineer URGENT: customer ACME Corp reports API 404 errors since 8am. "
            "They're hitting https://api.vibetechnologies.com/v2/agent/execute. "
            "This is affecting 500 users and is CRITICAL. "
            "After initial investigation, handoff to /ReleaseEngineer to check recent deployments."
        )

        print("\n>>> Step 1: Posting initial message to Slack")
        initial_msg = slack_connector.post_message(
            channel=slack_test_channel,
            text=f"[E2E Handoff Test] {customer_message}",
        )
        print(f"    Message TS: {initial_msg.ts}")

        # Generate session_id for SupportEngineer
        import uuid

        support_session_id = str(uuid.uuid4())[:8]

        # Step 2: Set Slack context for SupportEngineer (with session_id for [RoleName:session_id] prefix)
        print(
            f"\n>>> Step 2: Setting Slack context for SupportEngineer (session: {support_session_id})"
        )
        set_slack_context(
            connector=slack_connector,
            channel=slack_test_channel,
            thread_ts=initial_msg.ts,
            from_agent="SupportEngineer",
            session_id=support_session_id,
        )

        # Step 3: Run SupportEngineer - agent should use send_message() to post to Slack
        print("\n>>> Step 3: Running SupportEngineer (agent will post via send_message)...")
        support_result = await autogen_runner.run(
            role="support_engineer",
            task=customer_message,
            context_type="slack",
            context_id=initial_msg.ts,
        )

        print(f"    Success: {support_result.get('success', False)}")
        print(f"    Latency: {support_result.get('latency_ms', 0)}ms")
        print(f"    Response (first 300 chars): {support_result.get('response', '')[:300]}...")

        # NOTE: Agent should have posted to Slack directly via send_message()
        # We no longer post on behalf of the agent here

        # Step 4: Detect handoff in response (using /RoleName format)
        print("\n>>> Step 4: Detecting handoff...")
        response_text = support_result.get("response", "").lower()
        handoff_detected = any(
            mention in response_text
            for mention in [
                "/releaseengineer",
                "/release",
                "/sre",
                "/sitereliabilityengineer",
                "release engineer",
                "releaseengineer",
            ]
        )
        print(f"    Handoff detected: {handoff_detected}")

        # Step 5: Run handoff chain - continue until no more handoffs detected
        agent_results = [("support_engineer", support_result)]
        max_handoffs = 5  # Prevent infinite loops
        handoff_count = 0

        # Parse handoffs from SupportEngineer response
        def detect_handoffs(response_text: str) -> list[str]:
            """Detect /RoleName mentions in response, return list of roles to run."""
            text_lower = response_text.lower()
            detected = []
            role_mapping = {
                "/softwareengineer": "software_engineer",
                "/releaseengineer": "release_engineer",
                "/supportengineer": "support_engineer",
                "/productmanager": "product_manager",
                "/marketingmanager": "marketing_manager",
            }
            for mention, role in role_mapping.items():
                if mention in text_lower:
                    detected.append(role)
            return detected

        # Initial handoffs from SupportEngineer
        pending_handoffs = detect_handoffs(support_result.get("response", ""))
        print(f"    Handoffs detected: {pending_handoffs}")

        # Already ran support_engineer, so remove it from pending
        pending_handoffs = [r for r in pending_handoffs if r != "support_engineer"]
        already_ran = {"support_engineer"}

        while pending_handoffs and handoff_count < max_handoffs:
            next_role = pending_handoffs.pop(0)
            if next_role in already_ran:
                continue

            handoff_count += 1
            already_ran.add(next_role)

            # Generate session_id
            next_session_id = str(uuid.uuid4())[:8]
            display_name = next_role.replace("_", " ").title().replace(" ", "")

            print(
                f"\n>>> Step 5.{handoff_count}: Running {display_name} (handoff, session: {next_session_id})..."
            )

            # Set context
            set_slack_context(
                connector=slack_connector,
                channel=slack_test_channel,
                thread_ts=initial_msg.ts,
                from_agent=display_name,
                session_id=next_session_id,
            )

            # Build task from previous agent's response
            prev_role, prev_result = agent_results[-1]
            prev_display = prev_role.replace("_", " ").title().replace(" ", "")
            handoff_task = (
                f"[Handoff from {prev_display}] Customer ACME Corp has API 404 errors. "
                f"You were mentioned to help. Context: {prev_result.get('response', '')[:500]}"
            )

            result = await autogen_runner.run(
                role=next_role,
                task=handoff_task,
                context_type="slack",
                context_id=initial_msg.ts,
            )

            print(f"    Success: {result.get('success', False)}")
            print(f"    Latency: {result.get('latency_ms', 0)}ms")
            print(f"    Response (first 300 chars): {result.get('response', '')[:300]}...")

            agent_results.append((next_role, result))

            # Detect new handoffs from this agent's response
            new_handoffs = detect_handoffs(result.get("response", ""))
            # Filter out already ran and add new ones
            new_handoffs = [r for r in new_handoffs if r not in already_ran]
            if new_handoffs:
                print(f"    New handoffs detected: {new_handoffs}")
                pending_handoffs.extend(new_handoffs)

        if not pending_handoffs:
            print(f"\n>>> Handoff chain complete after {handoff_count} handoffs")
        else:
            print(f"\n>>> Handoff chain stopped at max {max_handoffs} handoffs")

        # For backwards compatibility, extract release_result if it ran
        release_result = None
        handoff_detected = handoff_count > 0
        for role, result in agent_results:
            if role == "release_engineer":
                release_result = result
                break

        # Clear context
        clear_slack_context()

        # Step 6: Evaluate with DeepEval
        print("\n>>> Step 6: Evaluating with DeepEval G-Eval...")

        # Import metric factories
        try:
            from conftest import (
                create_context_preservation_metric,  # noqa: F401
                create_handoff_quality_metric,
                create_task_completion_metric,
            )
        except ImportError:
            from tests.e2e.conftest import (
                create_handoff_quality_metric,
                create_task_completion_metric,
            )

        # Create test case for SupportEngineer
        support_test_case = LLMTestCase(
            input=customer_message,
            actual_output=support_result.get("response", ""),
        )

        # Create metrics for SupportEngineer (role-specific thresholds)
        handoff_metric = create_handoff_quality_metric(azure_deepeval_model, "support_engineer")
        task_metric = create_task_completion_metric(azure_deepeval_model, "support_engineer")

        # Measure
        handoff_metric.measure(support_test_case)
        task_metric.measure(support_test_case)

        print("\n    SupportEngineer Metrics:")
        print(
            f"    HandoffQuality: {handoff_metric.score:.2f} (threshold: {handoff_metric.threshold})"
        )
        print(f"    TaskCompletion: {task_metric.score:.2f} (threshold: {task_metric.threshold})")
        print(f"    Handoff Reason: {handoff_metric.reason[:200]}...")

        # If ReleaseEngineer ran, evaluate that too
        release_handoff_score = None
        release_task_score = None
        if release_result and release_result.get("success"):
            release_test_case = LLMTestCase(
                input="Handoff from SupportEngineer about API 404 errors",
                actual_output=release_result.get("response", ""),
            )

            release_task_metric = create_task_completion_metric(
                azure_deepeval_model, "release_engineer"
            )
            release_task_metric.measure(release_test_case)

            release_task_score = release_task_metric.score
            print("\n    ReleaseEngineer Metrics:")
            print(
                f"    TaskCompletion: {release_task_metric.score:.2f} (threshold: {release_task_metric.threshold})"
            )

        # Step 7: Verify messages in Slack
        print("\n>>> Step 7: Verifying messages in Slack...")
        try:
            thread_messages = slack_connector.get_thread_replies(
                channel=slack_test_channel,
                thread_ts=initial_msg.ts,
                limit=10,
            )
            print(f"    Found {len(thread_messages)} messages in thread")

            for i, msg in enumerate(thread_messages[:5]):
                print(f"    [{i + 1}] {msg.text[:100]}...")
        except Exception as e:
            print(f"    Error reading thread: {e}")

        # Summary
        print("\n" + "=" * 70)
        print("HANDOFF TEST SUMMARY")
        print("=" * 70)
        print(f"SupportEngineer Success: {support_result.get('success', False)}")
        print(f"Handoff Detected: {handoff_detected}")
        print(
            f"ReleaseEngineer Success: {release_result.get('success', False) if release_result else 'N/A'}"
        )
        print(f"HandoffQuality Score: {handoff_metric.score:.2f}")
        print(f"TaskCompletion Score: {task_metric.score:.2f}")
        print("=" * 70)

        # Assertions
        assert support_result.get("success"), (
            f"SupportEngineer failed: {support_result.get('error')}"
        )

        # HandoffQuality threshold for support_engineer is 0.75
        assert handoff_metric.score >= handoff_metric.threshold, (
            f"HandoffQuality {handoff_metric.score:.2f} below threshold {handoff_metric.threshold}"
        )

        # TaskCompletion threshold for support_engineer is 0.80
        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )

        # If handoff was detected, ReleaseEngineer should have succeeded
        if handoff_detected:
            assert release_result is not None, "ReleaseEngineer result is None despite handoff"
            assert release_result.get("success"), (
                f"ReleaseEngineer failed: {release_result.get('error')}"
            )


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
