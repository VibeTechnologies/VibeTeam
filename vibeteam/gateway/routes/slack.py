"""
Slack Event Handlers.

Handles Slack events and routes to agent microservices:
- app_mention: Respond to @VibeTeam mentions in channels
- message.im: Respond to direct messages

Uses the Router for /RoleName mention-based routing.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from vibeteam.gateway.server import call_agent_service, config
from vibeteam.router import Router, UnifiedMessage
from vibeteam.router.models import ROLE_DISPLAY_NAMES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])

# Message router for /RoleName parsing
_message_router: Router | None = None


def get_message_router() -> Router:
    """Get or create the message router."""
    global _message_router
    if _message_router is None:
        _message_router = Router()
    return _message_router


def verify_slack_signature(
    payload: bytes,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """Verify Slack request signature."""
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not set, skipping verification")
        return True

    if not signature or not timestamp:
        return False

    # Check timestamp to prevent replay attacks (5 minute window)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Slack request timestamp too old")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{payload.decode('utf-8')}"
    expected = (
        "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    )

    return hmac.compare_digest(expected, signature)


async def send_slack_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
) -> None:
    """Send a message to Slack."""
    if not config.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot send message")
        return

    try:
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
                    "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
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


async def add_reaction(
    channel: str,
    timestamp: str,
    emoji: str = "eyes",
) -> bool:
    """Add an emoji reaction to a Slack message.

    Args:
        channel: Channel ID where the message is
        timestamp: Message timestamp (ts)
        emoji: Emoji name without colons (default: "eyes" for 👀)

    Returns:
        True if reaction was added successfully
    """
    if not config.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot add reaction")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/reactions.add",
                headers={
                    "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": channel,
                    "timestamp": timestamp,
                    "name": emoji,
                },
            )
            result = response.json()
            if not result.get("ok"):
                # "already_reacted" is not an error - just means we already added this reaction
                if result.get("error") != "already_reacted":
                    logger.warning(f"Slack reactions.add error: {result.get('error')}")
                return result.get("error") == "already_reacted"
            else:
                logger.info(f"Added :{emoji}: reaction to message in {channel}")
                return True

    except Exception as e:
        logger.exception(f"Failed to add Slack reaction: {e}")
        return False


async def run_agent_for_slack(
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
) -> None:
    """
    Run the appropriate agent based on Slack message and respond.

    Uses the Router to parse /RoleName mentions and route to specific agents.
    Falls back to keyword-based routing if no role is mentioned.
    """
    logger.info(f"Processing Slack message from {user_id}: {user_message[:100]}")

    # Generate a thread_id if none provided (for new threads)
    effective_thread_id = thread_ts or f"new-{channel}-{int(time.time())}"

    # Create unified message for router
    message_router = get_message_router()
    unified = UnifiedMessage(
        source="slack",
        thread_id=effective_thread_id,
        channel_id=channel,
        content=user_message,
        author_id=user_id,
        author_name=user_id,
        is_bot=False,
        message_id=thread_ts or effective_thread_id,
    )

    # Parse /RoleName mentions
    role_mentions = message_router.parse_role_mentions(user_message)

    if role_mentions:
        # Route to mentioned roles
        for role in role_mentions:
            display_name = ROLE_DISPLAY_NAMES.get(role, role)
            await _run_agent_and_respond(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
            )
    else:
        # Fall back to keyword-based routing
        message_lower = user_message.lower()
        role = "support_engineer"  # default

        if any(kw in message_lower for kw in ["sentry", "error", "crash", "exception"]):
            role = "release_engineer"
        elif any(
            kw in message_lower for kw in ["fix", "implement", "code", "bug", "pr", "pull request"]
        ):
            role = "software_engineer"
        elif any(kw in message_lower for kw in ["release", "deploy", "version"]):
            role = "release_engineer"

        display_name = ROLE_DISPLAY_NAMES.get(role, role)
        await _run_agent_and_respond(
            role=role,
            display_name=display_name,
            user_message=user_message,
            channel=channel,
            thread_ts=thread_ts,
            user_id=user_id,
        )


async def _run_agent_and_respond(
    role: str,
    display_name: str,
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    max_handoff_depth: int = 3,
    current_depth: int = 0,
) -> None:
    """Run a specific agent and post response to Slack.

    Supports synchronous handoffs: if the agent mentions /RoleName in its response,
    that agent is immediately invoked (up to max_handoff_depth to prevent infinite loops).
    """
    # Build task for the agent
    task = f"""## Slack Request

