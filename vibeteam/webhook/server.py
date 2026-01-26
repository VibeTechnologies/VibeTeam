"""
Webhook Server for VibeTeam.

Receives GitHub and Slack webhook events and dispatches to appropriate agents.
Supports:
- GitHub issues.assigned: Trigger agent when issue assigned to vibeteam-bot
- GitHub issue_comment.created: Respond to @mentions in comments
- Slack app_mention: Respond to @VibeTeam mentions in Slack
- Slack message.im: Respond to direct messages
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
from typing import Any

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
    """Run the appropriate agent based on Slack message and respond."""
    logger.info(f"Processing Slack message from {user_id}: {user_message[:100]}")

    # For now, acknowledge and process with a general response
    # TODO: Integrate with proper agent dispatch based on message content

    try:
        # Run the orchestrator or appropriate agent
        cmd = [
            sys.executable,
            "-m",
            "vibeteam.cli",
            "run",
            user_message,
            "--agent",
            "swe",  # Default to SWE agent
        ]

        env = os.environ.copy()
        env["SLACK_RESPONSE_CHANNEL"] = channel
        if thread_ts:
            env["SLACK_RESPONSE_THREAD"] = thread_ts

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            response = stdout.decode().strip() or "Task completed successfully."
        else:
            response = f"I encountered an error processing your request. Please try again or check the logs."
            logger.error(f"Agent failed: {stderr.decode()}")

        await send_slack_message(channel, response, thread_ts)

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
            f"Got it! I'm working on your request...",
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
            f"Got it! I'm working on your request...",
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
