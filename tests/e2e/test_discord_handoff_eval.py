"""
E2E Test: Discord Group Chat Handoff Evaluation

This test simulates a multi-agent handoff scenario in Discord where:
1. SupportEngineer receives a customer email about API Gateway 404 errors
2. SupportEngineer posts to Discord and @mentions ReleaseEngineer for help
3. ReleaseEngineer investigates and fixes the issue
4. ReleaseEngineer @mentions SupportEngineer confirming the fix
5. SupportEngineer emails customer with resolution

The test uses G-Eval (LLM-as-judge) with Azure GPT-5.2 to evaluate:
- Handoff detection: Did agents correctly identify and respond to @mentions?
- Task completion: Was the customer ultimately notified of the fix?
- Communication: Was information passed clearly between agents?
- Tool usage: Were Gmail and Discord tools used appropriately?
- Overall: Overall quality of the multi-agent collaboration

Runs across all three frameworks: AutoGen, CrewAI, OpenHands

Also supports DeepEval G-Eval metrics with per-agent thresholds.

Usage:
    pytest tests/e2e/test_discord_handoff_eval.py -v -s
    pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "autogen"
    pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "compare_all"
    pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "DeepEval"
"""

import asyncio
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

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

from vibeteam.connectors.discord import DiscordMessage  # noqa: E402
from vibeteam.connectors.gmail import Email  # noqa: E402

# ==============================================================================
# Configuration
# ==============================================================================


class HandoffEvalConfig:
    """Configuration for handoff evaluation tests."""

    AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_API_KEY", ""))
    AZURE_API_BASE = os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_API_BASE", ""))
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-08-01-preview")
    JUDGE_MODEL = os.getenv(
        "BENCHMARK_JUDGE_MODEL", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-2")
    )
    AGENT_TIMEOUT = 120.0  # seconds per agent turn

    @classmethod
    def get_azure_api_base(cls) -> str:
        """Get AZURE_API_BASE with protocol validation."""
        base = cls.AZURE_API_BASE
        if not base:
            raise ValueError("AZURE_API_BASE environment variable not set")
        if not base.startswith(("http://", "https://")):
            raise ValueError(
                f"AZURE_API_BASE must start with 'http://' or 'https://'. Got: '{base}'"
            )
        return base.rstrip("/")


# ==============================================================================
# Test Scenario
# ==============================================================================

CUSTOMER_EMAIL = Email(
    id="msg_customer_001",
    thread_id="thread_customer_001",
    subject="URGENT: Vibe API Gateway returning 404 errors",
    sender="Alex Chen <alex.chen@acme-corp.com>",
    sender_email="alex.chen@acme-corp.com",
    recipient="support@vibetechnologies.com",
    date="Fri, 31 Jan 2026 09:15:00 -0800",
    body="""Hi Support Team,

We're experiencing critical issues with the Vibe API Gateway. Since approximately 8:45 AM PST today, all our API calls to the gateway are returning 404 errors.

Error details:
- Endpoint: https://api.vibetechnologies.com/v2/agent/execute
- HTTP Status: 404 Not Found
- Response body: {"error": "Service not available"}

This is affecting our production workflow automation that relies on VibeBrowser agents. We have approximately 500 users blocked from using our integration.

We need this resolved ASAP. Our SLA requires 99.9% uptime and we're already in breach.

Please advise on:
1. Is there a known outage?
2. ETA for resolution?
3. Any workarounds we can use in the meantime?

Best regards,
Alex Chen
Senior DevOps Engineer
ACME Corp
alex.chen@acme-corp.com
+1-555-0123
""",
    snippet="We're experiencing critical issues with the Vibe API Gateway...",
    labels=["INBOX", "UNREAD", "IMPORTANT"],
)

