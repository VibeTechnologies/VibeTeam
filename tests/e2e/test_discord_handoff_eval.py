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

Usage:
    pytest tests/e2e/test_discord_handoff_eval.py -v -s
    pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "autogen"
    pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "compare_all"
"""

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

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


@dataclass
class HandoffScore:
    """Score for a single evaluation criterion."""

    criterion: str
    score: int  # 0-5
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HandoffEvalResult:
    """Complete evaluation result for a framework."""

    framework: str
    scores: dict[str, HandoffScore]  # criterion -> score
    total_score: int
    max_score: int
    reasoning: str
    judge_model: str
    evaluation_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "total_score": self.total_score,
            "max_score": self.max_score,
            "reasoning": self.reasoning,
            "judge_model": self.judge_model,
            "evaluation_time_ms": self.evaluation_time_ms,
        }


# ==============================================================================
# G-Eval Evaluator for Handoffs
# ==============================================================================


class HandoffEvaluator:
    """
    G-Eval evaluator for multi-agent handoff scenarios.

    Uses LLM-as-judge to score conversations on multiple criteria.
    """

    EVAL_PROMPT = """You are an expert evaluator assessing multi-agent AI collaboration in a customer support handoff scenario.

SCENARIO:
A customer (ACME Corp) reported that the Vibe API Gateway is returning 404 errors.
The expected workflow was:
1. SupportEngineer reads the customer email and identifies it as an infrastructure issue
2. SupportEngineer autonomously decides to @mention ReleaseEngineer based on their responsibilities
3. ReleaseEngineer investigates, fixes, and @mentions SupportEngineer when done
4. SupportEngineer sends resolution email to customer

IMPORTANT: The SupportEngineer was NOT explicitly told to contact ReleaseEngineer.
They should decide this on their own based on understanding that API/infrastructure
issues require ReleaseEngineer's expertise.

CUSTOMER EMAIL:
{customer_email}

AGENT CONVERSATION:
{conversation}

Evaluate the conversation on these criteria (score each 0-5):

1. AUTONOMOUS_ESCALATION: Did SupportEngineer correctly identify this as an infrastructure issue and autonomously escalate to ReleaseEngineer?
   - 0: Failed to escalate or escalated to wrong team member
   - 3: Escalated but with unclear reasoning or delayed decision
   - 5: Promptly and correctly identified infrastructure issue and escalated to ReleaseEngineer

2. HANDOFF_DETECTION: Did agents correctly identify and respond to @mentions?
   - 0: Failed to detect mentions or ignored them
   - 3: Detected mentions but response was delayed or incomplete
   - 5: Promptly detected and responded to all mentions appropriately

3. TASK_COMPLETION: Was the customer ultimately notified of the fix?
   - 0: Customer was never contacted
   - 3: Customer was contacted but information was incomplete
   - 5: Customer received comprehensive resolution email with all details

4. COMMUNICATION: Was information passed clearly between agents?
   - 0: No meaningful communication between agents
   - 3: Basic information shared but missing important context
   - 5: Clear, comprehensive context transfer with all relevant details

5. OVERALL: Overall quality of the multi-agent collaboration
   - 0: Complete failure
   - 3: Acceptable but with notable issues
   - 5: Excellent collaboration, exceeded expectations