A user has requested help via Slack.

### User Message
{user_message}

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_ts or "new thread"}

### CRITICAL INSTRUCTIONS - READ CAREFULLY

**STEP 1 - Review Pre-Injected Data:**
Sentry/monitoring data has been injected above. Use this as INITIAL context.

**STEP 2 - RUN kubectl Commands (MANDATORY):**
You MUST run kubectl commands to complete your investigation. Example:
```bash
kubectl get pods -n vibeteam
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -20
kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100
```
If you skip kubectl, your investigation is INCOMPLETE.

**FORBIDDEN ACTIONS (will fail):**
- DO NOT run Python code to import slack_sdk or use Slack tools
- DO NOT try to read Slack threads or channels programmatically
- DO NOT list team roles - only @mention ONE role if hand off needed

**ROLE-SPECIFIC kubectl ACCESS:**
- SupportEngineer: READ-ONLY (get, describe, logs) - INVESTIGATE only
- ReleaseEngineer: WRITE ACCESS (rollout undo, rollout restart, scale) - TAKE ACTION

**HANDOFF DECISION LOGIC:**
- If customer reports issue started AFTER A DEPLOYMENT → Recommend ROLLBACK to @ReleaseEngineer
- If issue is clearly a CODE BUG (logic error, not deployment-related) → @SoftwareEngineer
- When in doubt about recent deployments, PREFER ROLLBACK (safer for customers)

**REQUIRED OUTPUT:**
Your response MUST include:
1. Sentry findings: "Found Sentry issue [ID]: [message] - [count] events"
2. kubectl findings: "kubectl get pods shows: [status]" / "kubectl logs shows: [patterns]"
3. Root cause: Analysis correlating BOTH Sentry AND kubectl findings
4. **RECOMMENDATION** (REQUIRED): One of:
   - "Recommend ROLLBACK" → @ReleaseEngineer please rollback the deployment to restore service
   - "Recommend CODE FIX" → @SoftwareEngineer please investigate [specific file/code]
   - "No action needed" → Explain why issue is resolved or non-impactful