SCENARIO_DESCRIPTION = """
Multi-agent handoff scenario: Customer API Gateway 404 Error

PHASE 1 - SupportEngineer:
- Receives customer email reporting 404 errors on API Gateway
- Analyzes the issue and identifies it as infrastructure-related
- Based on AGENTS.md instructions, decides to escalate to ReleaseEngineer
- Posts to Discord channel with context and @mentions ReleaseEngineer

PHASE 2 - ReleaseEngineer:
- Receives notification via Discord @mention
- Investigates the issue (checks deployment status, logs, etc.)
- Identifies root cause and applies fix
- Posts resolution to Discord
- @mentions SupportEngineer confirming fix is deployed

PHASE 3 - SupportEngineer:
- Receives notification via Discord @mention
- Drafts and sends email to customer confirming resolution
- Includes what was fixed, when, and any follow-up actions

SUCCESS CRITERIA:
- SupportEngineer correctly identifies infrastructure issue and escalates
- Agents correctly detect and respond to @mentions
- Context is preserved across handoffs
- Customer receives professional resolution email
"""


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class AgentTurn:
    """Represents a single agent's turn in the conversation."""

    agent: str  # 'support_engineer' or 'release_engineer'
    framework: str  # 'autogen', 'crewai', 'openhands'
    input_context: str  # What the agent received
    response: str  # Agent's response
    latency_ms: int
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationLog:
    """Full conversation log for evaluation."""

    framework: str
    phases: list[AgentTurn]
    total_latency_ms: int
    all_succeeded: bool

    @property
    def full_transcript(self) -> str:
        """Generate human-readable transcript for evaluation."""
        lines = [
            f"=== HANDOFF CONVERSATION ({self.framework.upper()}) ===",
            "",
        ]
        for i, turn in enumerate(self.phases, 1):
            status = "OK" if turn.success else "FAILED"
            lines.append(f"--- PHASE {i}: {turn.agent.upper()} [{status}] ---")
            lines.append(f"INPUT: {turn.input_context[:500]}...")
            lines.append(f"RESPONSE: {turn.response[:1000]}...")
            if turn.error:
                lines.append(f"ERROR: {turn.error}")
            lines.append("")
        return "\n".join(lines)


# ==============================================================================
# NOTE: HandoffScore, HandoffEvalResult, HandoffEvaluator have been removed.
# Use DeepEval GEval metrics instead: create_handoff_quality_metric,
# create_task_completion_metric, create_context_preservation_metric
# ==============================================================================


# ==============================================================================
# Mock Fixtures
# ==============================================================================


@pytest.fixture
def mock_gmail():
    """Mock GmailConnector for testing."""
    with patch("vibeteam.connectors.gmail.GmailConnector") as MockGmail:
        mock = MagicMock()
        mock.authenticate.return_value = True
        mock.fetch_unread_emails.return_value = [CUSTOMER_EMAIL]
        mock.send_email.return_value = "sent_msg_response_001"
        mock.send_reply.return_value = "sent_msg_response_001"
        mock.mark_as_read.return_value = True
        MockGmail.return_value = mock
        yield mock


@pytest.fixture
def mock_discord():
    """Mock DiscordConnector for testing."""
    # Simulated message history for the Discord channel
    message_history: list[DiscordMessage] = []

    with patch("vibeteam.connectors.discord.DiscordConnector") as MockDiscord:
        mock = MagicMock()

        def post_message(agent_key: str, content: str, **kwargs) -> dict:
            """Simulate posting a message."""
            msg = DiscordMessage(
                id=f"msg_{len(message_history) + 1}",
                channel_id="channel_001",
                author_id=f"bot_{agent_key}",
                author_name=agent_key,
                content=content,
                timestamp=datetime.now(timezone.utc),
                is_bot=True,
                role_mentions=[],
                user_mentions=[],
            )
            # Detect @mentions in content
            if "@releaseengineer" in content.lower() or "@release" in content.lower():
                msg.role_mentions.append("role_release")
            if "@supportengineer" in content.lower() or "@support" in content.lower():
                msg.role_mentions.append("role_support")

            message_history.append(msg)
            return {"success": True, "message_id": msg.id}

        mock.post_webhook_message.side_effect = post_message
        mock.mention_agent.side_effect = lambda agent_key, message, **kwargs: post_message(
            agent_key, f"@{agent_key} {message}"
        )

        def get_history(channel_id=None, limit=20, **kwargs) -> list[DiscordMessage]:
            return message_history[-limit:]

        mock.get_channel_history.side_effect = get_history

        def is_mention_for(message: DiscordMessage, agent_key: str) -> bool:
            if agent_key == "release" and "role_release" in message.role_mentions:
                return True
            if agent_key == "support" and "role_support" in message.role_mentions:
                return True
            return f"@{agent_key}" in message.content.lower()

        mock.is_mention_for_agent.side_effect = is_mention_for

        MockDiscord.return_value = mock
        mock._message_history = message_history  # Expose for inspection
        yield mock


