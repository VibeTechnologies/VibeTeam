#!/usr/bin/env python3
"""
E2E Evaluation: Post to Slack, get agent response, evaluate with DeepEval.

This script:
1. Posts a message to Slack mentioning an agent (e.g., /SupportEngineer)
2. Waits for the agent to respond in the thread
3. Evaluates the response with DeepEval G-Eval metrics
4. Saves a markdown report with full conversation history

Usage:
    python scripts/eval_e2e_slack.py
    python scripts/eval_e2e_slack.py --scenario api_gateway_400
    python scripts/eval_e2e_slack.py --scenario feature_request --channel C0123456789
    python scripts/eval_e2e_slack.py --list-scenarios

Environment Variables:
    SLACK_BOT_TOKEN: Slack bot OAuth token (required)
    SLACK_DEFAULT_CHANNEL: Default channel to post to
    AZURE_API_KEY: Azure OpenAI API key (for agents and DeepEval)
    AZURE_API_BASE: Azure OpenAI endpoint
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vibeteam.connectors.slack import SlackConnector

# ==============================================================================
# Evaluation Scenarios
# ==============================================================================

SCENARIOS = {
    "api_gateway_400": {
        "name": "API Gateway 400 Errors",
        "description": "SupportEngineer investigates customer-reported 400 errors",
        "message": (
            "/SupportEngineer there is a request from a user who sees the issue with "
            "Vibe API Gateway returning 400 errors. Customer ACME Corp reports this "
            "started after the deployment at 8am. Multiple customers affected, about "
            "500 users. This seems infrastructure-related. Please investigate."
        ),
        "expected_agent": "SupportEngineer",
        "metrics": [
            {
                "name": "InvestigationQuality",
                "criteria": (
                    "Did the SupportEngineer ACTUALLY investigate the reported issue? "
                    "A proper investigation MUST include: "
                    "(1) Using tools to check error tracking (Sentry), logs, or metrics; "
                    "(2) Reporting SPECIFIC findings from the investigation; "
                    "(3) Either resolving the issue OR handing off with specific details."
                ),
                "threshold": 0.70,
            },
            {
                "name": "HandoffOrResolution",
                "criteria": (
                    "Did the agent either RESOLVE the issue or make a PROPER HANDOFF? "
                    "Resolution means: identified root cause AND provided fix. "
                    "Proper handoff means: mentioned /ReleaseEngineer or /SoftwareEngineer "
                    "with SPECIFIC technical context."
                ),
                "threshold": 0.70,
            },
        ],
    },
    "feature_request": {
        "name": "Feature Request Triage",
        "description": "ProductManager analyzes a feature request",
        "message": (
            "/ProductManager A customer from Enterprise tier requested: "
            "'We need the ability to export automation recordings as video files "
            "so we can share them with stakeholders who don't have VibeBrowser installed.' "
            "Please analyze priority and next steps."
        ),
        "expected_agent": "ProductManager",
        "metrics": [
            {
                "name": "AnalysisQuality",
                "criteria": (
                    "Did the ProductManager provide a thorough analysis? "
                    "Should include: priority assessment, user value analysis, "
                    "implementation considerations, and clear next steps."
                ),
                "threshold": 0.70,
            },
        ],
    },
    "deployment_request": {
        "name": "Deployment Request",
        "description": "ReleaseEngineer handles deployment to staging",
        "message": (
            "/ReleaseEngineer Please deploy the latest changes from PR #142 to staging. "
            "The PR includes the new authentication flow. "
            "Make sure to run smoke tests after deployment."
        ),
        "expected_agent": "ReleaseEngineer",
        "metrics": [
            {
                "name": "DeploymentProcess",
                "criteria": (
                    "Did the ReleaseEngineer follow proper deployment process? "
                    "Should include: checking PR status, deployment steps, "
                    "verification/smoke tests, and status update."
                ),
                "threshold": 0.70,
            },
        ],
    },
    "github_issue": {
        "name": "GitHub Issue Investigation",
        "description": "SoftwareEngineer investigates a bug report",
        "message": (
            "/SoftwareEngineer There's a bug report in GitHub issue #89 about "
            "the browser extension crashing when processing large forms. "
            "Can you investigate and propose a fix?"
        ),
        "expected_agent": "SoftwareEngineer",
        "metrics": [
            {
                "name": "InvestigationQuality",
                "criteria": (
                    "Did the SoftwareEngineer properly investigate the issue? "
                    "Should include: reviewing the issue details, analyzing root cause, "
                    "and proposing a concrete fix or solution."
                ),
                "threshold": 0.70,
            },
        ],
    },
}


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class ConversationMessage:
    """A single message in the conversation."""

    role: str
    text: str
    timestamp: str
    is_bot: bool = False


@dataclass
class EvalResult:
    """Result from a single metric evaluation."""

    name: str
    score: float
    threshold: float
    reason: str
    passed: bool


@dataclass
class EvalReport:
    """Complete evaluation report."""

    scenario_name: str
    scenario_description: str
    slack_channel: str
    thread_ts: str
    timestamp: datetime
    user_message: str
    conversation: list[ConversationMessage] = field(default_factory=list)
    metrics: list[EvalResult] = field(default_factory=list)
    agents_responded: list[str] = field(default_factory=list)
    wait_time_seconds: float = 0.0
    overall_passed: bool = False


# ==============================================================================
# DeepEval Integration
# ==============================================================================


def create_geval_metric(name: str, criteria: str, threshold: float, model: Any):
    """Create a G-Eval metric for evaluation."""
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams

        return GEval(
            name=name,
            criteria=criteria,
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=threshold,
            model=model,
        )
    except ImportError:
        return None


def evaluate_with_deepeval(
    user_message: str,
    conversation: list[ConversationMessage],
    metric_configs: list[dict],
) -> list[EvalResult]:
    """Evaluate conversation with DeepEval G-Eval metrics."""
    try:
        from deepeval.test_case import LLMTestCase
        from deepeval.models import DeepEvalBaseLLM
    except ImportError:
        print("WARNING: DeepEval not installed. Skipping evaluation.")
        return []

    # Build transcript
    transcript_lines = []
    for msg in conversation:
        role_display = msg.role.title() if not msg.is_bot else f"🤖 {msg.role}"
        transcript_lines.append(f"[{role_display}]\n{msg.text}")
    transcript = "\n\n".join(transcript_lines)

    # Create Azure model for evaluation
    class AzureEvalModel(DeepEvalBaseLLM):
        def __init__(self):
            self.model_name = os.getenv("BENCHMARK_JUDGE_MODEL", "gpt-5-2")

        def load_model(self):
            return self

        def generate(self, prompt: str, **kwargs) -> str:
            import litellm

            response = litellm.completion(
                model=f"azure/{self.model_name}",
                messages=[{"role": "user", "content": prompt}],
                api_base=os.environ["AZURE_API_BASE"],
                api_key=os.environ["AZURE_API_KEY"],
                api_version=os.environ.get("AZURE_API_VERSION", "2024-12-01-preview"),
                temperature=0.1,
                max_tokens=2000,
            )
            return response.choices[0].message.content

        async def a_generate(self, prompt: str, **kwargs) -> str:
            return self.generate(prompt, **kwargs)

        def get_model_name(self) -> str:
            return self.model_name

    model = AzureEvalModel()

    # Create test case
    test_case = LLMTestCase(
        input=user_message,
        actual_output=transcript,
    )

    # Evaluate each metric
    results = []
    for config in metric_configs:
        metric = create_geval_metric(
            name=config["name"],
            criteria=config["criteria"],
            threshold=config["threshold"],
            model=model,
        )
        if metric:
            try:
                metric.measure(test_case)
                results.append(
                    EvalResult(
                        name=config["name"],
                        score=metric.score,
                        threshold=config["threshold"],
                        reason=metric.reason,
                        passed=metric.score >= config["threshold"],
                    )
                )
            except Exception as e:
                print(f"WARNING: Metric {config['name']} failed: {e}")
                results.append(
                    EvalResult(
                        name=config["name"],
                        score=0.0,
                        threshold=config["threshold"],
                        reason=f"Evaluation error: {e}",
                        passed=False,
                    )
                )

    return results


# ==============================================================================
# Report Generation
# ==============================================================================


def generate_markdown_report(report: EvalReport, output_dir: Path) -> Path:
    """Generate a markdown evaluation report."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = report.timestamp.strftime("%Y%m%d_%H%M%S")
    scenario_slug = report.scenario_name.lower().replace(" ", "_")
    filename = f"eval_{scenario_slug}_{timestamp_str}.md"
    filepath = output_dir / filename

    status_emoji = "✅" if report.overall_passed else "❌"

    lines = [
        f"# Evaluation Report: {report.scenario_name}",
        "",
        f"**Status:** {status_emoji} {'PASSED' if report.overall_passed else 'FAILED'}",
        f"**Timestamp:** {report.timestamp.isoformat()}",
        f"**Wait Time:** {report.wait_time_seconds:.1f}s",
        "",
        "---",
        "",
        "## Scenario",
        "",
        f"**Description:** {report.scenario_description}",
        "",
        "## Test Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Slack Channel | `{report.slack_channel}` |",
        f"| Thread TS | `{report.thread_ts}` |",
        f"| Agents Responded | {', '.join(report.agents_responded) or 'None'} |",
        "",
        "---",
        "",
        "## Evaluation Metrics",
        "",
    ]

    if report.metrics:
        lines.extend(
            [
                "| Metric | Score | Threshold | Status |",
                "|--------|-------|-----------|--------|",
            ]
        )
        for m in report.metrics:
            status = "✅ Pass" if m.passed else "❌ Fail"
            lines.append(f"| {m.name} | {m.score:.2f} | {m.threshold:.2f} | {status} |")

        lines.extend(
            [
                "",
                "### Metric Reasoning",
                "",
            ]
        )
        for m in report.metrics:
            lines.extend(
                [
                    f"#### {m.name}",
                    "",
                    f"> {m.reason}",
                    "",
                ]
            )
    else:
        lines.append("*No metrics evaluated (DeepEval not available or no responses)*")
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
            report.user_message,
            "```",
            "",
            "### Full Conversation",
            "",
        ]
    )

    for i, msg in enumerate(report.conversation, 1):
        role_emoji = "👤" if msg.role == "user" else "🤖"
        lines.extend(
            [
                f"#### {i}. {role_emoji} {msg.role.title()}",
                "",
                f"*{msg.timestamp}*",
                "",
                "```",
                msg.text,
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


def generate_json_report(report: EvalReport, output_dir: Path) -> Path:
    """Generate a JSON evaluation report."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = report.timestamp.strftime("%Y%m%d_%H%M%S")
    scenario_slug = report.scenario_name.lower().replace(" ", "_")
    filename = f"eval_{scenario_slug}_{timestamp_str}.json"
    filepath = output_dir / filename

    data = {
        "scenario_name": report.scenario_name,
        "scenario_description": report.scenario_description,
        "slack_channel": report.slack_channel,
        "thread_ts": report.thread_ts,
        "timestamp": report.timestamp.isoformat(),
        "user_message": report.user_message,
        "conversation": [
            {
                "role": msg.role,
                "text": msg.text,
                "timestamp": msg.timestamp,
                "is_bot": msg.is_bot,
            }
            for msg in report.conversation
        ],
        "metrics": [
            {
                "name": m.name,
                "score": m.score,
                "threshold": m.threshold,
                "reason": m.reason,
                "passed": m.passed,
            }
            for m in report.metrics
        ],
        "agents_responded": report.agents_responded,
        "wait_time_seconds": report.wait_time_seconds,
        "overall_passed": report.overall_passed,
    }

    filepath.write_text(json.dumps(data, indent=2))
    return filepath


# ==============================================================================
# Main Evaluation Flow
# ==============================================================================


def run_evaluation(
    scenario_key: str,
    channel: str | None = None,
    wait_timeout: int = 120,
    poll_interval: int = 5,
    output_dir: str = "results/eval_reports",
) -> EvalReport:
    """Run a full E2E evaluation."""
    if scenario_key not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario: {scenario_key}. Use --list-scenarios to see available options."
        )

    scenario = SCENARIOS[scenario_key]
    print(f"\n{'=' * 70}")
    print(f"E2E EVALUATION: {scenario['name']}")
    print(f"{'=' * 70}")
    print(f"Description: {scenario['description']}")
    print()

    # Initialize Slack connector
    slack = SlackConnector()
    channel = channel or os.getenv("SLACK_DEFAULT_CHANNEL") or os.getenv("SLACK_CHANNEL")
    if not channel:
        raise ValueError("No Slack channel specified. Use --channel or set SLACK_DEFAULT_CHANNEL")

    print(f">>> Step 1: Posting message to Slack channel {channel}")
    print(f"    Message: {scenario['message'][:80]}...")

    # Post message
    initial_msg = slack.post_message(
        channel=channel,
        text=scenario["message"],
    )
    thread_ts = initial_msg.ts
    print(f"    Posted. Thread TS: {thread_ts}")

    # Initialize report
    report = EvalReport(
        scenario_name=scenario["name"],
        scenario_description=scenario["description"],
        slack_channel=channel,
        thread_ts=thread_ts,
        timestamp=datetime.now(timezone.utc),
        user_message=scenario["message"],
    )
    report.conversation.append(
        ConversationMessage(
            role="user",
            text=scenario["message"],
            timestamp=datetime.now(timezone.utc).isoformat(),
            is_bot=False,
        )
    )

    # Wait for agent responses
    print(f"\n>>> Step 2: Waiting for agent responses (timeout: {wait_timeout}s)")
    start_time = time.time()
    last_message_count = 0

    while time.time() - start_time < wait_timeout:
        elapsed = time.time() - start_time
        print(f"    [{elapsed:.0f}s] Polling for responses...", end="\r")

        # Get thread messages
        try:
            messages = slack.get_thread_replies(
                channel=channel,
                thread_ts=thread_ts,
                limit=50,
            )
        except Exception as e:
            print(f"\n    WARNING: Failed to get thread: {e}")
            time.sleep(poll_interval)
            continue

        # Check for new bot messages
        bot_messages = [m for m in messages if m.is_bot and m.ts != thread_ts]

        if len(bot_messages) > last_message_count:
            for msg in bot_messages[last_message_count:]:
                # Extract agent name from message (e.g., "[SupportEngineer] ...")
                agent_name = "Agent"
                if msg.text.startswith("[") and "]" in msg.text:
                    agent_name = msg.text.split("]")[0].strip("[")

                report.conversation.append(
                    ConversationMessage(
                        role=agent_name,
                        text=msg.text,
                        timestamp=msg.ts,
                        is_bot=True,
                    )
                )
                if agent_name not in report.agents_responded:
                    report.agents_responded.append(agent_name)

                print(f"\n    ✓ Got response from {agent_name} ({len(msg.text)} chars)")

            last_message_count = len(bot_messages)

            # Wait a bit more in case of handoffs
            time.sleep(poll_interval)
        else:
            time.sleep(poll_interval)

        # Stop if we have responses and no new ones for a while
        if bot_messages and (time.time() - start_time) > 30:
            # Check if last message is recent (within last poll)
            break

    report.wait_time_seconds = time.time() - start_time
    print(f"\n    Done waiting. Got {len(report.agents_responded)} agent response(s).")

    # Evaluate with DeepEval
    print(f"\n>>> Step 3: Evaluating with DeepEval G-Eval")

    if len(report.conversation) > 1:  # More than just user message
        report.metrics = evaluate_with_deepeval(
            user_message=scenario["message"],
            conversation=report.conversation,
            metric_configs=scenario["metrics"],
        )

        for m in report.metrics:
            status = "✅" if m.passed else "❌"
            print(f"    {status} {m.name}: {m.score:.2f} (threshold: {m.threshold})")

        report.overall_passed = all(m.passed for m in report.metrics)
    else:
        print("    ⚠️  No agent responses received. Skipping evaluation.")
        report.overall_passed = False

    # Generate reports
    print(f"\n>>> Step 4: Generating reports")
    output_path = Path(output_dir)

    md_path = generate_markdown_report(report, output_path)
    print(f"    Markdown: {md_path}")

    json_path = generate_json_report(report, output_path)
    print(f"    JSON: {json_path}")

    # Summary
    print(f"\n{'=' * 70}")
    print("EVALUATION SUMMARY")
    print(f"{'=' * 70}")
    print(f"Scenario: {report.scenario_name}")
    print(f"Status: {'✅ PASSED' if report.overall_passed else '❌ FAILED'}")
    print(f"Agents: {', '.join(report.agents_responded) or 'None'}")
    print(f"Messages: {len(report.conversation)}")
    print(f"Wait Time: {report.wait_time_seconds:.1f}s")
    if report.metrics:
        print(f"Metrics:")
        for m in report.metrics:
            print(f"  - {m.name}: {m.score:.2f}")
    print(f"Report: {md_path}")
    print(f"{'=' * 70}\n")

    return report


def list_scenarios():
    """Print available scenarios."""
    print("\nAvailable Evaluation Scenarios:")
    print("-" * 50)
    for key, scenario in SCENARIOS.items():
        print(f"\n  {key}")
        print(f"    Name: {scenario['name']}")
        print(f"    Description: {scenario['description']}")
        print(f"    Agent: {scenario['expected_agent']}")
        print(f"    Metrics: {', '.join(m['name'] for m in scenario['metrics'])}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="E2E Evaluation: Post to Slack, get agent response, evaluate with DeepEval",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        default="api_gateway_400",
        help="Evaluation scenario to run (default: api_gateway_400)",
    )
    parser.add_argument(
        "--channel",
        help="Slack channel to post to (default: SLACK_DEFAULT_CHANNEL env var)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds to wait for agent responses (default: 120)",
    )
    parser.add_argument(
        "--output-dir",
        default="results/eval_reports",
        help="Directory to save evaluation reports (default: results/eval_reports)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available evaluation scenarios",
    )

    args = parser.parse_args()

    if args.list_scenarios:
        list_scenarios()
        return 0

    # Check required env vars
    required = ["SLACK_BOT_TOKEN", "AZURE_API_KEY", "AZURE_API_BASE"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("Run: source .env")
        return 1

    try:
        report = run_evaluation(
            scenario_key=args.scenario,
            channel=args.channel,
            wait_timeout=args.timeout,
            output_dir=args.output_dir,
        )
        return 0 if report.overall_passed else 1
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
