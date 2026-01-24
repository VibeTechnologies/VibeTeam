"""
FastAPI Webhook Server for VibeTeam.

Handles incoming webhooks from:
- Sentry: New errors, resolved issues
- GitHub: PR events, issue events
- Custom triggers via REST API

Endpoints:
- POST /webhook/sentry - Sentry webhook receiver
- POST /webhook/github - GitHub webhook receiver
- POST /api/fix-issue - Trigger issue fix
- POST /api/review-pr - Trigger PR review
- GET /health - Health check

Usage:
    uvicorn vibeteam.webhooks.server:app --host 0.0.0.0 --port 8000
"""

import hashlib
import hmac
import json
import os
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

# Lazy import to avoid circular imports
_agent = None


def get_agent():
    """Get or create the Release Engineer agent."""
    global _agent
    if _agent is None:
        from vibeteam.agents.release_engineer import ReleaseEngineerAgent

        _agent = ReleaseEngineerAgent()
    return _agent


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    return FastAPI(
        title="VibeTeam Webhook Server",
        description="Webhook handlers for autonomous AI agents",
        version="3.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )


app = create_app()


# =====================
# Health Check
# =====================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "vibeteam-webhooks",
        "version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "VibeTeam Webhook Server",
        "version": "3.0.0",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "sentry_webhook": "/webhook/sentry",
            "github_webhook": "/webhook/github",
            "fix_issue": "/api/fix-issue",
            "review_pr": "/api/review-pr",
            "triage": "/api/triage",
        },
    }


# =====================
# Sentry Webhook
# =====================


class SentryWebhookPayload(BaseModel):
    """Sentry webhook payload structure."""

    action: str
    data: dict
    actor: dict | None = None


