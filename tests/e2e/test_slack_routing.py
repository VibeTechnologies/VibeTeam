"""
E2E Test: Slack Agent Handoff Evaluation

Tests the agent pipeline via Gateway API with Slack context:
1. Post initial message to Slack (for visibility/thread creation)
2. Call Gateway /api/run with slack context (simulates webhook)
3. Gateway routes to Agent Service (openhands-agents)
4. Agent responds - test posts response to Slack thread
5. Detect /RoleName handoffs, repeat for each
6. Evaluate actual conversation with DeepEval G-Eval

This bypasses Slack webhook (which may not be configured) but tests
the real Gateway → Agent Service pipeline on K8s.

Usage:
    pytest tests/e2e/test_slack_routing.py -v -s --post-to-slack
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

# Import DeepEval if available
DEEPEVAL_AVAILABLE = False
LLMTestCase = None
LLMTestCaseParams = None
GEval = None

try:
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    DEEPEVAL_AVAILABLE = True
except ImportError:
    pass

# Import conftest helpers for Azure model
try:
    from conftest import AzureOpenAIModel
except ImportError:
    try:
        from tests.e2e.conftest import AzureOpenAIModel
    except ImportError:
        AzureOpenAIModel = None

if TYPE_CHECKING:
    from vibeteam.connectors.slack import SlackConnector


# ==============================================================================
# Configuration
# ==============================================================================

# Gateway URL - can be overridden via environment
GATEWAY_URL = os.environ.get(
    "VIBETEAM_GATEWAY_URL", "http://vibeteam-gateway.vibeteam.svc.cluster.local:8080"
)

# For local testing, try localhost or k8s service
GATEWAY_URLS = [
    os.environ.get("VIBETEAM_GATEWAY_URL", ""),
    "http://localhost:8080",
    "http://vibeteam-gateway.vibeteam.svc.cluster.local:8080",
    "http://10.43.14.189:8080",  # ClusterIP from kubectl
]

# Timeout for agent responses
AGENT_TIMEOUT = 120

# Maximum handoff chain depth
MAX_HANDOFFS = 3

# Role name pattern
ROLE_PATTERN = re.compile(
    r"[/@](SoftwareEngineer|ReleaseEngineer|SupportEngineer|ProductManager|MarketingManager|SWE|PM)",
    re.IGNORECASE,
)

# Role name normalization
ROLE_MAP = {
    "softwareengineer": "software_engineer",
    "swe": "software_engineer",
    "releaseengineer": "release_engineer",
    "supportengineer": "support_engineer",
    "productmanager": "product_manager",
    "pm": "product_manager",
    "marketingmanager": "marketing_manager",
}

ROLE_DISPLAY = {
    "software_engineer": "SoftwareEngineer",
    "release_engineer": "ReleaseEngineer",
    "support_engineer": "SupportEngineer",
    "product_manager": "ProductManager",
    "marketing_manager": "MarketingManager",
}


# ==============================================================================
# Strict G-Eval Metrics for Support Engineer Investigation Scenario
# ==============================================================================


def create_investigation_quality_metric(model):
    """
    Strict metric: Did the agent ACTUALLY investigate the issue?

    This should FAIL if the agent just gives generic advice without:
    - Using tools to check Sentry/logs/metrics
    - Providing specific findings from investigation
    - Taking concrete action or making specific handoff
    """
    if not DEEPEVAL_AVAILABLE or GEval is None:
        return None

    return GEval(
        name="InvestigationQuality",
        criteria=(
            "Did the SupportEngineer ACTUALLY investigate the reported issue using Sentry? "
            "A proper investigation MUST include: "
            "(1) Using Sentry tool to check error patterns, counts, and stack traces - not just saying they would check; "
            "(2) Reporting SPECIFIC findings from the investigation (error messages, affected endpoints, timestamps); "
            "(3) Either resolving the issue OR handing off to ReleaseEngineer/SoftwareEngineer with specific technical details. "
            "A generic 'triage checklist' or 'here's what I would do' response is a FAILURE - "
            "the agent must actually DO the investigation with Sentry, not describe how to do it."
        ),
        evaluation_steps=[
            "Check if the agent used Sentry tool to check errors - just mentioning Sentry is not enough",
            "Verify the agent reported SPECIFIC findings (actual error messages, specific endpoints, concrete data)",
            "Check if the response contains actual investigation results vs generic advice",
            "If no specific findings from Sentry, score should be LOW (< 0.5) regardless of how well-written the response is",
            "A checklist or process description without actual execution should score < 0.3",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.70,
        model=model,
    )


def create_handoff_or_resolution_metric(model):
    """
    Strict metric: Did the agent either resolve the issue OR make a proper handoff?

    For infrastructure issues, SupportEngineer should:
    - Investigate with Sentry and find root cause, OR
    - Hand off to ReleaseEngineer/SoftwareEngineer with specific findings

    This should FAIL if the agent neither resolves nor hands off.
    """
    if not DEEPEVAL_AVAILABLE or GEval is None:
        return None

    return GEval(
        name="HandoffOrResolution",
        criteria=(
            "Did the agent either RESOLVE the issue or make a PROPER HANDOFF? "
            "For an infrastructure issue (API Gateway 400 errors affecting 500 users): "
            "(1) RESOLUTION means: identified root cause using Sentry AND either fixed it or provided specific fix instructions; "
            "(2) PROPER HANDOFF means: explicitly mentioned /ReleaseEngineer or /SoftwareEngineer "
            "with SPECIFIC technical context from Sentry investigation (not just 'look into this'). "
            "If the agent neither resolved the issue nor handed off with specific context, this is a FAILURE. "
            "Providing a checklist without taking action is NOT resolution or handoff."
        ),
        evaluation_steps=[
            "Check if the issue was actually resolved (root cause identified using Sentry and fixed)",
            "If not resolved, check for explicit /ReleaseEngineer or /SoftwareEngineer handoff mention",
            "If handoff exists, verify it includes specific technical context from Sentry investigation",
            "A vague 'escalate to engineering' without specific findings should score < 0.4",
            "No resolution AND no handoff should score < 0.2",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.70,
        model=model,
    )


# ==============================================================================
# Helper Functions
# ==============================================================================


def get_working_gateway_url() -> str | None:
    """Find a working gateway URL."""
    for url in GATEWAY_URLS:
        if not url:
            continue
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                return url
        except Exception:
            continue
    return None


def detect_handoffs(text: str) -> list[str]:
    """Detect /RoleName mentions in text and return normalized role names."""
    mentions = ROLE_PATTERN.findall(text)
    roles = []
    for mention in mentions:
        normalized = ROLE_MAP.get(mention.lower())
        if normalized and normalized not in roles:
            roles.append(normalized)
    return roles


async def call_gateway_run(
    gateway_url: str,
    task: str,
    role: str,
    context_type: str = "slack",
    context_id: str = "",
    timeout: int = AGENT_TIMEOUT,
) -> dict:
    """
    Call Gateway /api/run endpoint.

    This simulates what the Slack webhook handler does.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{gateway_url}/api/run",
            json={
                "task": task,
                "role": role,
                "framework": "openhands",
                "context_type": context_type,
                "context_id": context_id,
            },
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Gateway returned {response.status_code}: {response.text}",
            }

        data = response.json()
        return {
            "success": True,
            "response": data.get("response", ""),
            "session_id": data.get("session_id", ""),
            "framework": data.get("framework", ""),
            "agents_used": data.get("agents_used", []),
        }


