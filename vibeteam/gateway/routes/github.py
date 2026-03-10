"""
GitHub Webhook Handlers.

Handles GitHub webhook events and routes to agent microservices:
- issues.assigned: Trigger SWE agent when issue assigned to bot
- issue_comment.created: Respond to /RoleName mentions in comments
- pull_request_review_comment.created: Respond to PR review comments
- discussion.created: Respond to /RoleName mentions in discussion body
- discussion_comment.created: Respond to /RoleName mentions in discussion comments

Uses the Router for /RoleName mention-based routing.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from vibeteam.gateway.server import call_agent_service, config
from vibeteam.router import Router
from vibeteam.agents_config import get_slack_handle
from vibeteam.router.models import AgentRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["GitHub"])

# Message router for /RoleName parsing
_message_router: Router | None = None

ROLE_ASSIGNEE_ENV_KEYS: dict[AgentRole, tuple[str, ...]] = {
    "software_engineer": (
        "GITHUB_SOFTWARE_ENGINEER_BOT_ASSIGNEE",
        "GITHUB_APP_BOT_USERNAME_SOFTWARE_ENGINEER",
        "GITHUB_BOT_USERNAME_SOFTWARE_ENGINEER",
    ),
    "support_engineer": (
        "GITHUB_SUPPORT_ENGINEER_BOT_ASSIGNEE",
        "GITHUB_APP_BOT_USERNAME_SUPPORT_ENGINEER",
        "GITHUB_BOT_USERNAME_SUPPORT_ENGINEER",
    ),
    "release_engineer": (
        "GITHUB_RELEASE_ENGINEER_BOT_ASSIGNEE",
        "GITHUB_APP_BOT_USERNAME_RELEASE_ENGINEER",
        "GITHUB_BOT_USERNAME_RELEASE_ENGINEER",
    ),
    "product_manager": (
        "GITHUB_PRODUCT_MANAGER_BOT_ASSIGNEE",
        "GITHUB_APP_BOT_USERNAME_PRODUCT_MANAGER",
        "GITHUB_BOT_USERNAME_PRODUCT_MANAGER",
    ),
    "marketing_manager": (
        "GITHUB_MARKETING_MANAGER_BOT_ASSIGNEE",
        "GITHUB_APP_BOT_USERNAME_MARKETING_MANAGER",
        "GITHUB_BOT_USERNAME_MARKETING_MANAGER",
    ),
}


def get_message_router() -> Router:
    """Get or create the message router."""
    global _message_router
    if _message_router is None:
        _message_router = Router()
    return _message_router


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not secret:
        return False

    if not signature or not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _iter_github_webhook_secrets() -> list[str]:
    """Collect all configured GitHub webhook secrets (default + role-scoped)."""
    secrets: list[str] = []

    def _append(raw: str | None) -> None:
        if not raw:
            return
        for candidate in raw.split(","):
            value = candidate.strip()
            if value and value not in secrets:
                secrets.append(value)

    _append(config.GITHUB_WEBHOOK_SECRET)
    _append(os.environ.get("GITHUB_WEBHOOK_SECRET", ""))
    _append(os.environ.get("GITHUB_WEBHOOK_SECRETS", ""))

    for key, value in os.environ.items():
        if not value:
            continue
        if key.startswith("GITHUB_WEBHOOK_SECRET_") or key.startswith("GITHUB_APP_WEBHOOK_SECRET_"):
            _append(value)

    return secrets


def verify_signature_any(payload: bytes, signature: str, secrets: list[str]) -> bool:
    """Verify webhook signature against any configured secret."""
    if not signature or not signature.startswith("sha256="):
        return False
    return any(verify_signature(payload, signature, secret) for secret in secrets)


def _normalize_login(login: str) -> str:
    normalized = (login or "").strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if normalized.endswith("[bot]"):
        normalized = normalized[:-5]
    return normalized


def _iter_assignment_bot_candidates() -> set[str]:
    """Collect bot handles that should trigger assignment workflow."""
    values: list[str] = []
    for env_name in (
        "GITHUB_BOT_USERNAME",
        "GITHUB_ISSUE_ASSIGNEE",
        "GITHUB_ASSIGNMENT_BOT_LOGINS",
    ):
        raw = os.environ.get(env_name, "")
        if raw:
            values.extend(raw.split(","))

    if config.BOT_USERNAME:
        values.append(config.BOT_USERNAME)

    # Optional per-role bot usernames (e.g., GITHUB_BOT_USERNAME_SOFTWARE_ENGINEER).
    for key, value in os.environ.items():
        if not value:
            continue
        if key.startswith("GITHUB_BOT_USERNAME_") or key.startswith("GITHUB_APP_BOT_USERNAME_"):
            values.extend(value.split(","))

    return {_normalize_login(v) for v in values if _normalize_login(v)}


def _iter_role_assignment_candidates() -> dict[AgentRole, set[str]]:
    mapping: dict[AgentRole, set[str]] = {}
    for role, env_names in ROLE_ASSIGNEE_ENV_KEYS.items():
        candidates: set[str] = set()
        for env_name in env_names:
            raw = os.environ.get(env_name, "")
            if not raw:
                continue
            for value in raw.split(","):
                normalized = _normalize_login(value)
                if normalized:
                    candidates.add(normalized)
        mapping[role] = candidates
    return mapping


def resolve_assignment_role(assignee: dict[str, Any] | None) -> AgentRole:
    """Resolve role for an assigned issue from assignee login/env mapping."""
    if not assignee:
        return "software_engineer"

    normalized_assignee_login = _normalize_login(assignee.get("login", ""))
    role_candidates = _iter_role_assignment_candidates()
    for role, candidates in role_candidates.items():
        if normalized_assignee_login in candidates:
            return role

    # Fallback to naming conventions when explicit mapping is absent.
    if "support" in normalized_assignee_login:
        return "support_engineer"
    if "release" in normalized_assignee_login:
        return "release_engineer"
    if "product" in normalized_assignee_login:
        return "product_manager"
    if "marketing" in normalized_assignee_login:
        return "marketing_manager"
    if "software" in normalized_assignee_login or "swe" in normalized_assignee_login:
        return "software_engineer"

    return "software_engineer"


def is_assigned_to_bot(assignee: dict[str, Any] | None) -> bool:
    """Check if the assignee is our bot."""
    if not assignee:
        return False

    assignee_login = assignee.get("login", "")
    normalized_assignee_login = _normalize_login(assignee_login)
    bot_user_id = os.environ.get("GITHUB_BOT_USER_ID")

    # Check by login name (supports single bot and role-specific bot handles).
    candidates = _iter_assignment_bot_candidates()
    if normalized_assignee_login in candidates:
        return True
    if any(normalized_assignee_login in role_candidates for role_candidates in _iter_role_assignment_candidates().values()):
        return True

    # Check by user ID if available
    if bot_user_id and str(assignee.get("id")) == bot_user_id:
        return True

    # Fallback for role bot naming convention (e.g. vibeteam-swe-bot-260301[bot]).
    if re.fullmatch(r"vibeteam-[a-z0-9-]+-bot(?:-\d+)?", normalized_assignee_login):
        return True

    return False


async def get_installation_token(role: str | None = None) -> str | None:
    """Get GitHub App installation token (optionally role-specific)."""
    try:
        from vibeteam.utils.github_app import get_installation_token_for_role

        if role:
            token = get_installation_token_for_role(role)
            if token:
                return token

        if (
            config.GITHUB_APP_ID
            and config.GITHUB_APP_PRIVATE_KEY
            and config.GITHUB_APP_INSTALLATION_ID
        ):
            return get_installation_token_for_role("__default__")
    except ImportError:
        logger.warning("github_app utility not available")
    except Exception as e:
        logger.error(f"Failed to get installation token: {e}")

    return None


async def get_required_installation_token(role: str | None, action: str) -> str | None:
    """Return a GitHub App installation token or log a hard failure for webhook flows."""
    token = await get_installation_token(role)
    if token:
        return token
    logger.error(
        "GitHub App token unavailable for action '%s' (role=%s). "
        "Gateway webhook actions require GitHub App credentials.",
        action,
        role or "default",
    )
    return None


async def post_acknowledgment(repo: str, issue_number: int, role: str = "software_engineer") -> None:
    """Post a comment acknowledging the assignment."""
    token = await get_required_installation_token(role, "post_acknowledgment")

    if not token:
        logger.warning("No GitHub App token available, skipping acknowledgment")
        return

    try:
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
        logger.error(f"Failed to post acknowledgment: {e}")


async def run_swe_agent(
    repo: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> None:
    """Run the Software Engineer agent on an issue via the agent service."""
    logger.info(f"Starting SWE agent for {repo}#{issue_number}: {issue_title}")

    # Build the task description
    task = f"""## GitHub Issue Assignment

