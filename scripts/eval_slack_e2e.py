#!/usr/bin/env python3
"""
E2E Slack Agent Evaluation Script.

This script runs a true end-to-end evaluation:
1. Posts a message to Slack mentioning an agent (e.g., /SupportEngineer)
2. Waits for the bot to respond in the thread (real agent processing)
3. Collects all thread messages including handoffs
4. Evaluates with DeepEval G-Eval metrics
5. Saves detailed markdown report with full conversation history

Usage:
    python scripts/eval_slack_e2e.py
    python scripts/eval_slack_e2e.py --scenario support_400_errors
    python scripts/eval_slack_e2e.py --scenario github_issue --timeout 300
    python scripts/eval_slack_e2e.py --channel C0123456789 --wait 180

Environment Variables:
    SLACK_BOT_TOKEN: Slack bot OAuth token (required)
    SLACK_DEFAULT_CHANNEL: Default channel for posting (required)
    AZURE_API_KEY: Azure OpenAI API key for G-Eval
    AZURE_API_BASE: Azure OpenAI endpoint
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibeteam.connectors.slack import SlackConnector

# Try to import DeepEval
DEEPEVAL_AVAILABLE = False
try:
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    from deepeval.metrics import GEval
    from deepeval.models.base_model import DeepEvalBaseLLM

    DEEPEVAL_AVAILABLE = True
except ImportError:
    print("WARNING: DeepEval not installed. Install with: uv add deepeval")
    print("         Evaluation will be skipped, only conversation will be collected.")


# ==============================================================================
# Test Scenarios
# ==============================================================================

SCENARIOS = {
    "support_400_errors": {
        "name": "Support Engineer - API 400 Errors Investigation",
        "message": (
            "@SupportEngineer there is a request from a user who sees the issue with "
            "Vibe API Gateway returning 400 errors. Customer ACME Corp reports this "
            "started after the deployment at 8am. Multiple customers affected, about "
            "500 users. This seems infrastructure-related. Please investigate."
        ),
        "expected_agent": "support_engineer",
        "evaluation_criteria": {
            "InvestigationQuality": (
                "Did the SupportEngineer ACTUALLY investigate the issue using their tools? "
                "EXPECTED BEHAVIOR: "
                "(1) SupportEngineer acknowledges the customer report; "
                "(2) SupportEngineer uses Sentry to check error patterns, counts, and stack traces; "
                "(3) Response includes SPECIFIC findings from Sentry (e.g., '127 400 errors in last 24h'); "
                "(4) If rollback/deployment action needed, SupportEngineer hands off to @ReleaseEngineer with findings. "
                "Score 0.0 if no investigation occurred. Score 0.5 if generic response without tool usage. "
                "Score 1.0 if Sentry was used and specific findings were reported."
            ),
            "ActionableResolution": (
                "Did the SupportEngineer provide actionable next steps based on investigation? "
                "EXPECTED: "
                "(1) Specific findings from Sentry (error patterns, affected endpoints, timestamps); "
                "(2) Either direct resolution OR handoff to @ReleaseEngineer/@SoftwareEngineer with context; "
                "(3) Clear communication to customer about what was found and next steps. "
                "Score 0.0 if no action taken. Score 0.5 if vague response. "
                "Score 1.0 if concrete findings and clear next steps provided."
            ),
        },
        "threshold": 0.70,
    },
    "github_issue": {
        "name": "Software Engineer - GitHub Issue Triage",
        "message": (
            "@SoftwareEngineer we have a new GitHub issue #42 reporting that the "
            "browser extension crashes when clicking the record button. The user says "
            "it happens on Chrome 120 with the latest extension version. Please investigate."
        ),
        "expected_agent": "software_engineer",
        "evaluation_criteria": {
            "IssueAnalysis": (
                "Did the SoftwareEngineer analyze the GitHub issue properly? "
                "Should include: checking the issue details, understanding the reproduction steps, "
                "identifying potential causes, and suggesting next steps."
            ),
            "ActionablePlan": (
                "Did the agent provide an actionable plan? "
                "Should include specific debugging steps, potential fixes, or handoffs to other agents."
            ),
        },
        "threshold": 0.70,
    },
    "release_deploy": {
        "name": "Release Engineer - Deployment Request",
        "message": (
            "@ReleaseEngineer we need to deploy the latest changes to staging. "
            "The PR #123 has been merged and all tests are passing. Please proceed "
            "with the staging deployment and notify the team when done."
        ),
        "expected_agent": "release_engineer",
        "evaluation_criteria": {
            "DeploymentExecution": (
                "Did the ReleaseEngineer handle the deployment request properly? "
                "Should include: confirming the PR status, executing deployment steps, "
                "and providing deployment status updates."
            ),
            "CommunicationQuality": (
                "Did the agent communicate clearly about the deployment? "
                "Should include: what was deployed, where, and any follow-up actions needed."
            ),
        },
        "threshold": 0.70,
    },
}

# Role display names
ROLE_DISPLAY = {
    "user": "User",
    "support_engineer": "SupportEngineer",
    "software_engineer": "SoftwareEngineer",
    "release_engineer": "ReleaseEngineer",
    "product_manager": "ProductManager",
    "marketing_manager": "MarketingManager",
}


# ==============================================================================
# Azure OpenAI Model for DeepEval
# ==============================================================================


class AzureOpenAIModel(DeepEvalBaseLLM if DEEPEVAL_AVAILABLE else object):
    """Azure OpenAI model wrapper for DeepEval G-Eval."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        api_version: str = "2024-12-01-preview",
        model: str = "gpt-5-2",
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        self.model_name = model

    def load_model(self):
        return self

    def generate(self, prompt: str, **kwargs) -> str:
        """Synchronous generation."""
        return asyncio.run(self.a_generate(prompt, **kwargs))

    async def a_generate(self, prompt: str, **kwargs) -> str:
        """Async generation using Azure OpenAI."""
        url = f"{self.api_base}/openai/deployments/{self.model_name}/chat/completions"

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": kwargs.get("max_tokens", 2000),
            "temperature": kwargs.get("temperature", 0.1),
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                params={"api-version": self.api_version},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def get_model_name(self) -> str:
        return f"azure/{self.model_name}"


