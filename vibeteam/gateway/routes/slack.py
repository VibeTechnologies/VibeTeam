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
import os
import re
import threading
import time
from typing import Any, cast

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from vibeteam.gateway.server import call_agent_service, call_agent_service_async, config
from vibeteam.router import Router
from vibeteam.router.models import ROLE_DISPLAY_NAMES, AgentRole, route_by_keywords

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])


# ==============================================================================
# Rate Limiter for trigger endpoint
# ==============================================================================


class TokenBucketRateLimiter:
    """
    Thread-safe token bucket rate limiter.

    Allows `max_requests` per `window_seconds`. Tokens refill continuously.
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Return True if the request is allowed, False if rate limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self.max_requests,
                self._tokens + elapsed * (self.max_requests / self.window_seconds),
            )
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def reset(self) -> None:
        """Reset the rate limiter (for testing)."""
        with self._lock:
            self._tokens = float(self.max_requests)
            self._last_refill = time.monotonic()


# Rate limiter for /slack/trigger (configurable via env vars)
_trigger_rate_limiter = TokenBucketRateLimiter(
    max_requests=int(os.environ.get("TRIGGER_RATE_LIMIT_MAX", "30")),
    window_seconds=float(os.environ.get("TRIGGER_RATE_LIMIT_WINDOW", "60")),
)


def split_long_message(text: str, max_chunk_size: int = 2900) -> list[str]:
    """
    Split a long message into chunks, trying to break at newlines or spaces.

    Args:
        text: The text to split
        max_chunk_size: Maximum size of each chunk (default 2900 to leave room for prefix)

    Returns:
        List of text chunks
    """
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chunk_size:
            chunks.append(remaining)
            break

        # Try to find a good break point (newline) within the chunk size
        break_point = remaining.rfind("\n", 0, max_chunk_size)
        if break_point == -1 or break_point < max_chunk_size // 2:
            # No good newline break, try space
            break_point = remaining.rfind(" ", 0, max_chunk_size)
        if break_point == -1 or break_point < max_chunk_size // 2:
            # No good break point, just cut at max size
            break_point = max_chunk_size

        chunks.append(remaining[:break_point])
        remaining = remaining[break_point:].lstrip()

    return chunks


# Message router for /RoleName parsing
_message_router: Router | None = None


# ==============================================================================
# Slack Event Deduplication
# ==============================================================================


_SLACK_EVENT_TTL_SECONDS = 15 * 60
_SLACK_EVENT_MAX_ENTRIES = 4096
_slack_event_seen: dict[str, float] = {}
_slack_event_lock = threading.Lock()


def _slack_event_key(payload: dict[str, Any], event: dict[str, Any]) -> str | None:
    """Build a stable dedup key for a Slack event."""
    event_id = payload.get("event_id")
    if event_id:
        return f"id:{event_id}"

    channel = event.get("channel")
    event_ts = event.get("ts") or payload.get("event_time")
    if channel and event_ts:
        return f"fallback:{channel}:{event_ts}"

    return None


def _is_duplicate_slack_event(key: str | None) -> bool:
    """Return True if we've already processed this Slack event."""
    if not key:
        return False

    now = time.monotonic()
    with _slack_event_lock:
        # Prune expired entries
        expired = [k for k, ts in _slack_event_seen.items() if now - ts > _SLACK_EVENT_TTL_SECONDS]
        for k in expired:
            _slack_event_seen.pop(k, None)

        if key in _slack_event_seen:
            return True

        _slack_event_seen[key] = now

        # Bound cache size (drop oldest)
        if len(_slack_event_seen) > _SLACK_EVENT_MAX_ENTRIES:
            oldest = sorted(_slack_event_seen.items(), key=lambda item: item[1])[
                : len(_slack_event_seen) - _SLACK_EVENT_MAX_ENTRIES
            ]
            for k, _ in oldest:
                _slack_event_seen.pop(k, None)

    return False


def _schedule_background(coro: Any) -> None:
    """Schedule background work for Slack events."""
    asyncio.create_task(coro)


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
) -> str | None:
    """Send a message to Slack.

    Returns:
        The message timestamp (ts) on success, None on failure.
    """
    if not config.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot send message")
        return None

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
                return None
            logger.info(f"Sent message to {channel}")
            return result.get("ts")

    except Exception as e:
        logger.exception(f"Failed to send Slack message: {e}")
        return None


async def update_slack_message(
    channel: str,
    ts: str,
    text: str,
) -> bool:
    """Update an existing Slack message using chat.update.

    Uses blocks to avoid showing the '(edited)' indicator in Slack.

    Returns:
        True if the update succeeded.
    """
    if not config.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot update message")
        return False

    try:
        payload: dict[str, Any] = {
            "channel": channel,
            "ts": ts,
            "text": text,  # Fallback for notifications
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/chat.update",
                headers={
                    "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            result = response.json()
            if not result.get("ok"):
                logger.error(f"Slack chat.update error: {result.get('error')}")
                return False
            logger.info(f"Updated message {ts} in {channel}")
            return True

    except Exception as e:
        logger.exception(f"Failed to update Slack message: {e}")
        return False


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


async def remove_reaction(
    channel: str,
    timestamp: str,
    emoji: str = "eyes",
) -> bool:
    """Remove an emoji reaction from a Slack message.

    Args:
        channel: Channel ID where the message is
        timestamp: Message timestamp (ts)
        emoji: Emoji name without colons (default: "eyes" for 👀)

    Returns:
        True if reaction was removed successfully
    """
    if not config.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set, cannot remove reaction")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/reactions.remove",
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
                # "no_reaction" just means we didn't have this reaction — not an error
                if result.get("error") != "no_reaction":
                    logger.warning(f"Slack reactions.remove error: {result.get('error')}")
                return result.get("error") == "no_reaction"
            else:
                logger.info(f"Removed :{emoji}: reaction from message in {channel}")
                return True

    except Exception as e:
        logger.exception(f"Failed to remove Slack reaction: {e}")
        return False


# Cache the bot user ID after the first lookup
_bot_user_id: str | None = None


async def get_bot_user_id() -> str | None:
    """Get the bot's own Slack user ID via auth.test (cached)."""
    global _bot_user_id
    if _bot_user_id is not None:
        return _bot_user_id
    if not config.SLACK_BOT_TOKEN:
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
            )
            data = resp.json()
            if data.get("ok"):
                _bot_user_id = data["user_id"]
                return _bot_user_id
    except Exception as e:
        logger.warning(f"Failed to get bot user ID: {e}")
    return None


async def bot_participated_in_thread(channel: str, thread_ts: str) -> bool:
    """Check whether the bot has posted any messages in a Slack thread.

    Fetches the thread replies and checks if any message was sent by the bot
    user. This provides a stateless way to determine bot participation without
    relying on in-memory subscription state.
    """
    bot_id = await get_bot_user_id()
    if not bot_id or not config.SLACK_BOT_TOKEN:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://slack.com/api/conversations.replies",
                headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
                params={"channel": channel, "ts": thread_ts, "limit": 50},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"conversations.replies error: {data.get('error')}")
                return False
            for msg in data.get("messages", []):
                if msg.get("user") == bot_id:
                    return True
    except Exception as e:
        logger.warning(f"Failed to check thread participation: {e}")
    return False


