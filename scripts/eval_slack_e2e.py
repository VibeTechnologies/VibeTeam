#!/usr/bin/env python3
"""
E2E Slack Agent Evaluation Script.

Consolidated evaluation script (replaces eval_slack_agent.py).

This script runs a true end-to-end evaluation:
1. Posts a message to Slack mentioning an agent (e.g., @SupportEngineer)
2. Triggers the gateway's /slack/trigger endpoint to invoke agent processing
   (bot-posted messages don't generate Slack webhook events, so direct trigger is required)
3. Polls the thread for agent responses, including handoff chains
4. Evaluates the conversation with DeepEval G-Eval metrics
5. Saves detailed markdown report with full conversation history

Usage:
    python scripts/eval_slack_e2e.py --scenario support_400_errors
    python scripts/eval_slack_e2e.py --scenario stripe_webhook_failure --timeout 300
    python scripts/eval_slack_e2e.py --scenario support_400_errors --use-async
    python scripts/eval_slack_e2e.py --message "@SupportEngineer check Sentry for errors"
    python scripts/eval_slack_e2e.py --channel C0123456789 --skip-eval
    python scripts/eval_slack_e2e.py --list-scenarios
    python scripts/eval_slack_e2e.py --scenario stripe_webhook_failure --thread-ts 1770710833.425539 --channel C0AATPSADB8

Environment Variables:
    SLACK_BOT_TOKEN: Slack bot OAuth token (required)
    SLACK_DEFAULT_CHANNEL: Default channel for posting
    AZURE_API_KEY / AZURE_OPENAI_API_KEY: Azure OpenAI API key for G-Eval judge
    AZURE_API_BASE / AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint
    GATEWAY_URL: Gateway URL to trigger agents (default: https://webhook.team.vibebrowser.app)
    SLACK_TRIGGER_SECRET: Bearer token for /slack/trigger auth (must match gateway config)
    BENCHMARK_JUDGE_MODEL: Override the judge model for evaluation (default: gpt-5.2)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_service.shared.llm import resolve_azure_model
from agent_service.shared.role_resolver import ROLE_PATTERN, parse_role_mentions
from vibeteam.connectors.slack import SlackConnector

# Try to import DeepEval
DEEPEVAL_AVAILABLE = False
DeepEvalBaseLLM: type = object  # default base class when deepeval not installed
try:
    from deepeval.metrics import GEval
    from deepeval.models.base_model import DeepEvalBaseLLM  # type: ignore[assignment]
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    DEEPEVAL_AVAILABLE = True
except ImportError:
    print("WARNING: DeepEval not installed. Install with: uv add deepeval")
    print("         Evaluation will be skipped, only conversation will be collected.")

    if TYPE_CHECKING:
        from deepeval.metrics import GEval as GEval
        from deepeval.test_case import LLMTestCase as LLMTestCase
        from deepeval.test_case import LLMTestCaseParams as LLMTestCaseParams


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
                "Did the SupportEngineer ACTUALLY investigate and RESOLVE the issue? "
                "This is a STRICT evaluation - attempting tools that fail is NOT success. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Successfully query Sentry and report SPECIFIC error counts, patterns, stack traces; "
                "(2) Successfully access Kubernetes/infrastructure to check deployment state; "
                "(3) Identify the ROOT CAUSE with evidence from internal tools (not just external HTTP checks); "
                "(4) Take concrete action OR provide findings that enable resolution. "
                "SCORING: "
                "Score 0.0-0.2: No investigation or all tools failed with no useful findings. "
                "Score 0.2-0.4: Tools failed but agent made reasonable external observations. "
                "Score 0.4-0.6: Some tools worked, partial findings, but no root cause identified. "
                "Score 0.6-0.8: Tools worked, root cause identified, but no resolution. "
                "Score 0.8-1.0: Full investigation with tools, root cause found, and resolution provided. "
                "CRITICAL: If agent just says 'tools failed, someone else please help' repeatedly, "
                "score should be 0.2 or lower. External curl/HTTP checks alone are worth at most 0.3."
            ),
            "EvidenceBasedDecision": (
                "Did the agent make EVIDENCE-BASED decisions, not speculative ones? "
                "CRITICAL: If investigation shows NO errors, NO issues, healthy pods, clean logs - "
                "the agent should NOT recommend drastic actions like rollback. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Recommendations must be supported by actual findings from tools; "
                "(2) If no evidence of problems found, agent should report 'infrastructure healthy, no action needed'; "
                "(3) If recommending rollback, there MUST be evidence of issues (errors in logs, failing pods, Sentry alerts); "
                "(4) Agent should ask customer for more details (request IDs, timestamps) if no issues found. "
                "SCORING: "
                "Score 0.0-0.3: Recommended rollback/drastic action with NO evidence of problems. "
                "Score 0.3-0.5: Made speculative recommendations not supported by findings. "
                "Score 0.5-0.7: Recommendations loosely aligned with findings but some speculation. "
                "Score 0.7-0.9: Recommendations clearly tied to evidence found. "
                "Score 0.9-1.0: Perfect alignment - actions match evidence, no unnecessary escalation. "
                "CRITICAL PENALTY: If agent found 'no errors, pods healthy, logs clean' but still recommended "
                "rollback, score should be 0.3 or lower - this is reckless escalation."
            ),
            "HandoffCompletion": (
                "If the agent handed off to another agent, did that handoff actually complete? "
                "CRITICAL: The agent should NOT hand off to themselves (e.g., SoftwareEngineer tagging @SoftwareEngineer). "
                "CRITICAL: A handoff that is never picked up is NOT a successful resolution. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If handoff was made, the target agent MUST have responded in the conversation; "
                "(2) The target agent must have taken meaningful action (not just acknowledged); "
                "(3) If no handoff response exists, the original agent should have followed up or resolved directly. "
                "SCORING: "
                "Score 0.0-0.2: Self-handoff (e.g., tagging own role) or handoff with NO response. "
                "Score 0.2-0.4: Handoff made but NO response from target agent - task left incomplete. "
                "Score 0.4-0.6: Handoff made, target acknowledged but took no action. "
                "Score 0.6-0.8: Handoff made, target responded with partial action. "
                "Score 0.8-0.9: Handoff completed with target taking appropriate action. "
                "Score 0.9-1.0: No handoff needed (resolved directly) OR handoff fully completed with resolution. "
                "NOTE: If only one agent responded and they completed the task without handoff, score 1.0. "
                "If only one agent responded and they made a handoff that was never picked up, score 0.2 max."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the agent's investigation was efficient and focused, "
                "avoiding unnecessary repetition, redundant tool usage, or circular handoffs. "
                "SCORING: "
                "Score 0.0-0.3: Circular handoffs or repeated tool calls with no new information. "
                "Score 0.3-0.5: Investigation unfocused with significant redundancy. "
                "Score 0.5-0.7: Somewhat verbose but reached a conclusion. "
                "Score 0.7-0.9: Focused investigation with clear, concise conclusion. "
                "Score 0.9-1.0: Highly efficient — minimal steps to reach an evidence-based conclusion."
            ),
        },
        "evaluation_steps": {
            "InvestigationQuality": [
                "Check if the agent queried Sentry for errors related to 400 errors or the API gateway",
                "Check if the agent used kubectl to inspect pod status, events, and logs",
                "Check if the agent identified a root cause with evidence from internal tools",
                "Check if the agent took concrete action or provided findings enabling resolution",
                "Score 0.0-0.2 if no investigation; 0.2-0.4 if external-only; 0.4-0.6 if partial tools; 0.6-0.8 if root cause found; 0.8-1.0 if full investigation with resolution",
            ],
            "EvidenceBasedDecision": [
                "Check if the agent's recommendations are supported by actual findings (not speculation)",
                "If no errors/issues found in tools, check that agent reported healthy infrastructure",
                "If agent recommended rollback, verify there was evidence of issues (failing pods, errors in logs)",
                "Score 0.0-0.3 if drastic action with no evidence; 0.5-0.7 if loosely aligned; 0.7-0.9 if clearly evidence-based; 0.9-1.0 if perfect alignment",
            ],
            "HandoffCompletion": [
                "Check if the agent completed the task without handoff (score 1.0) OR made a handoff that was picked up",
                "If handoff was made, check that the target agent responded and took meaningful action",
                "Check that the agent did NOT hand off to themselves",
                "Score 0.0-0.2 if self-handoff or no response; 0.2-0.4 if handoff abandoned; 0.6-0.8 if partial; 0.8-1.0 if complete",
            ],
            "ResponseEfficiency": [
                "Check for circular handoffs (agent A hands to B, B hands back to A without progress). Circular handoffs score <= 0.3.",
                "Check for truly redundant tool calls that re-run the exact same command and return the same information with no new parameters or angles. Identical-command repetition scores <= 0.5. NOTE: multiple curl calls with DIFFERENT parameters (GET vs POST, different headers, different endpoints) are NOT redundant — they are systematic debugging.",
                "Evaluate the final response: is it concise and actionable? Verbose low-signal responses score <= 0.6.",
                "Score 0.8-1.0 if investigation was focused and reached a clear conclusion. Score 0.5-0.7 if somewhat verbose but progressed logically. Score 0.0-0.5 if circular, truly redundant, or failed to converge on a finding.",
            ],
        },
        "threshold": 0.70,
    },
    "support_notify_check": {
        "name": "Support Engineer - Notification Request",
        "message": (
            "@SupportEngineer please notify the team that the deployment of PR #123 "
            "to staging is complete and verified."
        ),
        "expected_agent": "support_engineer",
        "evaluation_criteria": {
            "NotificationOnly": (
                "Did the SupportEngineer JUST notify without investigating? "
                "REQUIRED: "
                "(1) Confirm the message acknowledges the request; "
                "(2) Confirm NO investigation steps (Sentry/kubectl) were taken; "
                "(3) Confirm the output is a clear notification message. "
                "Score 0.0-0.3 if it tries to investigate or check Sentry."
            ),
        },
        "threshold": 0.80,
    },
    "support_sentry_triage": {
        "name": "Support Engineer - Sentry Triage Check",
        "message": "@VibeTeam @SupportEngineer. Check Sentry issues. Anything to address?",
        "expected_agent": "support_engineer",
        "timeout": 600,
        "skip_handoff": True,
        "evaluation_criteria": {
            "SentryUsage": (
                "Did the SupportEngineer actually check Sentry and report findings? "
                "REQUIRED: "
                "(1) Explicit mention of Sentry check; "
                "(2) Either list specific issues (IDs/messages/counts) OR clearly state no issues found. "
                "CRITICAL: If the response says Sentry is not configured or errors out, score 0.3 or lower. "
                "SCORING: "
                "Score 0.0-0.3: No Sentry mention or generic response. "
                "Score 0.3-0.6: Mentions Sentry but no concrete findings. "
                "Score 0.6-0.8: Reports Sentry findings or confirms none. "
                "Score 0.8-1.0: Clear, specific Sentry findings with context."
            ),
            "TaskCompletion": (
                "Did the agent answer 'Anything to address?' based on findings? "
                "REQUIRED: "
                "(1) Clear yes/no or action recommendation; "
                "(2) Tied to the Sentry findings. "
                "SCORING: "
                "Score 0.0-0.3: No answer to the question. "
                "Score 0.3-0.6: Vague answer without tying to Sentry. "
                "Score 0.6-0.8: Clear answer tied to findings. "
                "Score 0.8-1.0: Clear answer plus next steps or monitoring guidance."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused. "
                "SCORING: "
                "Score 0.0-0.3: Rambling or off-topic. "
                "Score 0.3-0.5: Some redundancy. "
                "Score 0.5-0.7: Reasonably concise. "
                "Score 0.7-0.9: Focused and efficient. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "SentryUsage": [
                "Check for explicit Sentry mention.",
                "Check for issue IDs/messages/counts OR explicit 'no issues found'.",
                "Score <= 0.3 if Sentry not mentioned or if it says Sentry is not configured.",
            ],
            "TaskCompletion": [
                "Check that the response directly answers whether there's anything to address.",
                "Verify the answer is tied to Sentry findings.",
            ],
            "ResponseEfficiency": [
                "Check that the response is concise and directly answers the request.",
            ],
        },
        "threshold": 0.70,
    },
    "support_sentry_to_pr": {
        "name": "Support Engineer - Sentry Review to PR",
        "message": (
            "@VibeTeam @SupportEngineer review Sentry issues and address anything urgent. "
            "If you see a bug, create a PR and close the Sentry issue."
        ),
        "expected_agent": "support_engineer",
        "timeout": 600,
        "post_checks": {
            "github_pr_created": True,
            "sentry_issue_closed": True,
        },
        "evaluation_criteria": {
            "SentryUsage": (
                "Did the SupportEngineer actually check Sentry and report findings? "
                "REQUIRED: "
                "(1) Explicit mention of Sentry check; "
                "(2) Either list specific issues (IDs/messages/counts) OR clearly state no issues found. "
                "CRITICAL: If the response says Sentry is not configured or errors out, score 0.3 or lower. "
                "SCORING: "
                "Score 0.0-0.3: No Sentry mention or generic response. "
                "Score 0.3-0.6: Mentions Sentry but no concrete findings. "
                "Score 0.6-0.8: Reports Sentry findings or confirms none. "
                "Score 0.8-1.0: Clear, specific Sentry findings with context."
            ),
            "TaskCompletion": (
                "Did the agent address issues, create a PR, and close the Sentry issue? "
                "REQUIRED: "
                "(1) Clear yes/no on issues to address; "
                "(2) If issues exist, triage and take action; "
                "(3) If a bug is identified, PR created and Sentry issue closed, OR explicit handoff with evidence; "
                "(4) If no issues, explicitly state nothing to address and no PR needed. "
                "SCORING: "
                "Score 0.0-0.3: No action or no answer to the question. "
                "Score 0.3-0.6: Sentry checked but no clear action or next steps. "
                "Score 0.6-0.8: Clear answer tied to findings with actionable next steps. "
                "Score 0.8-1.0: PR created and Sentry issue closed (or well-scoped handoff) with evidence."
            ),
            "EvidenceBasedDecision": (
                "Did the agent make evidence-based decisions (no speculative PRs)? "
                "REQUIRED: "
                "(1) If PR is created, cite the Sentry issue or code evidence; "
                "(2) If no issues found, do NOT propose a PR; "
                "(3) Recommendations should align with actual findings. "
                "SCORING: "
                "Score 0.0-0.3: PR suggested without evidence or no Sentry check. "
                "Score 0.3-0.6: Some evidence but weak linkage. "
                "Score 0.6-0.8: Actions aligned with findings. "
                "Score 0.8-1.0: Strong, explicit evidence linkage to actions."
            ),
            "HandoffCompletion": (
                "If the agent handed off to another agent, did that handoff actually complete? "
                "CRITICAL: The agent should NOT hand off to themselves (e.g., SupportEngineer tagging @SupportEngineer). "
                "CRITICAL: A handoff that is never picked up is NOT a successful resolution. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If handoff was made, the target agent MUST have responded in the conversation; "
                "(2) The target agent must have taken meaningful action (not just acknowledged); "
                "(3) If no handoff response exists, the original agent should have followed up or resolved directly. "
                "SCORING: "
                "Score 0.0-0.2: Self-handoff or handoff with NO response. "
                "Score 0.2-0.4: Handoff made but NO response from target agent. "
                "Score 0.4-0.6: Handoff made, target acknowledged but took no action. "
                "Score 0.6-0.8: Handoff made, target responded with partial action. "
                "Score 0.8-0.9: Handoff completed with target taking appropriate action. "
                "Score 0.9-1.0: No handoff needed (resolved directly) OR handoff fully completed."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused. "
                "SCORING: "
                "Score 0.0-0.3: Rambling or off-topic. "
                "Score 0.3-0.5: Some redundancy. "
                "Score 0.5-0.7: Reasonably concise. "
                "Score 0.7-0.9: Focused and efficient. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "SentryUsage": [
                "Check for explicit Sentry mention.",
                "Check for issue IDs/messages/counts OR explicit 'no issues found'.",
                "Score <= 0.3 if Sentry not mentioned or if it says Sentry is not configured.",
            ],
            "TaskCompletion": [
                "Check that the response directly answers whether there is anything to address.",
                "Verify the answer is tied to Sentry findings.",
                "If a bug is identified, check for PR creation and Sentry issue closure or explicit handoff with evidence.",
            ],
            "EvidenceBasedDecision": [
                "Check that actions are supported by Sentry findings.",
                "If no issues found, ensure no PR is proposed.",
            ],
            "HandoffCompletion": [
                "Check if the agent completed the task without handoff (score 1.0) OR made a handoff that was picked up.",
                "If handoff was made, check that the target agent responded and took meaningful action.",
                "Check that the agent did NOT hand off to themselves (self-tagging).",
            ],
            "ResponseEfficiency": [
                "Check that the response is concise and directly answers the request.",
            ],
        },
        "threshold": 0.70,
    },
    "support_vibe_dev_health": {
        "name": "Support Engineer - vibe-dev Health and Logs Validation",
        "message": (
            "@VibeTeam @SupportEngineer validate vibe-dev namespace health now. "
            "Run kubectl checks for pods, deployments, and events. "
            "If any workloads are unhealthy, inspect recent logs and summarize severity "
            "with evidence."
        ),
        "expected_agent": "support_engineer",
        "timeout": 600,
        "skip_handoff": True,
        "evaluation_criteria": {
            "NamespaceCoverage": (
                "Did the SupportEngineer explicitly validate the vibe-dev namespace "
                "with concrete kubectl evidence? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of vibe-dev; "
                "(2) Evidence from pods/deployments/events checks (or explicit 'no resources found'); "
                "(3) Findings tied to the observed namespace state. "
                "SCORING: "
                "Score 0.0-0.3: No vibe-dev check or generic response. "
                "Score 0.3-0.6: Mentions vibe-dev but little/no concrete evidence. "
                "Score 0.6-0.8: Provides concrete namespace evidence and summary. "
                "Score 0.8-1.0: Complete, evidence-based namespace validation."
            ),
            "HealthAndLogs": (
                "Did the agent evaluate health and logs appropriately based on what exists? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If unhealthy workloads exist, includes relevant logs/events evidence; "
                "(2) If namespace is empty, explicitly states no workloads and therefore no logs; "
                "(3) Severity assessment is consistent with evidence. "
                "SCORING: "
                "Score 0.0-0.3: No health/log assessment. "
                "Score 0.3-0.6: Partial assessment without clear evidence. "
                "Score 0.6-0.8: Correct assessment with evidence. "
                "Score 0.8-1.0: Correct, complete assessment with clear severity."
            ),
            "ResponseEfficiency": (
                "Was the response concise, focused, and non-speculative? "
                "SCORING: "
                "Score 0.0-0.3: Rambling, speculative, or contradictory. "
                "Score 0.3-0.5: Some redundancy or unclear conclusion. "
                "Score 0.5-0.7: Reasonably concise with clear conclusion. "
                "Score 0.7-0.9: Focused and efficient. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "NamespaceCoverage": [
                "Check for explicit vibe-dev mention and concrete kubectl-derived evidence.",
                "Accept explicit 'no resources found' as valid evidence when namespace is empty.",
                "Score <= 0.3 if vibe-dev is not validated.",
            ],
            "HealthAndLogs": [
                "If workloads are unhealthy, check for logs/events evidence and severity.",
                "If namespace is empty, check that the agent clearly states no workloads/logs.",
                "Penalize fabricated or speculative failures without evidence.",
            ],
            "ResponseEfficiency": [
                "Check that the response is concise and directly answers health/log status.",
            ],
        },
        "threshold": 0.70,
    },
    "software_engineer_pr_attribution": {
        "name": "Software Engineer - PR Attribution (GitHub App)",
        "message": (
            "@VibeTeam @SoftwareEngineer please create a small PR in VibeWebAgent "
            "that fixes a trivial issue (docs or comment). Include the PR URL in your reply "
            "so we can verify GitHub App attribution."
        ),
        "expected_agent": "software_engineer",
        "timeout": 600,
        "post_checks": {
            "github_pr_created": True,
            "github_pr_author_is_bot": True,
        },
        "evaluation_criteria": {
            "TaskCompletion": (
                "Did the SoftwareEngineer create a PR and provide the PR URL? "
                "REQUIRED: "
                "(1) PR exists and is accessible; "
                "(2) PR URL included in response; "
                "(3) Response confirms the change made. "
                "SCORING: "
                "Score 0.0-0.3: No PR or no URL. "
                "Score 0.3-0.6: PR mentioned but missing URL or unclear change. "
                "Score 0.6-0.8: PR created with URL and summary. "
                "Score 0.8-1.0: PR created with URL, clear summary, and verification notes."
            ),
            "EvidenceBasedDecision": (
                "Did the response include concrete evidence (PR URL, summary) rather than speculation? "
                "SCORING: "
                "Score 0.0-0.3: Vague claims, no evidence. "
                "Score 0.3-0.6: Some evidence but incomplete. "
                "Score 0.6-0.8: Clear evidence with PR URL. "
                "Score 0.8-1.0: Strong evidence with PR URL and concise summary."
            ),
            "ResponseEfficiency": (
                "Is the response concise and focused? "
                "SCORING: "
                "Score 0.0-0.3: Rambling or off-topic. "
                "Score 0.3-0.6: Some unnecessary detail. "
                "Score 0.6-0.8: Mostly concise. "
                "Score 0.8-1.0: Direct and minimal."
            ),
        },
        "threshold": 0.70,
    },
    "software_engineer_github_app_hello_world": {
        "name": "Software Engineer - GitHub App Hello World Repo",
        "message": (
            "@VibeTeam @SoftwareEngineer please create (or reuse if it already exists) "
            "the repo VibeTechnologies/vibeteam-eval-hello-world. Add a simple Python "
            "hello world app (e.g., main.py prints 'Hello, world!'), open a PR with the "
            "changes, and include the PR URL in your reply. Use the SoftwareEngineer "
            "GitHub App credentials (role bot), not a personal PAT."
        ),
        "expected_agent": "software_engineer",
        "post_checks": {
            "github_pr_created": True,
            "github_pr_author_is_bot": True,
            "github_pr_target_repo": "VibeTechnologies/vibeteam-eval-hello-world",
        },
        "evaluation_criteria": {
            "TaskCompletion": (
                "Did the SoftwareEngineer create a PR in the expected repo and provide the PR URL? "
                "REQUIRED: "
                "(1) PR URL included in response; "
                "(2) PR targets VibeTechnologies/vibeteam-eval-hello-world; "
                "(3) Response confirms the hello world implementation. "
                "SCORING: "
                "Score 0.0-0.3: No PR or no URL. "
                "Score 0.3-0.6: PR mentioned but wrong repo or unclear change. "
                "Score 0.6-0.8: PR created with URL and summary. "
                "Score 0.8-1.0: PR created with URL, clear summary, and run instructions."
            ),
            "GitHubAppUsage": (
                "Did the response align with GitHub App attribution (role bot) rather than a personal PAT? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) No mention of using a personal PAT; "
                "(2) Mentions role bot/GitHub App usage OR evidence consistent with bot attribution. "
                "SCORING: "
                "Score 0.0-0.3: Mentions PAT or personal account usage. "
                "Score 0.3-0.6: No mention of auth method. "
                "Score 0.6-0.8: Mentions GitHub App or bot identity. "
                "Score 0.8-1.0: Mentions GitHub App/bot and ties it to the PR link."
            ),
            "ResponseEfficiency": (
                "Is the response concise and focused? "
                "SCORING: "
                "Score 0.0-0.3: Rambling or off-topic. "
                "Score 0.3-0.6: Some unnecessary detail. "
                "Score 0.6-0.8: Mostly concise. "
                "Score 0.8-1.0: Direct and minimal."
            ),
        },
        "threshold": 0.70,
    },
    "github_issue_pr_handoff_slack": {
        "name": "GitHub Handoff - Issue + PR Comments (Slack Trigger)",
        "message": (
            "@VibeTeam @SoftwareEngineer please do GitHub coordination ONLY in "
            "VibeTechnologies/vibeteam-eval-hello-world (do NOT use VibeTeam or any other repo). "
            "Use these threads: "
            "Issue: https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/3 "
            "PR: https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1 "
            "1) Add an issue comment summarizing the plan. "
            "Include @SupportEngineer in the issue comment to request a follow-up. "
            "2) Add a PR comment summarizing the plan and include @SupportEngineer there too. "
            "Reply in Slack confirming both comments were posted."
        ),
        "expected_agent": "software_engineer",
        "timeout": 600,
        "post_checks": {
            "github_issue_multi_bot_comments": True,
            "github_pr_multi_bot_comments": True,
        },
        "evaluation_criteria": {
            "TaskCompletion": (
                "Did the SoftwareEngineer create the GitHub issue + PR comments and share URLs? "
                "REQUIRED: issue URL and PR URL present in the response, and comments exist in both threads."
            ),
            "HandoffCompletion": (
                "Did SupportEngineer post follow-up comments in the issue and PR threads? "
                "REQUIRED: at least two bot authors appear in both threads."
            ),
            "ResponseEfficiency": (
                "Is the response concise and focused? "
                "Score 0.8-1.0 for direct URLs + brief summary."
            ),
        },
        "metric_overrides": {
            "HandoffCompletion": [
                "github_issue_multi_bot_comments",
                "github_pr_multi_bot_comments",
            ],
        },
        "threshold": 0.70,
    },
    "support_gmail_inbox": {
        "name": "Support Engineer - Gmail Inbox Triage",
        "message": "@VibeTeam @SupportEngineer, check Gmail inbox, anything to address? If so, work on it.",
        "expected_agent": "support_engineer",
        "timeout": 600,
        "skip_handoff": True,
        "evaluation_criteria": {
            "GmailUsage": (
                "Did the SupportEngineer actually check Gmail inbox and report findings? "
                "REQUIRED: "
                "(1) Explicit mention of Gmail/inbox check; "
                "(2) Either list unread emails (subject/sender/date or IDs) OR clearly state no unread emails. "
                "If direct Gmail access is not configured, acceptable fallback is to cite "
                "gmail-processor logs or other system evidence with a concrete unread count. "
                "CRITICAL: If the response only says Gmail is not configured/errors without any "
                "concrete inbox evidence, score 0.3 or lower. "
                "SCORING: "
                "Score 0.0-0.3: No Gmail mention or generic response. "
                "Score 0.3-0.6: Mentions Gmail but no concrete findings. "
                "Score 0.6-0.8: Reports unread emails or confirms none. "
                "Score 0.8-1.0: Clear, specific inbox triage with actionable context."
            ),
            "TaskCompletion": (
                "Did the agent answer 'anything to address' and work on it if needed? "
                "REQUIRED: "
                "(1) Clear yes/no on items to address; "
                "(2) If items exist, draft replies or outline actions per email; "
                "(3) If no items, state inbox is clear. "
                "SCORING: "
                "Score 0.0-0.3: No answer to the question. "
                "Score 0.3-0.6: Vague answer without tying to inbox findings. "
                "Score 0.6-0.8: Clear answer tied to inbox findings. "
                "Score 0.8-1.0: Clear answer plus draft responses or next steps."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused. "
                "If direct Gmail access is unavailable, do not penalize inclusion of "
                "gmail-processor logs or brief infra status that directly explains the inbox state. "
                "SCORING: "
                "Score 0.0-0.3: Rambling or off-topic. "
                "Score 0.3-0.5: Some redundancy. "
                "Score 0.5-0.7: Reasonably concise. "
                "Score 0.7-0.9: Focused and efficient. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "GmailUsage": [
                "Check for explicit Gmail/inbox mention.",
                "Check for unread email details OR explicit 'no unread emails'.",
                "If Gmail access is not configured, require concrete unread count evidence from gmail-processor logs.",
                "Score <= 0.3 if Gmail not mentioned or if it says Gmail is not configured with no evidence.",
            ],
            "TaskCompletion": [
                "Check that the response directly answers whether there's anything to address.",
                "Verify it is tied to inbox findings and includes draft actions if needed.",
            ],
            "ResponseEfficiency": [
                "Check that the response is concise and directly answers the request.",
            ],
        },
        "threshold": 0.70,
    },
    "chrome_cdp_smoke": {
        "name": "Marketing Manager - Chrome CDP MCP Smoke Test",
        "message": (
            "@MarketingManager use Chrome DevTools MCP (CDP) to open https://example.com, "
            "take a full-page screenshot, and report: (1) the page title, (2) the number "
            "of console errors, and (3) the HTTP status code of the main document request. "
            "Confirm in your response that the CDP/DevTools tools were used."
        ),
        "expected_agent": "marketing_manager",
        "timeout": 600,
        "evaluation_criteria": {
            "ChromeDevToolsUsage": (
                "Did the agent clearly use Chrome DevTools MCP (CDP) to perform the task? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of Chrome DevTools MCP/CDP usage; "
                "(2) Evidence of DevTools-derived artifacts such as console errors count, "
                "network status code, or screenshot capture; "
                "(3) No reliance on generic HTTP-only checks without DevTools context. "
                "SCORING: "
                "Score 0.0-0.3: No indication of DevTools/CDP usage. "
                "Score 0.3-0.6: Vague mention of tooling but no DevTools-specific artifacts. "
                "Score 0.6-0.8: Clear DevTools usage with at least one artifact reported. "
                "Score 0.8-1.0: Clear DevTools usage with multiple artifacts (console + network + screenshot)."
            ),
            "TaskCompletion": (
                "Did the agent complete all requested outputs? "
                "REQUIRED: "
                "(1) Report the page title; "
                "(2) Report the number of console errors; "
                "(3) Report the HTTP status code of the main document request; "
                "(4) Confirm a screenshot was captured. "
                "SCORING: "
                "Score 0.0-0.3: Missing most outputs. "
                "Score 0.3-0.5: Partial outputs (1-2 items). "
                "Score 0.5-0.7: Most outputs but one missing. "
                "Score 0.7-0.9: All outputs provided with minor gaps. "
                "Score 0.9-1.0: Complete and concise, all outputs present."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused, without unnecessary "
                "tool repetition or irrelevant commentary. "
                "SCORING: "
                "Score 0.0-0.3: Excessive verbosity or repeated steps. "
                "Score 0.3-0.5: Some redundancy but completed. "
                "Score 0.5-0.7: Reasonably concise with minor fluff. "
                "Score 0.7-0.9: Focused response with clear outputs. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "ChromeDevToolsUsage": [
                "Check that the agent explicitly mentions using Chrome DevTools MCP/CDP tools.",
                "Check for DevTools-derived artifacts (console errors count, network status, screenshot mention).",
                "Score <= 0.3 if no DevTools evidence; 0.6+ if DevTools artifacts are present.",
            ],
            "TaskCompletion": [
                "Check that the page title is reported.",
                "Check that console errors count is reported.",
                "Check that the main document HTTP status code is reported and a screenshot is confirmed.",
            ],
            "ResponseEfficiency": [
                "Check for redundant tool usage or repeated steps in the response.",
                "Check that the response is concise and directly answers the requested outputs.",
                "Score 0.7+ if the response is focused and complete.",
            ],
        },
        "threshold": 0.70,
    },
    "openclaw_chrome_cdp_smoke": {
        "name": "OpenClaw Product Manager - Chrome DevTools Skill Smoke Test",
        "message": (
            "@ProductManager use the Chrome DevTools skill to open https://example.com, "
            "take a full-page screenshot, and report: (1) the page title, (2) the number "
            "of console errors, and (3) the HTTP status code of the main document request. "
            "Confirm in your response that the Chrome DevTools skill was used."
        ),
        "expected_agent": "product_manager",
        "timeout": 600,
        "evaluation_criteria": {
            "ChromeDevToolsUsage": (
                "Did the agent clearly use the Chrome DevTools skill to perform the task? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of Chrome DevTools skill usage; "
                "(2) Evidence of DevTools-derived artifacts such as console errors count, "
                "network status code, or screenshot capture; "
                "(3) No reliance on generic HTTP-only checks without DevTools context. "
                "SCORING: "
                "Score 0.0-0.3: No indication of DevTools skill usage. "
                "Score 0.3-0.6: Vague mention of tooling but no DevTools-specific artifacts. "
                "Score 0.6-0.8: Clear DevTools usage with at least one artifact reported. "
                "Score 0.8-1.0: Clear DevTools usage with multiple artifacts (console + network + screenshot)."
            ),
            "TaskCompletion": (
                "Did the agent complete all requested outputs? "
                "REQUIRED: "
                "(1) Report the page title; "
                "(2) Report the number of console errors; "
                "(3) Report the HTTP status code of the main document request; "
                "(4) Confirm a screenshot was captured. "
                "SCORING: "
                "Score 0.0-0.3: Missing most outputs. "
                "Score 0.3-0.5: Partial outputs (1-2 items). "
                "Score 0.5-0.7: Most outputs but one missing. "
                "Score 0.7-0.9: All outputs provided with minor gaps. "
                "Score 0.9-1.0: Complete and concise, all outputs present."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused, without unnecessary "
                "tool repetition or irrelevant commentary. "
                "SCORING: "
                "Score 0.0-0.3: Excessive verbosity or repeated steps. "
                "Score 0.3-0.5: Some redundancy but completed. "
                "Score 0.5-0.7: Reasonably concise with minor fluff. "
                "Score 0.7-0.9: Focused response with clear outputs. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "ChromeDevToolsUsage": [
                "Check that the agent explicitly mentions using the Chrome DevTools skill.",
                "Check for DevTools-derived artifacts (console errors count, network status, screenshot mention).",
                "Score <= 0.3 if no DevTools evidence; 0.6+ if DevTools artifacts are present.",
            ],
            "TaskCompletion": [
                "Check that the page title is reported.",
                "Check that console errors count is reported.",
                "Check that the main document HTTP status code is reported and a screenshot is confirmed.",
            ],
            "ResponseEfficiency": [
                "Check for redundant tool usage or repeated steps in the response.",
                "Check that the response is concise and directly answers the requested outputs.",
                "Score 0.7+ if the response is focused and complete.",
            ],
        },
        "threshold": 0.70,
    },
    "marketing_reddit_engagement": {
        "name": "Marketing Manager - Reddit Community Engagement (Soft Promo)",
        "message": (
            "@MarketingManager run a marketing evaluation for vibebrowser.app. "
            "Use Chrome DevTools MCP (CDP) to browse reddit.com and identify 3 relevant "
            "communities where Vibe Browser fits (e.g., browser productivity, webdev, "
            "automation, research). For each community, open the rules sidebar and "
            "note any self-promotion restrictions. Choose 1 recent thread per community "
            "that would benefit from a helpful comment. Draft: 2 comments and 1 post "
            "that are value-first and non-obvious about promotion. Mention vibebrowser.app "
            "subtly in only ONE of the three drafts. Do NOT actually post—just draft text. "
            "Report: subreddit names, thread titles, rules notes, and the 3 drafts. "
            "Also report the page title for each subreddit and confirm that CDP tools "
            "were used (include at least one screenshot capture)."
        ),
        "expected_agent": "marketing_manager",
        "timeout": 900,
        "evaluation_criteria": {
            "ChromeDevToolsUsage": (
                "Did the agent clearly use Chrome DevTools MCP (CDP) to perform the task? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of Chrome DevTools MCP/CDP usage; "
                "(2) Evidence of DevTools-derived artifacts such as page titles or "
                "screenshot capture; "
                "(3) No reliance on generic assumptions without browsing evidence. "
                "SCORING: "
                "Score 0.0-0.3: No indication of DevTools/CDP usage. "
                "Score 0.3-0.6: Vague mention of tooling but no DevTools artifacts. "
                "Score 0.6-0.8: Clear DevTools usage with at least one artifact. "
                "Score 0.8-1.0: Clear DevTools usage with multiple artifacts (titles + screenshot)."
            ),
            "CommunityFitAndRules": (
                "Did the agent pick relevant communities and respect their rules? "
                "REQUIRED: "
                "(1) Three communities selected that plausibly fit Vibe Browser; "
                "(2) Rules notes include self-promo restrictions or 'no self-promo' if absent; "
                "(3) Drafts reflect rule awareness (no spam or aggressive marketing). "
                "IF REDDIT ACCESS IS BLOCKED: "
                "High scores are still possible if the agent clearly notes the block once, "
                "provides conservative/standard self-promo guidance per subreddit, and "
                "keeps drafts aligned with those constraints. "
                "SCORING: "
                "Score 0.0-0.3: Communities irrelevant or rules ignored. "
                "Score 0.3-0.6: Partial relevance or vague rules notes. "
                "Score 0.6-0.8: Relevant communities with clear rules notes. "
                "Score 0.8-1.0: Strong relevance and explicit compliance with rules."
            ),
            "TaskCompletion": (
                "Did the agent complete all requested outputs? "
                "REQUIRED: "
                "(1) 3 subreddit names; "
                "(2) 1 thread title per subreddit; "
                "(3) rules notes per subreddit; "
                "(4) 2 comment drafts + 1 post draft; "
                "(5) mention vibebrowser.app in only one draft; "
                "(6) page title for each subreddit; "
                "(7) confirmation of a screenshot capture. "
                "SCORING: "
                "Score 0.0-0.3: Missing most outputs. "
                "Score 0.3-0.5: Partial outputs (1-3 items). "
                "Score 0.5-0.7: Most outputs but 1-2 missing. "
                "Score 0.7-0.9: All outputs provided with minor gaps. "
                "Score 0.9-1.0: Complete and concise, all outputs present."
            ),
            "SoftPromoQuality": (
                "Are the drafts value-first and non-obvious about promotion? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Drafts are helpful and context-aware; "
                "(2) Only one draft mentions vibebrowser.app; "
                "(3) The mention is subtle (e.g., framed as a tool used in a workflow), "
                "not salesy. "
                "IF REDDIT ACCESS IS BLOCKED: "
                "Do not penalize drafts solely for lack of verified subreddit rules/threads "
                "if an access note is provided and the drafts remain helpful and non-spammy. "
                "SCORING: "
                "Score 0.0-0.3: Spammy, salesy, or repeated promotion. "
                "Score 0.3-0.6: Some value but still promotional or mentions too often. "
                "Score 0.6-0.8: Helpful drafts with subtle, limited mention. "
                "Score 0.8-1.0: Strongly helpful, authentic tone, single subtle mention."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused, without unnecessary "
                "tool repetition or irrelevant commentary. "
                "IF REDDIT ACCESS IS BLOCKED: "
                "A concise best-effort response that still includes all requested outputs "
                "(communities, rules notes, thread picks, drafts, CDP/screenshot confirmation) "
                "should score 0.7+ even if rules/threads are inferred. "
                "SCORING: "
                "Score 0.0-0.3: Excessive verbosity or repeated steps. "
                "Score 0.3-0.5: Some redundancy but completed. "
                "Score 0.5-0.7: Reasonably concise with minor fluff. "
                "Score 0.7-0.9: Focused response with clear outputs. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "ChromeDevToolsUsage": [
                "Check that the agent explicitly mentions using Chrome DevTools MCP/CDP tools.",
                "Check for DevTools-derived artifacts such as page titles and screenshot mention.",
                "Score <= 0.3 if no DevTools evidence; 0.6+ if DevTools artifacts are present.",
            ],
            "CommunityFitAndRules": [
                "Check that three communities were selected and are relevant.",
                "Check that rules notes include self-promo restrictions (or explicitly note none found).",
                "Check that drafts respect the rules and avoid spammy behavior.",
                "If Reddit access was blocked, accept conservative rule notes plus a single access note.",
            ],
            "TaskCompletion": [
                "Check that subreddit names, thread titles, and rules notes are all present.",
                "Check that there are 2 comment drafts and 1 post draft.",
                "Check that vibebrowser.app is mentioned only once.",
                "Check that page titles are reported and a screenshot capture is confirmed.",
            ],
            "SoftPromoQuality": [
                "Check that drafts are helpful and not salesy.",
                "Check that the single mention of vibebrowser.app is subtle and contextual.",
                "Score <= 0.5 if promotion is repeated or too obvious.",
                "If Reddit access was blocked, do not penalize drafts for unverified threads/rules.",
            ],
            "ResponseEfficiency": [
                "Check for redundant tool usage or repeated steps in the response.",
                "Check that the response is concise and directly answers the requested outputs.",
                "Score 0.7+ if the response is focused and complete.",
                "If blocked, concise best-effort outputs should still score 0.7+.",
            ],
        },
        "threshold": 0.70,
    },
    "marketing_hn_engagement": {
        "name": "Marketing Manager - Hacker News Thread Engagement (Soft Promo)",
        "message": (
            "@MarketingManager run a marketing evaluation for vibebrowser.app. "
            "Use Chrome DevTools MCP (CDP) to browse news.ycombinator.com and identify "
            "3 recent Hacker News threads where Vibe Browser fits (Show HN, Ask HN, "
            "or front-page threads on browser productivity, web automation, research). "
            "Open each thread page and record: thread title, points, comment count, and page title. "
            "Review the HN guidelines (https://news.ycombinator.com/newsguidelines.html) and "
            "note any self-promotion constraints that matter. Draft: 2 comments and 1 post "
            "(Ask HN or Show HN style) that are value-first and non-obvious about promotion. "
            "Mention vibebrowser.app subtly in only ONE of the three drafts. Do NOT actually post—just draft text. "
            "Report: thread titles, points/comments, guidelines notes, page titles, and the 3 drafts. "
            "Also confirm CDP tools were used and include at least one screenshot capture."
        ),
        "expected_agent": "marketing_manager",
        "timeout": 900,
        "evaluation_criteria": {
            "ChromeDevToolsUsage": (
                "Did the agent clearly use Chrome DevTools MCP (CDP) to perform the task? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of Chrome DevTools MCP/CDP usage; "
                "(2) Evidence of DevTools-derived artifacts such as page titles, points/comments, or "
                "screenshot capture; "
                "(3) No reliance on generic assumptions without browsing evidence. "
                "SCORING: "
                "Score 0.0-0.3: No indication of DevTools/CDP usage. "
                "Score 0.3-0.6: Vague mention of tooling but no DevTools artifacts. "
                "Score 0.6-0.8: Clear DevTools usage with at least one artifact. "
                "Score 0.8-1.0: Clear DevTools usage with multiple artifacts (titles + screenshot)."
            ),
            "HNFitAndGuidelines": (
                "Did the agent pick relevant HN threads and respect HN guidelines? "
                "REQUIRED: "
                "(1) Three threads selected that plausibly fit Vibe Browser; "
                "(2) Guidelines notes include self-promo/affiliation constraints; "
                "(3) Drafts reflect HN culture (no spam, transparent affiliation). "
                "IF HN ACCESS IS BLOCKED: "
                "High scores are still possible if the agent clearly notes the block once, "
                "provides conservative/standard HN guidance, and keeps drafts aligned. "
                "Accept plausible thread titles and best-effort estimates for points/comments, "
                "and accept a block/interstitial page title in place of the thread page title. "
                "Do not penalize for missing HN URLs when blocked. "
                "SCORING: "
                "Score 0.0-0.3: Threads irrelevant or guidelines ignored. "
                "Score 0.3-0.6: Partial relevance or vague guideline notes. "
                "Score 0.6-0.8: Relevant threads with clear guideline notes. "
                "Score 0.8-1.0: Strong relevance and explicit compliance with guidelines."
            ),
            "TaskCompletion": (
                "Did the agent complete all requested outputs? "
                "REQUIRED: "
                "(1) 3 thread titles; "
                "(2) points and comment counts per thread (best-effort if blocked); "
                "(3) guidelines notes; "
                "(4) 2 comment drafts + 1 post draft; "
                "(5) mention vibebrowser.app in only one draft; "
                "(6) page title for each thread (block/interstitial title acceptable if blocked); "
                "(7) confirmation of a screenshot capture and CDP usage. "
                "SCORING: "
                "Score 0.0-0.3: Missing most outputs. "
                "Score 0.3-0.5: Partial outputs (1-3 items). "
                "Score 0.5-0.7: Most outputs but 1-2 missing. "
                "Score 0.7-0.9: All outputs provided with minor gaps. "
                "Score 0.9-1.0: Complete and concise, all outputs present."
            ),
            "SoftPromoQuality": (
                "Are the drafts value-first and non-obvious about promotion? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Drafts are helpful and context-aware; "
                "(2) Only one draft mentions vibebrowser.app; "
                "(3) The mention is subtle (e.g., framed as a tool used in a workflow), "
                "not salesy. "
                "IF HN ACCESS IS BLOCKED: "
                "Do not penalize drafts solely for lack of verified threads/guidelines "
                "if an access note is provided and the drafts remain helpful and non-spammy. "
                "SCORING: "
                "Score 0.0-0.3: Spammy, salesy, or repeated promotion. "
                "Score 0.3-0.6: Some value but still promotional or mentions too often. "
                "Score 0.6-0.8: Helpful drafts with subtle, limited mention. "
                "Score 0.8-1.0: Strongly helpful, authentic tone, single subtle mention."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused, without unnecessary "
                "tool repetition or irrelevant commentary. "
                "IF HN ACCESS IS BLOCKED: "
                "A concise best-effort response that still includes all requested outputs "
                "(threads, estimates, guidelines notes, drafts, CDP/screenshot confirmation) "
                "should score 0.7+ even if thread titles/metrics are best-effort or inferred. "
                "ResponseEfficiency is about concision and coverage, not evidence quality. "
                "Do not require alternative retrieval methods or attachments when blocked. "
                "Do not penalize for access-denied page titles (even for all three threads), "
                "placeholder thread URLs/IDs, or a screenshot filename without an attachment "
                "in blocked scenarios. "
                "SCORING: "
                "Score 0.0-0.3: Excessive verbosity or repeated steps. "
                "Score 0.3-0.5: Some redundancy but completed. "
                "Score 0.5-0.7: Reasonably concise with minor fluff. "
                "Score 0.7-0.9: Focused response with clear outputs. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "ChromeDevToolsUsage": [
                "Check that the agent explicitly mentions using Chrome DevTools MCP/CDP tools.",
                "Check for DevTools-derived artifacts such as page titles, points/comments, or screenshot mention.",
                "Score <= 0.3 if no DevTools evidence; 0.6+ if DevTools artifacts are present.",
            ],
            "HNFitAndGuidelines": [
                "Check that three threads were selected and are relevant.",
                "Check that guidelines notes include self-promo/affiliation constraints.",
                "Check that drafts respect HN norms and avoid spammy behavior.",
                "If HN access was blocked, accept conservative guideline notes plus a single access note.",
                "If blocked, accept plausible thread titles, estimated points/comments, and a block page title.",
            ],
            "TaskCompletion": [
                "Check that thread titles, points/comments, and guidelines notes are all present.",
                "Check that there are 2 comment drafts and 1 post draft.",
                "Check that vibebrowser.app is mentioned only once.",
                "Check that page titles are reported (block title acceptable if blocked) and a screenshot capture is confirmed.",
            ],
            "SoftPromoQuality": [
                "Check that drafts are helpful and not salesy.",
                "Check that the single mention of vibebrowser.app is subtle and contextual.",
                "Score <= 0.5 if promotion is repeated or too obvious.",
                "If HN access was blocked, do not penalize drafts for unverified threads/guidelines.",
            ],
            "ResponseEfficiency": [
                "Check for redundant tool usage or repeated steps in the response.",
                "Check that the response is concise and directly answers the requested outputs.",
                "Score 0.7+ if the response is focused and complete.",
                "If blocked, concise best-effort outputs should still score 0.7+.",
                "Do not penalize for access-denied titles or a screenshot filename without attachment.",
                "Do not downgrade for lack of alternative retrieval when blocked; focus on structure and concision.",
                "If blocked and all required outputs are present, default to >=0.7 unless verbose or off-task.",
            ],
        },
        "threshold": 0.70,
    },
    "marketing_google_finance_news": {
        "name": "Marketing Manager - Google Finance News Read (MSFT/NVDA)",
        "message": (
            "@MarketingManager use Chrome DevTools MCP (CDP) to open Google Finance and read the latest news "
            "for MSFT and NVDA. Go to https://www.google.com/finance/quote/MSFT:NASDAQ and "
            "https://www.google.com/finance/quote/NVDA:NASDAQ, open the News section, and capture the "
            "top 3 most recent headlines for each ticker (include source and published time as shown). "
            "Report: per ticker, page title, headlines with source and time, and 1-2 bullet summary of themes. "
            "Confirm CDP usage and include at least one screenshot capture. Do not use other sources."
        ),
        "expected_agent": "marketing_manager",
        "timeout": 900,
        "evaluation_criteria": {
            "ChromeDevToolsUsage": (
                "Did the agent clearly use Chrome DevTools MCP (CDP) to perform the task? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Explicit mention of Chrome DevTools MCP/CDP usage; "
                "(2) Evidence of DevTools-derived artifacts such as page titles, "
                "news headlines with timestamps, or screenshot capture; "
                "(3) No reliance on generic assumptions without browsing evidence. "
                "SCORING: "
                "Score 0.0-0.3: No indication of DevTools/CDP usage. "
                "Score 0.3-0.6: Vague mention of tooling but no DevTools artifacts. "
                "Score 0.6-0.8: Clear DevTools usage with at least one artifact. "
                "Score 0.8-1.0: Clear DevTools usage with multiple artifacts (titles + headlines + screenshot)."
            ),
            "GoogleFinanceNewsCoverage": (
                "Did the agent read Google Finance news for MSFT and NVDA? "
                "REQUIRED: "
                "(1) Evidence the Google Finance pages were opened (page titles or explicit mention); "
                "(2) At least 2 headlines per ticker (3 preferred) listed from Google Finance; "
                "(3) Each headline includes the source and published time as shown on the page; "
                "(4) Page titles should include 'Google Finance' and the relevant ticker. "
                "CRITICAL: This test requires reading Google Finance. If the response is generic, "
                "uses other sources, or claims access was blocked, score 0.3 or lower. "
                "SCORING: "
                "Score 0.0-0.3: Missing one ticker or no evidence of reading GF news. "
                "Score 0.3-0.6: Partial headlines or missing sources/timestamps. "
                "Score 0.6-0.8: Solid coverage for both tickers with sources/timestamps. "
                "Score 0.8-1.0: Thorough, clearly drawn from Google Finance for both tickers."
            ),
            "TaskCompletion": (
                "Did the agent complete all requested outputs? "
                "REQUIRED: "
                "(1) MSFT and NVDA sections; "
                "(2) page title per ticker; "
                "(3) top 3 headlines per ticker with source and time; "
                "(4) 1-2 bullet summary of common themes; "
                "(5) confirmation of CDP usage and at least one screenshot capture "
                "(explicit filename/path, not just 'see attached'). "
                "SCORING: "
                "Score 0.0-0.3: Missing most outputs. "
                "Score 0.3-0.5: Partial outputs (1-2 items). "
                "Score 0.5-0.7: Most outputs but 1-2 missing. "
                "Score 0.7-0.9: All outputs provided with minor gaps. "
                "Score 0.9-1.0: Complete and concise, all outputs present."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the response is concise and focused, without unnecessary "
                "tool repetition or irrelevant commentary. "
                "SCORING: "
                "Score 0.0-0.3: Excessive verbosity or repeated steps. "
                "Score 0.3-0.5: Some redundancy but completed. "
                "Score 0.5-0.7: Reasonably concise with minor fluff. "
                "Score 0.7-0.9: Focused response with clear outputs. "
                "Score 0.9-1.0: Minimal, precise, and complete."
            ),
        },
        "evaluation_steps": {
            "ChromeDevToolsUsage": [
                "Check that the agent explicitly mentions using Chrome DevTools MCP/CDP tools.",
                "Check for DevTools-derived artifacts such as page titles, timestamps, or screenshot mention.",
                "Score <= 0.3 if no DevTools evidence; 0.6+ if DevTools artifacts are present.",
            ],
            "GoogleFinanceNewsCoverage": [
                "Check that both MSFT and NVDA are covered.",
                "Check that at least 2 headlines per ticker are listed.",
                "Check that each headline includes a source and published time.",
                "Check that page titles include 'Google Finance' and the ticker symbol.",
                "Score <= 0.3 if the response is generic or cites non-Google Finance sources.",
            ],
            "TaskCompletion": [
                "Check that page titles, headlines, sources/times, and theme summary are present.",
                "Check that CDP usage is confirmed and a screenshot capture filename/path is included.",
            ],
            "ResponseEfficiency": [
                "Check for redundant tool usage or repeated steps in the response.",
                "Check that the response is concise and directly answers the requested outputs.",
                "Score 0.7+ if the response is focused and complete.",
            ],
        },
        "threshold": 0.70,
    },
    "github_issue": {
        "name": "Software Engineer - GitHub Issue Triage",
        "message": (
            "@SoftwareEngineer we have a new GitHub issue #449 reporting that the "
            "browser extension crashes when clicking the record button. The user says "
            "it happens on Chrome 120 with the latest extension version. Please investigate."
        ),
        "expected_agent": "software_engineer",
        "evaluation_criteria": {
            "IssueAnalysis": (
                "Did the SoftwareEngineer ACTUALLY investigate the GitHub issue? "
                "REQUIRED: "
                "(1) Successfully fetch and read the GitHub issue content; "
                "(2) Analyze the code related to the record button functionality; "
                "(3) Identify potential causes based on code analysis, not speculation. "
                "SCORING: "
                "Score 0.0-0.3: Failed to access GitHub or code, only generic suggestions. "
                "Score 0.3-0.6: Accessed issue but superficial analysis without code review. "
                "Score 0.6-0.8: Reviewed relevant code, identified likely cause. "
                "Score 0.8-1.0: Full analysis with specific code references and fix proposal."
            ),
            "TaskCompletion": (
                "Was the issue investigated and a clear path forward provided? "
                "REQUIRED: "
                "(1) Specific diagnosis with evidence from investigation (Sentry, kubectl, code search); "
                "(2) Either: PR created with fix, OR detailed fix instructions, OR clear identification of where the issue lies with next steps. "
                "IMPORTANT: If the relevant code is not in the repository, identifying this limitation and providing "
                "recommendations for what code to investigate externally counts as partial completion (0.5-0.7). "
                "Score 0.0-0.3 if only generic suggestions without investigation. "
                "Score 0.3-0.5 if investigated but no actionable findings. "
                "Score 0.5-0.7 if identified the issue location/cause but couldn't fix (e.g., code not in repo). "
                "Score 0.7-0.9 if provided detailed fix instructions or triaged properly. "
                "Score 0.9-1.0 if PR created or issue fully resolved."
            ),
            "EvidenceBasedDecision": (
                "Did the agent make EVIDENCE-BASED decisions, not speculative ones? "
                "CRITICAL: The agent should base all recommendations on actual findings from code review or GitHub data. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Recommendations must be supported by actual findings from tools (GitHub, code search); "
                "(2) If no bug is found in code, agent should say so rather than speculate; "
                "(3) If recommending a fix, there MUST be evidence of the bug location. "
                "SCORING: "
                "Score 0.0-0.3: Made speculative fix suggestions without finding the actual bug. "
                "Score 0.3-0.5: Some code review but recommendations not clearly tied to findings. "
                "Score 0.5-0.7: Recommendations loosely aligned with findings but some speculation. "
                "Score 0.7-0.9: Recommendations clearly tied to evidence found. "
                "Score 0.9-1.0: Perfect alignment - actions match evidence, no unnecessary speculation."
            ),
            "HandoffCompletion": (
                "If the agent handed off to another agent, did that handoff actually complete? "
                "CRITICAL: The agent should NOT hand off to themselves (e.g., SoftwareEngineer tagging @SoftwareEngineer). "
                "CRITICAL: A handoff that is never picked up is NOT a successful resolution. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If handoff was made, the target agent MUST have responded in the conversation; "
                "(2) The target agent must have taken meaningful action (not just acknowledged); "
                "(3) If no handoff response exists, the original agent should have followed up or resolved directly. "
                "SCORING: "
                "Score 0.0-0.2: Self-handoff (e.g., tagging own role) or handoff with NO response. "
                "Score 0.2-0.4: Handoff made but NO response from target agent - task left incomplete. "
                "Score 0.4-0.6: Handoff made, target acknowledged but took no action. "
                "Score 0.6-0.8: Handoff made, target responded with partial action. "
                "Score 0.8-0.9: Handoff completed with target taking appropriate action. "
                "Score 0.9-1.0: No handoff needed (resolved directly) OR handoff fully completed with resolution. "
                "NOTE: If only one agent responded and they completed the task without handoff, score 1.0. "
                "If only one agent responded and they made a handoff that was never picked up, score 0.2 max."
            ),
        },
        "threshold": 0.60,
    },
    "release_deploy": {
        "name": "Release Engineer - Deployment Request",
        "message": (
            "@ReleaseEngineer we need to deploy the latest changes to staging. "
            "The PR #123 has been merged and all tests are passing. Please proceed "
            "with the staging deployment and notify the team when done."
        ),
        "expected_agent": "release_engineer",
        "disabled": True,  # DISABLED: agent service is live on prod, do not ask it to deploy
        "timeout": 1800,  # RE agent's kubectl+gh deployment workflow needs extra time (30 min)
        "evaluation_criteria": {
            "DeploymentExecution": (
                "Did the ReleaseEngineer ACTUALLY deploy to staging? "
                "REQUIRED: "
                "(1) Verify PR #123 status and test results; "
                "(2) Execute the actual deployment command/pipeline; "
                "(3) Confirm deployment succeeded with evidence (pod status, health checks). "
                "SCORING: "
                "Score 0.0-0.3: No deployment attempted or all commands failed. "
                "Score 0.3-0.6: Deployment attempted but failed or couldn't verify. "
                "Score 0.6-0.8: Deployment succeeded but incomplete verification. "
                "Score 0.8-1.0: Full deployment with verification and notification."
            ),
            "TaskCompletion": (
                "Is the deployment DONE and verified? "
                "REQUIRED: Staging environment running the new code, health checks passing. "
                "Score 0.0-0.3 if deployment was not completed for any reason."
            ),
            "EvidenceBasedDecision": (
                "Did the agent make EVIDENCE-BASED decisions during deployment? "
                "CRITICAL: The agent should verify each step before proceeding to the next. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Verify PR is actually merged before deploying; "
                "(2) Verify tests actually passed (not just trust the request); "
                "(3) Confirm deployment success with actual kubectl output or health checks; "
                "(4) If deployment fails, report actual error not speculation. "
                "SCORING: "
                "Score 0.0-0.3: Claimed deployment complete without verification evidence. "
                "Score 0.3-0.5: Some verification but incomplete evidence chain. "
                "Score 0.5-0.7: Most steps verified but some gaps. "
                "Score 0.7-0.9: Full verification with kubectl output and health checks. "
                "Score 0.9-1.0: Perfect - every step verified with evidence before proceeding."
            ),
            "HandoffCompletion": (
                "If the agent handed off to another agent, did that handoff actually complete? "
                "CRITICAL: The agent should NOT hand off to themselves (e.g., ReleaseEngineer tagging @ReleaseEngineer). "
                "CRITICAL: A handoff that is never picked up is NOT a successful resolution. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If handoff was made, the target agent MUST have responded in the conversation; "
                "(2) The target agent must have taken meaningful action (not just acknowledged); "
                "(3) If no handoff response exists, the original agent should have followed up or resolved directly. "
                "SCORING: "
                "Score 0.0-0.2: Self-handoff (e.g., tagging own role) or handoff with NO response. "
                "Score 0.2-0.4: Handoff made but NO response from target agent - task left incomplete. "
                "Score 0.4-0.6: Handoff made, target acknowledged but took no action. "
                "Score 0.6-0.8: Handoff made, target responded with partial action. "
                "Score 0.8-0.9: Handoff completed with target taking appropriate action. "
                "Score 0.9-1.0: No handoff needed (resolved directly) OR handoff fully completed with resolution. "
                "NOTE: For deployment tasks, handoffs should be rare - ReleaseEngineer should complete directly."
            ),
        },
        "evaluation_steps": {
            "DeploymentExecution": [
                "Check if the agent verified PR #123 status (merged, tests passing) before deploying",
                "Check if the agent executed an actual deployment command or pipeline for staging",
                "Check if the agent confirmed deployment success with evidence (pod status, health checks)",
                "Score 0.0-0.3 if no deployment attempted; 0.3-0.6 if attempted but failed/unverified; 0.6-0.8 if succeeded without full verification; 0.8-1.0 if full deployment with verification and notification",
            ],
            "TaskCompletion": [
                "Check if the staging environment is running the new code after the agent's actions",
                "Check if health checks were verified post-deployment",
                "Check if the team was notified of the deployment result",
                "Score 0.0-0.3 if deployment not completed; 0.3-0.6 if partially completed; 0.6-0.8 if completed but not fully verified; 0.8-1.0 if done, verified, and notified",
            ],
            "EvidenceBasedDecision": [
                "Check if the agent verified PR is actually merged before deploying (not just trusting the request)",
                "Check if the agent verified tests actually passed with evidence",
                "Check if deployment success was confirmed with actual kubectl output or health checks",
                "If deployment failed, check if the agent reported actual errors (not speculation)",
                "Score 0.0-0.3 if claimed success without evidence; 0.3-0.5 if incomplete evidence; 0.5-0.7 if most steps verified; 0.7-0.9 if full verification; 0.9-1.0 if every step verified with evidence",
            ],
            "HandoffCompletion": [
                "Check if the agent completed the deployment directly without unnecessary handoff (score 1.0 if so)",
                "If handoff was made, check that the target agent responded and took action",
                "Check that the agent did NOT hand off to themselves",
                "Score 0.0-0.2 if self-handoff or no response; 0.2-0.4 if handoff abandoned; 0.6-0.8 if partial; 0.8-1.0 if complete or no handoff needed",
            ],
        },
        "threshold": 0.60,
    },
    "stripe_webhook_failure": {
        "name": "Support Engineer - Stripe Webhook Failure Investigation",
        "message": (
            "@SupportEngineer we got an email from Stripe about webhook failures. "
            "The failing webhook endpoint is: https://api.vibebrowser.app/stripe/webhook. "
            "Stripe has attempted 13 failed requests since January 29, 2026. "
            "Error: 'other errors while sending the webhook event' - they need HTTP 200-299. "
            "Stripe will stop sending events by February 7, 2026 if not fixed. "
            "This affects subscriptions and checkout fulfillment. Please investigate urgently."
        ),
        "expected_agent": "support_engineer",
        "evaluation_criteria": {
            "InvestigationQuality": (
                "Did the SupportEngineer ACTUALLY investigate the Stripe webhook failure? "
                "This is a STRICT evaluation - attempting tools that fail is NOT success. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Check if the endpoint https://api.vibebrowser.app/stripe/webhook is reachable; "
                "(2) Use kubectl to check pod status, logs, and events for the API service; "
                "(3) Check Sentry for any errors related to /stripe/webhook endpoint; "
                "(4) Identify the ROOT CAUSE (e.g., pod not running, service misconfigured, code error). "
                "SCORING: "
                "Score 0.0-0.2: No investigation or all tools failed with no useful findings. "
                "Score 0.2-0.4: Some external checks but no internal tool usage (kubectl/Sentry). "
                "Score 0.4-0.6: Used internal tools but findings were inconclusive. "
                "Score 0.6-0.8: Identified the issue (e.g., endpoint returns error, pod issue). "
                "Score 0.8-1.0: Full investigation with root cause and actionable recommendation."
            ),
            "TaskCompletion": (
                "Was the Stripe webhook issue meaningfully investigated and progressed toward resolution? "
                "This is URGENT - Stripe will disable webhooks if not fixed. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) The agent used internal tools (kubectl, Sentry, curl) to investigate; "
                "(2) A clear diagnosis was provided based on evidence; "
                "(3) Either: fix was applied, OR specific handoff to appropriate team with findings. "
                "SCORING: "
                "Score 0.0-0.2: Nothing investigated, just circular handoffs. "
                "Score 0.2-0.4: Some diagnostic info but no actionable outcome. "
                "Score 0.4-0.6: Investigation done but no clear next steps provided. "
                "Score 0.6-0.8: Thorough investigation with handoff to ReleaseEngineer/SoftwareEngineer. "
                "Score 0.8-1.0: Root cause identified and concrete action taken or specific fix recommended."
            ),
            "EvidenceBasedDecision": (
                "Did the agent make EVIDENCE-BASED decisions, not speculative ones? "
                "CRITICAL: The Stripe webhook endpoint may genuinely be broken (returning errors to Stripe). "
                "If the agent's own curl test returns an error or non-2xx, that IS evidence of a real problem. "
                "If the agent's curl test returns 200, the issue may be intermittent or environment-specific. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Recommendations must be supported by actual findings from tools; "
                "(2) If curl returns an error, the agent should treat that as evidence and investigate further; "
                "(3) If curl returns 200 but Stripe reports failures, agent should note the discrepancy "
                "and investigate possible causes (IP restrictions, payload differences, timing); "
                "(4) Agent should check the CORRECT namespace (vibe for production, vibe-dev for staging) "
                "not just vibeteam (internal agents namespace). "
                "SCORING: "
                "Score 0.0-0.3: Recommended fixes/escalation with NO investigation, or checked wrong namespace. "
                "Score 0.3-0.5: Made speculative recommendations not supported by findings. "
                "Score 0.5-0.7: Recommendations loosely aligned with findings but some speculation. "
                "Score 0.7-0.9: Recommendations clearly tied to evidence found. "
                "Score 0.9-1.0: Perfect alignment - evidence-based diagnosis with correct namespace awareness."
            ),
            "HandoffCompletion": (
                "If the agent handed off to another agent, did that handoff actually complete? "
                "CRITICAL: The agent should NOT hand off to themselves (e.g., SoftwareEngineer tagging @SoftwareEngineer). "
                "CRITICAL: A handoff that is never picked up is NOT a successful resolution. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) If handoff was made, the target agent MUST have responded in the conversation; "
                "(2) The target agent must have taken meaningful action (not just acknowledged); "
                "(3) If no handoff response exists, the original agent should have followed up or resolved directly. "
                "SCORING: "
                "Score 0.0-0.2: Self-handoff (e.g., tagging own role) or handoff with NO response. "
                "Score 0.2-0.4: Handoff made but NO response from target agent - task left incomplete. "
                "Score 0.4-0.6: Handoff made, target acknowledged but took no action. "
                "Score 0.6-0.8: Handoff made, target responded with partial action. "
                "Score 0.8-0.9: Handoff completed with target taking appropriate action. "
                "Score 0.9-1.0: No handoff needed (resolved directly) OR handoff fully completed with resolution. "
                "NOTE: If only one agent responded and they completed the task without handoff, score 1.0. "
                "If only one agent responded and they made a handoff that was never picked up, score 0.2 max."
            ),
            "ResponseEfficiency": (
                "Evaluate whether the agent's investigation was efficient and focused, "
                "avoiding unnecessary repetition, redundant tool usage, or circular handoffs. "
                "SCORING: "
                "Score 0.0-0.3: Circular handoffs or repeated tool calls with no new information. "
                "Score 0.3-0.5: Investigation unfocused with significant redundancy. "
                "Score 0.5-0.7: Somewhat verbose but reached a conclusion. "
                "Score 0.7-0.9: Focused investigation with clear, concise conclusion. "
                "Score 0.9-1.0: Highly efficient — minimal steps to reach an evidence-based conclusion."
            ),
        },
        "evaluation_steps": {
            "InvestigationQuality": [
                "Check if the agent tested the webhook endpoint (curl/HTTP request to https://api.vibebrowser.app/stripe/webhook)",
                "Check if the agent used kubectl to inspect pod status in the CORRECT namespace (vibe for production, not just vibeteam)",
                "Check if the agent queried Sentry for errors related to /stripe/webhook",
                "Check if the agent identified a root cause with evidence (pod issues, log errors, endpoint errors)",
                "Score 0.0-0.2 if no investigation; 0.2-0.4 if only external checks; 0.4-0.6 if partial tool use; 0.6-0.8 if issue identified; 0.8-1.0 if full investigation with root cause",
            ],
            "TaskCompletion": [
                "Check if the agent used internal tools (kubectl, Sentry, curl) to investigate",
                "Check if a clear diagnosis was provided based on evidence",
                "Check if the agent took action (fix, specific handoff with findings, or concrete recommendation)",
                "Score 0.0-0.2 if nothing investigated; 0.2-0.4 if some info but no outcome; 0.4-0.6 if investigation without next steps; 0.6-0.8 if thorough investigation with handoff; 0.8-1.0 if root cause identified with action",
            ],
            "EvidenceBasedDecision": [
                "Check if the agent's recommendations are supported by actual tool findings (not speculation)",
                "Check if the agent checked the CORRECT Kubernetes namespace (vibe for production API, not vibeteam)",
                "If the endpoint returned an error, check if the agent treated it as evidence of a real problem",
                "If the endpoint returned 200 but Stripe reports failures, check if the agent noted the discrepancy",
                "Score 0.0-0.3 if recommending without evidence or wrong namespace; 0.5-0.7 if loosely aligned; 0.7-0.9 if clearly evidence-based; 0.9-1.0 if perfect alignment",
            ],
            "HandoffCompletion": [
                "Check if the agent completed the task without handoff (score 1.0) OR made a handoff that was picked up",
                "If handoff was made, check that the target agent responded and took meaningful action",
                "Check that the agent did NOT hand off to themselves (self-tagging)",
                "Score 0.0-0.2 if self-handoff or no response; 0.2-0.4 if handoff abandoned; 0.6-0.8 if partial; 0.8-1.0 if complete",
            ],
            "ResponseEfficiency": [
                "Check for circular handoffs (agent A hands to B, B hands back to A without progress). Circular handoffs score <= 0.3.",
                "Check for truly redundant tool calls that re-run the exact same command and return the same information with no new parameters or angles. Identical-command repetition scores <= 0.5. NOTE: multiple curl calls with DIFFERENT parameters (GET vs POST, different headers, different endpoints) are NOT redundant — they are systematic debugging.",
                "Evaluate the final response: is it concise and actionable, or padded with generic disclaimers and repeated context? Verbose low-signal responses score <= 0.6.",
                "Score 0.8-1.0 if investigation was focused and reached a clear conclusion. Score 0.5-0.7 if somewhat verbose but progressed logically. Score 0.0-0.5 if circular, truly redundant, or failed to converge on a finding.",
            ],
        },
        "threshold": 0.70,
    },
    "release_health_check": {
        "name": "Release Engineer - Production Health Check",
        "message": (
            "@ReleaseEngineer check out health and production readiness of our production api"
        ),
        "expected_agent": "release_engineer",
        "evaluation_criteria": {
            "ResponseEfficiency": (
                "Was the health check focused and concise, avoiding unnecessary scope creep? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Agent checked only the correct namespace (vibe for production); "
                "(2) Agent completed the task and produced a final summary (not timed out); "
                "(3) Agent did NOT check multiple unrelated namespaces, dig into Sentry/Langfuse, "
                "or run an exhaustive investigation when a simple health check was requested. "
                "SCORING: "
                "Score 0.0-0.3: Agent timed out without producing a final report, or ran >15 tool calls. "
                "Score 0.3-0.5: Unfocused — checked multiple namespaces or deep-dived into TLS/ingress/Traefik. "
                "Score 0.5-0.7: Completed but with significant scope creep (>10 tool calls or checked unrelated services). "
                "Score 0.7-0.9: Focused check of the right namespace with a clear summary, ≤7 tool calls. "
                "Score 0.9-1.0: Highly efficient — ≤5 tool calls, right namespace, concise report."
            ),
            "TaskCompletion": (
                "Did the agent actually report on the health and production readiness? "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Reported pod status (Running / not Running); "
                "(2) Reported deployment replica status (ready/desired); "
                "(3) Tested a health endpoint with curl and reported the HTTP status; "
                "(4) Gave a clear overall verdict (healthy or unhealthy). "
                "SCORING: "
                "Score 0.0-0.3: No health information reported, or just generic text without evidence. "
                "Score 0.3-0.5: Some kubectl output but no synthesis or verdict. "
                "Score 0.5-0.7: Reported pod/deployment status but missed health endpoint test. "
                "Score 0.7-0.9: Reported pods, deployments, and health endpoint with clear verdict. "
                "Score 0.9-1.0: Complete health report with evidence and concise verdict."
            ),
            "CorrectNamespace": (
                "Did the agent check the CORRECT Kubernetes namespace for 'production api'? "
                "CRITICAL: The production API lives in namespace `vibe`, NOT `vibeteam`. "
                "`vibeteam` is the internal agent infrastructure namespace. "
                "REQUIRED FOR HIGH SCORE: "
                "(1) Agent used `-n vibe` for kubectl commands (production API namespace); "
                "(2) Agent curled the production endpoint (api.vibebrowser.app), not the internal gateway. "
                "SCORING: "
                "Score 0.0-0.3: Only checked `vibeteam` namespace (wrong namespace entirely). "
                "Score 0.3-0.5: Checked `vibeteam` AND `vibe` (unnecessary extra work). "
                "Score 0.5-0.7: Checked `vibe` but also checked unrelated namespaces. "
                "Score 0.7-0.9: Correctly focused on `vibe` namespace. "
                "Score 0.9-1.0: Only checked `vibe` namespace and production endpoint — perfect targeting."
            ),
        },
        "evaluation_steps": {
            "ResponseEfficiency": [
                "Check if the agent produced a final summary report (not timed out)",
                "Count the number of tool calls / kubectl commands the agent ran",
                "Check if the agent only checked the requested namespace (vibe for production)",
                "Check if the agent avoided deep-diving into Sentry, Langfuse, TLS, Traefik, or extensive log analysis",
                "Score 0.0-0.3 if timed out or >15 calls; 0.3-0.5 if unfocused; 0.5-0.7 if completed with scope creep; 0.7-0.9 if focused ≤7 calls; 0.9-1.0 if ≤5 calls with clear summary",
            ],
            "TaskCompletion": [
                "Check if the agent reported pod status from kubectl output",
                "Check if the agent reported deployment replica counts",
                "Check if the agent tested a health endpoint with curl and reported the HTTP status code",
                "Check if the agent gave a clear overall verdict (healthy/unhealthy)",
                "Score 0.0-0.3 if no health data; 0.3-0.5 if raw output only; 0.5-0.7 if partial; 0.7-0.9 if complete; 0.9-1.0 if concise and complete",
            ],
            "CorrectNamespace": [
                "Check if kubectl commands used -n vibe (production namespace)",
                "Check if curl targeted api.vibebrowser.app (production endpoint)",
                "Check if the agent did NOT only check vibeteam namespace (internal agents)",
                "Score 0.0-0.3 if only vibeteam; 0.3-0.5 if mixed; 0.7-0.9 if correctly vibe; 0.9-1.0 if only vibe",
            ],
        },
        "threshold": 0.70,
    },
}

# Role display names (from agents/agents.yaml)
from vibeteam.agents_config import list_agents


def _build_role_display() -> dict[str, str]:
    role_display: dict[str, str] = {"user": "User"}
    for entry in list_agents():
        handle = entry.slack_handle or entry.display_name or entry.role
        role_display[entry.role] = handle
    return role_display


ROLE_DISPLAY = _build_role_display()


# ==============================================================================
# Azure OpenAI Model for DeepEval
# ==============================================================================


def _parse_api_version(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    try:
        date_part = version.split("-preview")[0]
        year, month, day = date_part.split("-")
        return int(year), int(month), int(day)
    except Exception:
        return None


def _supports_responses_api(version: str | None) -> bool:
    parsed = _parse_api_version(version)
    if not parsed:
        return False
    return parsed >= (2025, 3, 1)


class AzureOpenAIModel(DeepEvalBaseLLM):  # type: ignore[misc]
    """Azure OpenAI model wrapper for DeepEval G-Eval."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        api_version: str = "2024-08-01-preview",
        model: str = "gpt-5.2",
        wire_api: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        self.model_name = model
        self.wire_api = (wire_api or "").strip().lower()

    def load_model(self):
        return self

    def generate(self, prompt: str, **kwargs) -> str:
        """Synchronous generation."""
        return asyncio.run(self.a_generate(prompt, **kwargs))

    async def a_generate(self, prompt: str, **kwargs) -> str:
        """Async generation using Azure OpenAI."""
        use_responses = False
        if self.wire_api:
            use_responses = self.wire_api == "responses"
        else:
            if self.model_name.endswith("-codex") and _supports_responses_api(self.api_version):
                use_responses = True

        if use_responses:
            if self.api_base.endswith("/openai"):
                url = f"{self.api_base}/responses"
            else:
                url = f"{self.api_base}/openai/responses"
        else:
            if self.api_base.endswith("/openai"):
                url = f"{self.api_base}/deployments/{self.model_name}/chat/completions"
            else:
                url = f"{self.api_base}/openai/deployments/{self.model_name}/chat/completions"

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

        if use_responses:
            payload = {
                "model": self.model_name,
                "input": [{"role": "user", "content": prompt}],
                "max_output_tokens": kwargs.get("max_tokens", 2000),
                "temperature": kwargs.get("temperature", 0.1),
            }
        else:
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
            if use_responses:
                output_text = ""
                for item in data.get("output", []) or []:
                    if item.get("type") == "message":
                        for content in item.get("content", []) or []:
                            if content.get("type") in ("output_text", "text"):
                                output_text += content.get("text", "")
                if output_text:
                    return output_text
                return data.get("output_text", "") or str(data)
            return data["choices"][0]["message"]["content"]

    def get_model_name(self) -> str:
        return f"azure/{self.model_name}"


