#!/usr/bin/env python3
"""
E2E Evaluation: Post to Slack, wait for agent response, evaluate with DeepEval.

This script:
1. Posts a message to Slack mentioning an agent (e.g., "/SupportEngineer ...")
2. Polls the thread for agent responses
3. Evaluates the conversation with DeepEval G-Eval
4. Saves a markdown report with full conversation history

Usage:
    python scripts/eval_slack_agent.py
    python scripts/eval_slack_agent.py --scenario api_gateway_error
    python scripts/eval_slack_agent.py --message "/SupportEngineer check Sentry for errors"
    python scripts/eval_slack_agent.py --channel "#ai-team" --timeout 120

Environment Variables:
    SLACK_BOT_TOKEN: Slack bot OAuth token (required)
    SLACK_DEFAULT_CHANNEL: Default channel to post to
    AZURE_API_KEY: Azure OpenAI API key (for DeepEval)
    AZURE_API_BASE: Azure OpenAI endpoint
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    import httpx

    DEEPEVAL_AVAILABLE = True
except ImportError:
    pass

# ==============================================================================
# Configuration
# ==============================================================================

DEFAULT_TIMEOUT = 180  # seconds to wait for agent response
POLL_INTERVAL = 5  # seconds between polls
RESULTS_DIR = Path("results/eval_reports")

# Predefined evaluation scenarios
SCENARIOS = {
    "api_gateway_error": {
        "message": (
            "/SupportEngineer there is a request from a user who sees the issue with "
            "Vibe API Gateway returning 400 errors. Customer ACME Corp reports this "
            "started after the deployment at 8am. Multiple customers affected, about "
            "500 users. This seems infrastructure-related. Please investigate."
        ),
        "expected_agent": "support_engineer",
        "description": "SupportEngineer investigates API Gateway 400 errors",
    },
    "sentry_errors": {
        "message": "/SupportEngineer check Sentry for recent errors and provide a summary",
        "expected_agent": "support_engineer",
        "description": "SupportEngineer checks Sentry for errors",
    },
    "github_issues": {
        "message": "/SoftwareEngineer list the top 3 open GitHub issues",
        "expected_agent": "software_engineer",
        "description": "SoftwareEngineer lists GitHub issues",
    },
    "release_status": {
        "message": "/ReleaseEngineer what is the current deployment status?",
        "expected_agent": "release_engineer",
        "description": "ReleaseEngineer checks deployment status",
    },
    "feature_request": {
        "message": "/ProductManager analyze this feature request: Add dark mode support",
        "expected_agent": "product_manager",
        "description": "ProductManager analyzes feature request",
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
# Azure DeepEval Model
# ==============================================================================


class AzureOpenAIModel(DeepEvalBaseLLM if DEEPEVAL_AVAILABLE else object):
    """Azure OpenAI model for DeepEval G-Eval metrics."""

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
        self._model = model

    def load_model(self):
        return self

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate completion using Azure OpenAI."""
        url = f"{self.api_base}/openai/deployments/{self._model}/chat/completions"

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                url,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                params={"api-version": self.api_version},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def a_generate(self, prompt: str, **kwargs) -> str:
        """Async generate - calls sync version."""
        return self.generate(prompt, **kwargs)

    def get_model_name(self) -> str:
        return f"azure/{self._model}"


# ==============================================================================
# G-Eval Metrics
# ==============================================================================


def create_investigation_quality_metric(model):
    """Create G-Eval metric for investigation quality."""
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="InvestigationQuality",
        criteria=(
            "Did the agent ACTUALLY investigate the reported issue? "
            "A proper investigation MUST include: "
            "(1) Using tools to check error tracking (Sentry), logs, or metrics - not just saying they would check; "
            "(2) Reporting SPECIFIC findings from the investigation (error messages, stack traces, affected endpoints); "
            "(3) Either resolving the issue OR handing off to another agent with specific technical details. "
            "A generic 'triage checklist' or 'here's what I would do' response is a FAILURE."
        ),
        evaluation_steps=[
            "Check if the agent used any tools (Sentry, logs, kubectl, etc.)",
            "Verify the agent reported SPECIFIC findings (actual error messages, specific endpoints)",
            "Check if the response contains actual investigation results vs generic advice",
            "If no specific findings, score should be LOW (< 0.5)",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.70,
        model=model,
    )


def create_task_completion_metric(model):
    """Create G-Eval metric for task completion."""
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="TaskCompletion",
        criteria=(
            "Did the agent complete the requested task or make meaningful progress? "
            "The agent should: "
            "(1) Address the specific request in the message; "
            "(2) Provide actionable output (not just acknowledgment); "
            "(3) Use appropriate tools if needed for the task."
        ),
        evaluation_steps=[
            "Check if the agent addressed the specific request",
            "Verify the agent provided actionable output",
            "Check if tools were used appropriately",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.60,
        model=model,
    )