# ==============================================================================
# Task prompt classification and building
# ==============================================================================


def classify_task_template(role: str, user_message: str, is_thread_reply: bool = False) -> str:
    """Classify a message into a task template type.

    Args:
        role: Agent role (e.g., 'release_engineer', 'support_engineer')
        user_message: The user's message text
        is_thread_reply: True if this message is a reply in an existing thread

    Returns:
        'deployment', 'notification', 'conversational', 'health_check', or 'investigation'
    """
    msg_lower = user_message.lower()

    is_notification = any(
        kw in msg_lower
        for kw in ["notify", "announce", "tell the team", "tell the customer", "confirm to"]
    )
    # Health check: user asks to check health/readiness/status WITHOUT indicating
    # something is broken.  This should be a quick, focused check — not a deep
    # investigation.  We detect negative indicators (error, fail, broken, down,
    # why, investigate, debug) separately to distinguish "check health" from
    # "check why things are broken".
    _negative_indicators = [
        "error",
        "fail",
        "broken",
        "down",
        "crash",
        "issue",
        "problem",
        "outage",
        "incident",
        "bug",
    ]
    has_negative_indicator = any(kw in msg_lower for kw in _negative_indicators)

    _health_keywords = [
        "health",
        "readiness",
        "ready",
        "status",
        "alive",
        "liveness",
        "uptime",
    ]
    is_health_check = (
        role == "release_engineer"
        and any(kw in msg_lower for kw in _health_keywords)
        and not has_negative_indicator
    )

    is_explicit_investigation = any(
        kw in msg_lower
        for kw in [
            "investigate",
            "check",
            "debug",
            "analyze",
            "why",
            "error",
            "fail",
            "broken",
            "down",
        ]
    )
    is_deployment = (
        role == "release_engineer"
        and any(
            re.search(rf"\b{kw}\b", msg_lower)
            for kw in ["deploy", "release", "ship it", "push to", "promote"]
        )
        and not is_explicit_investigation
    )

    if is_deployment:
        return "deployment"
    elif is_health_check:
        return "health_check"
    elif is_notification and not is_explicit_investigation:
        return "notification"
    elif is_thread_reply and not is_explicit_investigation:
        # Thread follow-ups get a conversational template unless the user
        # is explicitly asking for a new investigation (e.g., "check the pods")
        return "conversational"
    else:
        return "investigation"


