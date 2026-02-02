"""
E2E Test: GitHub Webhook Routing with /RoleName Mentions

This test validates the GitHub integration's ability to:
1. Handle issue_comment webhooks with /RoleName mentions
2. Handle pull_request_review_comment webhooks with mentions
3. Route newly opened issues based on labels/keywords
4. Execute REAL agents (OpenHands, AutoGen, CrewAI) for tasks
5. Evaluate agent responses using DeepEval G-Eval with Azure GPT-5.2

Uses DeepEval G-Eval metrics with Azure GPT-5.2 as the LLM judge.
Metrics evaluated: TaskCompletion, Professionalism

Usage:
    pytest tests/e2e/test_github_routing.py -v -s
    pytest tests/e2e/test_github_routing.py -v -s --framework=autogen
    pytest tests/e2e/test_github_routing.py -v -s -k "issue_comment"
    pytest tests/e2e/test_github_routing.py -v -s -k "DeepEval"
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
        create_professionalism_metric,
        create_task_completion_metric,
    )
except ImportError:
    try:
        from tests.e2e.conftest import (
            AGENT_THRESHOLDS,
            AzureOpenAIModel,
            create_professionalism_metric,
            create_task_completion_metric,
        )
    except ImportError:
        AGENT_THRESHOLDS = {}
        AzureOpenAIModel = None
        create_professionalism_metric = None
        create_task_completion_metric = None

if TYPE_CHECKING:
    from conftest import RealAgentRunner


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class GitHubWebhookPayload:
    """Simulated GitHub webhook payload."""

    event_type: str  # 'issues', 'issue_comment', 'pull_request_review_comment'
    action: str
    repository: str
    sender: str
    body: str
    title: str = ""
    issue_number: int = 1
    pr_number: int | None = None
    labels: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to GitHub webhook payload format."""
        payload: dict[str, Any] = {
            "action": self.action,
            "repository": {"full_name": self.repository},
            "sender": {"login": self.sender},
        }

        if self.event_type == "issues":
            payload["issue"] = {
                "number": self.issue_number,
                "title": self.title,
                "body": self.body,
                "labels": [{"name": label} for label in (self.labels or [])],
                "user": {"login": self.sender},
            }
        elif self.event_type == "issue_comment":
            payload["issue"] = {"number": self.issue_number, "title": self.title}
            payload["comment"] = {
                "id": 123456,
                "body": self.body,
                "user": {"login": self.sender},
            }
        elif self.event_type == "pull_request_review_comment":
            payload["pull_request"] = {"number": self.pr_number or 1, "title": self.title}
            payload["comment"] = {
                "id": 789012,
                "body": self.body,
                "user": {"login": self.sender},
            }

        return payload


@dataclass
class GitHubRoutingResult:
    """Result of routing a GitHub webhook to a real agent."""

    scenario_name: str
    event_type: str
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


# ==============================================================================
# G-Eval Prompt for GitHub Routing
# ==============================================================================

GITHUB_ROUTING_EVAL_PROMPT = """You are evaluating an AI agent's response to a GitHub webhook event.

SCENARIO: {scenario_name}
DESCRIPTION: {description}
EVENT TYPE: {event_type}
COMMENT/BODY: {body}
EXPECTED ROLE: {expected_role}
DETECTED ROLE: {detected_role}
AGENT FRAMEWORK: {framework}

AGENT RESPONSE:
{response}

Evaluate the agent's response on these criteria (score 0.0 to 1.0):

1. TASK_UNDERSTANDING: Did the agent understand the GitHub context (issue, PR, comment)?
   - 1.0: Fully understood the GitHub context and request
   - 0.5: Partially understood
   - 0.0: Did not understand

2. ACTION_TAKEN: Did the agent take appropriate actions for a GitHub workflow?
   - 1.0: Took correct actions (investigated code, used gh CLI, etc.)
   - 0.5: Took some actions but incomplete
   - 0.0: No meaningful action

3. RESULT_QUALITY: Is the response helpful and appropriate for a GitHub comment?
   - 1.0: Excellent response, well-formatted for GitHub
   - 0.5: Acceptable but could be better formatted
   - 0.0: Poor response

4. GITHUB_INTEGRATION: Did the agent's response show awareness of GitHub features?
   - 1.0: Used/referenced issues, PRs, commits, labels appropriately
   - 0.5: Limited GitHub awareness
   - 0.0: No GitHub-specific elements

5. COMPLETENESS: Is the response complete for a GitHub comment reply?
   - 1.0: Complete, ready to post as comment
   - 0.5: Partial, needs some additions
   - 0.0: Incomplete

Return ONLY valid JSON:
{{
    "task_understanding": 0.0,
    "action_taken": 0.0,
    "result_quality": 0.0,
    "github_integration": 0.0,
    "completeness": 0.0,
    "overall_score": 0.0,
    "feedback": "Brief explanation of scores"
}}"""