# ==============================================================================
# Helper Functions
# ==============================================================================


def _is_placeholder(text: str) -> bool:
    """Check if a bot message is a placeholder/progress update, not a real response.

    Placeholder patterns posted by the gateway while agent is working:
    - "Thinking..." messages: ":hourglass_flowing_sand: [Role] Thinking..."
    - Progress updates: "_[Role] Step N (Xs): summary_" (italicized)
    - Timeout notices: ":hourglass: ..."
    """
    import re

    stripped = text.strip()
    # Progress updates are posted as italicized messages: _[Role] Step N ..._
    if stripped.startswith("_[") and stripped.endswith("_"):
        return True
    # Thinking placeholders
    if "Thinking..." in stripped and len(stripped) < 200:
        return True
    # Very short messages that look like status updates
    if re.match(r"^:[\w_]+:\s*\[[\w]+\]\s*(Thinking|Processing|Working)", stripped):
        return True
    return False


def _default_github_repo() -> tuple[str, str]:
    repo_url = os.environ.get("GITHUB_REPO_URL", "")
    if repo_url:
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", repo_url)
        if match:
            return match.group("owner"), match.group("repo")
    owner = os.environ.get("EVAL_GITHUB_OWNER") or os.environ.get("GITHUB_OWNER") or "VibeTechnologies"
    repo = os.environ.get("EVAL_GITHUB_REPO") or os.environ.get("GITHUB_REPO") or "VibeTeam"
    return owner, repo