Return ONLY valid JSON in this exact format:
{{
    "autonomous_escalation": {{"score": 0, "feedback": "explanation"}},
    "handoff_detection": {{"score": 0, "feedback": "explanation"}},
    "task_completion": {{"score": 0, "feedback": "explanation"}},
    "communication": {{"score": 0, "feedback": "explanation"}},
    "overall": {{"score": 0, "feedback": "explanation"}},
    "total_score": 0,
    "reasoning": "One paragraph summary of the evaluation"
}}"""

    def __init__(self, config: HandoffEvalConfig | None = None):
        self.config = config or HandoffEvalConfig()

    async def evaluate(
        self,
        framework: str,
        conversation: ConversationLog,
    ) -> HandoffEvalResult:
        """
        Evaluate a handoff conversation using LLM-as-judge.

        Args:
            framework: The framework being evaluated
            conversation: The full conversation log

        Returns:
            HandoffEvalResult with scores for each criterion
        """
        start_time = time.perf_counter()

        prompt = self.EVAL_PROMPT.format(
            customer_email=CUSTOMER_EMAIL.body[:1500],
            conversation=conversation.full_transcript[:4000],
        )

        try:
            result_json = await self._call_llm(prompt)
            result = self._parse_result(framework, result_json)
            result.evaluation_time_ms = int((time.perf_counter() - start_time) * 1000)
            return result
        except Exception as e:
            # Return error result
            error_score = HandoffScore(criterion="error", score=0, feedback=str(e))
            return HandoffEvalResult(
                framework=framework,
                scores={"error": error_score},
                total_score=0,
                max_score=25,
                reasoning=f"Evaluation failed: {e}",
                judge_model=self.config.JUDGE_MODEL,
                evaluation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    async def _call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI for evaluation."""
        api_base = self.config.get_azure_api_base()
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{api_base}/openai/deployments/{self.config.JUDGE_MODEL}/chat/completions",
                headers={
                    "api-key": self.config.AZURE_API_KEY,
                    "Content-Type": "application/json",
                },
                params={"api-version": self.config.AZURE_API_VERSION},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_completion_tokens": 1000,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_result(self, framework: str, json_str: str) -> HandoffEvalResult:
        """Parse JSON result from LLM response."""
        # Extract JSON from potential markdown code blocks
        json_match = re.search(r"\{[\s\S]*\}", json_str)
        if not json_match:
            raise ValueError("No JSON found in LLM response")

        data = json.loads(json_match.group())

        criteria = [
            "autonomous_escalation",
            "handoff_detection",
            "task_completion",
            "communication",
            "overall",
        ]

        scores = {}
        for criterion in criteria:
            criterion_data = data.get(criterion, {})
            scores[criterion] = HandoffScore(
                criterion=criterion,
                score=int(criterion_data.get("score", 0)),
                feedback=str(criterion_data.get("feedback", "No feedback")),
            )

        total = sum(s.score for s in scores.values())

        return HandoffEvalResult(
            framework=framework,
            scores=scores,
            total_score=total,
            max_score=25,  # 5 criteria * 5 max score
            reasoning=str(data.get("reasoning", "No reasoning provided")),
            judge_model=self.config.JUDGE_MODEL,
        )


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
# Individual Framework Tests
# ==============================================================================


class TestDiscordHandoffAutoGen:
    """Test AutoGen agents in Discord handoff scenario."""

    @pytest.mark.asyncio
    async def test_autogen_handoff_scenario(self, mock_gmail, mock_discord):
        """Test AutoGen agents can complete the handoff scenario."""
        framework = "autogen"

        print(f"\n{'=' * 70}")
        print(f"DISCORD HANDOFF TEST: {framework.upper()}")
        print(f"{'=' * 70}")
        print(f"\nScenario: {SCENARIO_DESCRIPTION[:200]}...")

        conversation = await run_handoff_scenario(framework)

        # Print transcript
        print(f"\n{'=' * 70}")
        print("CONVERSATION TRANSCRIPT")
        print(f"{'=' * 70}")
        print(conversation.full_transcript)

        # Evaluate
        print(f"\n{'=' * 70}")
        print("G-EVAL EVALUATION")
        print(f"{'=' * 70}")

        evaluator = HandoffEvaluator()
        result = await evaluator.evaluate(framework, conversation)

        print(f"\nJudge: {result.judge_model}")
        print(f"Evaluation Time: {result.evaluation_time_ms}ms")
        print(f"\nScores (out of 5):")
        for criterion, score in result.scores.items():
            print(f"  {criterion}: {score.score}/5 - {score.feedback}")

        print(f"\nTotal: {result.total_score}/{result.max_score}")
        print(f"Reasoning: {result.reasoning}")

        # Assertions
        assert conversation.all_succeeded, f"Not all phases succeeded: {[p.error for p in conversation.phases if not p.success]}"
        assert result.total_score >= 10, f"Score too low: {result.total_score}/25"


class TestDiscordHandoffCrewAI:
    """Test CrewAI agents in Discord handoff scenario."""

    @pytest.mark.asyncio
    async def test_crewai_handoff_scenario(self, mock_gmail, mock_discord):
        """Test CrewAI agents can complete the handoff scenario."""
        framework = "crewai"

        print(f"\n{'=' * 70}")
        print(f"DISCORD HANDOFF TEST: {framework.upper()}")
        print(f"{'=' * 70}")

        conversation = await run_handoff_scenario(framework)

        print(f"\n{conversation.full_transcript}")

        evaluator = HandoffEvaluator()
        result = await evaluator.evaluate(framework, conversation)

        print(f"\nTotal Score: {result.total_score}/{result.max_score}")
        print(f"Reasoning: {result.reasoning}")

        assert conversation.all_succeeded
        assert result.total_score >= 10


