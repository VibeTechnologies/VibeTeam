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

from agents.shared.role_resolver import ROLE_PATTERN
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


class AzureOpenAIModel(DeepEvalBaseLLM):  # type: ignore[misc]
    """Azure OpenAI model wrapper for DeepEval G-Eval."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        api_version: str = "2024-08-01-preview",
        model: str = "gpt-5.2",
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
    agents_ran = list({role for role, _ in conversation if role != "user"})

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
    wait_timeout: int = 600,
    poll_interval: int = 5,
    gateway_url: str | None = None,
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

        initial_msg = slack.post_message(channel=channel, text=user_message)
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
        print(f"\n>>> Step 2: Waiting for agent response (timeout: {wait_timeout}s)")
        start_time = time.time()
        last_message_count = 1  # We posted 1 message
        # Stable time: how long to wait after the last change before concluding.
        # Agent async processing can take 90-120s, and progress/placeholder messages
        # arrive early. We use a short stable time (30s) once a substantive response
        # is detected, but require at least one substantive response before exiting.
        stable_time_no_handoff = 30
        stable_time_with_handoff = 300  # 5min wait for handoff agent
        last_change_time = 0.0  # Tracks BOTH new messages AND content edits
        last_content_fingerprint = ""  # Hash of all message texts to detect chat.update edits
        pending_handoff = False
        effective_timeout = wait_timeout
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

        while time.time() - start_time < effective_timeout:
            await asyncio.sleep(poll_interval)

            replies = slack.get_thread_replies(channel=channel, thread_ts=thread_ts, limit=50)
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
                    has_handoff = bool(ROLE_PATTERN.search(latest_bot_msg.text))
                    if has_handoff:
                        # Auto-extend timeout on handoff detection
                        remaining = (start_time + effective_timeout) - time.time()
                        if handoff_timeout_extension > remaining:
                            effective_timeout = time.time() - start_time + handoff_timeout_extension
                            print(
                                f"    Handoff detected! Extended timeout to "
                                f"{int(effective_timeout)}s "
                                f"(+{handoff_timeout_extension}s from now)"
                            )
                        else:
                            print("    Handoff detected in response! Waiting for next agent...")
                        pending_handoff = True
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
                    has_handoff = bool(ROLE_PATTERN.search(latest_bot_msg.text))
                    if not has_handoff:
                        print(
                            f"    Conversation stable for {int(time_since_last)}s, "
                            "no pending handoffs."
                        )
                        break
                    else:
                        print("    Still waiting for handoff response...")

            elapsed = int(time.time() - start_time)
            print(f"    Waiting... ({elapsed}s / {int(effective_timeout)}s)")

        latency_ms = int((time.time() - start_time) * 1000)

    # Track conversation
    conversation: list[tuple[str, str]] = [("user", user_message)]

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

    if skip_eval:
        print("\n>>> Step 4: SKIPPED - Evaluation disabled (--skip-eval)")
    elif DEEPEVAL_AVAILABLE and len(conversation) > 1:
        print("\n>>> Step 4: Evaluating with DeepEval G-Eval")

        # Get Azure credentials
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", os.environ.get("AZURE_API_KEY"))
        api_base = os.environ.get("AZURE_OPENAI_ENDPOINT", os.environ.get("AZURE_API_BASE"))
        api_version = os.environ.get(
            "AZURE_EVAL_API_VERSION",
            os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
        )

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
                model = AzureOpenAIModel(
                    api_key=api_key,
                    api_base=api_base,
                    model=os.environ.get(
                        "BENCHMARK_JUDGE_MODEL",
                        os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2"),
                    ),
                    api_version=api_version,
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
