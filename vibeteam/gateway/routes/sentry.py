"""
Sentry Webhook Handlers.

Handles Sentry webhook events for error monitoring:
- issue.created: Triage new errors and route to Release Engineer
"""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from vibeteam.gateway.server import call_agent_service, config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sentry"])


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


async def run_release_engineer_agent(issue_data: dict[str, Any], classification: str) -> None:
    """Run the Release Engineer agent on a Sentry issue."""
    issue_id = issue_data.get("shortId", "unknown")
    logger.info(f"Starting Release Engineer agent for Sentry issue {issue_id}")

    # Build task for the agent
    task = f"""## Sentry Error Triage

A new error has been detected in production that requires your attention.

### Error Classification
Classification: {classification}

### Error Details
- Issue ID: {issue_data.get("id")}
- Short ID: {issue_data.get("shortId")}
- Title: {issue_data.get("title")}
- Culprit: {issue_data.get("culprit", "Unknown")}
- Event Count: {issue_data.get("count", 0)}
- Affected Users: {issue_data.get("userCount", 0)}
- First Seen: {issue_data.get("firstSeen", "Unknown")}
- Last Seen: {issue_data.get("lastSeen", "Unknown")}

### Full Issue Data
```json
{json.dumps(issue_data, indent=2, default=str)}
```

### Instructions
1. Analyze the error and determine root cause
2. Check if this is a known issue or regression
3. Assess severity and impact on users
4. If it's a valid bug:
   - Create a GitHub issue with details
   - Suggest a fix if possible
   - Assign appropriate priority
5. If it's noise, document why and recommend ignoring
6. Provide a summary of your findings

Please triage this error and take appropriate action.
"""

    try:
        result = await call_agent_service(
            task=task,
            role="release_engineer",
            context_type="sentry",
            context_id=issue_id,
        )

        if "error" in result:
            logger.error(f"Release Engineer agent failed for {issue_id}: {result['error']}")
        else:
            logger.info(f"Release Engineer agent completed for {issue_id}")

    except Exception as e:
        logger.exception(f"Failed to run Release Engineer agent: {e}")


@router.post("/webhook/sentry")
async def handle_sentry_webhook(
    request: Request,
    sentry_hook_signature: str = Header(None, alias="Sentry-Hook-Signature"),
) -> dict[str, Any]:
    """
    Handle incoming Sentry webhook events.

    Sentry webhooks are triggered when new issues are created or existing
    issues receive new events. We route these to the Release Engineer agent
    for triage.
    """
    payload_bytes = await request.body()

    # Verify signature
    if not verify_sentry_signature(
        payload_bytes, sentry_hook_signature or "", config.SENTRY_CLIENT_SECRET
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

    # Trigger Release Engineer agent in background
    asyncio.create_task(run_release_engineer_agent(issue, classification))

    return {
        "status": "accepted",
        "classification": classification,
        "issue_id": issue.get("id"),
        "short_id": issue.get("shortId"),
    }