# ==============================================================================
# Helper Functions
# ==============================================================================


def detect_agent_role(text: str) -> str | None:
    """Detect which agent role is being addressed in the message."""
    text_lower = text.lower()
    if "/supportengineer" in text_lower or "support_engineer" in text_lower:
        return "support_engineer"
    if "/softwareengineer" in text_lower or "/swe" in text_lower:
        return "software_engineer"
    if "/releaseengineer" in text_lower or "/sre" in text_lower:
        return "release_engineer"
    if "/productmanager" in text_lower or "/pm" in text_lower:
        return "product_manager"
    if "/marketingmanager" in text_lower:
        return "marketing_manager"
    return None


def build_transcript(messages: list[tuple[str, str]]) -> str:
    """Build transcript from (role, text) pairs."""
    lines = []
    for role, text in messages:
        display = ROLE_DISPLAY.get(role, role.title())
        lines.append(f"[{display}] {text}")
    return "\n\n".join(lines)


def generate_eval_report(
    scenario_name: str,
    scenario_config: dict,
    slack_channel: str,
    thread_ts: str,
    conversation: list[tuple[str, str]],
    metrics_results: list[dict],
    latency_ms: int,
    output_dir: str | Path = "results/eval_reports",
) -> Path:
    """Generate a markdown evaluation report with full conversation history."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{scenario_name}_{timestamp_str}.md"
    filepath = output_path / filename

    # Calculate overall pass/fail
    if metrics_results:
        all_passed = all(m["score"] >= m["threshold"] for m in metrics_results)
        status_emoji = "✅" if all_passed else "❌"
        status_text = "PASSED" if all_passed else "FAILED"
    else:
        status_emoji = "⚠️"
        status_text = "NO EVALUATION (DeepEval not available)"

    # Extract agents from conversation
    agents_ran = list(set(role for role, _ in conversation if role != "user"))

    # Build the report
    lines = [
        f"# Evaluation Report: {scenario_config['name']}",
        "",
        f"**Status:** {status_emoji} {status_text}",
        f"**Timestamp:** {timestamp.isoformat()}",
        f"**Scenario:** `{scenario_name}`",
        "",
        "---",
        "",
        "## Test Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Slack Channel | `{slack_channel}` |",
        f"| Thread TS | `{thread_ts}` |",
        f"| Expected Agent | {scenario_config['expected_agent']} |",
        f"| Agents Responded | {', '.join(agents_ran) if agents_ran else 'None'} |",
        f"| Response Latency | {latency_ms}ms |",
        f"| Message Count | {len(conversation)} |",
        "",
    ]

    if metrics_results:
        lines.extend(
            [
                "---",
                "",
                "## Evaluation Metrics",
                "",
                "| Metric | Score | Threshold | Status |",
                "|--------|-------|-----------|--------|",
            ]
        )

        for m in metrics_results:
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

        for m in metrics_results:
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
            scenario_config["message"],
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
            "*Generated by VibeTeam E2E Evaluation Script*",
        ]
    )

    # Write the report
    report_content = "\n".join(lines)
    filepath.write_text(report_content)

    return filepath


# ==============================================================================
# Main Evaluation Function
# ==============================================================================


async def run_evaluation(
    scenario_name: str,
    channel: str | None = None,
    wait_timeout: int = 180,
    poll_interval: int = 5,
) -> dict[str, Any]:
    """
    Run a full E2E evaluation:
    1. Post message to Slack
    2. Wait for bot response
    3. Evaluate with DeepEval
    4. Generate report
    """
    # Get scenario config
    if scenario_name not in SCENARIOS:
        available = ", ".join(SCENARIOS.keys())
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {available}")

    scenario = SCENARIOS[scenario_name]

    # Initialize Slack connector
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    if not slack_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable not set")

    slack = SlackConnector(token=slack_token)

    # Determine channel
    if not channel:
        channel = os.environ.get("SLACK_DEFAULT_CHANNEL")
    if not channel:
        raise ValueError("No channel specified. Use --channel or set SLACK_DEFAULT_CHANNEL")

    print("=" * 70)
    print(f"E2E SLACK AGENT EVALUATION")
    print("=" * 70)
    print(f"Scenario: {scenario['name']}")
    print(f"Channel: {channel}")
    print(f"Wait Timeout: {wait_timeout}s")
    print()

    # Step 1: Post message to Slack
    print(">>> Step 1: Posting message to Slack")
    user_message = scenario["message"]
    print(f"    Message: {user_message[:80]}...")

    initial_msg = slack.post_message(channel=channel, text=user_message)
    thread_ts = initial_msg.ts
    print(f"    Thread TS: {thread_ts}")
    print(f"    Posted successfully!")

    # Step 1b: Trigger the gateway to process this message
    # Slack doesn't send webhooks for messages the bot itself posts,
    # so we need to explicitly trigger the gateway
    print("\n>>> Step 1b: Triggering gateway to process message")
    gateway_url = os.environ.get("GATEWAY_URL", "https://webhook.team.vibebrowser.app")
    trigger_url = f"{gateway_url}/slack/trigger"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                trigger_url,
                json={
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "text": user_message,
                    "user_id": "eval_script",
                },
            )
            if response.status_code == 200:
                result = response.json()
                print(f"    Gateway accepted: routing to {result.get('roles', [])}")
            else:
                print(f"    WARNING: Gateway returned {response.status_code}: {response.text}")
    except Exception as e:
        print(f"    WARNING: Failed to trigger gateway: {e}")
        print("    Falling back to webhook-only mode (may not work)")

    # Track conversation
    conversation: list[tuple[str, str]] = [("user", user_message)]

    # Step 2: Wait for bot response (with handoff chain support)
    print(f"\n>>> Step 2: Waiting for agent response (timeout: {wait_timeout}s)")
    start_time = time.time()
    last_message_count = 1  # We posted 1 message
    handoff_wait_time = 30  # Seconds to wait after detecting handoff mention
    stable_time = 10  # Seconds with no new messages = conversation complete
    last_new_message_time = 0.0

    # Pattern to detect @/RoleName mentions (handoffs)
    import re

    handoff_pattern = re.compile(
        r"[@/](SoftwareEngineer|ReleaseEngineer|SupportEngineer|"
        r"ProductManager|MarketingManager)",
        re.IGNORECASE,
    )

    while time.time() - start_time < wait_timeout:
        await asyncio.sleep(poll_interval)

        # Get thread replies
        replies = slack.get_thread_replies(channel=channel, thread_ts=thread_ts, limit=50)
        current_count = len(replies)

        if current_count > last_message_count:
            print(f"    New messages detected: {current_count - last_message_count}")
            last_message_count = current_count
            last_new_message_time = time.time()

            # Check if latest bot message contains a handoff mention
            bot_messages = [r for r in replies if r.is_bot and r.ts != thread_ts]
            if bot_messages:
                latest_bot_msg = bot_messages[-1]
                has_handoff = bool(handoff_pattern.search(latest_bot_msg.text))
                if has_handoff:
                    print(f"    Handoff detected in response! Waiting for next agent...")
                    # Continue polling for the handoff response
                    continue

        # Check if we've received bot responses and conversation is stable
        bot_messages = [r for r in replies if r.is_bot and r.ts != thread_ts]
        if bot_messages and last_new_message_time > 0:
            # Check if enough time has passed with no new messages
            time_since_last = time.time() - last_new_message_time
            if time_since_last >= stable_time:
                # Check if latest message has no handoff (conversation complete)
                latest_bot_msg = bot_messages[-1]
                has_handoff = bool(handoff_pattern.search(latest_bot_msg.text))
                if not has_handoff:
                    print(f"    Conversation stable for {stable_time}s, no pending handoffs.")
                    break
                else:
                    print(f"    Still waiting for handoff response...")

        elapsed = int(time.time() - start_time)
        print(f"    Waiting... ({elapsed}s / {wait_timeout}s)")

    latency_ms = int((time.time() - start_time) * 1000)

    # Step 3: Collect conversation
    print("\n>>> Step 3: Collecting conversation")
    replies = slack.get_thread_replies(channel=channel, thread_ts=thread_ts, limit=50)

    for reply in replies:
        if reply.ts == thread_ts:
            continue  # Skip original message

        # Detect agent role from message prefix like "[SupportEngineer]"
        text = reply.text
        role = "bot"

        if text.startswith("["):
            bracket_end = text.find("]")
            if bracket_end > 0:
                role_name = text[1:bracket_end].lower().replace(" ", "_")
                if role_name in ROLE_DISPLAY.values() or role_name.replace("_", "") in [
                    r.lower().replace("_", "") for r in ROLE_DISPLAY.keys()
                ]:
                    # Normalize role name
                    for key, display in ROLE_DISPLAY.items():
                        if display.lower() == role_name or key == role_name:
                            role = key
                            break
                text = text[bracket_end + 1 :].strip()

        conversation.append((role, text))
        sender = ROLE_DISPLAY.get(role, role.title())
        print(f"    [{sender}] {text[:60]}...")

    print(f"    Total messages: {len(conversation)}")

    # Step 4: Evaluate with DeepEval
    metrics_results = []

    if DEEPEVAL_AVAILABLE and len(conversation) > 1:
        print("\n>>> Step 4: Evaluating with DeepEval G-Eval")

        # Get Azure credentials
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", os.environ.get("AZURE_API_KEY"))
        api_base = os.environ.get("AZURE_OPENAI_ENDPOINT", os.environ.get("AZURE_API_BASE"))

        if api_key and api_base:
            try:
                model = AzureOpenAIModel(
                    api_key=api_key,
                    api_base=api_base,
                    model=os.environ.get("BENCHMARK_JUDGE_MODEL", "gpt-5-2"),
                )

                transcript = build_transcript(conversation)
                test_case = LLMTestCase(
                    input=user_message,
                    actual_output=transcript,
                )

                for metric_name, criteria in scenario["evaluation_criteria"].items():
                    print(f"    Evaluating: {metric_name}")

                    metric = GEval(
                        name=metric_name,
                        criteria=criteria,
                        evaluation_params=[
                            LLMTestCaseParams.INPUT,
                            LLMTestCaseParams.ACTUAL_OUTPUT,
                        ],
                        threshold=scenario["threshold"],
                        model=model,
                    )

                    metric.measure(test_case)

                    metrics_results.append(
                        {
                            "name": metric_name,
                            "score": metric.score,
                            "threshold": metric.threshold,
                            "reason": metric.reason,
                        }
                    )

                    status = "✅" if metric.score >= metric.threshold else "❌"
                    print(
                        f"      {status} Score: {metric.score:.2f} (threshold: {metric.threshold})"
                    )

            except Exception as e:
                print(f"    ERROR: Evaluation failed: {e}")
        else:
            print("    WARNING: Azure credentials not set. Skipping evaluation.")
    else:
        if len(conversation) <= 1:
            print("\n>>> Step 4: SKIPPED - No agent response received")
        else:
            print("\n>>> Step 4: SKIPPED - DeepEval not available")

    # Step 5: Generate report
    print("\n>>> Step 5: Generating evaluation report")

    report_path = generate_eval_report(
        scenario_name=scenario_name,
        scenario_config=scenario,
        slack_channel=channel,
        thread_ts=thread_ts,
        conversation=conversation,
        metrics_results=metrics_results,
        latency_ms=latency_ms,
    )

    print(f"    Report saved: {report_path}")

    # Summary
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Scenario: {scenario['name']}")
    print(f"Channel: {channel}")
    print(f"Thread: {thread_ts}")
    print(f"Messages: {len(conversation)}")
    print(f"Latency: {latency_ms}ms")

    if metrics_results:
        all_passed = all(m["score"] >= m["threshold"] for m in metrics_results)
        print(f"Overall: {'✅ PASSED' if all_passed else '❌ FAILED'}")
        for m in metrics_results:
            status = "✅" if m["score"] >= m["threshold"] else "❌"
            print(f"  {status} {m['name']}: {m['score']:.2f}")
    else:
        print("Overall: ⚠️ NOT EVALUATED")

    print(f"Report: {report_path}")
    print("=" * 70)

    return {
        "scenario": scenario_name,
        "channel": channel,
        "thread_ts": thread_ts,
        "conversation": conversation,
        "metrics": metrics_results,
        "latency_ms": latency_ms,
        "report_path": str(report_path),
        "passed": all(m["score"] >= m["threshold"] for m in metrics_results)
        if metrics_results
        else None,
    }


# ==============================================================================
# CLI
# ==============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Run E2E Slack Agent Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available Scenarios:
{chr(10).join(f"  {k}: {v['name']}" for k, v in SCENARIOS.items())}

Examples:
  python scripts/eval_slack_e2e.py --scenario support_400_errors
  python scripts/eval_slack_e2e.py --scenario github_issue --timeout 300
  python scripts/eval_slack_e2e.py --channel C0123456789 --wait 180
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="support_400_errors",
        help="Evaluation scenario to run (default: support_400_errors)",
    )
    parser.add_argument(
        "--channel",
        help="Slack channel ID to post to (default: SLACK_DEFAULT_CHANNEL env var)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout in seconds waiting for agent response (default: 180)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Polling interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit",
    )

    args = parser.parse_args()

    if args.list_scenarios:
        print("Available Scenarios:")
        for name, config in SCENARIOS.items():
            print(f"  {name}:")
            print(f"    Name: {config['name']}")
            print(f"    Agent: {config['expected_agent']}")
            print(f"    Message: {config['message'][:60]}...")
            print()
        return 0

    try:
        result = asyncio.run(
            run_evaluation(
                scenario_name=args.scenario,
                channel=args.channel,
                wait_timeout=args.timeout,
                poll_interval=args.poll_interval,
            )
        )

        # Exit with error code if evaluation failed
        if result.get("passed") is False:
            return 1
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