def _build_task_prompt(
    role: str,
    user_message: str,
    user_id: str,
    channel: str,
    thread_ts: str | None,
) -> str:
    """Build the task prompt for an agent based on role and message classification.

    Extracts the large task template logic from _run_agent_and_respond into a
    standalone, testable function.

    Args:
        role: Agent role (e.g., 'release_engineer', 'support_engineer')
        user_message: The user's message text
        user_id: Slack user ID
        channel: Slack channel ID
        thread_ts: Thread timestamp (or None for new threads)

    Returns:
        The complete task prompt string for the agent
    """
    is_thread_reply = thread_ts is not None
    template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)
    thread_display = thread_ts or "new thread"
    internal_ns = os.getenv("VIBETEAM_NAMESPACE", "vibeteam")

    if template == "deployment":
        return f"""## Slack Deployment Request

A user has requested a deployment via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### =================================================================
### CRITICAL SAFETY RULE: DO NOT DESTROY YOUR OWN INFRASTRUCTURE
### =================================================================
###
### You (ReleaseEngineer) run INSIDE {internal_ns} (vibeteam-gateway, openhands-svc).
### If you restart or replace these pods, YOUR REQUEST DIES and the
### response NEVER reaches Slack. The eval/user sees a timeout.
###
### FORBIDDEN (kills your in-flight request):
###   kubectl apply -k (ANY path) — modifies pod specs, kills your pod
###   kubectl rollout restart deployment/vibeteam-gateway -n {internal_ns}
###   kubectl rollout restart deployment/openhands-svc -n {internal_ns}
###   kubectl delete pod/deployment for gateway or openhands
###
### CRITICAL: YOU HAVE NO LOCAL REPOSITORY FILES
### DO NOT look for local files (k8s/, Dockerfile, etc.) — you have NO local repo
###
### SAFE ALTERNATIVE: kubectl set image (rolling update, safe)
### =================================================================

### =================================================================
### CRITICAL: YOU HAVE NO LOCAL REPOSITORY FILES
### =================================================================
###
### You run in a temporary sandbox with NO access to the source code.
### DO NOT try to: ls, cat, find, or access k8s/, Dockerfile, or any repo files.
### Your tools are: kubectl commands and `gh` CLI (GitHub CLI, pre-authenticated).
### To find image tags, use `gh pr view` to get the merge commit SHA from a PR.
### NEVER use `:latest` — always use a specific commit SHA for traceability.
###
### =================================================================

### =================================================================
### NAMESPACE MAP (CRITICAL — deploy to the CORRECT namespace!)
### =================================================================
###
### | Namespace   | Environment | What Lives There |
### |-------------|-------------|------------------|
### | `vibe`      | Production  | VibeBrowser: user-portal, stripe-service, litellm |
### | `vibe-dev`  | Staging     | VibeBrowser (staging mirrors prod) |
### | `{internal_ns}`  | Internal    | VibeTeam agents: vibeteam-gateway, openhands-svc |
###
### Repository → Image Map:
### | Repository                        | Image                                              | Namespaces    |
### |-----------------------------------|------------------------------------------------------|---------------|
### | VibeTechnologies/VibeWebAgent     | ghcr.io/vibetechnologies/vibe-user-portal:<SHA>      | vibe, vibe-dev |
### | VibeTechnologies/VibeWebAgent     | ghcr.io/vibetechnologies/vibe-stripe-service:<SHA>   | vibe, vibe-dev |
### | VibeTechnologies/VibeTeam         | ghcr.io/vibetechnologies/vibeteam:<SHA>              | {internal_ns}       |
###
### "staging" / "dev" → namespace: vibe-dev
### "production" / "prod" → namespace: vibe
### =================================================================

### CRITICAL INSTRUCTIONS — DEPLOYMENT EXECUTION

You are the ReleaseEngineer. You MUST execute the deployment, not just describe it.

**STEP 1 — Identify Target Namespace (MANDATORY):**
From the user's message, determine the target namespace:
- "staging" / "dev" → namespace: `vibe-dev`
- "production" / "prod" → namespace: `vibe`
- "agents" / "vibeteam" → namespace: `{internal_ns}`
If the request mentions a PR on VibeTechnologies/VibeWebAgent, default to `vibe-dev`.

**STEP 2 — Get Image Tag from PR (MANDATORY):**
Use `gh` CLI to get the merge commit SHA from the PR:
```bash
gh pr view <PR_NUMBER> --repo VibeTechnologies/VibeWebAgent --json mergeCommit -q .mergeCommit.oid
```
This returns a 40-char SHA — use it as the image tag. NEVER use `:latest`.

**STEP 3 — Verify Pre-Deployment State (MANDATORY):**
Run kubectl to check current state in the TARGET namespace:
```bash
kubectl get pods -n <NAMESPACE> -o wide
kubectl get deployments -n <NAMESPACE> -o wide
```

**STEP 4 — Check Current Image Tags (MANDATORY):**
```bash
kubectl get deployment user-portal -n <NAMESPACE> -o jsonpath='{{{{.spec.template.spec.containers[0].image}}}}'
kubectl get deployment stripe-service -n <NAMESPACE> -o jsonpath='{{{{.spec.template.spec.containers[0].image}}}}'
```

**STEP 5 — Execute Deployment (MANDATORY):**
Use `kubectl set image` to update VibeBrowser deployments:
```bash
kubectl set image deployment/user-portal user-portal=ghcr.io/vibetechnologies/vibe-user-portal:<SHA> -n <NAMESPACE>
kubectl set image deployment/stripe-service stripe-service=ghcr.io/vibetechnologies/vibe-stripe-service:<SHA> -n <NAMESPACE>
```
Do NOT run `kubectl apply -k` — it modifies pod specs and kills your own pod.
Do NOT deploy to the `{internal_ns}` namespace unless the request is explicitly about VibeTeam agents.

Then monitor rollout (safe, read-only):
```bash
kubectl rollout status deployment/user-portal -n <NAMESPACE> --timeout=120s
kubectl rollout status deployment/stripe-service -n <NAMESPACE> --timeout=120s
```

**STEP 6 — Verify Post-Deployment (MANDATORY):**
Confirm pods are healthy after deployment:
```bash
kubectl get pods -n <NAMESPACE>
kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp' | tail -10
```

**STEP 7 — Report Results (MANDATORY):**
Summarize deployment outcome clearly.

**FORBIDDEN ACTIONS:**
- DO NOT run `kubectl apply -k` (ANY path) — kills your pod
- DO NOT run `kubectl rollout restart` on gateway or openhands-svc — kills your pod
- DO NOT look for local files (k8s/, Dockerfile, etc.) — you have NO local repo
- DO NOT just describe what you would do — ACTUALLY RUN the commands
- DO NOT hand off deployment to another agent — YOU are the ReleaseEngineer
- DO NOT skip verification steps
- DO NOT use `:latest` tag — always use a specific commit SHA

**REQUIRED OUTPUT:**
Your response MUST include:
1. Target namespace identified (vibe-dev, vibe, or {internal_ns}) and why
2. PR merge commit SHA (from `gh pr view`)
3. Pre-deployment state (pod status before)
4. Current image tags (what's running now)
5. Deployment commands and output (kubectl set image for vibe-user-portal and vibe-stripe-service)
6. Rollout status (success/failure)
7. Post-deployment verification (pods healthy, events clean)
8. Summary: deployment succeeded/failed with evidence
"""

    elif template == "notification":
        return f"""## Slack Notification Request

A user has requested you to send a notification via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### INSTRUCTIONS
1. **Action:** Specify the message requested.
2. **Tools:** You do NOT need to run kubectl, Sentry, or curl.
3. **Format:** Just write the message clearly.
4. **Handoffs:** If you need to hand off, use the standard format (e.g., @RoleName).
"""

    elif template == "conversational":
        # Thread follow-ups: let the agent respond naturally without
        # forcing rigid investigation steps or output format.
        return f"""## Slack Thread Follow-Up

A user has replied in a thread where you previously responded.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### INSTRUCTIONS

This is a follow-up message in an existing conversation thread.
Respond naturally and directly to the user's question or comment.

- Answer their question based on your knowledge and the context of the thread
- If they ask for clarification on a previous response, elaborate naturally
- If they ask you to take an action (e.g., rollback, investigate further), do it
- You MAY use kubectl or other tools if the follow-up requires it, but only if relevant
- Keep your response concise and focused on what the user asked
- If you need to hand off, use @RoleName format
- DO NOT repeat your full previous investigation — the user can see the thread history
"""

    elif template == "health_check":
        return f"""## Slack Health Check Request

A user has requested a quick health & production-readiness check.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### Namespace Map
| Namespace   | Environment | What Lives There |
|-------------|-------------|------------------|
| `vibe`      | Production  | VibeBrowser: user-portal, stripe-service, litellm |
| `vibe-dev`  | Staging     | VibeBrowser (staging mirrors prod) |
| `{internal_ns}`  | Internal    | VibeTeam agents: vibeteam-gateway, openhands-svc |

"production" / "prod" / "api" → namespace: `vibe`
"staging" / "dev" → namespace: `vibe-dev`
"agents" / "vibeteam" / "gateway" → namespace: `{internal_ns}`
If unclear, default to the production namespace `vibe`.

### Safety Rule
This is a READ-ONLY health check. Do NOT restart, scale, rollback,
or modify any resources. Just observe and report.

### Instructions

You are the ReleaseEngineer performing a focused health check.
Follow "Health Check Mode" from your system instructions.

**Execute EXACTLY these commands (adapt NAMESPACE). Do NOT add extra commands.**

**Tool call 1** — Determine namespace & get infra status (run as ONE command):
```bash
kubectl get pods -n <NAMESPACE> -o wide && kubectl get deployments -n <NAMESPACE> && kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp' 2>/dev/null | tail -5
```

**Tool call 2** — Curl the health endpoint:
- `vibe` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://api.vibebrowser.app/health/readiness`
- `vibe-dev` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://api-dev.vibebrowser.app/health/readiness`
- `{internal_ns}` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://webhook.team.vibebrowser.app/health`

**Tool call 3** — Post your final summary to the conversation (finish action).

That's it. **3 tool calls total.** Do NOT:
- Re-run kubectl to "show" or "capture" output you already have
- Check services, ingress, TLS, or Sentry
- Run curl a second time to "confirm"
- Deep-dive into logs or events beyond the tail-5 above

**Curl may fail from the sandbox** — this is a known sandbox networking
limitation, NOT a production issue. If curl returns 000 or times out,
note "could not verify from sandbox" and move on. kubectl status is the
primary indicator.

**Report format**: namespace, pod status, replica counts, health endpoint
result, overall verdict (Healthy / Unhealthy).
"""

    else:
        # Investigation (default)
        return f"""## Slack Request

A user has requested help via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### CRITICAL INSTRUCTIONS — READ CAREFULLY

**STEP 1 — Review Pre-Injected Data:**
Sentry/monitoring data has been injected above. Use this as INITIAL context.

**STEP 2 — RUN kubectl Commands (MANDATORY):**
You MUST run kubectl commands to complete your investigation. Example:
```bash
kubectl get pods -n {internal_ns}
kubectl get events -n {internal_ns} --sort-by='.lastTimestamp' | tail -20
kubectl logs deployment/vibeteam-gateway -n {internal_ns} --tail=100
```
If you skip kubectl, your investigation is INCOMPLETE.

**STEP 3 — TEST THE REPORTED ENDPOINT WITH CURL (MANDATORY):**
If the user message contains a URL (like https://...), you MUST test it:
```bash
curl -s -o /dev/null -w "HTTP_STATUS:%{{{{http_code}}}}" <URL-from-user-message>
```
Interpret the result:
- HTTP_STATUS:404 = Route/endpoint doesn't exist → CODE BUG, hand off to @SoftwareEngineer
- HTTP_STATUS:5xx = Server error → Check logs, possibly ROLLBACK
- HTTP_STATUS:2xx = Endpoint is healthy
CRITICAL: If you don't test the URL with curl, your investigation is INCOMPLETE.
DO NOT conclude "infrastructure healthy" if you haven't tested the actual URL!

**FORBIDDEN ACTIONS (will fail):**
- DO NOT run Python code to import slack_sdk or use Slack tools
- DO NOT try to read Slack threads or channels programmatically
- DO NOT list team roles — only @mention ONE role if hand off needed

**ROLE-SPECIFIC kubectl ACCESS:**
- SupportEngineer: READ-ONLY (get, describe, logs) — INVESTIGATE only
- ReleaseEngineer: WRITE ACCESS (rollout undo, rollout restart, scale) — TAKE ACTION

**HANDOFF DECISION LOGIC (EVIDENCE-BASED):**
- ONLY recommend ROLLBACK if you find EVIDENCE of problems (errors in logs, failing pods, Sentry alerts)
- If investigation shows NO errors, healthy pods, clean logs → report "infrastructure healthy, no action needed"
- If no evidence of problems but customer reports issues → ask for more details (request IDs, timestamps, specific endpoints)
- NEVER recommend rollback based solely on customer report timing — you need actual evidence

**REQUIRED OUTPUT:**
Your response MUST include:
1. Sentry findings: "Found Sentry issue [ID]: [message] — [count] events" OR "No Sentry issues found"
2. kubectl findings: "kubectl get pods shows: [status]" / "kubectl logs shows: [patterns]"
3. Endpoint test (if webhook/API issue): "curl shows: [HTTP status code and response]" — a 404 means the route doesn't exist!
4. Root cause: Analysis correlating Sentry, kubectl, AND endpoint test findings
5. **RECOMMENDATION** (REQUIRED — must match evidence):
   - If EVIDENCE of issues found: "Recommend ROLLBACK" → @ReleaseEngineer please rollback the deployment
   - If CODE BUG identified (e.g., 404 endpoint): "Recommend CODE FIX" → @SoftwareEngineer please investigate [specific file/code]
   - If NO issues found: "Infrastructure appears healthy. No errors in Sentry, pods running normally, logs clean. Please ask customer for: request IDs, specific timestamps, exact error messages they see."
   - CRITICAL: Do NOT recommend rollback if no issues were found — this wastes engineering time and may cause unnecessary downtime
   - CRITICAL: DO NOT TAG YOUR OWN ROLE. If you are @SoftwareEngineer, do NOT tag @SoftwareEngineer. Just do the work.
"""