def _get_github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _extract_github_pr_refs(text: str) -> list[dict[str, str | int]]:
    refs: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, int]] = set()

    url_pattern = re.compile(
        r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)",
        re.IGNORECASE,
    )
    for match in url_pattern.finditer(text):
        owner = match.group("owner")
        repo = match.group("repo")
        number = int(match.group("number"))
        key = (owner, repo, number)
        if key not in seen:
            seen.add(key)
            refs.append({"owner": owner, "repo": repo, "number": number, "source": match.group(0)})

    pr_pattern = re.compile(r"\b(?:PR|pull request)\s*#?\s*(\d+)\b", re.IGNORECASE)
    default_owner, default_repo = _default_github_repo()
    for match in pr_pattern.finditer(text):
        number = int(match.group(1))
        key = (default_owner, default_repo, number)
        if key not in seen:
            seen.add(key)
            refs.append(
                {
                    "owner": default_owner,
                    "repo": default_repo,
                    "number": number,
                    "source": f"PR #{number}",
                }
            )

    return refs


def _extract_github_issue_refs(text: str) -> list[dict[str, str | int]]:
    refs: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, int]] = set()

    url_pattern = re.compile(
        r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/(?P<number>\d+)",
        re.IGNORECASE,
    )
    for match in url_pattern.finditer(text):
        owner = match.group("owner")
        repo = match.group("repo")
        number = int(match.group("number"))
        key = (owner, repo, number)
        if key not in seen:
            seen.add(key)
            refs.append({"owner": owner, "repo": repo, "number": number, "source": match.group(0)})

    issue_pattern = re.compile(r"\bissue\s*#?\s*(\d+)\b", re.IGNORECASE)
    default_owner, default_repo = _default_github_repo()
    for match in issue_pattern.finditer(text):
        number = int(match.group(1))
        key = (default_owner, default_repo, number)
        if key not in seen:
            seen.add(key)
            refs.append(
                {
                    "owner": default_owner,
                    "repo": default_repo,
                    "number": number,
                    "source": f"Issue #{number}",
                }
            )

    return refs