def build_transcript(messages: list[tuple[str, str]]) -> str:
    """Build transcript from (role, text) pairs."""
    lines = []
    for role, text in messages:
        display = ROLE_DISPLAY.get(role, role)
        lines.append(f"[{display}] {text[:500]}")
    return "\n\n".join(lines)


def generate_eval_report(
    test_name: str,
    gateway_url: str,
    slack_channel: str,
    thread_ts: str,
    user_message: str,
    conversation: list[tuple[str, str]],
    agents_ran: list[str],
    handoff_count: int,
    metrics: list[dict],
    output_dir: str | Path = "results/eval_reports",
) -> Path:
    """
    Generate a markdown evaluation report with full conversation history.

    Args:
        test_name: Name of the test
        gateway_url: Gateway URL used
        slack_channel: Slack channel ID
        thread_ts: Slack thread timestamp
        user_message: Original user message
        conversation: List of (role, text) tuples
        agents_ran: List of agent names that ran
        handoff_count: Number of handoffs
        metrics: List of metric results with keys: name, score, threshold, reason
        output_dir: Directory to save reports

    Returns:
        Path to the generated report file
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{test_name}_{timestamp_str}.md"
    filepath = output_path / filename

    # Calculate overall pass/fail
    all_passed = all(m["score"] >= m["threshold"] for m in metrics)
    status_emoji = "✅" if all_passed else "❌"

    # Build the report
    lines = [
        f"# Evaluation Report: {test_name}",
        "",
        f"**Status:** {status_emoji} {'PASSED' if all_passed else 'FAILED'}",
        f"**Timestamp:** {timestamp.isoformat()}",
        "",
        "---",
        "",
        "## Test Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Gateway URL | `{gateway_url}` |",
        f"| Slack Channel | `{slack_channel}` |",
        f"| Thread TS | `{thread_ts}` |",
        f"| Agents Ran | {', '.join(agents_ran)} |",
        f"| Handoff Count | {handoff_count} |",
        "",
        "---",
        "",
        "## Evaluation Metrics",
        "",
        "| Metric | Score | Threshold | Status |",
        "|--------|-------|-----------|--------|",
    ]

    for m in metrics:
        passed = m["score"] >= m["threshold"]
        status = "✅ Pass" if passed else "❌ Fail"
        lines.append(f"| {m['name']} | {m['score']:.2f} | {m['threshold']:.2f} | {status} |")

    lines.extend(
        [
            "",
            "### Metric Reasoning",
            "",
        ]
    )

    for m in metrics:
        lines.extend(
            [
                f"#### {m['name']}",
                "",
                f"> {m['reason']}",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "## Conversation History",
            "",
            "### Original User Request",
            "",
            "```",
            user_message,
            "```",
            "",
            "### Full Conversation",
            "",
        ]
    )

    for i, (role, text) in enumerate(conversation, 1):
        display_role = ROLE_DISPLAY.get(role, role.title())
        role_emoji = "👤" if role == "user" else "🤖"
        lines.extend(
            [
                f"#### {i}. {role_emoji} {display_role}",
                "",
                "```",
                text,
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "*Generated by VibeTeam E2E Test Suite*",
        ]
    )

    # Write the report
    report_content = "\n".join(lines)
    filepath.write_text(report_content)

    return filepath


# ==============================================================================
# E2E Test
# ==============================================================================


@pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="DeepEval not installed")
class TestSlackHandoffE2E:
    """
    E2E test for Slack agent handoffs via Gateway API.

    Flow:
    1. Post message to Slack (creates visible thread)
    2. Call Gateway /api/run (real agent service on K8s)
    3. Post agent response to Slack thread
    4. Detect handoffs, run next agent
    5. Evaluate with DeepEval
    """

    @pytest.mark.asyncio
    async def test_support_engineer_handoff(
        self,
        slack_connector: SlackConnector,
        slack_test_channel: str,
        should_post_to_slack: bool,
        azure_deepeval_model: AzureOpenAIModel,
    ):
        """
        E2E: SupportEngineer investigates issue, may handoff to other agents.
        """
        if not should_post_to_slack:
            pytest.skip("--post-to-slack not enabled")

        # Find working gateway
        gateway_url = get_working_gateway_url()
        if not gateway_url:
            pytest.skip(
                "No working gateway found. Set VIBETEAM_GATEWAY_URL or ensure "
                "vibeteam-gateway is accessible."
            )

        print("\n" + "=" * 70)
        print("E2E SLACK HANDOFF TEST (Gateway API)")
        print("=" * 70)
        print(f"Gateway: {gateway_url}")
        print(f"Channel: {slack_test_channel}")

        # Step 1: Post initial message to Slack
        user_message = (
            "/SupportEngineer there is a request from a user who sees the issue with "
            "Vibe API Gateway returning 400 errors. Customer ACME Corp reports this "
            "started after the deployment at 8am. Multiple customers affected, about "
            "500 users. This seems infrastructure-related. Please investigate."
        )

        print("\n>>> Step 1: Posting initial message to Slack")
        initial_msg = slack_connector.post_message(
            channel=slack_test_channel,
            text=user_message,
        )
        thread_ts = initial_msg.ts
        context_id = f"{slack_test_channel}:{thread_ts}"
        print(f"    Thread: {thread_ts}")

        # Track conversation
        conversation: list[tuple[str, str]] = [("user", user_message)]
        agents_ran: list[str] = []

        # Step 2: Call Gateway for SupportEngineer
        print("\n>>> Step 2: Calling Gateway /api/run for SupportEngineer")
        start_time = time.time()

        result = await call_gateway_run(
            gateway_url=gateway_url,
            task=user_message,
            role="support_engineer",
            context_type="slack",
            context_id=context_id,
        )

        latency = int((time.time() - start_time) * 1000)
        print(f"    Success: {result.get('success')}")
        print(f"    Latency: {latency}ms")

        if not result.get("success"):
            print(f"    Error: {result.get('error')}")
            # Post error to Slack
            slack_connector.post_message(
                channel=slack_test_channel,
                text=f"[SupportEngineer] Error: {result.get('error', 'Unknown error')}",
                thread_ts=thread_ts,
            )
            pytest.fail(f"Gateway call failed: {result.get('error')}")

        response_text = result.get("response", "")
        print(f"    Response: {response_text[:200]}...")

        # Post response to Slack
        slack_connector.post_message(
            channel=slack_test_channel,
            text=f"[SupportEngineer] {response_text}",
            thread_ts=thread_ts,
        )

        conversation.append(("support_engineer", response_text))
        agents_ran.append("support_engineer")

        # Step 3: Handle handoff chain
        print("\n>>> Step 3: Processing handoff chain")

        pending_handoffs = detect_handoffs(response_text)
        already_ran = {"support_engineer"}
        handoff_count = 0
        last_response = response_text

        while pending_handoffs and handoff_count < MAX_HANDOFFS:
            next_role = pending_handoffs.pop(0)
            if next_role in already_ran:
                continue

            handoff_count += 1
            already_ran.add(next_role)
            display_name = ROLE_DISPLAY.get(next_role, next_role)

            print(f"    Handoff #{handoff_count}: {display_name}")

            # Build context for handoff
            handoff_task = (
                f"[Handoff from previous agent]\n\n"
                f"Original request: {user_message}\n\n"
                f"Previous agent's findings: {last_response[:500]}"
            )

            result = await call_gateway_run(
                gateway_url=gateway_url,
                task=handoff_task,
                role=next_role,
                context_type="slack",
                context_id=context_id,
            )

            if result.get("success"):
                response_text = result.get("response", "")
                print(f"      Response: {response_text[:100]}...")

                # Post to Slack
                slack_connector.post_message(
                    channel=slack_test_channel,
                    text=f"[{display_name}] {response_text}",
                    thread_ts=thread_ts,
                )

                conversation.append((next_role, response_text))
                agents_ran.append(next_role)
                last_response = response_text

                # Check for more handoffs
                new_handoffs = detect_handoffs(response_text)
                for h in new_handoffs:
                    if h not in already_ran and h not in pending_handoffs:
                        pending_handoffs.append(h)
            else:
                print(f"      Error: {result.get('error')}")
                slack_connector.post_message(
                    channel=slack_test_channel,
                    text=f"[{display_name}] Error: {result.get('error', 'Unknown')}",
                    thread_ts=thread_ts,
                )

        print(f"    Total handoffs: {handoff_count}")

        # Step 4: Read back Slack thread to verify
        print("\n>>> Step 4: Verifying Slack thread")
        thread_messages = slack_connector.get_thread_replies(
            channel=slack_test_channel,
            thread_ts=thread_ts,
            limit=20,
        )
        print(f"    Messages in thread: {len(thread_messages)}")

        for i, msg in enumerate(thread_messages):
            sender = "Bot" if msg.is_bot else "User"
            print(f"    [{i + 1}] {sender}: {msg.text[:80]}...")

        # Step 5: Evaluate with DeepEval
        print("\n>>> Step 5: DeepEval G-Eval evaluation")

        transcript = build_transcript(conversation)

        test_case = LLMTestCase(
            input=user_message,
            actual_output=transcript,
        )

        investigation_metric = create_investigation_quality_metric(azure_deepeval_model)
        handoff_metric = create_handoff_or_resolution_metric(azure_deepeval_model)

        investigation_metric.measure(test_case)
        handoff_metric.measure(test_case)

        print(
            f"    InvestigationQuality: {investigation_metric.score:.2f} (threshold: {investigation_metric.threshold})"
        )
        print(
            f"    HandoffOrResolution: {handoff_metric.score:.2f} (threshold: {handoff_metric.threshold})"
        )
        print(f"    Investigation reason: {investigation_metric.reason[:200]}...")
        print(f"    Handoff reason: {handoff_metric.reason[:200]}...")

        # Step 6: Generate markdown evaluation report
        print("\n>>> Step 6: Generating evaluation report")

        metrics_data = [
            {
                "name": "InvestigationQuality",
                "score": investigation_metric.score,
                "threshold": investigation_metric.threshold,
                "reason": investigation_metric.reason,
            },
            {
                "name": "HandoffOrResolution",
                "score": handoff_metric.score,
                "threshold": handoff_metric.threshold,
                "reason": handoff_metric.reason,
            },
        ]

        report_path = generate_eval_report(
            test_name="support_engineer_handoff",
            gateway_url=gateway_url,
            slack_channel=slack_test_channel,
            thread_ts=thread_ts,
            user_message=user_message,
            conversation=conversation,
            agents_ran=agents_ran,
            handoff_count=handoff_count,
            metrics=metrics_data,
        )
        print(f"    Report saved to: {report_path}")

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print(f"Thread: {slack_test_channel} / {thread_ts}")
        print(f"Agents ran: {agents_ran}")
        print(f"Handoffs: {handoff_count}")
        print(f"Slack messages: {len(thread_messages)}")
        print(f"InvestigationQuality: {investigation_metric.score:.2f}")
        print(f"HandoffOrResolution: {handoff_metric.score:.2f}")
        print(f"Report: {report_path}")
        print("=" * 70)

        # Assertions
        assert len(agents_ran) >= 1, "No agents ran successfully"

        # Must have at least 2 messages in thread (user + 1 agent)
        assert len(thread_messages) >= 2, (
            f"Expected at least 2 messages in Slack thread, got {len(thread_messages)}. "
            f"Agent responses may not have been posted."
        )

        assert investigation_metric.score >= investigation_metric.threshold, (
            f"InvestigationQuality {investigation_metric.score:.2f} below threshold {investigation_metric.threshold}. "
            f"Reason: {investigation_metric.reason}"
        )

        assert handoff_metric.score >= handoff_metric.threshold, (
            f"HandoffOrResolution {handoff_metric.score:.2f} below threshold {handoff_metric.threshold}. "
            f"Reason: {handoff_metric.reason}"
        )


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--post-to-slack"])