"""

    try:
        result = await call_agent_service(
            task=task,
            role=role,
            context_type="slack",
            context_id=f"{channel}:{thread_ts or 'new'}",
        )

        if "error" in result:
            await send_slack_message(
                channel,
                f"[{display_name}] Sorry, I encountered an error: {result['error']}",
                thread_ts,
            )
        else:
            response = result.get("response", "I completed the task but have no output to share.")
            # Truncate long responses for Slack
            if len(response) > 3000:
                response = response[:2900] + "\n\n... (truncated)"

            # Prefix with role name
            formatted_response = f"[{display_name}] {response}"
            await send_slack_message(channel, formatted_response, thread_ts)

            # Check for handoffs in the response and execute them synchronously
            message_router = get_message_router()
            handoff_roles = message_router.parse_role_mentions(response)
            if handoff_roles and current_depth < max_handoff_depth:
                logger.info(
                    f"Detected handoff to: {handoff_roles} (depth {current_depth + 1}/{max_handoff_depth})"
                )
                # Execute handoffs synchronously
                for handoff_role in handoff_roles:
                    if handoff_role == role:
                        # Skip self-handoffs
                        continue
                    handoff_display = ROLE_DISPLAY_NAMES.get(handoff_role, handoff_role)
                    # Pass the original message + full context about handoff
                    handoff_message = (
                        f"[Handoff from {display_name}]\n\n"
                        f"Original request: {user_message}\n\n"
                        f"Previous response: {response}"
                    )
                    await _run_agent_and_respond(
                        role=handoff_role,
                        display_name=handoff_display,
                        user_message=handoff_message,
                        channel=channel,
                        thread_ts=thread_ts,
                        user_id=user_id,
                        max_handoff_depth=max_handoff_depth,
                        current_depth=current_depth + 1,
                    )
            elif handoff_roles:
                logger.warning(
                    f"Max handoff depth ({max_handoff_depth}) reached, ignoring: {handoff_roles}"
                )

    except Exception as e:
        logger.exception(f"Failed to run agent for Slack: {e}")
        await send_slack_message(
            channel,
            f"[{display_name}] Sorry, I encountered an unexpected error. Please try again later.",
            thread_ts,
        )


@router.post("/slack/events")
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
        config.SLACK_SIGNING_SECRET,
    ):
        logger.warning("Invalid Slack signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Handle events
    event = payload.get("event", {})
    event_type = event.get("type")

    logger.info(f"Received Slack event: {event_type}")

    # Handle bot messages: process if they contain role mentions (handoffs/eval)
    # Per requirements: "Bot Messages: Router processes bot's own messages to detect handoffs"
    is_bot_message = event.get("bot_id") or event.get("subtype") == "bot_message"
    if is_bot_message:
        text = event.get("text", "")
        message_router = get_message_router()
        has_role_mention = bool(message_router.parse_role_mentions(text))
        if not has_role_mention:
            # Ignore bot messages without role mentions to prevent loops
            return {"status": "ignored", "reason": "bot_message_no_role_mention"}
        # Continue processing - bot message has a role mention (handoff or eval)
        logger.info(f"Processing bot message with role mention: {text[:80]}...")

    # Handle app_mention events
    if event_type == "app_mention":
        user_id = event.get("user", "")
        channel = event.get("channel", "")
        text = event.get("text", "")
        message_ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or message_ts

        # Remove the bot mention from the text
        clean_text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        # React with 👀 to show we're looking at the message
        await add_reaction(channel, message_ts, "eyes")

        # Process in background
        asyncio.create_task(run_agent_for_slack(clean_text, channel, thread_ts, user_id))

        return {"status": "accepted", "event": "app_mention"}

    # Handle direct messages
    if event_type == "message" and event.get("channel_type") == "im":
        user_id = event.get("user", "")
        channel = event.get("channel", "")
        text = event.get("text", "")
        message_ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or message_ts

        # React with 👀 to show we're looking at the message
        await add_reaction(channel, message_ts, "eyes")

        # Process in background
        asyncio.create_task(run_agent_for_slack(text, channel, thread_ts, user_id))

        return {"status": "accepted", "event": "message.im"}

    # Handle bot messages with role mentions in channels (handoffs and eval)
    # This handles cases where the bot posts /RoleName mentions (eval script or agent handoffs)
    if event_type == "message" and is_bot_message:
        channel = event.get("channel", "")
        text = event.get("text", "")
        message_ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or message_ts
        user_id = event.get("bot_id", "bot")  # Use bot_id as user_id for bot messages

        # React with 👀 to show we're processing the message
        await add_reaction(channel, message_ts, "eyes")

        # Process in background
        asyncio.create_task(run_agent_for_slack(text, channel, thread_ts, user_id))

        return {"status": "accepted", "event": "message.bot_with_role_mention"}

    return {"status": "ignored", "event": event_type}


@router.post("/slack/trigger")
async def trigger_agent_for_slack(request: Request) -> dict[str, Any]:
    """
    Directly trigger an agent for a Slack thread.

    This endpoint bypasses Slack webhooks and directly invokes the agent routing logic.
    Useful for:
    - E2E eval tests that post messages via Slack API but need to trigger agents
    - Manual testing and debugging
    - Programmatic agent invocation

    Request body:
    {
        "channel": "C0AATPSADB8",
        "thread_ts": "1234567890.123456",
        "text": "@SupportEngineer please investigate the issue",
        "user_id": "eval_script"
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    channel = body.get("channel")
    thread_ts = body.get("thread_ts")
    text = body.get("text", "")
    user_id = body.get("user_id", "trigger_api")

    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    # Check for role mentions
    message_router = get_message_router()
    role_mentions = message_router.parse_role_mentions(text)

    if not role_mentions:
        raise HTTPException(
            status_code=400,
            detail="text must contain @RoleName mention (e.g., @SupportEngineer)",
        )

    logger.info(f"Trigger API: routing to {role_mentions} in {channel}")

    # Process in background (same as webhook handler)
    asyncio.create_task(run_agent_for_slack(text, channel, thread_ts, user_id))

    return {
        "status": "accepted",
        "channel": channel,
        "thread_ts": thread_ts,
        "roles": role_mentions,
    }