class TestDiscordHandoffOpenHands:
    """Test OpenHands agents in Discord handoff scenario."""

    @pytest.mark.asyncio
    async def test_openhands_handoff_scenario(self, mock_gmail, mock_discord):
        """Test OpenHands agents can complete the handoff scenario."""
        framework = "openhands"

        print(f"\n{'=' * 70}")
        print(f"DISCORD HANDOFF TEST: {framework.upper()}")
        print(f"{'=' * 70}")

        conversation = await run_handoff_scenario(framework)

        print(f"\n{conversation.full_transcript}")

        evaluator = HandoffEvaluator()
        result = await evaluator.evaluate(framework, conversation)

        print(f"\nTotal Score: {result.total_score}/{result.max_score}")
        print(f"Reasoning: {result.reasoning}")

        assert conversation.all_succeeded
        assert result.total_score >= 10


# ==============================================================================
# Cross-Framework Comparison Test
# ==============================================================================


class TestDiscordHandoffComparison:
    """Compare all three frameworks on the same handoff scenario."""

    @pytest.mark.asyncio
    async def test_compare_all_frameworks_handoff(self, mock_gmail, mock_discord):
        """
        Run the same handoff scenario across all three frameworks.

        Uses G-Eval to score each framework and determine the winner.
        """
        frameworks = ["autogen", "crewai", "openhands"]
        conversations: dict[str, ConversationLog] = {}
        results: dict[str, HandoffEvalResult] = {}

        print("\n" + "=" * 70)
        print("CROSS-FRAMEWORK DISCORD HANDOFF COMPARISON")
        print("=" * 70)
        print(f"\nScenario: Customer API Gateway 404 Error")
        print(f"Phases: SupportEngineer -> ReleaseEngineer -> SupportEngineer")
        print("-" * 70)

        # Run each framework
        for framework in frameworks:
            print(f"\n>>> Testing {framework.upper()}...")
            conversation = await run_handoff_scenario(framework)
            conversations[framework] = conversation

            status = "PASS" if conversation.all_succeeded else "FAIL"
            print(f"    Status: {status}")
            print(f"    Total Latency: {conversation.total_latency_ms}ms")

        # Evaluate each framework
        print("\n" + "=" * 70)
        print("G-EVAL EVALUATION")
        print("=" * 70)

        evaluator = HandoffEvaluator()
        for framework, conversation in conversations.items():
            print(f"\n>>> Evaluating {framework.upper()}...")
            result = await evaluator.evaluate(framework, conversation)
            results[framework] = result
            print(f"    Score: {result.total_score}/{result.max_score}")

        # Determine winner
        winner = max(results.keys(), key=lambda f: results[f].total_score)
        winner_result = results[winner]

        # Print summary table
        print("\n" + "=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(f"\n{'Framework':<15} {'Status':<10} {'Latency':<12} {'Score':<10} {'Verdict':<10}")
        print("-" * 70)

        for fw in sorted(frameworks, key=lambda f: -results[f].total_score):
            conv = conversations[fw]
            res = results[fw]
            status = "PASS" if conv.all_succeeded else "FAIL"
            latency = f"{conv.total_latency_ms}ms"
            score = f"{res.total_score}/{res.max_score}"
            verdict = "WINNER" if fw == winner else ""
            print(f"{fw.upper():<15} {status:<10} {latency:<12} {score:<10} {verdict:<10}")

        print("-" * 70)

        # Print detailed scores for winner
        print(f"\n>>> WINNER: {winner.upper()} with {winner_result.total_score}/{winner_result.max_score}")
        print("\nDetailed Scores:")
        for criterion, score in winner_result.scores.items():
            print(f"  {criterion}: {score.score}/5")
            print(f"    {score.feedback}")

        print(f"\nReasoning: {winner_result.reasoning}")

        # Print sample responses
        print("\n" + "-" * 70)
        print("PHASE 1 RESPONSES (SupportEngineer initial response)")
        print("-" * 70)

        for fw, conv in conversations.items():
            if conv.phases and conv.phases[0].response:
                score = results[fw].total_score
                print(f"\n>>> {fw.upper()} [Score: {score}/25]:")
                print(conv.phases[0].response[:600])
                if len(conv.phases[0].response) > 600:
                    print(f"... ({len(conv.phases[0].response) - 600} more chars)")

        print("\n" + "=" * 70)

        # Assertions
        assert len(results) == 3, f"Expected 3 frameworks, got {len(results)}"

        succeeded = [fw for fw, conv in conversations.items() if conv.all_succeeded]
        assert len(succeeded) >= 1, f"No frameworks succeeded! {[(fw, conv.phases[0].error if conv.phases else 'no phases') for fw, conv in conversations.items()]}"

        assert winner_result.total_score > 0, f"Winner {winner} has score 0"

        print(f"\nFINAL VERDICT: {winner.upper()} wins with score {winner_result.total_score}/25")


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