# ==============================================================================
# Core Functions
# ==============================================================================


def post_message_and_wait(
    slack: SlackConnector,
    channel: str,
    message: str,
    timeout: int = DEFAULT_TIMEOUT,
    poll_interval: int = POLL_INTERVAL,
) -> tuple[str, list[dict]]:
    """
    Post a message to Slack and wait for agent responses.

    Returns:
        Tuple of (thread_ts, list of response messages)
    """
    print(f"\n>>> Posting message to Slack channel {channel}")
    print(f"    Message: {message[:100]}...")

    # Post the message
    result = slack.post_message(channel=channel, text=message)
    thread_ts = result.ts
    print(f"    Thread TS: {thread_ts}")

    # Wait for responses
    print(f"\n>>> Waiting for agent responses (timeout: {timeout}s)")
    start_time = time.time()
    responses = []
    last_message_count = 0

    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)

        # Get thread replies
        thread_messages = slack.get_thread_replies(
            channel=channel,
            thread_ts=thread_ts,
            limit=50,
        )

        # Filter to only bot responses (exclude our original message)
        bot_responses = [m for m in thread_messages if m.is_bot and m.ts != thread_ts]

        if len(bot_responses) > last_message_count:
            # New response(s) received
            for msg in bot_responses[last_message_count:]:
                print(f"    [{elapsed}s] Bot response: {msg.text[:80]}...")
                responses.append(
                    {
                        "ts": msg.ts,
                        "text": msg.text,
                        "user": msg.user,
                        "is_bot": msg.is_bot,
                    }
                )
            last_message_count = len(bot_responses)

            # Give a bit more time for potential handoffs
            time.sleep(poll_interval * 2)
        else:
            # Check if we should keep waiting
            if len(bot_responses) > 0:
                # We have at least one response, wait a bit more for handoffs
                if elapsed > 30:  # After 30s with response, we can stop
                    break
            print(f"    [{elapsed}s] Waiting...", end="\r")
            time.sleep(poll_interval)

    print(f"\n    Total responses: {len(responses)}")
    return thread_ts, responses


def build_conversation(
    user_message: str,
    responses: list[dict],
) -> list[tuple[str, str]]:
    """Build conversation from user message and responses."""
    conversation = [("user", user_message)]

    for resp in responses:
        # Try to extract role from message prefix like "[SupportEngineer]"
        text = resp["text"]
        role = "agent"

        for role_key, display in ROLE_DISPLAY.items():
            if text.startswith(f"[{display}]"):
                role = role_key
                text = text[len(f"[{display}]") :].strip()
                break

        conversation.append((role, text))

    return conversation


def evaluate_conversation(
    user_message: str,
    conversation: list[tuple[str, str]],
    model: AzureOpenAIModel,
) -> list[dict]:
    """Evaluate conversation with DeepEval G-Eval metrics."""
    if not DEEPEVAL_AVAILABLE:
        print("    DeepEval not available, skipping evaluation")
        return []

    # Build transcript
    transcript_lines = []
    for role, text in conversation:
        display = ROLE_DISPLAY.get(role, role.title())
        transcript_lines.append(f"[{display}] {text}")
    transcript = "\n\n".join(transcript_lines)

    # Create test case
    test_case = LLMTestCase(
        input=user_message,
        actual_output=transcript,
    )

    # Create metrics
    metrics = [
        create_investigation_quality_metric(model),
        create_task_completion_metric(model),
    ]

    results = []
    for metric in metrics:
        if metric is None:
            continue

        print(f"    Evaluating {metric.name}...")
        metric.measure(test_case)
        results.append(
            {
                "name": metric.name,
                "score": metric.score,
                "threshold": metric.threshold,
                "reason": metric.reason,
                "passed": metric.score >= metric.threshold,
            }
        )
        print(f"    {metric.name}: {metric.score:.2f} (threshold: {metric.threshold})")

    return results