# ==============================================================================
# Async agent submission
# ==============================================================================


async def _submit_agent_async(
    role: str,
    display_name: str,
    user_message: str,
    channel: str,
    thread_ts: str | None,
    message_ts: str,
    user_id: str,
    max_handoff_depth: int = 3,
    current_depth: int = 0,
) -> None:
    """Submit an agent task asynchronously via /run/async.

    Uses a :thinking_face: reaction as typing indicator (added by event handler),
    submits the task, and returns immediately.
    The agent service will POST results to /callback/agent when done.
    """
    task = _build_task_prompt(
        role=role,
        user_message=user_message,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )

    # Determine if we should skip heavy context injection.
    # Health checks are self-contained — the template has all instructions.
    # Pre-fetched context (logs, events from all namespaces) causes the agent
    # to rabbit-hole into investigating every anomaly it sees.
    is_thread_reply = thread_ts is not None
    template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)
    skip_context = template == "health_check"

    # Set max_iterations based on task type to prevent scope creep.
    # Health checks need very few tool calls; investigations need more.
    max_iterations_map = {
        "health_check": 8,
        "conversational": 10,
        "notification": 10,
        "deployment": 25,
        "investigation": 30,
    }
    max_iterations = max_iterations_map.get(template, 30)

    # Build callback URL
    callback_url = f"{config.GATEWAY_URL}/callback/agent"
    progress_url = f"{config.GATEWAY_URL}/callback/agent/progress"

    # Submit async task
    result = await call_agent_service_async(
        task=task,
        role=role,
        context_type="slack",
        context_id=f"{channel}:{thread_ts or 'new'}",
        callback_url=callback_url,
        progress_url=progress_url,
        skip_context_injection=skip_context,
        max_iterations=max_iterations,
        execution_timeout=(
            config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS
            if config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS > 0
            else None
        ),
        callback_metadata={
            "channel": channel,
            "thread_ts": thread_ts,
            "message_ts": message_ts,
            "user_id": user_id,
            "role": role,
            "display_name": display_name,
            "user_message": user_message,
            "max_handoff_depth": max_handoff_depth,
            "current_depth": current_depth,
            # Include callback secret for authentication
            # Agent service echoes this back; gateway verifies on receipt
            "callback_secret": config.CALLBACK_SECRET,
        },
    )

    if "error" in result:
        # Remove thinking face, add X
        await remove_reaction(channel, message_ts, "thinking_face")
        await add_reaction(channel, message_ts, "x")
        error_text = (
            f"[{display_name}] Sorry, I couldn't reach the agent service: {result['error']}"
        )
        await send_slack_message(channel, error_text, thread_ts)
        logger.error(f"[ASYNC] Failed to submit task for {role}: {result['error']}")
    else:
        job_id = result.get("job_id", "unknown")
        logger.info(
            f"[ASYNC] Submitted job {job_id} for {role} in {channel} (depth={current_depth})"
        )


