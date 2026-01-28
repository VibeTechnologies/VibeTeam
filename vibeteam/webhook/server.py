"""
Webhook Server for VibeTeam.

Receives webhook events and routes to appropriate agents via OpenHands.
Supports:
- GitHub issues.assigned: Trigger agent when issue assigned to vibeteam-bot
- GitHub issue_comment.created: Respond to @mentions in comments
- Slack app_mention: Respond to @VibeTeam mentions in Slack
- Slack message.im: Respond to direct messages
- Sentry issue.created: Triage new errors and create GitHub issues

Routing Strategy:
- Known sources (Sentry, GitHub) → Inject specific context/instructions
- Unknown intent (Slack) → Let microagents handle via keyword triggers
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VibeTeam Webhook",
    description="GitHub webhook handler for VibeTeam agents",
    version="1.0.0",
)

# Configuration - GitHub
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
BOT_USERNAME = os.environ.get("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")

# Configuration - Slack
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Configuration - Sentry
SENTRY_CLIENT_SECRET = os.environ.get("SENTRY_CLIENT_SECRET", "")

# Configuration - OpenHands Agent Server
OPENHANDS_SERVER_URL = os.environ.get("OPENHANDS_SERVER_URL", "http://openhands-server:8000")
OPENHANDS_API_KEY = os.environ.get("OPENHANDS_API_KEY", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "azure/gpt-5-2")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")


class WebhookPayload(BaseModel):
    """Generic webhook payload."""

    action: str
    repository: dict[str, Any] | None = None
    issue: dict[str, Any] | None = None
    comment: dict[str, Any] | None = None
    sender: dict[str, Any] | None = None
    assignee: dict[str, Any] | None = None


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET not set, skipping verification")
        return True

    if not signature or not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_bot_user_id() -> str | None:
    """Get the bot's user ID from environment or cache."""
    return os.environ.get("GITHUB_BOT_USER_ID")


def is_assigned_to_bot(assignee: dict[str, Any] | None) -> bool:
    """Check if the assignee is our bot."""
    if not assignee:
        return False

    assignee_login = assignee.get("login", "")
    bot_user_id = get_bot_user_id()

    # Check by login name
    if BOT_USERNAME.replace("[bot]", "") in assignee_login:
        return True

    # Check by user ID if available
    if bot_user_id and str(assignee.get("id")) == bot_user_id:
        return True

    return False


async def run_swe_agent(repo: str, issue_number: int, issue_title: str, issue_body: str) -> None:
    """Run the Software Engineer agent on an issue."""
    logger.info(f"Starting SWE agent for {repo}#{issue_number}: {issue_title}")

    # Run the CLI command asynchronously
    cmd = [
        sys.executable,
        "-m",
        "vibeteam.cli",
        "scheduled",
        "swe-issues",
        "--repo",
        repo,
        "--label",
        "",  # Process this specific issue regardless of label
    ]

    # Set environment to process specific issue
    env = os.environ.copy()
    env["VIBETEAM_ISSUE_NUMBER"] = str(issue_number)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            logger.info(f"SWE agent completed successfully for {repo}#{issue_number}")
        else:
            logger.error(f"SWE agent failed: {stderr.decode()}")

    except Exception as e:
        logger.exception(f"Failed to run SWE agent: {e}")


async def post_acknowledgment(repo: str, issue_number: int) -> None:
    """Post a comment acknowledging the assignment."""
    from vibeteam.utils.github_app import get_installation_token

    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

    if not app_id or not private_key or not installation_id:
        logger.warning("GitHub App credentials not configured, skipping acknowledgment")
        return

    try:
        import httpx

        token = get_installation_token(str(app_id), str(private_key), str(installation_id))

        comment_body = (
            "I've been assigned to this issue and will start working on it.\n\n"
            "I'll analyze the problem and create a PR with a fix if possible. "
            "You can track my progress in the linked PR once it's created."
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"body": comment_body},
            )
            response.raise_for_status()
            logger.info(f"Posted acknowledgment to {repo}#{issue_number}")

    except Exception as e:
        logger.exception(f"Failed to post acknowledgment: {e}")