def generate_markdown_report(
    scenario_name: str,
    channel: str,
    thread_ts: str,
    user_message: str,
    conversation: list[tuple[str, str]],
    metrics: list[dict],
    latency_ms: int,
) -> Path:
    """Generate markdown evaluation report with full conversation history."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{scenario_name}_{timestamp_str}.md"
    filepath = RESULTS_DIR / filename

    # Calculate overall pass/fail
    all_passed = all(m["passed"] for m in metrics) if metrics else False
    status_emoji = "✅" if all_passed else "❌"

    lines = [
        f"# Evaluation Report: {scenario_name}",
        "",
        f"**Status:** {status_emoji} {'PASSED' if all_passed else 'FAILED'}",
        f"**Timestamp:** {timestamp.isoformat()}",
        f"**Latency:** {latency_ms}ms",
        "",
        "---",
        "",
        "## Test Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Slack Channel | `{channel}` |",
        f"| Thread TS | `{thread_ts}` |",
        f"| Responses | {len(conversation) - 1} |",
        "",
        "---",
        "",
        "## Evaluation Metrics",
        "",
    ]

    if metrics:
        lines.extend(
            [
                "| Metric | Score | Threshold | Status |",
                "|--------|-------|-----------|--------|",
            ]
        )
        for m in metrics:
            status = "✅ Pass" if m["passed"] else "❌ Fail"
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
    else:
        lines.append("*No metrics evaluated (DeepEval not available)*")
        lines.append("")

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
            "*Generated by VibeTeam E2E Evaluation*",
        ]
    )

    report_content = "\n".join(lines)
    filepath.write_text(report_content)

    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="E2E Evaluation: Post to Slack and evaluate agent response",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Predefined scenarios:
{chr(10).join(f"  {k}: {v['description']}" for k, v in SCENARIOS.items())}

Examples:
  python scripts/eval_slack_agent.py --scenario api_gateway_error
  python scripts/eval_slack_agent.py --message "/SupportEngineer check Sentry"
  python scripts/eval_slack_agent.py --list-scenarios
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        help="Predefined evaluation scenario",
    )
    parser.add_argument(
        "--message",
        help="Custom message to send (overrides scenario)",
    )
    parser.add_argument(
        "--channel",
        default=os.getenv("SLACK_DEFAULT_CHANNEL", ""),
        help="Slack channel to post to",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip DeepEval evaluation (just post and collect responses)",
    )

    args = parser.parse_args()

    if args.list_scenarios:
        print("Available scenarios:")
        for name, scenario in SCENARIOS.items():
            print(f"  {name}:")
            print(f"    Message: {scenario['message'][:60]}...")
            print(f"    Agent: {scenario['expected_agent']}")
            print()
        return 0

    # Validate inputs
    if not args.message and not args.scenario:
        print("ERROR: Either --scenario or --message is required")
        parser.print_help()
        return 1

    if not args.channel:
        print("ERROR: --channel is required or set SLACK_DEFAULT_CHANNEL")
        return 1

    # Get message
    if args.message:
        message = args.message
        scenario_name = "custom"
    else:
        scenario = SCENARIOS[args.scenario]
        message = scenario["message"]
        scenario_name = args.scenario

    # Check Slack token
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    if not slack_token:
        print("ERROR: SLACK_BOT_TOKEN environment variable not set")
        return 1

    # Initialize Slack
    slack = SlackConnector()

    print("=" * 70)
    print("VIBETEAM E2E EVALUATION")
    print("=" * 70)
    print(f"Scenario: {scenario_name}")
    print(f"Channel: {args.channel}")
    print(f"Timeout: {args.timeout}s")
    print(f"DeepEval: {'Available' if DEEPEVAL_AVAILABLE else 'Not installed'}")

    # Step 1: Post and wait for responses
    start_time = time.time()
    thread_ts, responses = post_message_and_wait(
        slack=slack,
        channel=args.channel,
        message=message,
        timeout=args.timeout,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    if not responses:
        print("\n❌ No agent responses received!")
        print("   Make sure the Slack bot is running: python scripts/run_slack_bot.py")
        return 1

    # Step 2: Build conversation
    conversation = build_conversation(message, responses)
    print(f"\n>>> Conversation has {len(conversation)} messages")

    # Step 3: Evaluate with DeepEval
    metrics = []
    if not args.skip_eval and DEEPEVAL_AVAILABLE:
        print("\n>>> Evaluating with DeepEval G-Eval")

        api_key = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_API_KEY", ""))
        api_base = os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_API_BASE", ""))

        if api_key and api_base:
            model = AzureOpenAIModel(api_key=api_key, api_base=api_base)
            metrics = evaluate_conversation(message, conversation, model)
        else:
            print("    Azure credentials not set, skipping evaluation")

    # Step 4: Generate report
    print("\n>>> Generating evaluation report")
    report_path = generate_markdown_report(
        scenario_name=scenario_name,
        channel=args.channel,
        thread_ts=thread_ts,
        user_message=message,
        conversation=conversation,
        metrics=metrics,
        latency_ms=latency_ms,
    )
    print(f"    Report saved to: {report_path}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Thread: {args.channel} / {thread_ts}")
    print(f"Responses: {len(responses)}")
    print(f"Latency: {latency_ms}ms")

    if metrics:
        all_passed = all(m["passed"] for m in metrics)
        for m in metrics:
            status = "✅" if m["passed"] else "❌"
            print(f"{m['name']}: {m['score']:.2f} {status}")
        print(f"\nOverall: {'✅ PASSED' if all_passed else '❌ FAILED'}")
    else:
        print("No evaluation metrics (DeepEval not configured)")

    print(f"\nReport: {report_path}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