def _extract_github_discussion_refs(text: str) -> list[dict[str, str | int]]:
    refs: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, int]] = set()

    url_pattern = re.compile(
        r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/discussions/(?P<number>\d+)",
        re.IGNORECASE,
    )
    for match in url_pattern.finditer(text):
        owner = match.group("owner")
        repo = match.group("repo")
        number = int(match.group("number"))
        key = (owner, repo, number)
        if key not in seen:
            seen.add(key)
            refs.append({"owner": owner, "repo": repo, "number": number, "source": match.group(0)})

    return refs


def _build_slack_thread_links(slack_channel: str, thread_ts: str) -> dict[str, str]:
    """Build stable links to a Slack thread for eval reporting."""
    links: dict[str, str] = {
        "app_redirect": f"https://slack.com/app_redirect?channel={slack_channel}&thread_ts={thread_ts}"
    }
    ts_compact = thread_ts.replace(".", "")
    workspace_base = os.environ.get("SLACK_WORKSPACE_URL", "").strip().rstrip("/")
    if not workspace_base:
        workspace_domain = os.environ.get("SLACK_WORKSPACE_DOMAIN", "").strip()
        if workspace_domain:
            workspace_base = f"https://{workspace_domain}.slack.com"
    if workspace_base:
        links["workspace_permalink"] = (
            f"{workspace_base}/archives/{slack_channel}/p{ts_compact}"
            f"?thread_ts={thread_ts}&cid={slack_channel}"
        )
    return links