async def run_release_engineer_agent(issue_data: dict[str, Any], classification: str) -> None:
    """Run the Release Engineer agent on a Sentry issue."""
    issue_id = issue_data.get("shortId", "unknown")
    logger.info(f"Starting Release Engineer agent for Sentry issue {issue_id}")

    # Run the CLI command asynchronously
    cmd = [
        sys.executable,
        "-m",
        "vibeteam.cli",
        "scheduled",
        "release-triage",
        "--issue-json",
        json.dumps(issue_data),
        "--classification",
        classification,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            logger.info(f"Release Engineer agent completed successfully for {issue_id}")
        else:
            logger.error(f"Release Engineer agent failed: {stderr.decode()}")

    except Exception as e:
        logger.exception(f"Failed to run Release Engineer agent: {e}")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "vibeteam-webhook"}


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Handle incoming GitHub webhook events."""
    payload_bytes = await request.body()

    # Verify signature
    if not verify_signature(payload_bytes, x_hub_signature_256 or "", GITHUB_WEBHOOK_SECRET):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(payload_bytes)
    action = payload.get("action", "")
    repo_data = payload.get("repository", {})
    repo_full_name = repo_data.get("full_name", "")

    logger.info(f"Received {x_github_event}.{action} for {repo_full_name}")

    # Handle issue assignment
    if x_github_event == "issues" and action == "assigned":
        assignee = payload.get("assignee")
        issue = payload.get("issue", {})

        if is_assigned_to_bot(assignee):
            issue_number = issue.get("number")
            issue_title = issue.get("title", "")
            issue_body = issue.get("body", "")

            logger.info(f"Issue #{issue_number} assigned to bot, triggering SWE agent")

            # Post acknowledgment and run agent in background
            asyncio.create_task(post_acknowledgment(repo_full_name, issue_number))
            asyncio.create_task(
                run_swe_agent(repo_full_name, issue_number, issue_title, issue_body)
            )

            return {"status": "accepted", "message": f"Processing issue #{issue_number}"}

    # Handle @mention in comments
    if x_github_event == "issue_comment" and action == "created":
        comment = payload.get("comment", {})
        comment_body = comment.get("body", "")
        issue = payload.get("issue", {})

        # Check if bot is mentioned
        if f"@{BOT_USERNAME.replace('[bot]', '')}" in comment_body:
            issue_number = issue.get("number")
            logger.info(f"Bot mentioned in comment on #{issue_number}")

            # Parse command from comment (e.g., "@vibeteam-bot fix this")
            # For now, trigger SWE agent on any mention
            asyncio.create_task(
                run_swe_agent(
                    repo_full_name,
                    issue_number,
                    issue.get("title", ""),
                    issue.get("body", ""),
                )
            )

            return {"status": "accepted", "message": f"Processing mention in #{issue_number}"}

    return {"status": "ignored", "event": f"{x_github_event}.{action}"}


# ==============================================================================
# OpenHands Agent Server Integration
# ==============================================================================


async def start_openhands_conversation(
    task: str,
    workspace_dir: str = "/workspace/VibeWebAgent",
) -> dict[str, Any]:
    """
    Start a conversation with the OpenHands Agent Server.

    This routes the task to OpenHands which will use microagents based on
    keyword triggers in the task message.

    Args:
        task: The task description (keywords trigger appropriate microagents)
        workspace_dir: Working directory for the agent

    Returns:
        Conversation response with ID and status
    """
    if not LLM_API_KEY:
        logger.error("LLM_API_KEY not set, cannot start agent conversation")
        return {"error": "LLM_API_KEY not configured"}

    agent_config = {
        "agent": {
            "llm": {
                "model": LLM_MODEL,
                "api_key": LLM_API_KEY,
                "base_url": LLM_BASE_URL or None,
                "temperature": 0.3,
            },
            "tools": [
                {"name": "TerminalTool"},
                {"name": "FileEditorTool"},
                {"name": "TaskTrackerTool"},
            ],
            "kind": "Agent",
        },
        "workspace": {
            "working_dir": workspace_dir,
            "kind": "LocalWorkspace",
        },
        "initial_message": {
            "content": [{"text": task}],
        },
        "max_iterations": 100,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Content-Type": "application/json"}
            if OPENHANDS_API_KEY:
                headers["Authorization"] = f"Bearer {OPENHANDS_API_KEY}"

            response = await client.post(
                f"{OPENHANDS_SERVER_URL}/api/conversations",
                headers=headers,
                json=agent_config,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Started OpenHands conversation: {result.get('id')}")
            return result

    except httpx.HTTPError as e:
        logger.exception(f"Failed to start OpenHands conversation: {e}")
        return {"error": str(e)}


# ==============================================================================
# Sentry Webhook Handler
# ==============================================================================


def verify_sentry_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Sentry webhook signature (HMAC-SHA256)."""
    if not secret:
        logger.warning("SENTRY_CLIENT_SECRET not set, skipping verification")
        return True

    if not signature:
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def classify_sentry_issue(issue: dict[str, Any]) -> str:
    """
    Classify a Sentry issue as NOISE, VALID_BUG, or NEEDS_INVESTIGATION.

    This provides a fast pre-filter before invoking the LLM agent.
    """
    title = issue.get("title", "")
    count = issue.get("count", 0)
    user_count = issue.get("userCount", 0)

    # NOISE patterns - auto-skip
    noise_patterns = [
        "Failed to fetch",
        "NetworkError",
        "net::ERR_",
        "ResizeObserver loop",
        "Script error.",
        "AbortError",
        "ECONNREFUSED",
    ]

    for pattern in noise_patterns:
        if pattern.lower() in title.lower():
            # Even noise with high impact should be investigated
            if count >= 100 or user_count >= 20:
                return "NEEDS_INVESTIGATION"
            return "NOISE"

    # Check for chrome extension errors (except ours)
    if "chrome-extension://" in title:
        our_extension_id = "ajfjlohdpfgngdjfafhhcnpmijbbdgln"
        if our_extension_id not in title:
            return "NOISE"

    # VALID_BUG patterns
    bug_patterns = [
        "TypeError",
        "ReferenceError",
        "Cannot read property",
        "is not a function",
        "undefined is not",
        "Unhandled Promise",
    ]

    for pattern in bug_patterns:
        if pattern.lower() in title.lower():
            return "VALID_BUG"

    # High impact issues need investigation
    if count >= 50 or user_count >= 10:
        return "VALID_BUG"

    # Low impact unknown issues
    if count < 5 and user_count < 3:
        return "NOISE"

    return "NEEDS_INVESTIGATION"