You have been assigned to fix GitHub issue #{issue_number} in repository {repo}.

### Issue Title
{issue_title}

### Issue Description
{issue_body}

### Instructions
1. Analyze the issue to understand the problem
2. Search the codebase for relevant files
3. Implement a fix following the project's coding standards
4. Create unit tests if applicable
5. Create a pull request with your changes
6. Link the PR to this issue

If you need another team member's help, mention them with /RoleName:
- /ReleaseEngineer - for deployment or release issues
- /SupportEngineer - for customer-facing issues
- /ProductManager - for requirements clarification

Repository: {repo}
Issue: #{issue_number}
"""

    try:
        result = await call_agent_service(
            task=task,
            role="software_engineer",
            context_type="github_issue",
            context_id=f"{repo}:{issue_number}",
        )

        if "error" in result:
            logger.error(f"SWE agent failed for {repo}#{issue_number}: {result['error']}")
            await post_github_comment(
                repo,
                issue_number,
                f"I encountered an error while working on this issue: {result['error']}",
                role="software_engineer",
            )
        else:
            response = result.get("response", "I've completed my analysis.")
            # Post response as comment
            await post_github_comment(repo, issue_number, response, role="software_engineer")

            # Check for handoffs
            message_router = get_message_router()
            handoff_roles = message_router.parse_role_mentions(response)
            if handoff_roles:
                logger.info(f"Detected handoff to: {handoff_roles}")
                for role in handoff_roles:
                    await run_agent_for_github(
                        repo=repo,
                        issue_number=issue_number,
                        role=role,
                        context=f"Handoff from SoftwareEngineer:\n\n{response}",
                    )

    except Exception as e:
        logger.exception(f"Failed to run SWE agent: {e}")


async def run_agent_for_github(
    repo: str,
    issue_number: int,
    role: AgentRole,
    context: str,
    handoff_depth: int = 0,
    max_handoff_depth: int = 1,
    visited_roles: set[AgentRole] | None = None,
) -> None:
    """Run a specific agent for a GitHub issue."""
    display_name = get_slack_handle(role) or role.replace("_", " ").title()
    logger.info(f"Running {display_name} agent for {repo}#{issue_number}")

    task = f"""## GitHub Issue Context