# ==============================================================================
# Router Helper Functions
# ==============================================================================


def parse_role_mention(body: str) -> AgentRole | None:
    """Parse /RoleName mention from body text."""
    pattern = r"/([A-Za-z]+)"
    matches = re.findall(pattern, body)

    for match in matches:
        normalized = match.lower()
        if normalized in ROLE_MENTION_MAP:
            return ROLE_MENTION_MAP[normalized]

    return None


def route_by_labels(labels: list[str]) -> AgentRole | None:
    """Route based on issue labels."""
    labels_lower = [label.lower() for label in labels]

    if "bug" in labels_lower or any("bug" in label for label in labels_lower):
        return "software_engineer"
    if "feature" in labels_lower or "enhancement" in labels_lower:
        return "product_manager"
    if "infrastructure" in labels_lower or "devops" in labels_lower:
        return "release_engineer"
    if "support" in labels_lower or "customer" in labels_lower:
        return "support_engineer"

    return None


def route_by_title(title: str) -> AgentRole | None:
    """Route based on issue title prefix."""
    title_upper = title.upper()

    if title_upper.startswith("[BUG]"):
        return "software_engineer"
    if title_upper.startswith("[FEATURE]"):
        return "product_manager"
    if title_upper.startswith("[DEPLOY]") or title_upper.startswith("[INFRA]"):
        return "release_engineer"
    if title_upper.startswith("[SUPPORT]"):
        return "support_engineer"

    return None


def detect_role_from_payload(payload: GitHubWebhookPayload) -> AgentRole | None:
    """Detect the appropriate agent role from a GitHub webhook payload."""
    # First try to parse explicit mention from body
    role = parse_role_mention(payload.body)

    # For new issues, also check labels and title
    if role is None and payload.event_type == "issues" and payload.action == "opened":
        role = route_by_labels(payload.labels or [])
        if role is None:
            role = route_by_title(payload.title)

    return role


# ==============================================================================
# Test Classes: Unit Tests for Parsing
# ==============================================================================


class TestGitHubMentionParsing:
    """Test /RoleName mention parsing from GitHub content (unit tests)."""

    def test_parse_mention_in_comment(self):
        """Test parsing mention from comment body."""
        body = "Hey /SoftwareEngineer can you look at this?"
        role = parse_role_mention(body)
        assert role == "software_engineer"

    def test_parse_mention_multiline(self):
        """Test parsing mention from multiline body."""
        body = """
        This is a bug report.

        /ReleaseEngineer please deploy the fix when ready.

        Thanks!
        """
        role = parse_role_mention(body)
        assert role == "release_engineer"

    def test_parse_no_mention(self):
        """Test body with no mention returns None."""
        body = "Just a regular comment without any mentions."
        role = parse_role_mention(body)
        assert role is None

    def test_parse_short_forms(self):
        """Test short form mentions."""
        assert parse_role_mention("/SWE fix this") == "software_engineer"
        assert parse_role_mention("/PM prioritize") == "product_manager"


class TestGitHubLabelRouting:
    """Test routing based on issue labels (unit tests)."""

    def test_bug_label(self):
        """Test 'bug' label routes to software_engineer."""
        role = route_by_labels(["bug", "priority:high"])
        assert role == "software_engineer"

    def test_feature_label(self):
        """Test 'feature' label routes to product_manager."""
        role = route_by_labels(["feature", "enhancement"])
        assert role == "product_manager"

    def test_infrastructure_label(self):
        """Test 'infrastructure' label routes to release_engineer."""
        role = route_by_labels(["infrastructure"])
        assert role == "release_engineer"

    def test_support_label(self):
        """Test 'support' label routes to support_engineer."""
        role = route_by_labels(["customer", "support"])
        assert role == "support_engineer"


class TestGitHubTitleRouting:
    """Test routing based on issue title prefix (unit tests)."""

    def test_bug_prefix(self):
        """Test [BUG] prefix routes to software_engineer."""
        role = route_by_title("[BUG] Login page not loading")
        assert role == "software_engineer"

    def test_feature_prefix(self):
        """Test [FEATURE] prefix routes to product_manager."""
        role = route_by_title("[FEATURE] Add dark mode support")
        assert role == "product_manager"

    def test_deploy_prefix(self):
        """Test [DEPLOY] prefix routes to release_engineer."""
        role = route_by_title("[DEPLOY] Release v2.0 to production")
        assert role == "release_engineer"

    def test_no_prefix(self):
        """Test no prefix returns None."""
        role = route_by_title("Regular issue title")
        assert role is None


# ==============================================================================
# NOTE: Legacy test classes (TestOpenHandsGitHubRouting, TestGitHubRoutingAllScenarios,
# TestGitHubNewIssueRouting, TestCrossFrameworkGitHubComparison) have been removed.
# They used the deprecated GPT52Evaluator. Use DeepEval test classes below instead.
# ==============================================================================