# ==============================================================================
# Main entry point for Slack → agent routing
# ==============================================================================


async def run_agent_for_slack(
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    message_ts: str | None = None,
    use_async: bool = True,
) -> None:
    """
    Run the appropriate agent based on Slack message and respond.

    Uses the Router to parse /RoleName mentions and route to specific agents.
    Falls back to keyword-based routing if no role is mentioned.

    Args:
        user_message: The user's Slack message
        channel: Slack channel ID
        thread_ts: Thread timestamp (or None for new threads)
        user_id: Slack user ID
        message_ts: Message timestamp (needed for async reaction management)
        use_async: If True and message_ts is available, use async callback flow
    """
    logger.info(f"Processing Slack message from {user_id}: {user_message[:100]}")

    # Route the message
    message_router = get_message_router()

    # Parse /RoleName mentions
    role_mentions = message_router.parse_role_mentions(user_message)

    if not role_mentions:
        # Fall back to keyword-based routing (shared with openhands team.py)
        role_mentions = [route_by_keywords(user_message)]

    # Determine effective message_ts for reaction management
    effective_message_ts = message_ts or thread_ts or ""

    for role in role_mentions:
        display_name = ROLE_DISPLAY_NAMES.get(cast(AgentRole, role), role)

        if use_async and effective_message_ts:
            await _submit_agent_async(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                message_ts=effective_message_ts,
                user_id=user_id,
            )
        else:
            await _run_agent_and_respond(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                message_ts=effective_message_ts or None,
            )