def verify_sentry_signature(
    request_body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify Sentry webhook signature."""
    expected = hmac.new(
        key=secret.encode(),
        msg=request_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.post("/webhook/sentry")
async def sentry_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    sentry_hook_signature: str = Header(None, alias="Sentry-Hook-Signature"),
):
    """
    Receive Sentry webhooks.

    Handles:
    - issue.created: New error occurred
    - issue.resolved: Issue was resolved
    - issue.assigned: Issue was assigned

    The handler will triage new issues and potentially create
    GitHub issues for valid bugs.
    """
    body = await request.body()

    # Verify signature if secret is configured
    sentry_secret = os.getenv("SENTRY_WEBHOOK_SECRET")
    if sentry_secret and sentry_hook_signature:
        if not verify_sentry_signature(body, sentry_hook_signature, sentry_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    action = payload.get("action", "unknown")
    data = payload.get("data", {})

    # Handle different actions
    if action == "created":
        # New issue - triage in background
        issue_data = data.get("issue", {})
        background_tasks.add_task(
            triage_sentry_issue_background,
            issue_id=issue_data.get("id"),
        )
        return {
            "status": "accepted",
            "action": action,
            "issue_id": issue_data.get("id"),
            "message": "Issue queued for triage",
        }

    elif action == "resolved":
        # Issue resolved - log it
        issue_data = data.get("issue", {})
        return {
            "status": "accepted",
            "action": action,
            "issue_id": issue_data.get("id"),
            "message": "Resolution noted",
        }

    return {
        "status": "accepted",
        "action": action,
        "message": f"Action {action} received but not handled",
    }


async def triage_sentry_issue_background(issue_id: str):
    """Background task to triage a Sentry issue."""
    try:
        agent = get_agent()
        # Fetch full issue details
        issue_details = agent.sentry.get_issue_details(issue_id)

        # Create a minimal SentryIssue object
        from vibeteam.connectors.sentry import SentryIssue

        issue = SentryIssue(
            id=issue_id,
            short_id=issue_details.get("shortId", ""),
            title=issue_details.get("title", ""),
            culprit=issue_details.get("culprit", ""),
            level=issue_details.get("level", "error"),
            status=issue_details.get("status", "unresolved"),
            first_seen=issue_details.get("firstSeen", ""),
            last_seen=issue_details.get("lastSeen", ""),
            count=issue_details.get("count", 0),
            user_count=issue_details.get("userCount", 0),
            project=issue_details.get("project", {}).get("slug", ""),
            permalink=issue_details.get("permalink", ""),
            metadata=issue_details.get("metadata", {}),
        )

        # Triage the issue
        result = await agent.triage_sentry_issue(issue, auto_create_github=True)
        print(f"Triage result for {issue.short_id}: {result.classification}")
    except Exception as e:
        print(f"Error triaging issue {issue_id}: {e}")


# =====================
# GitHub Webhook
# =====================


def verify_github_signature(
    request_body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify GitHub webhook signature (SHA-256)."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        key=secret.encode(),
        msg=request_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
):
    """
    Receive GitHub webhooks.

    Handles:
    - issues.opened: New issue created
    - issues.labeled: Issue labeled (trigger on 'auto-fix')
    - pull_request.opened: New PR for review
    - pull_request.synchronize: PR updated
    """
    body = await request.body()

    # Verify signature if secret is configured
    github_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if github_secret and x_hub_signature_256:
        if not verify_github_signature(body, x_hub_signature_256, github_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = x_github_event or "unknown"
    action = payload.get("action", "unknown")

    # Handle different events
    if event == "issues":
        if action == "labeled":
            # Check if 'auto-fix' label was added
            label = payload.get("label", {}).get("name", "")
            if label == "auto-fix":
                issue_number = payload.get("issue", {}).get("number")
                background_tasks.add_task(
                    fix_issue_background,
                    issue_number=issue_number,
                )
                return {
                    "status": "accepted",
                    "event": event,
                    "action": action,
                    "issue_number": issue_number,
                    "message": "Auto-fix triggered",
                }

    elif event == "pull_request":
        if action in ["opened", "synchronize"]:
            pr_number = payload.get("pull_request", {}).get("number")
            # Check if 'auto-review' label exists
            labels = [
                lbl.get("name", "")
                for lbl in payload.get("pull_request", {}).get("labels", [])
            ]
            if "auto-review" in labels:
                background_tasks.add_task(
                    review_pr_background,
                    pr_number=pr_number,
                )
                return {
                    "status": "accepted",
                    "event": event,
                    "action": action,
                    "pr_number": pr_number,
                    "message": "Auto-review triggered",
                }

    return {
        "status": "accepted",
        "event": event,
        "action": action,
        "message": f"Event {event}.{action} received",
    }


async def fix_issue_background(issue_number: int):
    """Background task to fix an issue."""
    try:
        agent = get_agent()
        result = await agent.fix_issue(issue_number)
        print(f"Fix result for #{issue_number}: success={result.success}, PR={result.pr_url}")
    except Exception as e:
        print(f"Error fixing issue #{issue_number}: {e}")


async def review_pr_background(pr_number: int):
    """Background task to review a PR."""
    try:
        agent = get_agent()
        result = await agent.review_pr(pr_number, auto_submit=True)
        print(f"Review result for PR #{pr_number}: verdict={result.get('verdict')}")
    except Exception as e:
        print(f"Error reviewing PR #{pr_number}: {e}")


# =====================
# REST API Endpoints
# =====================


class FixIssueRequest(BaseModel):
    """Request to fix an issue."""

    issue_number: int
    run_tests: bool = True
    create_pr: bool = True


class ReviewPRRequest(BaseModel):
    """Request to review a PR."""

    pr_number: int
    auto_submit: bool = False


class TriageRequest(BaseModel):
    """Request to triage Sentry issues."""

    hours: int = 24
    limit: int = 10
    auto_create_github: bool = True


@app.post("/api/fix-issue")
async def api_fix_issue(
    request: FixIssueRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger fix for a GitHub issue.

    This will create a branch, implement a fix, and optionally
    create a PR.
    """
    background_tasks.add_task(
        fix_issue_background,
        issue_number=request.issue_number,
    )
    return {
        "status": "accepted",
        "issue_number": request.issue_number,
        "message": "Fix task queued",
    }


@app.post("/api/review-pr")
async def api_review_pr(
    request: ReviewPRRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger review for a PR.

    This will analyze the PR and optionally submit a review.
    """
    background_tasks.add_task(
        review_pr_background,
        pr_number=request.pr_number,
    )
    return {
        "status": "accepted",
        "pr_number": request.pr_number,
        "message": "Review task queued",
    }


@app.post("/api/triage")
async def api_triage(
    request: TriageRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger Sentry issue triage.

    This will fetch recent unresolved issues and classify them.
    """

    async def triage_background():
        try:
            agent = get_agent()
            results = await agent.triage_sentry_issues(
                hours=request.hours,
                limit=request.limit,
                auto_create_github=request.auto_create_github,
            )
            print(f"Triage completed: {len(results)} issues processed")
        except Exception as e:
            print(f"Error during triage: {e}")

    background_tasks.add_task(triage_background)
    return {
        "status": "accepted",
        "hours": request.hours,
        "limit": request.limit,
        "message": "Triage task queued",
    }


@app.get("/api/status")
async def api_status():
    """Get current agent status."""
    agent = get_agent()
    return {
        "status": "ready",
        "workspace": agent.workspace_path,
        "model": agent.model,
        "total_cost": agent.get_total_cost(),
    }


# =====================
# Main Entry Point
# =====================


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "vibeteam.webhooks.server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
    )