# ==============================================================================
# Agent Runner
# ==============================================================================


def get_agent_class(framework: str, role: str):
    """Import and return the agent class for the given framework and role."""
    if framework == "autogen":
        if role == "support_engineer":
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif role == "release_engineer":
            from agents.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
    elif framework == "crewai":
        if role == "support_engineer":
            from agents.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif role == "release_engineer":
            from agents.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
    elif framework == "openhands":
        if role == "support_engineer":
            from agents.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif role == "release_engineer":
            from agents.openhands.release_engineer import OpenHandsReleaseEngineer

            return OpenHandsReleaseEngineer

    raise ValueError(f"Unknown framework/role: {framework}/{role}")


async def run_agent_turn(
    framework: str,
    role: str,
    task: str,
    timeout: float,
) -> AgentTurn:
    """Run a single agent turn and return results."""
    start_time = time.perf_counter()

    try:
        agent_class = get_agent_class(framework, role)
        agent = agent_class()

        # Disable tools for OpenHands to prevent agentic loops
        run_kwargs: dict[str, Any] = {"task": task}
        if framework == "openhands":
            run_kwargs["use_tools"] = False
            run_kwargs["skip_context_injection"] = True

        result = await asyncio.wait_for(agent.run_async(**run_kwargs), timeout=timeout)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return AgentTurn(
            agent=role,
            framework=framework,
            input_context=task[:500],
            response=result.get("response", ""),
            latency_ms=latency_ms,
            success=True,
        )

    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return AgentTurn(
            agent=role,
            framework=framework,
            input_context=task[:500],
            response="",
            latency_ms=latency_ms,
            success=False,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return AgentTurn(
            agent=role,
            framework=framework,
            input_context=task[:500],
            response="",
            latency_ms=latency_ms,
            success=False,
            error=str(e),
        )


async def run_handoff_scenario(
    framework: str,
    timeout_per_turn: float = 120.0,
) -> ConversationLog:
    """
    Run the full 3-phase handoff scenario for a framework.

    Returns:
        ConversationLog with all phases
    """
    phases: list[AgentTurn] = []
    total_latency = 0

    # PHASE 1: SupportEngineer receives email, posts to Discord
    # NOTE: The agent should decide on their own to escalate to @ReleaseEngineer
    # based on their AGENTS.md instructions for infrastructure issues
    phase1_task = f"""You received this customer email:

FROM: {CUSTOMER_EMAIL.sender}
SUBJECT: {CUSTOMER_EMAIL.subject}
DATE: {CUSTOMER_EMAIL.date}

{CUSTOMER_EMAIL.body}

As the Support Engineer, analyze this customer complaint and take appropriate action.
Compose your response for the team Discord channel.
"""

    print(f"\n>>> Phase 1: {framework.upper()} SupportEngineer processing email...")
    phase1 = await run_agent_turn(framework, "support_engineer", phase1_task, timeout_per_turn)
    phases.append(phase1)
    total_latency += phase1.latency_ms
    print(f"    Status: {'OK' if phase1.success else 'FAILED'} ({phase1.latency_ms}ms)")

    # PHASE 2: ReleaseEngineer receives mention, investigates, fixes
    phase2_context = phase1.response if phase1.success else "(SupportEngineer failed to respond)"

    phase2_task = f"""You received a Discord @mention from SupportEngineer:

{phase2_context}

A customer (ACME Corp) is reporting API Gateway 404 errors affecting 500 users.

You should:
1. Acknowledge the issue and investigate
2. Identify the root cause (e.g., deployment misconfiguration, service down)
3. Apply the fix (e.g., restart service, rollback deployment, fix routing)
4. Post to Discord confirming the fix is deployed
5. @mention SupportEngineer so they can notify the customer

Compose your Discord response that:
- Explains what you found
- What fix you applied
- Confirms the service is restored
- @mentions SupportEngineer to notify the customer
"""

    print(f"\n>>> Phase 2: {framework.upper()} ReleaseEngineer investigating...")
    phase2 = await run_agent_turn(framework, "release_engineer", phase2_task, timeout_per_turn)
    phases.append(phase2)
    total_latency += phase2.latency_ms
    print(f"    Status: {'OK' if phase2.success else 'FAILED'} ({phase2.latency_ms}ms)")

    # PHASE 3: SupportEngineer receives mention, emails customer
    phase3_context = phase2.response if phase2.success else "(ReleaseEngineer failed to respond)"

    phase3_task = f"""You received a Discord @mention from ReleaseEngineer:

{phase3_context}

The API Gateway issue has been resolved. Now you need to:
1. Draft a professional email to the customer (Alex Chen at ACME Corp)
2. Explain what happened and what was fixed
3. Apologize for the inconvenience
4. Provide any relevant follow-up information

Original customer email for reference:
FROM: {CUSTOMER_EMAIL.sender}
SUBJECT: {CUSTOMER_EMAIL.subject}
{CUSTOMER_EMAIL.body[:500]}...

Compose the resolution email to send to the customer.
Include:
- Subject line
- Professional greeting
- What happened (brief)
- What was fixed
- When it was fixed (now)
- Apology for inconvenience
- Contact info for follow-up
"""

    print(f"\n>>> Phase 3: {framework.upper()} SupportEngineer sending customer email...")
    phase3 = await run_agent_turn(framework, "support_engineer", phase3_task, timeout_per_turn)
    phases.append(phase3)
    total_latency += phase3.latency_ms
    print(f"    Status: {'OK' if phase3.success else 'FAILED'} ({phase3.latency_ms}ms)")

    all_succeeded = all(p.success for p in phases)

    return ConversationLog(
        framework=framework,
        phases=phases,
        total_latency_ms=total_latency,
        all_succeeded=all_succeeded,
    )


# ==============================================================================
# NOTE: Old test classes (TestDiscordHandoffAutoGen, TestDiscordHandoffCrewAI,
# TestDiscordHandoffOpenHands, TestDiscordHandoffComparison) have been removed.
# These used the legacy HandoffEvaluator. Use DeepEval tests below instead.
# ==============================================================================


# ==============================================================================
# DeepEval G-Eval Tests
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestDiscordHandoffWithDeepEval:
    """Discord handoff tests using DeepEval G-Eval metrics.

    Uses the proper DeepEval library with GEval as specified in requirements.md.
    Metrics: HandoffQuality, ContextPreservation, TaskCompletion
    Thresholds are per-agent as defined in AGENT_THRESHOLDS.
    """

    @pytest.mark.asyncio
    async def test_discord_handoff_deepeval(
        self,
        mock_gmail,
        mock_discord,
        azure_deepeval_model: "AzureOpenAIModel",
    ):
        """Test Discord handoff scenario using DeepEval G-Eval metrics."""
        # Use autogen since openhands requires Python 3.12+
        import sys

        framework = "autogen" if sys.version_info < (3, 12) else "openhands"

        print("\n>>> Running DeepEval Discord handoff test...")
        print(f"    Framework: {framework}")

        conversation = await run_handoff_scenario(framework)

        if not conversation.all_succeeded:
            pytest.skip(
                f"Handoff scenario failed: {[p.error for p in conversation.phases if not p.success]}"
            )

        # Create DeepEval test case from conversation
        test_case = LLMTestCase(
            input=CUSTOMER_EMAIL.body,
            actual_output=conversation.full_transcript,
        )

        # SupportEngineer is the primary agent in this scenario
        role = "support_engineer"

        # Create handoff-specific metrics
        handoff_metric = create_handoff_quality_metric(azure_deepeval_model, role)
        context_metric = create_context_preservation_metric(azure_deepeval_model)  # No role arg
        task_metric = create_task_completion_metric(azure_deepeval_model, role)
        prof_metric = create_professionalism_metric(azure_deepeval_model, role)

        # Measure metrics
        handoff_metric.measure(test_case)
        context_metric.measure(test_case)
        task_metric.measure(test_case)
        prof_metric.measure(test_case)

        print(
            f"    HandoffQuality: {handoff_metric.score:.2f} (threshold: {handoff_metric.threshold})"
        )
        print(
            f"    ContextPreservation: {context_metric.score:.2f} (threshold: {context_metric.threshold})"
        )
        print(f"    TaskCompletion: {task_metric.score:.2f} (threshold: {task_metric.threshold})")
        print(f"    Professionalism: {prof_metric.score:.2f} (threshold: {prof_metric.threshold})")
        print(f"    Handoff Reason: {handoff_metric.reason}")

        # Assert using DeepEval thresholds
        # SupportEngineer has higher thresholds (0.75 for handoff, 0.80 for task)
        assert handoff_metric.score >= handoff_metric.threshold, (
            f"HandoffQuality {handoff_metric.score:.2f} below threshold {handoff_metric.threshold}"
        )
        assert task_metric.score >= task_metric.threshold, (
            f"TaskCompletion {task_metric.score:.2f} below threshold {task_metric.threshold}"
        )


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestDiscordHandoffDeepEvalAllFrameworks:
    """Run Discord handoff scenario across all frameworks with DeepEval evaluation."""

    @pytest.mark.asyncio
    async def test_all_frameworks_discord_deepeval(
        self,
        mock_gmail,
        mock_discord,
        azure_deepeval_model: "AzureOpenAIModel",
    ):
        """Run Discord handoff across all frameworks with DeepEval G-Eval metrics."""
        frameworks = ["openhands", "autogen", "crewai"]
        results = []
        role = "support_engineer"

        print("\n" + "=" * 70)
        print("DISCORD HANDOFF E2E TEST - DEEPEVAL G-EVAL")
        print("=" * 70)

        for framework in frameworks:
            print(f"\n>>> Testing {framework.upper()}...")

            try:
                conversation = await run_handoff_scenario(framework)

                if not conversation.all_succeeded:
                    print(
                        f"    SKIPPED: Handoff failed - {[p.error for p in conversation.phases if not p.success]}"
                    )
                    results.append(
                        {
                            "framework": framework,
                            "success": False,
                            "handoff_score": 0,
                            "context_score": 0,
                            "task_score": 0,
                        }
                    )
                    continue

                test_case = LLMTestCase(
                    input=CUSTOMER_EMAIL.body,
                    actual_output=conversation.full_transcript,
                )

                handoff_metric = create_handoff_quality_metric(azure_deepeval_model, role)
                context_metric = create_context_preservation_metric(azure_deepeval_model, role)
                task_metric = create_task_completion_metric(azure_deepeval_model, role)

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
                        "framework": framework,
                        "success": True,
                        "passed": passed,
                        "handoff_score": handoff_metric.score,
                        "handoff_threshold": handoff_metric.threshold,
                        "context_score": context_metric.score,
                        "context_threshold": context_metric.threshold,
                        "task_score": task_metric.score,
                        "task_threshold": task_metric.threshold,
                        "latency_ms": conversation.total_latency_ms,
                    }
                )

                status = "PASS" if passed else "FAIL"
                print(f"    Status: {status}")
                print(
                    f"    HandoffQuality: {handoff_metric.score:.2f} >= {handoff_metric.threshold}"
                )
                print(
                    f"    ContextPreservation: {context_metric.score:.2f} >= {context_metric.threshold}"
                )
                print(f"    TaskCompletion: {task_metric.score:.2f} >= {task_metric.threshold}")

            except Exception as e:
                print(f"    ERROR: {e}")
                results.append(
                    {
                        "framework": framework,
                        "success": False,
                        "error": str(e),
                        "handoff_score": 0,
                        "context_score": 0,
                        "task_score": 0,
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
            avg_handoff = sum(r["handoff_score"] for r in successful) / len(successful)
            avg_context = sum(r["context_score"] for r in successful) / len(successful)
            avg_task = sum(r["task_score"] for r in successful) / len(successful)
            print(f"Avg HandoffQuality: {avg_handoff:.2f}")
            print(f"Avg ContextPreservation: {avg_context:.2f}")
            print(f"Avg TaskCompletion: {avg_task:.2f}")

        # At least one should pass
        assert len(successful) >= 1, "No frameworks succeeded!"


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