async def _run_agent_and_respond(
    role: str,
    display_name: str,
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    message_ts: str | None = None,
    max_handoff_depth: int = 3,
    current_depth: int = 0,
) -> None:
    """Run a specific agent synchronously and post response to Slack.

    This is the sync path — used by /slack/trigger and as fallback when
    message_ts is unavailable for async reaction management.

    Uses :thinking_face: reaction as typing indicator (added by event handler).

    Supports synchronous handoffs: if the agent mentions /RoleName in its response,
    that agent is immediately invoked (up to max_handoff_depth to prevent infinite loops).
    """
    task = _build_task_prompt(
        role=role,
        user_message=user_message,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )

    agent_start_time = time.time()
    logger.info(f"[TIMING] Starting agent {role} (depth={current_depth})")

    try:
        result = await call_agent_service(
            task=task,
            role=role,
            context_type="slack",
            context_id=f"{channel}:{thread_ts or 'new'}",
        )

        agent_duration = time.time() - agent_start_time
        logger.info(f"[TIMING] Agent {role} completed in {agent_duration:.1f}s")

        if "error" in result:
            error_text = f"[{display_name}] Sorry, I encountered an error: {result['error']}"
            if message_ts:
                await remove_reaction(channel, message_ts, "thinking_face")
                await add_reaction(channel, message_ts, "x")
            await send_slack_message(channel, error_text, thread_ts)
        else:
            response = result.get("response", "I completed the task but have no output to share.")

            # Remove thinking face, add checkmark
            if message_ts:
                await remove_reaction(channel, message_ts, "thinking_face")
                await add_reaction(channel, message_ts, "white_check_mark")

            # Build display prefix with model info if available
            model_name = result.get("model", "")
            if model_name:
                agent_prefix = f"[{display_name}:{model_name}]"
            else:
                agent_prefix = f"[{display_name}]"

            # Split long responses into multiple messages instead of truncating
            # This preserves handoff mentions that might be at the end
            chunks = split_long_message(response)

            # Send each chunk as a separate message
            for i, chunk in enumerate(chunks):
                if i == 0:
                    formatted_chunk = f"{agent_prefix} {chunk}"
                else:
                    formatted_chunk = f"{agent_prefix} (cont.) {chunk}"
                await send_slack_message(channel, formatted_chunk, thread_ts)

            # Check for handoffs in the response and execute them synchronously
            message_router = get_message_router()
            handoff_roles = message_router.parse_role_mentions(response)
            logger.info(f"Checking for handoffs in response from {role}: found {handoff_roles}")
            if handoff_roles and current_depth < max_handoff_depth:
                logger.info(
                    f"Detected handoff to: {handoff_roles} (depth {current_depth + 1}/{max_handoff_depth})"
                )
                # Execute handoffs synchronously
                for handoff_role in handoff_roles:
                    if handoff_role == role:
                        # Skip self-handoffs
                        logger.info(f"Skipping self-handoff to {role}")
                        continue
                    handoff_start = time.time()
                    logger.info(f"[TIMING] Executing handoff to {handoff_role}...")
                    handoff_display = ROLE_DISPLAY_NAMES.get(
                        cast(AgentRole, handoff_role), handoff_role
                    )
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
                    handoff_duration = time.time() - handoff_start
                    logger.info(
                        f"[TIMING] Handoff to {handoff_role} completed in {handoff_duration:.1f}s"
                    )
            elif handoff_roles:
                logger.warning(
                    f"Max handoff depth ({max_handoff_depth}) reached, ignoring: {handoff_roles}"
                )

    except Exception as e:
        logger.exception(f"Failed to run agent for Slack: {e}")
        error_text = (
            f"[{display_name}] Sorry, I encountered an unexpected error. Please try again later."
        )
        if message_ts:
            await remove_reaction(channel, message_ts, "thinking_face")
            await add_reaction(channel, message_ts, "x")
        await send_slack_message(channel, error_text, thread_ts)


# ==============================================================================
# Callback endpoint for async agent results
# ==============================================================================


@router.post("/callback/agent")
async def handle_agent_callback(request: Request) -> dict[str, Any]:
    """Handle callback from agent service when an async job completes.

    The agent service POSTs here with:
    - job_id, status, response/error
    - callback_metadata (Slack context: channel, thread_ts, message_ts, role, etc.)

    This endpoint:
    1. Removes the :thinking_face: reaction
    2. Posts the response (or error) to Slack as a new message
    3. Checks for handoff mentions and submits new async jobs if needed
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    job_id = payload.get("job_id", "unknown")
    status = payload.get("status", "unknown")
    response_text = payload.get("response", "")
    error = payload.get("error", "")
    meta = payload.get("callback_metadata", {})

    channel = meta.get("channel", "")
    thread_ts = meta.get("thread_ts")
    message_ts = meta.get("message_ts", "")
    role = meta.get("role", "unknown")
    display_name = meta.get("display_name", role)
    user_message = meta.get("user_message", "")
    user_id = meta.get("user_id", "")
    max_handoff_depth = meta.get("max_handoff_depth", 3)
    current_depth = meta.get("current_depth", 0)

    logger.info(f"[CALLBACK] Received callback for job {job_id}: status={status}, role={role}")

    # Verify callback authentication
    # If CALLBACK_SECRET is configured, the agent must echo it back in callback_metadata
    if config.CALLBACK_SECRET:
        callback_secret = meta.get("callback_secret", "")
        if callback_secret != config.CALLBACK_SECRET:
            logger.warning(f"[CALLBACK] Invalid callback_secret for job {job_id}")
            raise HTTPException(status_code=403, detail="Invalid callback secret")

    if not channel:
        logger.error(f"[CALLBACK] Missing channel in callback_metadata for job {job_id}")
        return {"status": "error", "detail": "missing channel in callback_metadata"}

    # Remove thinking_face reaction
    if message_ts:
        await remove_reaction(channel, message_ts, "thinking_face")

    if status == "timeout":
        # Timeout path — agent ran out of time
        if message_ts:
            await add_reaction(channel, message_ts, "hourglass")
        # Post partial response if available, otherwise generic timeout message
        timeout_response = response_text or (
            "Sorry, I ran out of time working on this task. "
            "Please try again or break the request into smaller steps."
        )
        timeout_text = f"[{display_name}] :hourglass: {timeout_response}"
        await send_slack_message(channel, timeout_text, thread_ts)
        return {"status": "ok", "job_id": job_id, "outcome": "timeout_posted"}

    if status == "failed" or error:
        # Failure path
        if message_ts:
            await add_reaction(channel, message_ts, "x")
        error_msg = error or "Unknown error"
        error_text = f"[{display_name}] Sorry, I encountered an error: {error_msg}"
        await send_slack_message(channel, error_text, thread_ts)
        return {"status": "ok", "job_id": job_id, "outcome": "error_posted"}

    # Success path
    if message_ts:
        await add_reaction(channel, message_ts, "white_check_mark")

    response = response_text or "I completed the task but have no output to share."

    # Build display prefix with model info if available
    result_metadata = payload.get("metadata", {})
    model_name = result_metadata.get("model", "")
    if model_name:
        agent_prefix = f"[{display_name}:{model_name}]"
    else:
        agent_prefix = f"[{display_name}]"

    # Split long responses into multiple messages
    chunks = split_long_message(response)

    for i, chunk in enumerate(chunks):
        if i == 0:
            formatted_chunk = f"{agent_prefix} {chunk}"
        else:
            formatted_chunk = f"{agent_prefix} (cont.) {chunk}"
        await send_slack_message(channel, formatted_chunk, thread_ts)

    # Check for handoffs in the response
    message_router = get_message_router()
    handoff_roles = message_router.parse_role_mentions(response)

    if handoff_roles and current_depth < max_handoff_depth:
        for handoff_role in handoff_roles:
            if handoff_role == role:
                logger.info(f"[CALLBACK] Skipping self-handoff to {role}")
                continue

            handoff_display = ROLE_DISPLAY_NAMES.get(cast(AgentRole, handoff_role), handoff_role)
            handoff_message = (
                f"[Handoff from {display_name}]\n\n"
                f"Original request: {user_message}\n\n"
                f"Previous response: {response}"
            )
            await _submit_agent_async(
                role=handoff_role,
                display_name=handoff_display,
                user_message=handoff_message,
                channel=channel,
                thread_ts=thread_ts,
                message_ts=message_ts,
                user_id=user_id,
                max_handoff_depth=max_handoff_depth,
                current_depth=current_depth + 1,
            )
    elif handoff_roles:
        logger.warning(
            f"[CALLBACK] Max handoff depth ({max_handoff_depth}) reached for job {job_id}"
        )

    return {"status": "ok", "job_id": job_id, "outcome": "response_posted"}


# ==============================================================================
# Progress callback endpoint for agent intermediate updates
# ==============================================================================


@router.post("/callback/agent/progress")
async def handle_agent_progress(request: Request) -> dict[str, Any]:
    """Handle progress updates from agent service while agent is working.

    The agent service POSTs here periodically with:
    - job_id, step_number, step_summary, elapsed_seconds
    - callback_metadata (Slack context: channel, thread_ts, etc.)

    This endpoint posts a progress message to the Slack thread so users
    can see what the agent is doing instead of just seeing :thinking_face:.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    job_id = payload.get("job_id", "unknown")
    step_number = payload.get("step_number", 0)
    step_summary = payload.get("step_summary", "")
    elapsed_seconds = payload.get("elapsed_seconds", 0)
    meta = payload.get("callback_metadata", {})

    channel = meta.get("channel", "")
    thread_ts = meta.get("thread_ts")
    display_name = meta.get("display_name", meta.get("role", "Agent"))

    if not channel or not step_summary:
        return {"status": "ignored", "reason": "missing channel or step_summary"}

    # Verify callback authentication
    if config.CALLBACK_SECRET:
        callback_secret = meta.get("callback_secret", "")
        if callback_secret != config.CALLBACK_SECRET:
            logger.warning(f"[PROGRESS] Invalid callback_secret for job {job_id}")
            raise HTTPException(status_code=403, detail="Invalid callback secret")

    # Format elapsed time
    mins, secs = divmod(elapsed_seconds, 60)
    time_str = f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"

    # Post progress as a subtle update
    progress_text = f"_[{display_name}] Step {step_number} ({time_str}): {step_summary}_"
    await send_slack_message(channel, progress_text, thread_ts)

    logger.info(
        f"[PROGRESS] job={job_id} step={step_number} elapsed={time_str}: {step_summary[:80]}"
    )

    return {"status": "ok", "job_id": job_id}