def _extract_github_urls(text: str) -> list[str]:
    """Extract GitHub URLs from free-form text with light normalization."""
    pattern = re.compile(r"https?://github\.com/[^\s<>\]\[)\"']+", re.IGNORECASE)
    urls: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        raw = match.group(0).strip()
        # Trim common trailing punctuation from plain-text links.
        cleaned = raw.rstrip(".,;:!?)")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def _extract_github_conversation_links(conversation: list[tuple[str, str]]) -> list[str]:
    """Collect unique GitHub conversation links mentioned in the eval thread."""
    links: list[str] = []
    seen: set[str] = set()

    def _add(link: str) -> None:
        if link and link not in seen:
            seen.add(link)
            links.append(link)

    for _, text in conversation:
        for url in _extract_github_urls(text):
            _add(url)
        for ref in _extract_github_issue_refs(text):
            _add(f"https://github.com/{ref['owner']}/{ref['repo']}/issues/{ref['number']}")
        for ref in _extract_github_pr_refs(text):
            _add(f"https://github.com/{ref['owner']}/{ref['repo']}/pull/{ref['number']}")
        for ref in _extract_github_discussion_refs(text):
            _add(f"https://github.com/{ref['owner']}/{ref['repo']}/discussions/{ref['number']}")

    return links