You are helping with GitHub issue #{issue_number} in repository {repo}.

### Context
{context}

### Instructions
1. Analyze the context and provide helpful information
2. Use available tools to investigate or take action
3. If you need another team member, mention them with /RoleName

Repository: {repo}
Issue: #{issue_number}
"""

    visited = set(visited_roles or set())
    visited.add(role)

    try:
        result = await call_agent_service(
            task=task,
            role=role,
            context_type="github_issue",
            context_id=f"{repo}:{issue_number}",
        )

        if "error" in result:
            logger.error(f"{display_name} agent failed: {result['error']}")
        else:
            response = result.get("response", "")
            if response:
                formatted = f"[{display_name}] {response}"
                await post_github_comment(repo, issue_number, formatted, role=role)

                if handoff_depth < max_handoff_depth:
                    message_router = get_message_router()
                    handoff_roles = message_router.parse_role_mentions(response)
                    if handoff_roles:
                        logger.info(
                            f"Detected GitHub handoff from {display_name} to: {handoff_roles}"
                        )
                        for next_role in handoff_roles:
                            if next_role == role or next_role in visited:
                                continue
                            await run_agent_for_github(
                                repo=repo,
                                issue_number=issue_number,
                                role=next_role,
                                context=f"Handoff from {display_name}:\n\n{response}",
                                handoff_depth=handoff_depth + 1,
                                max_handoff_depth=max_handoff_depth,
                                visited_roles=visited,
                            )

    except Exception as e:
        logger.exception(f"Failed to run {display_name} agent: {e}")


async def post_github_discussion_comment(
    repo: str,
    discussion_number: int,
    body: str,
    role: str | None = None,
) -> None:
    """Post a comment on a GitHub discussion."""
    token = await get_installation_token(role)

    if not token:
        logger.warning("No GitHub App token available, skipping discussion comment")
        return

    try:
        owner, name = repo.split("/", 1)
    except ValueError:
        logger.error(f"Invalid repo format for discussion comment: {repo}")
        return

    discussion_query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        discussion(number: $number) { id }
      }
    }
    """
    comment_mutation = """
    mutation($discussionId: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
        comment { id }
      }
    }
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "query": discussion_query,
                    "variables": {"owner": owner, "repo": name, "number": discussion_number},
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            discussion = (payload.get("data") or {}).get("repository", {}).get("discussion")
            discussion_id = discussion.get("id") if isinstance(discussion, dict) else None
            if not discussion_id:
                logger.error(f"Missing discussion ID for {repo}#{discussion_number}")
                return

            response = await client.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "query": comment_mutation,
                    "variables": {"discussionId": discussion_id, "body": body},
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            logger.info(f"Posted discussion comment to {repo}#{discussion_number}")

    except Exception as e:
        logger.error(f"Failed to post discussion comment: {e}")


async def fetch_github_discussion(
    repo: str,
    discussion_number: int,
    role: str | None = None,
) -> dict[str, Any] | None:
    """Fetch discussion details from GitHub."""
    token = await get_installation_token(role)

    if not token:
        logger.warning("No GitHub App token available, skipping discussion fetch")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo}/discussions/{discussion_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch discussion details: {e}")
        return None


async def fetch_github_discussion_comment(
    repo: str,
    comment_node_id: str,
    role: str | None = None,
) -> dict[str, Any] | None:
    """Fetch discussion comment details via GraphQL node ID."""
    token = await get_installation_token(role)

    if not token:
        logger.warning("No GitHub App token available, skipping discussion comment fetch")
        return None

    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on DiscussionComment {
          body
          createdAt
          discussion {
            number
            title
            body
          }
        }
      }
    }
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"query": query, "variables": {"id": comment_node_id}},
            )
            response.raise_for_status()
            data = response.json()
        node = (data.get("data") or {}).get("node") or {}
        return node if isinstance(node, dict) else None
    except Exception as e:
        logger.error(f"Failed to fetch discussion comment details: {e}")
        return None


async def run_agent_for_github_discussion(
    repo: str,
    discussion_number: int,
    discussion_title: str,
    role: AgentRole,
    context: str,
    handoff_depth: int = 0,
    max_handoff_depth: int = 1,
    visited_roles: set[AgentRole] | None = None,
) -> None:
    """Run a specific agent for a GitHub discussion."""
    display_name = get_slack_handle(role) or role.replace("_", " ").title()
    logger.info(f"Running {display_name} agent for {repo} discussion #{discussion_number}")

    task = f"""## GitHub Discussion Context