# ==============================================================================
# Slack event handlers
# ==============================================================================


async def _process_slack_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Process Slack events in a background task."""
    try:
        event = payload.get("event", {})
        event_type = event.get("type")

        logger.info(
            f"Received Slack event: {event_type}, "
            f"subtype={event.get('subtype')}, "
            f"thread_ts={bool(event.get('thread_ts'))}, "
            f"channel_type={event.get('channel_type')}"
        )

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
            clean_text = re.sub(r"<@[A-Z0-9]+>\\s*", "", text).strip()

            # React with thinking face to show we're working on it
            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face")

            await run_agent_for_slack(
                clean_text, channel, thread_ts, user_id, message_ts=message_ts
            )

            return {"status": "accepted", "event": "app_mention"}

        # Handle direct messages
        if event_type == "message" and event.get("channel_type") == "im":
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts

            # React with thinking face to show we're working on it
            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face")

            await run_agent_for_slack(text, channel, thread_ts, user_id, message_ts=message_ts)

            return {"status": "accepted", "event": "message.im"}

        # Handle thread replies in threads where the bot has participated.
        # When VibeTeam participates in a thread (via app_mention or trigger),
        # subsequent user messages in the thread should be delivered to agents —
        # even without an explicit @mention of the bot.
        # We check two sources: in-memory subscriptions (fast) and, as a fallback,
        # the Slack thread history (stateless, survives pod restarts).
        thread_handler_match = (
            event_type == "message"
            and not is_bot_message
            and event.get("thread_ts")
            and event.get("channel_type") != "im"
        )
        logger.info(
            f"Thread handler check: match={thread_handler_match}, "
            f"event_type={event_type}, is_bot={is_bot_message}, "
            f"thread_ts={event.get('thread_ts')}, "
            f"channel_type={event.get('channel_type')}, "
            f"user={event.get('user')}, text={event.get('text', '')[:80]}"
        )
        if thread_handler_match:
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts", "")

            # Fast path: check in-memory subscriptions
            message_router = get_message_router()
            subscriptions = await message_router.get_subscriptions(
                source="slack",
                thread_id=thread_ts,
            )
            logger.info(
                f"Thread {thread_ts}: subscriptions={bool(subscriptions)}, "
                f"checking bot participation..."
            )

            # Slow path: if no subscriptions found (e.g. after pod restart),
            # check the actual Slack thread to see if the bot has replied before.
            participated = bool(subscriptions)
            if not participated:
                participated = await bot_participated_in_thread(channel, thread_ts)
                logger.info(f"Thread {thread_ts}: bot_participated={participated}")
                if participated:
                    logger.info(
                        f"No subscriptions for thread {thread_ts}, but bot "
                        f"participated in thread history. Processing message."
                    )

            if participated:
                if subscriptions:
                    logger.info(
                        f"Thread {thread_ts} has subscribed agents: "
                        f"{[s.agent_role for s in subscriptions]}. Processing message."
                    )

                if message_ts:
                    await add_reaction(channel, message_ts, "thinking_face")

                await run_agent_for_slack(text, channel, thread_ts, user_id, message_ts=message_ts)

                return {"status": "accepted", "event": "message.subscribed_thread"}

        # Handle bot messages with role mentions in channels (handoffs and eval)
        # IMPORTANT: Bot messages posted by OUR OWN bot (via callback handler) that
        # contain @RoleName handoff mentions should NOT be re-processed here, because
        # the callback handler (handle_agent_callback) already submits handoff jobs.
        # Only process bot messages from OTHER bots (e.g., eval script trigger API)
        # or external integrations.
        if event_type == "message" and is_bot_message:
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts
            bot_id = event.get("bot_id", "")

            # Check if this message was posted by our own bot (self-posted handoff).
            # Our bot's messages from the callback handler contain a "[RoleName]" prefix.
            # The callback handler already processes handoffs in the response, so
            # re-processing here would cause duplicate agent executions.
            is_self_bot_message = False
            if text:
                # Our callback handler formats messages as "[DisplayName] ..." or
                # "[DisplayName:model] ...". If the message starts with this pattern
                # and is in a thread, it's a response we posted — not a new request.
                import re as _re

                self_bot_pattern = _re.match(r"^\[[\w:.\-]+\]\s", text)
                if self_bot_pattern and thread_ts and thread_ts != message_ts:
                    is_self_bot_message = True
                    logger.info(
                        f"Skipping self-posted bot message with role mention "
                        f"(handoff already handled by callback): {text[:80]}..."
                    )

            if is_self_bot_message:
                return {"status": "ignored", "reason": "self_bot_handoff_already_handled"}

            user_id = bot_id or "bot"

            # React with thinking face to show we're processing the message
            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face")

            await run_agent_for_slack(text, channel, thread_ts, user_id, message_ts=message_ts)

            return {"status": "accepted", "event": "message.bot_with_role_mention"}

        logger.info(
            f"Event fell through all handlers: event_type={event_type}, "
            f"is_bot_message={is_bot_message}, "
            f"has_thread_ts={bool(event.get('thread_ts'))}, "
            f"channel_type={event.get('channel_type')}"
        )
        return {"status": "ignored", "event": event_type}

    except Exception as e:
        logger.exception(f"Failed to process Slack event: {e}")
        return {"status": "error", "detail": str(e)}


@router.post("/slack/events")
async def handle_slack_events(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
    x_slack_retry_num: str | None = Header(None, alias="X-Slack-Retry-Num"),
    x_slack_retry_reason: str | None = Header(None, alias="X-Slack-Retry-Reason"),
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

    event = payload.get("event", {})
    event_type = event.get("type")
    event_key = _slack_event_key(payload, event)

    if _is_duplicate_slack_event(event_key):
        logger.info(
            f"Ignoring duplicate Slack event: key={event_key}, "
            f"retry_num={x_slack_retry_num}, retry_reason={x_slack_retry_reason}"
        )
        return {"status": "ignored", "event": event_type, "reason": "duplicate_event"}

    if x_slack_retry_num:
        logger.info(
            f"Slack retry header received: retry_num={x_slack_retry_num}, "
            f"retry_reason={x_slack_retry_reason}"
        )

    # Process in background to avoid Slack retrying due to slow responses
    _schedule_background(_process_slack_event(payload))

    # Return immediately to satisfy Slack's 3s requirement
    event_label = event_type or "unknown"
    if event_type == "message":
        channel_type = event.get("channel_type")
        if channel_type == "im":
            event_label = "message.im"
        elif event.get("bot_id") or event.get("subtype") == "bot_message":
            event_label = "message.bot_with_role_mention"
        elif event.get("thread_ts"):
            event_label = "message.thread"

    return {"status": "accepted", "event": event_label}


@router.post("/slack/trigger")
async def trigger_agent_for_slack(
    request: Request,
    authorization: str = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    """
    Directly trigger an agent for a Slack thread.

    This endpoint bypasses Slack webhooks and directly invokes the agent routing logic.
    Useful for:
    - E2E eval tests that post messages via Slack API but need to trigger agents
    - Manual testing and debugging
    - Programmatic agent invocation

    Authentication:
    - If SLACK_TRIGGER_SECRET is set, requires Bearer token in Authorization header.
    - If SLACK_TRIGGER_SECRET is not set, logs a warning and allows unauthenticated access.

    Request body:
    {
        "channel": "C0AATPSADB8",
        "thread_ts": "1234567890.123456",
        "text": "@SupportEngineer please investigate the issue",
        "user_id": "eval_script",
        "use_async": false
    }

    Fields:
    - channel (required): Slack channel ID
    - text (required): Message text with @RoleName mention
    - thread_ts (optional): Thread timestamp to post in
    - user_id (optional): Identifier for the caller (default: "trigger_api")
    - use_async (optional, default: false): If true, uses the async callback flow
      (POST /run/async → agent processes → POST /callback/agent) instead of the
      synchronous path. Useful for testing the full async lifecycle including
      CALLBACK_SECRET verification.
    """
    # Rate limiting
    if not _trigger_rate_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for /slack/trigger. Try again later.",
        )

    # Verify trigger secret if configured
    if config.SLACK_TRIGGER_SECRET:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authorization header with Bearer token required",
            )
        token = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, config.SLACK_TRIGGER_SECRET):
            logger.warning("Invalid trigger secret in /slack/trigger request")
            raise HTTPException(status_code=403, detail="Invalid trigger secret")
    else:
        logger.warning(
            "SLACK_TRIGGER_SECRET not set - /slack/trigger endpoint is unauthenticated. "
            "Set SLACK_TRIGGER_SECRET env var to secure this endpoint."
        )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    channel = body.get("channel")
    thread_ts = body.get("thread_ts")
    text = body.get("text", "")
    user_id = body.get("user_id", "trigger_api")
    use_async = body.get("use_async", False)

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

    mode = "async" if use_async else "sync"
    logger.info(f"Trigger API: routing to {role_mentions} in {channel} (mode={mode})")

    # Process in background
    # use_async=True exercises the full /run/async → /callback/agent flow
    # use_async=False (default) uses the synchronous path
    asyncio.create_task(run_agent_for_slack(text, channel, thread_ts, user_id, use_async=use_async))

    return {
        "status": "accepted",
        "channel": channel,
        "thread_ts": thread_ts,
        "roles": role_mentions,
        "mode": mode,
    }