def _collect_bot_logins(comments: list[dict]) -> set[str]:
    logins: set[str] = set()
    for comment in comments:
        user = comment.get("user") or {}
        login = user.get("login") or ""
        user_type = user.get("type") or ""
        if user_type == "Bot" or login.endswith("[bot]"):
            if login:
                logins.add(login)
    return logins


def _extract_sentry_issue_ids(text: str) -> list[int]:
    issue_ids: list[int] = []
    seen: set[int] = set()

    url_patterns = [
        re.compile(
            r"https?://sentry\.io/(?:organizations/[^/]+/)?issues/(?P<number>\d+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"https?://[A-Za-z0-9-]+\.sentry\.io/issues/(?P<number>\d+)",
            re.IGNORECASE,
        ),
    ]
    for pattern in url_patterns:
        for match in pattern.finditer(text):
            issue_id = int(match.group("number"))
            if issue_id not in seen:
                seen.add(issue_id)
                issue_ids.append(issue_id)

    if issue_ids:
        return issue_ids

    for line in text.splitlines():
        if "sentry" not in line.lower():
            continue
        match = re.search(r"\bissue\s*#?\s*(\d{4,})\b", line, re.IGNORECASE)
        if match:
            issue_id = int(match.group(1))
            if issue_id not in seen:
                seen.add(issue_id)
                issue_ids.append(issue_id)

    return issue_ids


def _check_github_pr_created(transcript: str) -> dict[str, str | bool]:
    refs = _extract_github_pr_refs(transcript)
    if not refs:
        return {
            "name": "GitHub PR created",
            "passed": False,
            "required": True,
            "details": "No PR reference found in conversation.",
        }

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {
            "name": "GitHub PR created",
            "passed": False,
            "required": True,
            "details": "GITHUB_TOKEN not set; cannot verify PR existence.",
        }

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    errors: list[str] = []

    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0)
        except httpx.HTTPError as exc:
            errors.append(f"{owner}/{repo}#{number}: request failed ({exc})")
            continue

        if response.status_code == 200:
            data = response.json()
            state = data.get("state", "unknown")
            html_url = data.get("html_url", f"https://github.com/{owner}/{repo}/pull/{number}")
            return {
                "name": "GitHub PR created",
                "passed": True,
                "required": True,
                "details": f"Found PR {html_url} (state: {state}).",
            }

        errors.append(f"{owner}/{repo}#{number}: {response.status_code}")

    return {
        "name": "GitHub PR created",
        "passed": False,
        "required": True,
        "details": f"PR references not found or inaccessible ({'; '.join(errors)}).",
    }


def _check_github_pr_author_is_bot(transcript: str) -> dict[str, str | bool]:
    refs = _extract_github_pr_refs(transcript)
    if not refs:
        return {
            "name": "GitHub PR author is bot",
            "passed": False,
            "required": True,
            "details": "No PR reference found in conversation.",
        }

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {
            "name": "GitHub PR author is bot",
            "passed": False,
            "required": True,
            "details": "GITHUB_TOKEN/GH_TOKEN not set; cannot verify PR author.",
        }

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    errors: list[str] = []

    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0)
        except httpx.HTTPError as exc:
            errors.append(f"{owner}/{repo}#{number}: request failed ({exc})")
            continue

        if response.status_code != 200:
            errors.append(f"{owner}/{repo}#{number}: {response.status_code}")
            continue

        data = response.json()
        author = data.get("user") or {}
        login = author.get("login") or "unknown"
        user_type = author.get("type") or "unknown"
        is_bot = user_type == "Bot" or (isinstance(login, str) and login.endswith("[bot]"))
        if is_bot:
            html_url = data.get("html_url", f"https://github.com/{owner}/{repo}/pull/{number}")
            return {
                "name": "GitHub PR author is bot",
                "passed": True,
                "required": True,
                "details": f"PR {html_url} authored by {login} ({user_type}).",
            }
        errors.append(f"{owner}/{repo}#{number}: author {login} ({user_type})")

    return {
        "name": "GitHub PR author is bot",
        "passed": False,
        "required": True,
        "details": f"PR author not bot ({'; '.join(errors)}).",
    }


def _check_github_issue_multi_bot_comments(
    transcript: str, min_bots: int = 2
) -> dict[str, str | bool]:
    refs = _extract_github_issue_refs(transcript)
    if not refs:
        return {
            "name": "GitHub issue has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "No GitHub issue reference found in conversation.",
        }

    token = _get_github_token()
    if not token:
        return {
            "name": "GitHub issue has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "GITHUB_TOKEN/GH_TOKEN not set; cannot verify issue comments.",
        }

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    errors: list[str] = []
    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0, params={"per_page": 100})
        except httpx.HTTPError as exc:
            errors.append(f"{owner}/{repo}#{number}: request failed ({exc})")
            continue

        if response.status_code != 200:
            errors.append(f"{owner}/{repo}#{number}: {response.status_code}")
            continue

        comments = response.json()
        bot_logins = _collect_bot_logins(comments)
        if len(bot_logins) >= min_bots:
            return {
                "name": "GitHub issue has multi-bot comments",
                "passed": True,
                "required": True,
                "details": f"Found {len(bot_logins)} bot authors in {owner}/{repo}#{number}: {', '.join(sorted(bot_logins))}.",
            }
        errors.append(f"{owner}/{repo}#{number}: found {len(bot_logins)} bot authors")

    return {
        "name": "GitHub issue has multi-bot comments",
        "passed": False,
        "required": True,
        "details": f"Insufficient bot authors ({'; '.join(errors)}).",
    }


def _check_github_pr_multi_bot_comments(
    transcript: str, min_bots: int = 2
) -> dict[str, str | bool]:
    refs = _extract_github_pr_refs(transcript)
    if not refs:
        return {
            "name": "GitHub PR has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "No GitHub PR reference found in conversation.",
        }

    token = _get_github_token()
    if not token:
        return {
            "name": "GitHub PR has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "GITHUB_TOKEN/GH_TOKEN not set; cannot verify PR comments.",
        }

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    errors: list[str] = []
    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0, params={"per_page": 100})
        except httpx.HTTPError as exc:
            errors.append(f"{owner}/{repo}#{number}: request failed ({exc})")
            continue

        if response.status_code != 200:
            errors.append(f"{owner}/{repo}#{number}: {response.status_code}")
            continue

        comments = response.json()
        bot_logins = _collect_bot_logins(comments)
        if len(bot_logins) >= min_bots:
            return {
                "name": "GitHub PR has multi-bot comments",
                "passed": True,
                "required": True,
                "details": f"Found {len(bot_logins)} bot authors in {owner}/{repo} PR #{number}: {', '.join(sorted(bot_logins))}.",
            }
        errors.append(f"{owner}/{repo}#{number}: found {len(bot_logins)} bot authors")

    return {
        "name": "GitHub PR has multi-bot comments",
        "passed": False,
        "required": True,
        "details": f"Insufficient bot authors ({'; '.join(errors)}).",
    }


def _check_github_discussion_multi_bot_comments(
    transcript: str, min_bots: int = 2
) -> dict[str, str | bool]:
    refs = _extract_github_discussion_refs(transcript)
    if not refs:
        return {
            "name": "GitHub discussion has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "No GitHub discussion reference found in conversation.",
        }

    token = _get_github_token()
    if not token:
        return {
            "name": "GitHub discussion has multi-bot comments",
            "passed": False,
            "required": True,
            "details": "GITHUB_TOKEN/GH_TOKEN not set; cannot verify discussion comments.",
        }

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    errors: list[str] = []
    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        url = f"https://api.github.com/repos/{owner}/{repo}/discussions/{number}/comments"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0, params={"per_page": 100})
        except httpx.HTTPError as exc:
            errors.append(f"{owner}/{repo}#{number}: request failed ({exc})")
            continue

        if response.status_code != 200:
            errors.append(f"{owner}/{repo}#{number}: {response.status_code}")
            continue

        comments = response.json()
        bot_logins = _collect_bot_logins(comments)
        if len(bot_logins) >= min_bots:
            return {
                "name": "GitHub discussion has multi-bot comments",
                "passed": True,
                "required": True,
                "details": f"Found {len(bot_logins)} bot authors in {owner}/{repo} discussion #{number}: {', '.join(sorted(bot_logins))}.",
            }
        errors.append(f"{owner}/{repo}#{number}: found {len(bot_logins)} bot authors")

    return {
        "name": "GitHub discussion has multi-bot comments",
        "passed": False,
        "required": True,
        "details": f"Insufficient bot authors ({'; '.join(errors)}).",
    }