# ==============================================================================
# DeepEval G-Eval Tests
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestGitHubRoutingWithDeepEval:
    """GitHub routing tests using DeepEval G-Eval metrics.

    Uses the proper DeepEval library with GEval as specified in requirements.md.
    Metrics: TaskCompletion, Professionalism
    Thresholds are per-agent as defined in AGENT_THRESHOLDS.
    """

    @pytest.mark.asyncio
    async def test_issue_comment_with_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        github_routing_scenarios,
    ):
        """Test GitHub issue comment using DeepEval G-Eval metrics."""
        scenario = next(s for s in github_routing_scenarios if s["event"] == "issue_comment")
        role = scenario["expected_role"]

        print(f"\n>>> Running DeepEval test for {role}...")
        print(f"    Threshold: {AGENT_THRESHOLDS.get(role, {}).get('task_completion', 0.7)}")

        task = f"""GitHub issue comment:

{scenario["body"]}

Please respond appropriately as {role}.
"""

        # Run the agent
        result = await openhands_runner.run(
            role=role,
            task=task,
            context_type="github",
            context_id="deepeval-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        # Create DeepEval test case
        test_case = LLMTestCase(
            input=task,
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

        # Assert using DeepEval thresholds
        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )

    @pytest.mark.asyncio
    async def test_pr_review_with_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        github_routing_scenarios,
    ):
        """Test PR review comment using DeepEval G-Eval metrics."""
        scenario = next(
            (s for s in github_routing_scenarios if s["event"] == "pull_request_review_comment"),
            github_routing_scenarios[0],  # fallback
        )
        role = scenario["expected_role"]

        print(f"\n>>> Running DeepEval test for PR review (role: {role})...")

        task = f"""GitHub PR review comment:

{scenario["body"]}

Please respond appropriately as {role}.
"""

        result = await openhands_runner.run(
            role=role,
            task=task,
            context_type="github",
            context_id="deepeval-pr-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        test_case = LLMTestCase(
            input=task,
            actual_output=result.get("response", ""),
        )

        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        prof_metric = create_professionalism_metric(azure_deepeval_model, role)

        task_metric.measure(test_case)
        prof_metric.measure(test_case)

        print(f"    TaskCompletion: {task_metric.score:.2f}")
        print(f"    Professionalism: {prof_metric.score:.2f}")

        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )

    @pytest.mark.asyncio
    async def test_new_issue_routing_with_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        github_routing_scenarios,
    ):
        """Test new issue (opened) routing using DeepEval."""
        scenario = next(
            (s for s in github_routing_scenarios if s["event"] == "issues"),
            github_routing_scenarios[0],
        )
        role = scenario["expected_role"]

        print(f"\n>>> Running DeepEval test for new issue (role: {role})...")

        task = f"""New GitHub issue opened:

Title: {scenario.get("title", "Issue")}
Body: {scenario["body"]}

Please triage and respond appropriately as {role}.
"""

        result = await openhands_runner.run(
            role=role,
            task=task,
            context_type="github",
            context_id="deepeval-issue-test",
        )

        if not result.get("success"):
            pytest.skip(f"Agent failed: {result.get('error')}")

        test_case = LLMTestCase(
            input=task,
            actual_output=result.get("response", ""),
        )

        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        task_metric.measure(test_case)

        print(f"    TaskCompletion: {task_metric.score:.2f}")
        print(f"    Reason: {task_metric.reason}")

        assert task_metric.score >= task_metric.threshold


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestGitHubRoutingDeepEvalAllScenarios:
    """Run all GitHub scenarios with DeepEval and summarize results."""

    @pytest.mark.asyncio
    async def test_all_github_scenarios_deepeval(
        self,
        openhands_runner: RealAgentRunner,
        azure_deepeval_model: AzureOpenAIModel,
        github_routing_scenarios,
    ):
        """Run all GitHub routing scenarios with DeepEval G-Eval metrics."""
        results = []

        print("\n" + "=" * 70)
        print("GITHUB ROUTING E2E TEST - DEEPEVAL G-EVAL")
        print("=" * 70)

        for scenario in github_routing_scenarios:
            role = scenario["expected_role"]
            print(f"\n>>> {scenario['name']} (role: {role})")

            task = f"""GitHub {scenario["event"]}:

{scenario["body"]}

Please respond appropriately as {role}.
"""

            # Run agent
            agent_result = await openhands_runner.run(
                role=role,
                task=task,
                context_type="github",
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
                input=task,
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
                    "event": scenario["event"],
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

            # Group by event type
            print("\nBy Event Type:")
            for event_type in {r.get("event", "unknown") for r in successful}:
                event_results = [r for r in successful if r.get("event") == event_type]
                event_passed = sum(1 for r in event_results if r.get("passed"))
                print(f"  {event_type}: {event_passed}/{len(event_results)} passed")

        # At least half should pass
        assert len(passed) >= len(successful) // 2, (
            f"Only {len(passed)}/{len(successful)} passed DeepEval thresholds"
        )


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