You are helping with GitHub discussion #{discussion_number} in repository {repo}.

### Discussion Title
{discussion_title}

### Context
{context}

### Instructions
1. Respond in the discussion thread with helpful context or action
2. Use available tools to investigate or take action
3. If you need another team member, mention them with /RoleName

Repository: {repo}
Discussion: #{discussion_number}
"""

    visited = set(visited_roles or set())
    visited.add(role)

    try:
        result = await call_agent_service(
            task=task,
            role=role,
            context_type="github_discussion",
            context_id=f"{repo}:discussion:{discussion_number}",
        )

        if "error" in result:
            logger.error(f"{display_name} agent failed: {result['error']}")
        else:
            response = result.get("response", "")
            if response:
                formatted = f"[{display_name}] {response}"
                await post_github_discussion_comment(
                    repo, discussion_number, formatted, role=role
                )

                if handoff_depth < max_handoff_depth:
                    message_router = get_message_router()
                    handoff_roles = message_router.parse_role_mentions(response)
                    if handoff_roles:
                        logger.info(
                            f"Detected GitHub discussion handoff from {display_name} to: {handoff_roles}"
                        )
                        for next_role in handoff_roles:
                            if next_role == role or next_role in visited:
                                continue
                            await run_agent_for_github_discussion(
                                repo=repo,
                                discussion_number=discussion_number,
                                discussion_title=discussion_title,
                                role=next_role,
                                context=f"Handoff from {display_name}:\n\n{response}",
                                handoff_depth=handoff_depth + 1,
                                max_handoff_depth=max_handoff_depth,
                                visited_roles=visited,
                            )

    except Exception as e:
        logger.exception(f"Failed to run {display_name} discussion agent: {e}")


async def post_github_comment(
    repo: str,
    issue_number: int,
    body: str,
    role: str | None = None,
) -> None:
    """Post a comment on a GitHub issue."""
    token = await get_required_installation_token(role, "post_github_comment")

    if not token:
        logger.warning("No GitHub App token available, skipping comment")
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"body": body},
            )
            response.raise_for_status()
            logger.info(f"Posted comment to {repo}#{issue_number}")

    except Exception as e:
        logger.error(f"Failed to post GitHub comment: {e}")


@router.post("/webhook")
async def handle_github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
) -> dict[str, str]:
    """Handle incoming GitHub webhook events."""
    payload_bytes = await request.body()
    payload_preview: dict[str, Any] = {}
    try:
        payload_preview = json.loads(payload_bytes) if payload_bytes else {}
    except json.JSONDecodeError:
        payload_preview = {}

    preview_repo = str((payload_preview.get("repository") or {}).get("full_name") or "n/a")
    preview_action = str(payload_preview.get("action") or "n/a")
    preview_sender = str((payload_preview.get("sender") or {}).get("login") or "n/a")
    preview_installation = str((payload_preview.get("installation") or {}).get("id") or "n/a")

    webhook_secrets = _iter_github_webhook_secrets()
    if not webhook_secrets:
        logger.error("GitHub webhook secret is not configured")
        raise HTTPException(status_code=503, detail="GitHub webhook secret not configured")

    # Verify signature
    if not verify_signature_any(payload_bytes, x_hub_signature_256 or "", webhook_secrets):
        logger.warning(
            "Invalid webhook signature: event=%s action=%s repo=%s sender=%s installation=%s delivery=%s configured_secrets=%d",
            x_github_event,
            preview_action,
            preview_repo,
            preview_sender,
            preview_installation,
            x_github_delivery or "n/a",
            len(webhook_secrets),
        )
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = payload_preview or json.loads(payload_bytes)
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
            assignee_login = (assignee or {}).get("login", "")
            assigned_role = resolve_assignment_role(assignee)

            logger.info(
                "Issue #%s assigned to %s; triggering %s",
                issue_number,
                assignee_login,
                assigned_role,
            )

            # Post acknowledgment and run agent in background
            asyncio.create_task(
                post_acknowledgment(repo_full_name, issue_number, role=assigned_role)
            )
            if assigned_role == "software_engineer":
                asyncio.create_task(
                    run_swe_agent(repo_full_name, issue_number, issue_title, issue_body)
                )
            else:
                assignment_context = (
                    f"Issue assigned to {get_slack_handle(assigned_role) or assigned_role}.\n\n"
                    f"Issue title: {issue_title}\n\n"
                    f"Issue body:\n{issue_body}"
                )
                asyncio.create_task(
                    run_agent_for_github(
                        repo=repo_full_name,
                        issue_number=issue_number,
                        role=assigned_role,
                        context=assignment_context,
                    )
                )

            return {
                "status": "accepted",
                "message": f"Processing issue #{issue_number} as {assigned_role}",
            }

    # Handle @mention or /RoleName in issue comments
    if x_github_event == "issue_comment" and action == "created":
        comment = payload.get("comment", {})
        comment_body = comment.get("body", "")
        issue = payload.get("issue", {})
        comment_user = comment.get("user", {}).get("login", "")

        # Ignore bot's own comments
        if config.BOT_USERNAME.replace("[bot]", "") in comment_user:
            return {"status": "ignored", "reason": "own_comment"}

        issue_number = issue.get("number")

        # Check for /RoleName mentions
        message_router = get_message_router()
        role_mentions = message_router.parse_role_mentions(comment_body)

        if role_mentions:
            logger.info(f"Role mentions in comment on #{issue_number}: {role_mentions}")
            for role in role_mentions:
                asyncio.create_task(
                    run_agent_for_github(
                        repo=repo_full_name,
                        issue_number=issue_number,
                        role=role,
                        context=f"User comment:\n\n{comment_body}",
                    )
                )
            return {
                "status": "accepted",
                "message": f"Processing roles {role_mentions} for #{issue_number}",
            }

        # Check if bot is mentioned (fallback to SWE)
        bot_mention = f"@{config.BOT_USERNAME.replace('[bot]', '')}"
        if bot_mention in comment_body or "@VibeTeam" in comment_body:
            logger.info(f"Bot mentioned in comment on #{issue_number}")

            asyncio.create_task(
                run_swe_agent(
                    repo_full_name,
                    issue_number,
                    issue.get("title", ""),
                    f"Original issue:\n{issue.get('body', '')}\n\nNew comment:\n{comment_body}",
                )
            )

            return {"status": "accepted", "message": f"Processing mention in #{issue_number}"}

    # Handle /RoleName mentions in discussions
    if x_github_event == "discussion" and action == "created":
        discussion = payload.get("discussion", {})
        discussion_body = discussion.get("body", "")
        discussion_title = discussion.get("title", "")
        discussion_number = discussion.get("number")
        discussion_user = discussion.get("user", {}).get("login", "")
        discussion_user_type = discussion.get("user", {}).get("type", "")

        # Ignore bot discussions
        if discussion_user_type == "Bot" or config.BOT_USERNAME.replace("[bot]", "") in discussion_user:
            return {"status": "ignored", "reason": "own_comment"}

        if discussion_number:
            fetched = await fetch_github_discussion(
                repo_full_name, discussion_number, role="software_engineer"
            )
            if fetched:
                discussion_body = fetched.get("body", discussion_body) or discussion_body
                discussion_title = fetched.get("title", discussion_title) or discussion_title

        message_router = get_message_router()
        role_mentions = message_router.parse_role_mentions(discussion_body)
        if not role_mentions and discussion_body:
            fallback_roles: list[AgentRole] = []
            for role in ("software_engineer", "support_engineer", "release_engineer", "product_manager", "marketing_manager"):
                handle = get_slack_handle(role) or role.replace("_", " ").title()
                if handle and re.search(rf"\\b{re.escape(handle)}\\b", discussion_body, re.IGNORECASE):
                    fallback_roles.append(role)
            if fallback_roles:
                role_mentions = fallback_roles

        if role_mentions:
            logger.info(f"Role mentions in discussion #{discussion_number}: {role_mentions}")
            for role in role_mentions:
                asyncio.create_task(
                    run_agent_for_github_discussion(
                        repo=repo_full_name,
                        discussion_number=discussion_number,
                        discussion_title=discussion_title,
                        role=role,
                        context=f"Discussion body:\n\n{discussion_body}",
                    )
                )
            return {
                "status": "accepted",
                "message": f"Processing roles {role_mentions} for discussion #{discussion_number}",
            }

        bot_mention = f"@{config.BOT_USERNAME.replace('[bot]', '')}"
        if bot_mention in discussion_body or "@VibeTeam" in discussion_body:
            logger.info(f"Bot mentioned in discussion #{discussion_number}")
            asyncio.create_task(
                run_agent_for_github_discussion(
                    repo=repo_full_name,
                    discussion_number=discussion_number,
                    discussion_title=discussion_title,
                    role="software_engineer",
                    context=f"Discussion body:\n\n{discussion_body}",
                )
            )
            return {
                "status": "accepted",
                "message": f"Processing mention in discussion #{discussion_number}",
            }

    # Handle /RoleName in discussion comments
    if x_github_event == "discussion_comment" and action == "created":
        comment = payload.get("comment", {})
        comment_body = comment.get("body", "")
        comment_node_id = comment.get("node_id", "")
        comment_user = comment.get("user", {}).get("login", "")
        comment_user_type = comment.get("user", {}).get("type", "")
        discussion = payload.get("discussion", {})
        discussion_body = discussion.get("body", "")
        discussion_title = discussion.get("title", "")
        discussion_number = discussion.get("number")

        # Ignore bot's own comments
        if comment_user_type == "Bot" or config.BOT_USERNAME.replace("[bot]", "") in comment_user:
            return {"status": "ignored", "reason": "own_comment"}

        if comment_node_id and not comment_body:
            fetched_comment = await fetch_github_discussion_comment(
                repo_full_name, comment_node_id, role="software_engineer"
            )
            if fetched_comment:
                comment_body = fetched_comment.get("body", comment_body) or comment_body
                fetched_discussion = fetched_comment.get("discussion") or {}
                discussion_number = discussion_number or fetched_discussion.get("number")
                discussion_body = discussion_body or fetched_discussion.get("body", "")
                discussion_title = discussion_title or fetched_discussion.get("title", "")

        if discussion_number and (not discussion_body or not discussion_title):
            fetched = await fetch_github_discussion(
                repo_full_name, discussion_number, role="software_engineer"
            )
            if fetched:
                discussion_body = discussion_body or fetched.get("body", "")
                discussion_title = discussion_title or fetched.get("title", "")

        message_router = get_message_router()
        role_mentions = message_router.parse_role_mentions(comment_body)
        if not role_mentions and comment_body:
            fallback_roles: list[AgentRole] = []
            for role in (
                "software_engineer",
                "support_engineer",
                "release_engineer",
                "product_manager",
                "marketing_manager",
            ):
                handle = get_slack_handle(role) or role.replace("_", " ").title()
                if handle and re.search(rf"\\b{re.escape(handle)}\\b", comment_body, re.IGNORECASE):
                    fallback_roles.append(role)
            if fallback_roles:
                role_mentions = fallback_roles

        if role_mentions:
            logger.info(
                f"Role mentions in discussion comment on #{discussion_number}: {role_mentions}"
            )
            for role in role_mentions:
                asyncio.create_task(
                    run_agent_for_github_discussion(
                        repo=repo_full_name,
                        discussion_number=discussion_number,
                        discussion_title=discussion_title,
                        role=role,
                        context=(
                            "Discussion body:\n\n"
                            f"{discussion_body}\n\n"
                            f"New comment:\n{comment_body}"
                        ),
                    )
                )
            return {
                "status": "accepted",
                "message": f"Processing roles {role_mentions} for discussion #{discussion_number}",
            }

        bot_mention = f"@{config.BOT_USERNAME.replace('[bot]', '')}"
        if bot_mention in comment_body or "@VibeTeam" in comment_body:
            logger.info(f"Bot mentioned in discussion comment on #{discussion_number}")
            asyncio.create_task(
                run_agent_for_github_discussion(
                    repo=repo_full_name,
                    discussion_number=discussion_number,
                    discussion_title=discussion_title,
                    role="software_engineer",
                    context=(
                        "Discussion body:\n\n"
                        f"{discussion_body}\n\n"
                        f"New comment:\n{comment_body}"
                    ),
                )
            )
            return {
                "status": "accepted",
                "message": f"Processing mention in discussion #{discussion_number}",
            }

    # Handle PR review comments
    if x_github_event == "pull_request_review_comment" and action == "created":
        comment = payload.get("comment", {})
        comment_body = comment.get("body", "")
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")
        comment_user = comment.get("user", {}).get("login", "")

        # Ignore bot's own comments
        if config.BOT_USERNAME.replace("[bot]", "") in comment_user:
            return {"status": "ignored", "reason": "own_comment"}

        # Check for /RoleName mentions
        message_router = get_message_router()
        role_mentions = message_router.parse_role_mentions(comment_body)

        if role_mentions:
            logger.info(f"Role mentions in PR comment on #{pr_number}: {role_mentions}")
            for role in role_mentions:
                asyncio.create_task(
                    run_agent_for_github(
                        repo=repo_full_name,
                        issue_number=pr_number,  # PRs use the same comment API
                        role=role,
                        context=f"PR review comment:\n\n{comment_body}",
                    )
                )
            return {
                "status": "accepted",
                "message": f"Processing roles {role_mentions} for PR #{pr_number}",
            }

    return {"status": "ignored", "event": f"{x_github_event}.{action}"}