@app.post("/webhook/sentry")
async def handle_sentry_webhook(
    request: Request,
    sentry_hook_signature: str = Header(None, alias="Sentry-Hook-Signature"),
) -> dict[str, Any]:
    """
    Handle incoming Sentry webhook events.

    Sentry webhooks are triggered when new issues are created or existing
    issues receive new events. We route these to the Release Engineer agent
    via OpenHands with Sentry-specific context.
    """
    payload_bytes = await request.body()

    # Verify signature
    if not verify_sentry_signature(
        payload_bytes, sentry_hook_signature or "", SENTRY_CLIENT_SECRET
    ):
        logger.warning("Invalid Sentry webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(payload_bytes)
    action = payload.get("action", "")
    data = payload.get("data", {})
    issue = data.get("issue", {})

    logger.info(f"Received Sentry webhook: action={action}, issue={issue.get('shortId')}")

    # Only process issue events
    if not issue:
        return {"status": "ignored", "reason": "no_issue_data"}

    # Pre-classify to avoid LLM calls for obvious noise
    classification = classify_sentry_issue(issue)

    if classification == "NOISE":
        logger.info(f"Sentry issue {issue.get('shortId')} classified as NOISE, skipping")
        return {
            "status": "skipped",
            "reason": "noise",
            "issue_id": issue.get("id"),
            "short_id": issue.get("shortId"),
        }

    # Build task for OpenHands agent with Sentry-specific context
    # This will trigger the sentry.md microagent via keywords

    # Start agent conversation in background
    # asyncio.create_task(start_openhands_conversation(task))

    # Trigger Release Engineer agent directly
    asyncio.create_task(run_release_engineer_agent(issue, classification))

    return {
        "status": "accepted",
        "classification": classification,
        "issue_id": issue.get("id"),
        "short_id": issue.get("shortId"),
    }


def verify_slack_signature(payload: bytes, timestamp: str, signature: str, secret: str) -> bool:
    """Verify Slack request signature."""
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not set, skipping verification")
        return True

    if not signature or not timestamp:
        return False

    # Check timestamp to prevent replay attacks (5 minute window)
    import time

    if abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Slack request timestamp too old")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{payload.decode('utf-8')}"
    expected = (
        "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    )

    return hmac.compare_digest(expected, signature)


async def send_slack_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    """Send a message to Slack."""
    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot send message")
        return

    try:
        import httpx

        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            result = response.json()
            if not result.get("ok"):
                logger.error(f"Slack API error: {result.get('error')}")
            else:
                logger.info(f"Sent message to {channel}")

    except Exception as e:
        logger.exception(f"Failed to send Slack message: {e}")


async def run_agent_for_slack(
    user_message: str, channel: str, thread_ts: str | None, user_id: str
) -> None:
    """
    Run the appropriate agent based on Slack message and respond.

    Slack messages have unknown intent, so we pass them to OpenHands and let
    the microagents handle routing based on keyword triggers:
    - "sentry", "error" → sentry.md microagent
    - "email", "customer" → support.md microagent
    - "fix", "implement" → code_fix.md microagent
    """
    logger.info(f"Processing Slack message from {user_id}: {user_message[:100]}")

    try:
        # Build task for OpenHands - microagents will activate based on keywords
        task = f"""## Slack Request

A user has requested help via Slack.

### User Message
{user_message}

### Context
- User ID: {user_id}
- Channel: {channel}
- Response thread: {thread_ts or "new thread"}

### Instructions
1. Analyze what the user is asking for
2. Complete the task using available tools
3. Provide a clear, concise response

Please help with this request.
"""

        # Start OpenHands conversation
        result = await start_openhands_conversation(task)

        if "error" in result:
            await send_slack_message(
                channel,
                f"Sorry, I encountered an error: {result['error']}",
                thread_ts,
            )
        else:
            # TODO: Stream conversation events back to Slack
            # For now, just acknowledge that processing started
            await send_slack_message(
                channel,
                f"I'm working on your request. Conversation ID: {result.get('id', 'unknown')}",
                thread_ts,
            )

    except Exception as e:
        logger.exception(f"Failed to run agent for Slack: {e}")
        await send_slack_message(
            channel,
            "Sorry, I encountered an unexpected error. Please try again later.",
            thread_ts,
        )


@app.post("/slack/events")
async def handle_slack_events(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
) -> dict[str, Any]:
    """Handle incoming Slack events."""
    payload_bytes = await request.body()
    payload = json.loads(payload_bytes)

    # Handle URL verification challenge first (Slack requires immediate response)
    if payload.get("type") == "url_verification":
        logger.info("Responding to Slack URL verification challenge")
        return {"challenge": payload.get("challenge")}

    # Verify signature for all other events
    if not verify_slack_signature(
        payload_bytes,
        x_slack_request_timestamp or "",
        x_slack_signature or "",
        SLACK_SIGNING_SECRET,
    ):
        logger.warning("Invalid Slack signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Handle events
    event = payload.get("event", {})
    event_type = event.get("type")

    logger.info(f"Received Slack event: {event_type}")

    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return {"status": "ignored", "reason": "bot_message"}

    # Handle app_mention events
    if event_type == "app_mention":
        user_id = event.get("user", "")
        channel = event.get("channel", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        # Remove the bot mention from the text
        # Format is usually "<@BOTID> message"
        import re

        clean_text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        # Acknowledge immediately
        await send_slack_message(
            channel,
            "Got it! I'm working on your request...",
            thread_ts,
        )

        # Process in background
        asyncio.create_task(run_agent_for_slack(clean_text, channel, thread_ts, user_id))

        return {"status": "accepted", "event": "app_mention"}

    # Handle direct messages
    if event_type == "message" and event.get("channel_type") == "im":
        user_id = event.get("user", "")
        channel = event.get("channel", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        # Acknowledge immediately
        await send_slack_message(
            channel,
            "Got it! I'm working on your request...",
            thread_ts,
        )

        # Process in background
        asyncio.create_task(run_agent_for_slack(text, channel, thread_ts, user_id))

        return {"status": "accepted", "event": "message.im"}

    return {"status": "ignored", "event": event_type}


def main() -> None:
    """Run the webhook server."""
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting webhook server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