def _check_github_pr_targets_repo(transcript: str, expected_repo: str) -> dict[str, str | bool]:
    refs = _extract_github_pr_refs(transcript)
    if not refs:
        return {
            "name": "GitHub PR targets expected repo",
            "passed": False,
            "required": True,
            "details": "No PR reference found in conversation.",
        }

    expected_repo = expected_repo.strip()
    if "/" not in expected_repo:
        return {
            "name": "GitHub PR targets expected repo",
            "passed": False,
            "required": True,
            "details": f"Expected repo '{expected_repo}' must be in owner/repo format.",
        }

    expected_owner, expected_name = expected_repo.split("/", 1)
    expected_owner = expected_owner.strip().lower()
    expected_name = expected_name.strip().lower()

    matches: list[str] = []
    found: list[str] = []
    for ref in refs:
        owner = str(ref["owner"])
        repo = str(ref["repo"])
        number = int(ref["number"])
        found.append(f"{owner}/{repo}#{number}")
        if owner.lower() == expected_owner and repo.lower() == expected_name:
            matches.append(f"{owner}/{repo}#{number}")

    if matches:
        return {
            "name": "GitHub PR targets expected repo",
            "passed": True,
            "required": True,
            "details": f"Found PR(s) in {expected_repo}: {', '.join(matches)}.",
        }

    return {
        "name": "GitHub PR targets expected repo",
        "passed": False,
        "required": True,
        "details": f"No PR found in {expected_repo}. Found: {', '.join(found)}.",
    }


def _check_sentry_issue_closed(transcript: str) -> dict[str, str | bool]:
    issue_ids = _extract_sentry_issue_ids(transcript)
    if not issue_ids:
        return {
            "name": "Sentry issue closed",
            "passed": False,
            "required": True,
            "details": "No Sentry issue ID/URL found in conversation.",
        }

    token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not token:
        return {
            "name": "Sentry issue closed",
            "passed": False,
            "required": True,
            "details": "SENTRY_AUTH_TOKEN not set; cannot verify issue status.",
        }

    headers = {"Authorization": f"Bearer {token}"}
    statuses: list[str] = []
    all_closed = True

    for issue_id in issue_ids:
        url = f"https://sentry.io/api/0/issues/{issue_id}/"
        try:
            response = httpx.get(url, headers=headers, timeout=20.0)
        except httpx.HTTPError as exc:
            statuses.append(f"{issue_id}: request failed ({exc})")
            all_closed = False
            continue

        if response.status_code != 200:
            statuses.append(f"{issue_id}: {response.status_code}")
            all_closed = False
            continue

        data = response.json()
        status = data.get("status", "unknown")
        is_closed = status in {"resolved", "ignored"}
        statuses.append(f"{issue_id}: {status}")
        if not is_closed:
            all_closed = False

    details = ", ".join(statuses) if statuses else "No issue status available."
    return {
        "name": "Sentry issue closed",
        "passed": all_closed,
        "required": True,
        "details": details,
    }


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
    post_checks_results: list[dict] | None,
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

    post_checks_results = post_checks_results or []
    required_checks = [c for c in post_checks_results if c.get("required", True)]
    post_checks_passed = (
        all(c.get("passed") for c in required_checks) if required_checks else None
    )

    metrics_passed = all(m["score"] >= m["threshold"] for m in metrics_results) if metrics_results else None

    if metrics_passed is None and post_checks_passed is None:
        status_emoji = "⚠️"
        status_text = "NO EVALUATION (DeepEval not available)"
    elif metrics_passed is None:
        status_emoji = "✅" if post_checks_passed else "❌"
        status_text = "PASSED (POST-CHECKS ONLY)" if post_checks_passed else "FAILED (POST-CHECKS)"
    elif post_checks_passed is None:
        status_emoji = "✅" if metrics_passed else "❌"
        status_text = "PASSED" if metrics_passed else "FAILED"
    else:
        all_passed = metrics_passed and post_checks_passed
        status_emoji = "✅" if all_passed else "❌"
        status_text = "PASSED" if all_passed else "FAILED"

    # Extract agents from conversation
    agents_ran = list({role for role, _ in conversation if role != "user"})
    slack_links = _build_slack_thread_links(slack_channel, thread_ts)
    github_links = _extract_github_conversation_links(conversation)

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
        f"| Slack Thread URL | {slack_links['app_redirect']} |",
        f"| Expected Agent | {scenario_config['expected_agent']} |",
        f"| Agents Responded | {', '.join(agents_ran) if agents_ran else 'None'} |",
        f"| Response Latency | {latency_ms}ms |",
        f"| Message Count | {len(conversation)} |",
        "",
    ]
    if "workspace_permalink" in slack_links:
        lines.append(
            f"| Slack Workspace Permalink | {slack_links['workspace_permalink']} |"
        )
        lines.append("")

    lines.extend(
        [
            "## Conversation Links",
            "",
            f"- Slack thread (app redirect): {slack_links['app_redirect']}",
        ]
    )
    if "workspace_permalink" in slack_links:
        lines.append(f"- Slack thread (workspace permalink): {slack_links['workspace_permalink']}")
    if github_links:
        for link in github_links:
            lines.append(f"- GitHub: {link}")
    else:
        lines.append("- GitHub: none detected in conversation")
    lines.append("")

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

    if post_checks_results:
        lines.extend(
            [
                "---",
                "",
                "## Post Checks",
                "",
                "| Check | Required | Status | Details |",
                "|-------|----------|--------|---------|",
            ]
        )
        for check in post_checks_results:
            required = "Yes" if check.get("required", True) else "No"
            status = "✅ Pass" if check.get("passed") else "❌ Fail"
            details = str(check.get("details", "")).replace("\n", " ")
            lines.append(f"| {check.get('name','')} | {required} | {status} | {details} |")

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
    wait_timeout: int = 600,
    poll_interval: int = 5,
    gateway_url: str | None = None,
    framework: str | None = None,
    custom_message: str | None = None,
    skip_eval: bool = False,
    existing_thread_ts: str | None = None,
    handoff_timeout_extension: int = 600,
    use_async: bool = False,
) -> dict[str, Any]:
    """
    Run a full E2E evaluation:
    1. Post message to Slack (or use existing thread if existing_thread_ts provided)
    2. Trigger gateway to process the message (skipped for existing threads)
    3. Wait for bot response (skipped for existing threads)
    4. Evaluate with DeepEval
    5. Generate report

    Args:
        scenario_name: Name of the scenario to run (or "custom" for custom messages)
        channel: Slack channel ID (defaults to SLACK_DEFAULT_CHANNEL env var)
        wait_timeout: Timeout in seconds for agent response
        poll_interval: Polling interval in seconds
        gateway_url: Gateway URL for triggering agents (defaults to GATEWAY_URL env var)
        framework: Optional agent framework override (e.g., "openclaw")
        custom_message: Custom message to send (overrides scenario message)
        skip_eval: Skip DeepEval evaluation (just post and collect responses)
        existing_thread_ts: If provided, re-score an existing Slack thread instead of
            posting a new message. Skips Steps 1, 1b, and 2 — jumps directly to
            conversation collection and evaluation.
        handoff_timeout_extension: Seconds to extend wait_timeout when a handoff is
            detected (default: 600). Applied once per handoff detection.
        use_async: If True, trigger gateway in async mode (POST /run/async →
            POST /callback/agent). This exercises the full async callback lifecycle
            including CALLBACK_SECRET verification. Default: False (sync mode).
    """
    # Get scenario config
    if custom_message:
        # Custom message mode — create a minimal scenario config
        scenario = {
            "name": f"Custom: {custom_message[:50]}...",
            "message": custom_message,
            "expected_agent": "unknown",
            "evaluation_criteria": {
                "TaskCompletion": (
                    "Did the agent complete the requested task or make meaningful progress? "
                    "The agent should address the specific request and provide actionable output."
                ),
            },
            "threshold": 0.60,
        }
    elif scenario_name not in SCENARIOS:
        available = ", ".join(SCENARIOS.keys())
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {available}")
    else:
        scenario = SCENARIOS[scenario_name]

    # Check if scenario is disabled
    if scenario.get("disabled"):
        print(f"\n>>> Scenario '{scenario_name}' is DISABLED: skipping.")
        print(f"    Reason: {scenario.get('disabled_reason', 'See scenario config')}")
        return

    # Use per-scenario timeout if defined and CLI didn't explicitly override
    if "timeout" in scenario and wait_timeout == 600:
        wait_timeout = scenario["timeout"]

    # Initialize Slack connector
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    if not slack_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable not set")

    slack = SlackConnector(token=slack_token)

    async def _slack_call(fn: Any, *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
        """Run a Slack API call in a thread with a timeout to avoid hangs."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Slack API call timed out") from exc

    # Determine channel
    if not channel:
        channel = os.environ.get("SLACK_DEFAULT_CHANNEL")
    if not channel:
        raise ValueError("No channel specified. Use --channel or set SLACK_DEFAULT_CHANNEL")

    print("=" * 70)
    print("E2E SLACK AGENT EVALUATION")
    print("=" * 70)
    print(f"Scenario: {scenario['name']}")
    print(f"Channel: {channel}")
    if existing_thread_ts:
        print(f"Mode: RE-SCORE existing thread {existing_thread_ts}")
    else:
        print(f"Wait Timeout: {wait_timeout}s")
    print()

    user_message = scenario["message"]

    if existing_thread_ts:
        # ── Re-score mode: skip Steps 1, 1b, 2 ──────────────────────────
        thread_ts = existing_thread_ts
        print(f">>> Steps 1/1b/2: SKIPPED (re-scoring existing thread {thread_ts})")
        start_time = time.time()
        latency_ms = 0  # Not meaningful for re-score
    else:
        # ── Normal mode: post message, trigger gateway, poll ─────────────
        # Step 1: Post message to Slack
        print(">>> Step 1: Posting message to Slack")
        print(f"    Message: {user_message[:80]}...")

        # Post without role mentions to avoid duplicate processing from Slack bot events.
        posted_message = ROLE_PATTERN.sub("", user_message).strip()
        if not posted_message:
            posted_message = "Evaluation run (role mention omitted to avoid duplicate routing)."

        initial_msg = await _slack_call(slack.post_message, channel=channel, text=posted_message)
        thread_ts = initial_msg.ts
        print(f"    Thread TS: {thread_ts}")
        print("    Posted successfully!")

        # Step 1b: Trigger the gateway to process this message
        mode_label = "ASYNC" if use_async else "SYNC"
        print(f"\n>>> Step 1b: Triggering gateway to process message ({mode_label} mode)")
        default_prod_url = "https://webhook.team.vibebrowser.app"
        resolved_gateway_url = gateway_url or os.environ.get("GATEWAY_URL", default_prod_url)
        trigger_url = f"{resolved_gateway_url}/slack/trigger"

        if (
            resolved_gateway_url == default_prod_url
            and not gateway_url
            and not os.environ.get("GATEWAY_URL")
        ):
            print(f"    WARNING: Using default PRODUCTION gateway ({default_prod_url})")
            print("    Set GATEWAY_URL env var or --gateway-url to target a different environment")

        trigger_secret = os.environ.get("SLACK_TRIGGER_SECRET", "")
        headers: dict[str, str] = {}
        if trigger_secret:
            headers["Authorization"] = f"Bearer {trigger_secret}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                trigger_payload: dict[str, Any] = {
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "text": user_message,
                    "user_id": "eval_script",
                }
                if framework:
                    trigger_payload["framework"] = framework
                if use_async:
                    trigger_payload["use_async"] = True

                response = await client.post(
                    trigger_url,
                    json=trigger_payload,
                    headers=headers,
                )
                if response.status_code == 200:
                    result = response.json()
                    mode = result.get("mode", "sync")
                    print(
                        f"    Gateway accepted: routing to {result.get('roles', [])} (mode={mode})"
                    )
                else:
                    print(f"    WARNING: Gateway returned {response.status_code}: {response.text}")
        except Exception as e:
            print(f"    WARNING: Failed to trigger gateway: {e}")
            print(
                "    ERROR: Gateway trigger failed. No agent will be invoked — "
                "bot-posted messages do not generate Slack webhook events. "
                "The eval will wait but no response will arrive."
            )

        # Step 2: Wait for bot response (with handoff chain support + auto-extend)
        print(
            f"\n>>> Step 2: Waiting for agent response (idle timeout: {wait_timeout}s, no hard cap)"
        )
        start_time = time.time()
        effective_timeout = wait_timeout
        last_message_count = 1  # We posted 1 message
        # Stable time: how long to wait after the last change before concluding.
        # Agent async processing can take 90-120s, and progress/placeholder messages
        # arrive early. We use a short stable time (30s) once a substantive response
        # is detected, but require at least one substantive response before exiting.
        stable_time_no_handoff = 30
        stable_time_with_handoff = 300  # 5min wait for handoff agent
        last_change_time = start_time  # Tracks BOTH new messages AND content edits
        last_content_fingerprint = ""  # Hash of all message texts to detect chat.update edits
        pending_handoff = False
        has_substantive_response = False  # True once a real (non-placeholder) bot msg arrives
        # Track substantive responses per agent role for handoff completion.
        # When a handoff is detected, we need a substantive response from the
        # handoff *target* agent, not just the original agent.
        handoff_source_agent = ""  # e.g. "SupportEngineer" — the agent that initiated handoff
        handoff_target_responded = False  # True once the handoff target posts a real response

        def _content_fingerprint(replies: list) -> str:
            """Create a fingerprint of all message texts to detect in-place edits."""
            import hashlib

            content = "|".join(r.text for r in replies)
            return hashlib.md5(content.encode()).hexdigest()

        def _extract_agent_prefix(text: str) -> str:
            """Extract the agent name from a bot message prefix like '[SupportEngineer]'.

            Works for both substantive messages ('[Agent] ...') and progress
            messages ('_[Agent] Step N ..._').
            """
            import re

            # Match [AgentName] at start, optionally preceded by _ (italic progress)
            m = re.match(r"_?\[([A-Za-z]+)\]", text.strip())
            return m.group(1) if m else ""

        def _display_to_role(display: str) -> str:
            """Convert display name like 'SupportEngineer' to role key 'support_engineer'."""
            if not display:
                return ""
            lowered = display.strip().lower()
            for role, disp in ROLE_DISPLAY.items():
                if disp.lower() == lowered:
                    return role
            return ""

        def _parse_role_mentions_loose(text: str) -> list[str]:
            """Parse role mentions, including bare role names in handoff phrasing."""
            explicit = parse_role_mentions(text)
            if explicit:
                return explicit
            # Remove leading agent prefix like "[SupportEngineer]"
            clean = re.sub(r"_?\[[A-Za-z]+\]\s*", "", text.strip())
            names_pattern = "|".join(re.escape(v) for v in ROLE_DISPLAY.values())
            if not names_pattern:
                return []
            pattern = re.compile(rf"(?i)(?<![@/])\b({names_pattern})\b")
            display_to_role = {v.lower(): k for k, v in ROLE_DISPLAY.items()}
            roles: list[str] = []
            for match in pattern.findall(clean):
                role = display_to_role.get(match.lower())
                if role and role not in roles:
                    roles.append(role)
            return roles

        def _has_non_self_handoff(text: str) -> bool:
            """True if text mentions a role other than the current agent."""
            targets = _parse_role_mentions_loose(text)
            if not targets:
                return False
            source_role = _display_to_role(_extract_agent_prefix(text))
            # If we can't identify the source role, treat any mention as a handoff
            if not source_role:
                return True
            return any(t != source_role for t in targets)

        while True:
            await asyncio.sleep(poll_interval)

            replies = await _slack_call(
                slack.get_thread_replies, channel=channel, thread_ts=thread_ts, limit=50
            )
            current_count = len(replies)
            current_fingerprint = _content_fingerprint(replies)

            # Detect changes: new messages OR content edits (chat.update)
            count_changed = current_count > last_message_count
            content_changed = (
                current_fingerprint != last_content_fingerprint and last_content_fingerprint != ""
            )

            if count_changed or content_changed:
                if count_changed:
                    print(f"    New messages detected: {current_count - last_message_count}")
                if content_changed and not count_changed:
                    print("    Message content updated (chat.update detected)")
                last_message_count = current_count
                last_content_fingerprint = current_fingerprint
                last_change_time = time.time()

                bot_messages = [r for r in replies if r.is_bot and r.ts != thread_ts]
                if bot_messages:
                    latest_bot_msg = bot_messages[-1]
                    has_handoff = _has_non_self_handoff(latest_bot_msg.text)
                    if has_handoff and not scenario.get("skip_handoff", False):
                        print("    Handoff detected in response! Waiting for next agent...")
                        pending_handoff = True
                        effective_timeout = time.time() - start_time + handoff_timeout_extension
                        # Track which agent initiated the handoff so we can
                        # distinguish its messages from the handoff target's
                        handoff_source_agent = _extract_agent_prefix(latest_bot_msg.text)
                        handoff_target_responded = False
                        continue
                    else:
                        # DON'T clear pending_handoff on placeholder/progress messages!
                        # The handoff target agent posts progress updates (_[Agent] Step N_)
                        # before its final substantive response. We must keep waiting.
                        if pending_handoff and not handoff_target_responded:
                            # Check if this is a substantive response from the handoff target
                            new_substantive = [
                                m for m in bot_messages if not _is_placeholder(m.text)
                            ]
                            for msg in new_substantive:
                                agent = _extract_agent_prefix(msg.text)
                                if agent and agent != handoff_source_agent:
                                    handoff_target_responded = True
                                    pending_handoff = False
                                    print(
                                        f"    Handoff target [{agent}] posted substantive response."
                                    )
                                    break
                            # If still only progress from target, keep waiting
                            if not handoff_target_responded:
                                # Progress messages from handoff target reset the timer
                                # but don't clear handoff state
                                pass
                        else:
                            pending_handoff = False

                    # Check if any bot message is substantive (not a placeholder)
                    if not has_substantive_response:
                        substantive = [m for m in bot_messages if not _is_placeholder(m.text)]
                        if substantive:
                            has_substantive_response = True
                            print("    Substantive agent response detected.")
            else:
                # First poll — initialize fingerprint without treating as a change
                if last_content_fingerprint == "":
                    last_content_fingerprint = current_fingerprint

            bot_messages = [r for r in replies if r.is_bot and r.ts != thread_ts]
            if bot_messages and last_change_time > 0:
                time_since_last = time.time() - last_change_time
                stable_time = (
                    stable_time_with_handoff if pending_handoff else stable_time_no_handoff
                )
                if time_since_last >= stable_time:
                    # Only exit if we have a substantive response, not just placeholders
                    if not has_substantive_response:
                        # Re-check: messages may have been updated in-place
                        substantive = [m for m in bot_messages if not _is_placeholder(m.text)]
                        if substantive:
                            has_substantive_response = True
                        else:
                            # Still only placeholders — keep waiting
                            elapsed = int(time.time() - start_time)
                            print(
                                f"    Only placeholder messages so far, "
                                f"waiting for substantive response... ({elapsed}s)"
                            )
                            continue

                    latest_bot_msg = bot_messages[-1]
                    has_handoff = _has_non_self_handoff(latest_bot_msg.text)
                    if not has_handoff or scenario.get("skip_handoff", False):
                        print(
                            f"    Conversation stable for {int(time_since_last)}s, "
                            "no pending handoffs."
                        )
                        break
                    else:
                        print("    Still waiting for handoff response...")

            idle_timeout = handoff_timeout_extension if pending_handoff else wait_timeout
            idle_for = int(time.time() - last_change_time)
            elapsed = int(time.time() - start_time)
            print(f"    Waiting... (idle {idle_for}s / {idle_timeout}s, total {elapsed}s)")

            if idle_for >= idle_timeout:
                if not has_substantive_response:
                    print(
                        "    No substantive response before idle timeout. Stopping evaluation wait."
                    )
                else:
                    print("    Idle timeout reached after last response. Stopping wait.")
                break

        latency_ms = int((time.time() - start_time) * 1000)

    # Track conversation
    conversation: list[tuple[str, str]] = [("user", user_message)]

    # Step 3: Collect conversation
    print("\n>>> Step 3: Collecting conversation")
    replies = await _slack_call(
        slack.get_thread_replies, channel=channel, thread_ts=thread_ts, limit=50
    )

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

    post_checks_results: list[dict] = []
    post_checks_config = scenario.get("post_checks", {})
    if post_checks_config:
        print("\n>>> Step 3b: Running post checks")
        transcript = build_transcript(conversation)

        if post_checks_config.get("github_pr_created"):
            result = _check_github_pr_created(transcript)
            result["id"] = "github_pr_created"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("github_pr_author_is_bot"):
            result = _check_github_pr_author_is_bot(transcript)
            result["id"] = "github_pr_author_is_bot"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("github_issue_multi_bot_comments"):
            result = _check_github_issue_multi_bot_comments(transcript)
            result["id"] = "github_issue_multi_bot_comments"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("github_pr_multi_bot_comments"):
            result = _check_github_pr_multi_bot_comments(transcript)
            result["id"] = "github_pr_multi_bot_comments"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("github_discussion_multi_bot_comments"):
            result = _check_github_discussion_multi_bot_comments(transcript)
            result["id"] = "github_discussion_multi_bot_comments"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("github_pr_target_repo"):
            expected_repo = str(post_checks_config["github_pr_target_repo"])
            result = _check_github_pr_targets_repo(transcript, expected_repo)
            result["id"] = "github_pr_target_repo"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

        if post_checks_config.get("sentry_issue_closed"):
            result = _check_sentry_issue_closed(transcript)
            result["id"] = "sentry_issue_closed"
            post_checks_results.append(result)
            status = "✅" if result.get("passed") else "❌"
            print(f"    {status} {result.get('name')}: {result.get('details')}")

    # Step 4: Evaluate with DeepEval
    metrics_results = []

    if skip_eval:
        print("\n>>> Step 4: SKIPPED - Evaluation disabled (--skip-eval)")
    elif DEEPEVAL_AVAILABLE and len(conversation) > 1:
        print("\n>>> Step 4: Evaluating with DeepEval G-Eval")

        # Get Azure credentials
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", os.environ.get("AZURE_API_KEY"))
        api_base = os.environ.get("AZURE_OPENAI_ENDPOINT", os.environ.get("AZURE_API_BASE"))
        if not api_key:
            api_key = os.environ.get("LITELLM_AZURE_OPENAI_API_KEY")
        if not api_base:
            api_base = os.environ.get("LITELLM_AZURE_OPENAI_BASE_URL")
        api_version = os.environ.get(
            "AZURE_EVAL_API_VERSION",
            os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
        )
        wire_api = os.environ.get("AZURE_EVAL_WIRE_API", os.environ.get("AZURE_WIRE_API", "")).strip().lower()
        if not os.environ.get("AZURE_EVAL_API_VERSION") and api_base and api_base.rstrip("/").endswith("/openai"):
            # Matches ~/.codex/config.toml defaults (responses API).
            api_version = "2025-04-01-preview"
            if not wire_api:
                wire_api = "responses"

        # Warn if credentials appear to be from wrong environment
        if api_base and "vibebrowser" not in api_base.lower():
            print(f"    WARNING: Azure endpoint '{api_base}' doesn't contain 'vibebrowser'.")
            print("    This may be a shell env var overriding .env. Try:")
            print(
                "    unset AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_API_BASE AZURE_API_KEY"
            )
            print("    export $(grep -v '^#' .env | grep -E '^AZURE_' | xargs)")
            print("")

        if api_key and api_base:
            try:
                raw_model = os.environ.get(
                    "BENCHMARK_JUDGE_MODEL",
                    os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2"),
                )
                resolved_model = resolve_azure_model(
                    raw_model,
                    api_base=api_base,
                    api_version=api_version,
                    allow_responses_models=False,
                )
                # Azure deployment names should NOT include "azure/" prefix
                if resolved_model and resolved_model.startswith("azure/"):
                    resolved_model = resolved_model.split("/", 1)[1]
                if resolved_model and resolved_model != raw_model:
                    print(
                        f"    WARNING: Judge model '{raw_model}' is not chat-compatible. "
                        f"Using '{resolved_model}' instead."
                    )
                model = AzureOpenAIModel(
                    api_key=api_key,
                    api_base=api_base,
                    model=resolved_model or raw_model or "gpt-5.2",
                    api_version=api_version,
                    wire_api=wire_api or None,
                )

                transcript = build_transcript(conversation)
                test_case = LLMTestCase(
                    input=user_message,
                    actual_output=transcript,
                )

                for metric_name, criteria in scenario["evaluation_criteria"].items():
                    print(f"    Evaluating: {metric_name}")

                    # Build evaluation_steps from the criteria's SCORING rubric
                    # if available, so the LLM judge follows our rubric faithfully
                    # instead of auto-generating potentially divergent steps.
                    eval_steps = scenario.get("evaluation_steps", {}).get(metric_name)

                    geval_kwargs: dict = {
                        "name": metric_name,
                        "criteria": criteria,
                        "evaluation_params": [
                            LLMTestCaseParams.INPUT,
                            LLMTestCaseParams.ACTUAL_OUTPUT,
                        ],
                        "threshold": scenario["threshold"],
                        "model": model,
                    }
                    if eval_steps:
                        geval_kwargs["evaluation_steps"] = eval_steps

                    metric = GEval(**geval_kwargs)

                    metric.measure(test_case)

                    metrics_results.append(
                        {
                            "name": metric_name,
                            "score": metric.score,
                            "threshold": metric.threshold,
                            "reason": metric.reason,
                        }
                    )

                    score = metric.score if metric.score is not None else 0.0
                    threshold = metric.threshold if metric.threshold is not None else 0.0
                    status = "✅" if score >= threshold else "❌"
                    print(f"      {status} Score: {score:.2f} (threshold: {threshold})")

            except Exception as e:
                print(f"    ERROR: Evaluation failed: {e}")
        else:
            print("    WARNING: Azure credentials not set. Skipping evaluation.")
    else:
        if len(conversation) <= 1:
            print("\n>>> Step 4: SKIPPED - No agent response received")
        else:
            print("\n>>> Step 4: SKIPPED - DeepEval not available")

    metric_overrides = scenario.get("metric_overrides", {})
    if metrics_results and metric_overrides and post_checks_results:
        checks_by_id = {c.get("id"): c for c in post_checks_results if c.get("id")}
        for metric in metrics_results:
            override_checks = metric_overrides.get(metric["name"])
            if not override_checks:
                continue
            if all(checks_by_id.get(check_id, {}).get("passed") for check_id in override_checks):
                metric["score"] = 1.0
                metric["reason"] = (
                    "Overridden to pass based on required post-checks: "
                    + ", ".join(override_checks)
                )

    # Step 5: Generate report
    print("\n>>> Step 5: Generating evaluation report")

    report_path = generate_eval_report(
        scenario_name=scenario_name,
        scenario_config=scenario,
        slack_channel=channel,
        thread_ts=thread_ts,
        conversation=conversation,
        metrics_results=metrics_results,
        post_checks_results=post_checks_results,
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

    required_checks = [c for c in post_checks_results if c.get("required", True)]
    post_checks_passed = (
        all(c.get("passed") for c in required_checks) if required_checks else None
    )
    metrics_passed = all(m["score"] >= m["threshold"] for m in metrics_results) if metrics_results else None

    if metrics_passed is None and post_checks_passed is None:
        print("Overall: ⚠️ NOT EVALUATED")
    elif metrics_passed is None:
        print(f"Overall: {'✅ PASSED' if post_checks_passed else '❌ FAILED'} (post-checks only)")
    elif post_checks_passed is None:
        print(f"Overall: {'✅ PASSED' if metrics_passed else '❌ FAILED'}")
    else:
        overall_passed = metrics_passed and post_checks_passed
        print(f"Overall: {'✅ PASSED' if overall_passed else '❌ FAILED'}")

    if metrics_results:
        for m in metrics_results:
            status = "✅" if m["score"] >= m["threshold"] else "❌"
            print(f"  {status} {m['name']}: {m['score']:.2f}")

    if post_checks_results:
        print("Post-checks:")
        for check in post_checks_results:
            status = "✅" if check.get("passed") else "❌"
            print(f"  {status} {check.get('name')}: {check.get('details')}")

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
  python scripts/eval_slack_e2e.py --scenario stripe_webhook_failure --timeout 300
  python scripts/eval_slack_e2e.py --message "@SupportEngineer check Sentry for errors"
  python scripts/eval_slack_e2e.py --channel C0123456789 --skip-eval
  python scripts/eval_slack_e2e.py --list-scenarios
  python scripts/eval_slack_e2e.py --scenario stripe_webhook_failure --thread-ts 1770710833.425539 --channel C0AATPSADB8
  python scripts/eval_slack_e2e.py --scenario support_400_errors --use-async
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="support_400_errors",
        help="Evaluation scenario to run (default: support_400_errors)",
    )
    parser.add_argument(
        "--message",
        help="Custom message to send (overrides --scenario). Must include @RoleName mention.",
    )
    parser.add_argument(
        "--channel",
        help="Slack channel ID to post to (default: SLACK_DEFAULT_CHANNEL env var)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds waiting for agent response (default: 600). "
        "Per-scenario timeouts in SCENARIOS dict override this default unless explicitly set.",
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
    parser.add_argument(
        "--gateway-url",
        help="Gateway URL for triggering agents (default: GATEWAY_URL env var or https://webhook.team.vibebrowser.app)",
    )
    parser.add_argument(
        "--framework",
        help='Agent framework override for /slack/trigger (e.g., "openclaw")',
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip DeepEval evaluation (just post and collect responses)",
    )
    parser.add_argument(
        "--thread-ts",
        help=(
            "Re-score an existing Slack thread instead of posting a new message. "
            "Requires --scenario (for evaluation criteria) and --channel."
        ),
    )
    parser.add_argument(
        "--handoff-timeout",
        type=int,
        default=600,
        help=(
            "Seconds to extend wait timeout when a handoff is detected (default: 600). "
            "Ignored in --thread-ts mode."
        ),
    )
    parser.add_argument(
        "--use-async",
        action="store_true",
        help=(
            "Use async callback flow (POST /run/async -> POST /callback/agent) "
            "instead of the default synchronous path. This exercises the full "
            "async lifecycle including CALLBACK_SECRET verification."
        ),
    )

    args = parser.parse_args()

    if args.list_scenarios:
        print("Available Scenarios:")
        for name, config in SCENARIOS.items():
            disabled = " [DISABLED]" if config.get("disabled") else ""
            print(f"  {name}{disabled}:")
            print(f"    Name: {config['name']}")
            print(f"    Agent: {config['expected_agent']}")
            print(f"    Message: {config['message'][:60]}...")
            print()
        return 0

    # Determine scenario name and custom message
    scenario_name = "custom" if args.message else args.scenario
    custom_message = args.message

    # Validate --thread-ts usage
    if args.thread_ts and args.message:
        print("ERROR: --thread-ts and --message are mutually exclusive.")
        print("       --thread-ts re-scores an existing thread; --message posts a new one.")
        return 1

    try:
        result = asyncio.run(
            run_evaluation(
                scenario_name=scenario_name,
                channel=args.channel,
                wait_timeout=args.timeout,
                poll_interval=args.poll_interval,
                gateway_url=args.gateway_url,
                framework=args.framework,
                custom_message=custom_message,
                skip_eval=args.skip_eval,
                existing_thread_ts=args.thread_ts,
                handoff_timeout_extension=args.handoff_timeout,
                use_async=args.use_async,
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
