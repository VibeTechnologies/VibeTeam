#!/usr/bin/env python3
"""
End-to-end GitHub webhook evaluation.

Scenarios create GitHub issues/discussions/PR comments containing native
@RoleName mentions and then verify that multiple agent bots respond in the thread.

Usage:
  uv run python scripts/eval_github_e2e.py --scenario github_issue_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_discussion_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_pr_comment_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_threads_all
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable

import httpx

DEFAULT_REPO = os.environ.get("GITHUB_TEST_REPO", "VibeTechnologies/vibeteam-eval-hello-world")
DEFAULT_PR = int(os.environ.get("GITHUB_TEST_PR", "1"))
DEFAULT_ISSUE_ASSIGNEE = os.environ.get("GITHUB_ISSUE_ASSIGNEE", "").strip()
DEFAULT_ACTOR_LOGIN = os.environ.get("GITHUB_EVAL_ACTOR_LOGIN", "OpenCodeEngineer").strip()
DEFAULT_ISSUE_ROLE_RAW = os.environ.get("GITHUB_ISSUE_ROLE", "software_engineer").strip()
NATIVE_GITHUB_HANDOFF_MENTIONS = "@SoftwareEngineer @SupportEngineer"

ROLE_DEFAULT_ASSIGNEES: dict[str, str] = {
    "software_engineer": os.environ.get(
        "GITHUB_SOFTWARE_ENGINEER_BOT_ASSIGNEE",
        os.environ.get("GITHUB_APP_BOT_USERNAME_SOFTWARE_ENGINEER", "vibeteam-swe-bot-260301[bot]"),
    ).strip(),
    "support_engineer": os.environ.get(
        "GITHUB_SUPPORT_ENGINEER_BOT_ASSIGNEE",
        os.environ.get("GITHUB_APP_BOT_USERNAME_SUPPORT_ENGINEER", "vibeteam-support-bot-260301[bot]"),
    ).strip(),
    "release_engineer": os.environ.get(
        "GITHUB_RELEASE_ENGINEER_BOT_ASSIGNEE",
        os.environ.get("GITHUB_APP_BOT_USERNAME_RELEASE_ENGINEER", "vibeteam-release-bot-260301[bot]"),
    ).strip(),
    "product_manager": os.environ.get(
        "GITHUB_PRODUCT_MANAGER_BOT_ASSIGNEE",
        os.environ.get("GITHUB_APP_BOT_USERNAME_PRODUCT_MANAGER", "vibeteam-pm-bot-260301[bot]"),
    ).strip(),
    "marketing_manager": os.environ.get(
        "GITHUB_MARKETING_MANAGER_BOT_ASSIGNEE",
        os.environ.get("GITHUB_APP_BOT_USERNAME_MARKETING_MANAGER", "vibeteam-mktg-bot-260301[bot]"),
    ).strip(),
}
ROLE_ASSIGNEE_ENV_KEYS: dict[str, tuple[str, ...]] = {
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
DEFAULT_ISSUE_ROLE = (
    DEFAULT_ISSUE_ROLE_RAW
    if DEFAULT_ISSUE_ROLE_RAW in ROLE_DEFAULT_ASSIGNEES
    else "software_engineer"
)

SCENARIOS = {
    "github_issue_handoff": {
        "name": "GitHub Issue Handoff (Webhook)",
    },
    "github_issue_pr_handoff_github": {
        "name": "GitHub Issue + PR Handoff (Webhook)",
    },
    "github_discussion_handoff": {
        "name": "GitHub Discussion Handoff (Webhook)",
    },
    "github_pr_comment_handoff": {
        "name": "GitHub PR Comment Handoff (Webhook)",
    },
    "github_threads_all": {
        "name": "GitHub Issue + Discussion + PR Handoff (Webhook)",
    },
}


def _normalize_login(login: str) -> str:
    normalized = (login or "").strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized


def _configured_bot_handles() -> set[str]:
    handles: set[str] = set()

    if DEFAULT_ISSUE_ASSIGNEE:
        for value in DEFAULT_ISSUE_ASSIGNEE.split(","):
            normalized = _normalize_login(value)
            if normalized:
                handles.add(normalized)
    for value in ROLE_DEFAULT_ASSIGNEES.values():
        if not value:
            continue
        for candidate in value.split(","):
            normalized = _normalize_login(candidate)
            if normalized:
                handles.add(normalized)

    for env_name in (
        "GITHUB_ASSIGNMENT_BOT_LOGINS",
        "GITHUB_ISSUE_ASSIGNEE",
    ):
        raw = os.environ.get(env_name, "")
        if not raw:
            continue
        for value in raw.split(","):
            normalized = _normalize_login(value)
            if normalized:
                handles.add(normalized)

    return handles


def _is_bot_login(login: str, extra_allowed: set[str] | None = None) -> bool:
    lowered = _normalize_login(login)
    if lowered.endswith("[bot]") or "-bot" in lowered:
        return True

    allowlist = set(extra_allowed or set())
    allowlist.update(_configured_bot_handles())
    return lowered in {_normalize_login(x) for x in allowlist if x}


def _is_conventional_bot_login(login: str) -> bool:
    lowered = _normalize_login(login)
    return lowered.endswith("[bot]") or "-bot" in lowered


def _is_expected_actor(actor_login: str, creator_login: str) -> bool:
    return _normalize_login(actor_login) == _normalize_login(creator_login)


def _default_assignee_for_role(role: str) -> str:
    candidates = _role_assignee_candidates(role)
    return candidates[0] if candidates else ""


def _role_assignee_candidates(role: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for env_name in ROLE_ASSIGNEE_ENV_KEYS.get(role, ()):
        raw = os.environ.get(env_name, "")
        if not raw:
            continue
        for value in raw.split(","):
            candidate = value.strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    default_raw = ROLE_DEFAULT_ASSIGNEES.get(role, "")
    for value in default_raw.split(","):
        candidate = value.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    return candidates


def _allowed_assignees_for_role(role: str) -> set[str]:
    return {_normalize_login(candidate) for candidate in _role_assignee_candidates(role)}


def _assignee_matches_issue_role(assignee: str, issue_role: str) -> bool:
    normalized_assignee = _normalize_login(assignee)
    role_allowed = _allowed_assignees_for_role(issue_role)
    if not role_allowed:
        return True
    return normalized_assignee in role_allowed


def _is_token_usable(token: str) -> bool:
    if not token:
        return False
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://api.github.com/rate_limit",
                headers=_headers(token),
            )
        return response.status_code == 200
    except Exception:
        return False


def _get_gh_cli_token(user: str | None = None) -> str | None:
    try:
        env = os.environ.copy()
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        cmd = ["gh", "auth", "token"]
        if user:
            cmd.extend(["--user", user])
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        token = result.stdout.strip()
        return token or None
    except Exception:
        return None


def _require_token(prefer_gh_user: str | None = None) -> str:
    if prefer_gh_user:
        preferred_gh_token = _get_gh_cli_token(prefer_gh_user)
        if preferred_gh_token and _is_token_usable(preferred_gh_token):
            return preferred_gh_token

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and _is_token_usable(token):
        return token

    gh_cli_token = _get_gh_cli_token()
    if gh_cli_token and _is_token_usable(gh_cli_token):
        return gh_cli_token

    # Fallback to role-scoped GitHub App token when PAT is missing/invalid.
    try:
        from vibeteam.utils.github_app import get_installation_token_for_role

        app_token = get_installation_token_for_role("software_engineer")
    except Exception:
        app_token = None

    if app_token and _is_token_usable(app_token):
        return app_token

    raise SystemExit(
        "No usable GitHub token found. Set GH_TOKEN/GITHUB_TOKEN with valid credentials "
        "or configure SOFTWARE_ENGINEER GitHub App credentials."
    )


def _split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError("Repo must be in owner/repo format")
    owner, name = repo.split("/", 1)
    return owner, name


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _graphql_request(token: str, query: str, variables: dict[str, object]) -> dict:
    url = "https://api.github.com/graphql"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            url,
            headers=_headers(token),
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data", {})


def _get_authenticated_login(token: str) -> str:
    url = "https://api.github.com/user"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token))
        response.raise_for_status()
        payload = response.json()
    return str(payload.get("login") or "").strip()


def _validate_actor_login(token: str, actor_login: str) -> None:
    expected = _normalize_login(actor_login)
    if not expected or expected == "n/a":
        return

    try:
        actual = _normalize_login(_get_authenticated_login(token))
    except Exception as exc:
        raise SystemExit(
            "Unable to verify GitHub token identity for actor-login "
            f"'{actor_login}': {exc}"
        ) from exc

    if not actual:
        raise SystemExit(
            "GitHub token identity lookup returned empty login. "
            f"Expected actor-login '{actor_login}'."
        )

    if actual != expected:
        raise SystemExit(
            "GitHub token identity does not match --actor-login. "
            f"expected={actor_login}, actual={actual}. "
            "Use credentials for the requested actor or omit --actor-login."
        )


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _collect_bot_logins(items: Iterable[dict]) -> set[str]:
    logins: set[str] = set()
    for item in items:
        user = item.get("user") or {}
        login = user.get("login") or ""
        user_type = user.get("type") or ""
        if user_type == "Bot" or login.endswith("[bot]"):
            if login:
                logins.add(login)
    return logins


def _collect_comment_logins(items: Iterable[dict]) -> set[str]:
    logins: set[str] = set()
    for item in items:
        user = item.get("user") or {}
        login = str(user.get("login") or "").strip()
        if login:
            logins.add(login)
    return logins


def _build_issue_trigger_comment() -> str:
    """Build issue trigger text using role mentions only (never app handles)."""
    return (
        "Triggering issue handoff + assignment check.\n"
        "Please triage this issue and assign it to the SoftwareEngineer role owner.\n"
        f"{NATIVE_GITHUB_HANDOFF_MENTIONS}\n"
        "Do not @mention any GitHub App bot handle."
    )


def _wait_for_bot_authors(
    fetch_comments: Callable[[], list[dict]],
    since: datetime,
    min_bots: int,
    timeout: int,
    poll_interval: int = 10,
) -> set[str]:
    start = time.time()
    while time.time() - start < timeout:
        comments = fetch_comments()
        recent = [
            c
            for c in comments
            if _parse_ts(c.get("created_at", "1970-01-01T00:00:00Z")) > since
        ]
        bot_logins = _collect_bot_logins(recent)
        if len(bot_logins) >= min_bots:
            return bot_logins
        time.sleep(poll_interval)
    return set()


def _ensure_discussions_enabled(owner: str, repo: str, token: str) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token))
        response.raise_for_status()
        data = response.json()
        if data.get("has_discussions"):
            return
        patch = client.patch(url, headers=_headers(token), json={"has_discussions": True})
        patch.raise_for_status()


def _get_repo_and_category_id(owner: str, repo: str, token: str) -> tuple[str, str]:
    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        id
        discussionCategories(first: 10) {
          nodes { id name }
        }
      }
    }
    """
    data = _graphql_request(token, query, {"owner": owner, "repo": repo})
    repository = data.get("repository") or {}
    categories = (repository.get("discussionCategories") or {}).get("nodes") or []
    if not repository.get("id"):
        raise RuntimeError("Repository ID not found via GraphQL")
    if not categories:
        raise RuntimeError("No discussion categories available")
    preferred = [
        "General",
        "Q&A",
        "Ideas",
        "Show and tell",
        "Polls",
        "Announcements",
    ]
    by_name = {str(cat.get("name", "")).lower(): cat for cat in categories}
    for name in preferred:
        match = by_name.get(name.lower())
        if match and match.get("id"):
            return str(repository["id"]), str(match["id"])
    return str(repository["id"]), str(categories[0]["id"])


def _create_issue(owner: str, repo: str, token: str) -> tuple[int, str, datetime, str]:
    title = f"Eval GitHub issue handoff {uuid.uuid4().hex[:8]}"
    body = (
        "Eval issue to test agent handoff via GitHub comments.\n"
        "Please respond after the trigger comment."
    )
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"title": title, "body": body})
        response.raise_for_status()
        data = response.json()
    creator_login = str((data.get("user") or {}).get("login") or "")
    return int(data["number"]), data["html_url"], _parse_ts(data["created_at"]), creator_login


def _create_issue_comment(
    owner: str, repo: str, token: str, number: int, body: str
) -> datetime:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"body": body})
        response.raise_for_status()
        data = response.json()
    return _parse_ts(data["created_at"])


def _fetch_issue_comments(
    owner: str,
    repo: str,
    number: int,
    token: str,
    since: datetime | None = None,
) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    params = {"per_page": 100}
    if since is not None:
        params["since"] = since.isoformat().replace("+00:00", "Z")
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token), params=params)
        response.raise_for_status()
        return response.json()


def _fetch_issue_assignees(owner: str, repo: str, number: int, token: str) -> list[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token))
        response.raise_for_status()
        data = response.json()
    assignees = data.get("assignees") or []
    return [str(a.get("login")) for a in assignees if a.get("login")]


def _fetch_repo_assignees(owner: str, repo: str, token: str) -> list[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/assignees"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token), params={"per_page": 100})
        response.raise_for_status()
        data = response.json()
    return [str(a.get("login")) for a in data if isinstance(a, dict) and a.get("login")]


def _pick_issue_assignee(bot_logins: set[str], preferred_assignee: str | None = None) -> str | None:
    preferred = (preferred_assignee or "").strip()
    if preferred:
        return preferred
    if not bot_logins:
        return None
    for login in sorted(bot_logins):
        lowered = login.lower()
        if "swe" in lowered or "software" in lowered:
            return login
    return sorted(bot_logins)[0]


def _resolve_issue_assignee(
    owner: str,
    repo: str,
    token: str,
    preferred_assignee: str | None = None,
    issue_role: str = "software_engineer",
) -> str | None:
    preferred = (preferred_assignee or "").strip()
    if preferred:
        return preferred.split(",")[0].strip()

    role_candidates = _role_assignee_candidates(issue_role)
    assignees = _fetch_repo_assignees(owner, repo, token)
    normalized_assignees = {_normalize_login(login): login for login in assignees}
    for candidate in role_candidates:
        matched = normalized_assignees.get(_normalize_login(candidate))
        if matched:
            return matched

    if role_candidates:
        # Keep role mapping strict even when GitHub currently marks the assignee as non-assignable.
        return role_candidates[0]

    bot_assignees = {login for login in assignees if login.endswith("[bot]")}
    if bot_assignees:
        return _pick_issue_assignee(bot_assignees)
    return None


def _assign_issue(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    assignee: str,
) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/assignees"
    assigned_at = datetime.now(timezone.utc)
    current_assignees: list[str] = []
    assigned = False
    error = ""
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers=_headers(token),
                json={"assignees": [assignee]},
            )
            response.raise_for_status()
            data = response.json()
        current_assignees = [
            str(a.get("login")) for a in (data.get("assignees") or []) if a.get("login")
        ]
        assigned = assignee in current_assignees
        updated_at = data.get("updated_at") or data.get("created_at")
        if isinstance(updated_at, str) and updated_at:
            assigned_at = _parse_ts(updated_at)
        if not assigned:
            error = (
                f"Failed to assign issue to {assignee}; current assignees are "
                f"{', '.join(current_assignees) or 'n/a'}"
            )
    except Exception as exc:
        error = str(exc)

    return {
        "assigned": assigned,
        "assigned_at": assigned_at,
        "issue_assignees": current_assignees,
        "error": error,
    }


def _fetch_issue_assignment_events(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    target_assignee: str,
    since: datetime,
) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/events"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            url,
            headers=_headers(token),
            params={"per_page": 100},
        )
        response.raise_for_status()
        data = response.json()

    matched: list[dict] = []
    for event in data:
        if not isinstance(event, dict):
            continue
        if event.get("event") != "assigned":
            continue
        assignee_login = str((event.get("assignee") or {}).get("login") or "")
        created_at_raw = str(event.get("created_at") or "")
        if not assignee_login or not created_at_raw:
            continue
        if _normalize_login(assignee_login) != _normalize_login(target_assignee):
            continue
        if _parse_ts(created_at_raw) <= since:
            continue
        matched.append(event)

    return matched


def _unassign_issue(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    assignee: str,
) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/assignees"
    current_assignees: list[str] = []
    removed = False
    error = ""
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(
                "DELETE",
                url,
                headers=_headers(token),
                json={"assignees": [assignee]},
            )
            response.raise_for_status()
            data = response.json()
        current_assignees = [
            str(a.get("login")) for a in (data.get("assignees") or []) if a.get("login")
        ]
        removed = assignee not in current_assignees
    except Exception as exc:
        error = str(exc)

    return {
        "removed": removed,
        "issue_assignees": current_assignees,
        "error": error,
    }


def _wait_for_assignee_activity(
    fetch_comments: Callable[[], list[dict]],
    since: datetime,
    target_assignee: str,
    timeout: int,
    poll_interval: int = 10,
) -> set[str]:
    start = time.time()
    while time.time() - start < timeout:
        comments = fetch_comments()
        recent = [
            c
            for c in comments
            if _parse_ts(c.get("created_at", "1970-01-01T00:00:00Z")) > since
        ]
        recent_logins = _collect_comment_logins(recent)
        if target_assignee in recent_logins:
            return recent_logins
        time.sleep(poll_interval)
    return set()


def _evaluate_issue_assignment(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    bot_logins: set[str],
    preferred_assignee: str | None = None,
    issue_role: str = "software_engineer",
    wait_seconds: int = 0,
    poll_interval: int = 5,
    force_reassign: bool = False,
    assignment_started_at: datetime | None = None,
    expected_actor_login: str | None = None,
) -> dict:
    target_assignee = _pick_issue_assignee(
        bot_logins,
        preferred_assignee or _default_assignee_for_role(issue_role),
    )
    issue_assignees: list[str] = []
    assignment_error = ""
    assignment_passed = False
    assignment_event_seen = False
    assignment_event_error = ""
    assignment_event_count = 0
    assignment_event_actors: list[str] = []
    assignment_actor_passed = True
    assignment_actor_error = ""
    assignment_fallback_mode = False
    assignment_fallback_reason = ""
    started_at = assignment_started_at or datetime.now(timezone.utc)

    if not target_assignee:
        return {
            "target_assignee": "n/a",
            "issue_assignees": issue_assignees,
            "assignment_passed": False,
            "assignment_error": "No candidate assignee available (no bot author detected).",
            "assignment_event_seen": False,
            "assignment_event_count": 0,
            "assignment_event_error": "",
            "assignment_event_actors": [],
            "assignment_actor_passed": False,
            "assignment_actor_error": "Missing target assignee; cannot validate assignment actor.",
            "assignment_fallback_mode": False,
            "assignment_fallback_reason": "",
        }

    try:
        issue_assignees = _fetch_issue_assignees(owner, repo, issue_number, token)
        assignment_passed = target_assignee in issue_assignees

        if assignment_passed and force_reassign:
            unassign_result = _unassign_issue(owner, repo, token, issue_number, target_assignee)
            issue_assignees = unassign_result.get("issue_assignees", issue_assignees)
            unassign_error = str(unassign_result.get("error") or "")
            assign_result = _assign_issue(owner, repo, token, issue_number, target_assignee)
            issue_assignees = assign_result.get("issue_assignees", issue_assignees)
            assignment_passed = bool(assign_result.get("assigned"))
            assignment_error = str(assign_result.get("error") or "")
            if not assignment_error and unassign_error:
                assignment_error = f"Reassignment warning: {unassign_error}"

        if not assignment_passed:
            assign_result = _assign_issue(owner, repo, token, issue_number, target_assignee)
            issue_assignees = assign_result.get("issue_assignees", [])
            assignment_passed = bool(assign_result.get("assigned"))
            assignment_error = str(assign_result.get("error") or "")

        # Allow eventual consistency for assignee propagation when requested.
        if not assignment_passed and wait_seconds > 0:
            deadline = time.time() + max(wait_seconds, 0)
            while True:
                issue_assignees = _fetch_issue_assignees(owner, repo, issue_number, token)
                assignment_passed = target_assignee in issue_assignees
                if assignment_passed or time.time() >= deadline:
                    break
                time.sleep(max(poll_interval, 1))

        if not assignment_passed:
            if not assignment_error:
                assignment_error = (
                    f"Expected assignee {target_assignee}, but current assignees are: "
                    f"{', '.join(issue_assignees) or 'n/a'}"
                )

            if _is_bot_login(target_assignee):
                assignment_fallback_mode = True
                assignment_fallback_reason = (
                    f"Target role bot assignee {target_assignee} is not assignable in "
                    f"{owner}/{repo}; using mention-trigger fallback and requiring bot responses."
                )

        try:
            assignment_events = _fetch_issue_assignment_events(
                owner,
                repo,
                token,
                issue_number,
                target_assignee,
                started_at,
            )
            assignment_event_count = len(assignment_events)
            assignment_event_seen = assignment_event_count > 0
            assignment_event_actors = sorted(
                {
                    str((event.get("actor") or {}).get("login") or "")
                    for event in assignment_events
                    if isinstance(event, dict)
                }
                - {""}
            )
            if expected_actor_login and _normalize_login(expected_actor_login) != "n/a":
                normalized_expected_actor = _normalize_login(expected_actor_login)
                assignment_actor_passed = (
                    assignment_event_seen
                    and normalized_expected_actor
                    in {_normalize_login(actor) for actor in assignment_event_actors}
                )
                if not assignment_actor_passed:
                    assignment_actor_error = (
                        "Assignment event actor mismatch: expected "
                        f"{expected_actor_login}, observed "
                        f"{', '.join(assignment_event_actors) or 'n/a'}"
                    )
        except Exception as exc:
            assignment_event_error = str(exc)
            if expected_actor_login and _normalize_login(expected_actor_login) != "n/a":
                assignment_actor_passed = False
                assignment_actor_error = (
                    "Assignment event actor check failed due to event fetch error: "
                    f"{assignment_event_error}"
                )
    except Exception as exc:
        assignment_error = str(exc)

    return {
        "target_assignee": target_assignee,
        "issue_assignees": issue_assignees,
        "assignment_passed": assignment_passed,
        "assignment_error": assignment_error,
        "assignment_event_seen": assignment_event_seen,
        "assignment_event_count": assignment_event_count,
        "assignment_event_error": assignment_event_error,
        "assignment_event_actors": assignment_event_actors,
        "assignment_actor_passed": assignment_actor_passed,
        "assignment_actor_error": assignment_actor_error,
        "assignment_fallback_mode": assignment_fallback_mode,
        "assignment_fallback_reason": assignment_fallback_reason,
    }


def _create_discussion(owner: str, repo: str, token: str) -> tuple[int, str, str, datetime]:
    repo_id, category_id = _get_repo_and_category_id(owner, repo, token)
    title = f"Eval GitHub discussion handoff {uuid.uuid4().hex[:8]}"
    body = "Eval discussion to test agent handoff via GitHub discussion comments."
    mutation = """
    mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
      createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
        discussion { id number url createdAt }
      }
    }
    """
    data = _graphql_request(
        token,
        mutation,
        {"repoId": repo_id, "catId": category_id, "title": title, "body": body},
    )
    discussion = (data.get("createDiscussion") or {}).get("discussion") or {}
    if not discussion:
        raise RuntimeError("Failed to create discussion via GraphQL")
    return (
        int(discussion["number"]),
        discussion["url"],
        discussion["id"],
        _parse_ts(discussion["createdAt"]),
    )


def _resolve_discussion(
    owner: str, repo: str, token: str, number: int
) -> tuple[int, str, str, datetime]:
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        discussion(number: $number) {
          id
          number
          url
          createdAt
        }
      }
    }
    """
    data = _graphql_request(token, query, {"owner": owner, "repo": repo, "number": number})
    discussion = (data.get("repository") or {}).get("discussion") or {}
    if not discussion:
        raise RuntimeError(f"Discussion #{number} not found in {owner}/{repo}")
    return (
        int(discussion["number"]),
        discussion["url"],
        discussion["id"],
        _parse_ts(discussion["createdAt"]),
    )


def _create_discussion_comment(
    owner: str, repo: str, token: str, discussion_id: str, body: str
) -> datetime:
    mutation = """
    mutation($discussionId: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
        comment { createdAt }
      }
    }
    """
    data = _graphql_request(
        token,
        mutation,
        {"discussionId": discussion_id, "body": body},
    )
    comment = (data.get("addDiscussionComment") or {}).get("comment") or {}
    created_at = comment.get("createdAt")
    if not created_at:
        raise RuntimeError("Failed to create discussion comment via GraphQL")
    return _parse_ts(created_at)


def _fetch_discussion_comments(owner: str, repo: str, number: int, token: str) -> list[dict]:
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        discussion(number: $number) {
          comments(first: 100) {
            nodes {
              createdAt
              author {
                login
                __typename
              }
            }
          }
        }
      }
    }
    """
    data = _graphql_request(token, query, {"owner": owner, "repo": repo, "number": number})
    discussion = (data.get("repository") or {}).get("discussion") or {}
    comments = (discussion.get("comments") or {}).get("nodes") or []
    normalized: list[dict] = []
    for comment in comments:
        author = comment.get("author") or {}
        normalized.append(
            {
                "created_at": comment.get("createdAt", ""),
                "user": {
                    "login": author.get("login"),
                    "type": author.get("__typename"),
                },
            }
        )
    return normalized


def _create_pr_comment(owner: str, repo: str, token: str, pr_number: int, body: str) -> datetime:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"body": body})
        response.raise_for_status()
        data = response.json()
    return _parse_ts(data["created_at"])


def _run_issue_handoff(
    owner: str,
    repo: str,
    token: str,
    timeout: int,
    issue_assignee: str | None = None,
    issue_role: str = "software_engineer",
    actor_login: str = DEFAULT_ACTOR_LOGIN,
) -> dict:
    issue_number, issue_url, _, creator_login = _create_issue(owner, repo, token)
    creator_passed = _is_expected_actor(actor_login, creator_login)
    creator_error = ""
    if not creator_passed:
        creator_error = (
            f"Issue creator mismatch: expected {actor_login}, got {creator_login or 'n/a'}"
        )
    target_assignee = _resolve_issue_assignee(
        owner,
        repo,
        token,
        preferred_assignee=issue_assignee,
        issue_role=issue_role,
    )
    assignment_checkpoint = datetime.now(timezone.utc)
    assignment = _evaluate_issue_assignment(
        owner,
        repo,
        token,
        issue_number,
        set(),
        target_assignee,
        issue_role,
        wait_seconds=min(timeout, 60),
        force_reassign=True,
        assignment_started_at=assignment_checkpoint,
        expected_actor_login=actor_login,
    )

    def fetch_after_assignment() -> list[dict]:
        return _fetch_issue_comments(owner, repo, issue_number, token, since=assignment_checkpoint)

    assignee_recent_activity: set[str] = set()
    recent_bot_logins: set[str] = set()
    assignment_target = assignment.get("target_assignee", "n/a")
    normalized_assignment_target = _normalize_login(str(assignment_target))
    normalized_actor = _normalize_login(actor_login)
    if (
        assignment["assignment_passed"]
        and assignment_target != "n/a"
        and normalized_assignment_target == normalized_actor
        and not _is_conventional_bot_login(str(assignment_target))
    ):
        # Assignment fallback path for repos where bot handles are not assignable:
        # emit one native role-mention comment from the actor to trigger routing.
        _create_issue_comment(owner, repo, token, issue_number, _build_issue_trigger_comment())

    if assignment["assignment_passed"] and assignment_target != "n/a":
        assignee_recent_activity = _wait_for_assignee_activity(
            fetch_after_assignment,
            assignment_checkpoint,
            assignment_target,
            timeout,
        )
        recent_bot_logins = set(assignee_recent_activity)
    elif bool(assignment.get("assignment_fallback_mode")):
        trigger_ts = _create_issue_comment(owner, repo, token, issue_number, _build_issue_trigger_comment())

        def fetch_after_trigger() -> list[dict]:
            return _fetch_issue_comments(owner, repo, issue_number, token, since=trigger_ts)

        # In fallback mode we require both role bots to reply.
        recent_bot_logins = _wait_for_bot_authors(fetch_after_trigger, trigger_ts, 2, timeout)

    all_bot_logins = _collect_bot_logins(
        _fetch_issue_comments(owner, repo, issue_number, token, since=None)
    )
    fallback_mode = bool(assignment.get("assignment_fallback_mode"))
    strict_assignment_pass = (
        bool(assignee_recent_activity)
        and bool(assignment["assignment_passed"])
        and bool(assignment["assignment_event_seen"])
        and bool(assignment.get("assignment_actor_passed", True))
    )
    fallback_pass = bool(recent_bot_logins) and bool(creator_passed)

    return {
        "thread": issue_url,
        "bot_logins": sorted(all_bot_logins),
        "recent_bot_logins": sorted(recent_bot_logins),
        "actor_login": actor_login,
        "issue_creator": creator_login or "n/a",
        "creator_passed": creator_passed,
        "creator_error": creator_error,
        "target_assignee": assignment["target_assignee"],
        "issue_assignees": assignment["issue_assignees"],
        "assignment_passed": assignment["assignment_passed"],
        "assignment_error": assignment["assignment_error"],
        "assignment_event_seen": assignment["assignment_event_seen"],
        "assignment_event_count": assignment["assignment_event_count"],
        "assignment_event_error": assignment["assignment_event_error"],
        "assignment_event_actors": assignment.get("assignment_event_actors", []),
        "assignment_actor_passed": assignment.get("assignment_actor_passed", True),
        "assignment_actor_error": assignment.get("assignment_actor_error", ""),
        "assignment_fallback_mode": fallback_mode,
        "assignment_fallback_reason": assignment.get("assignment_fallback_reason", ""),
        "passed": (
            fallback_pass if fallback_mode else (strict_assignment_pass and bool(creator_passed))
        ),
    }


def _run_issue_handoff_existing(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    timeout: int,
    issue_assignee: str | None = None,
    issue_role: str = "software_engineer",
    post_trigger_comment: bool = False,
    actor_login: str = DEFAULT_ACTOR_LOGIN,
) -> dict:
    return _run_issue_handoff_presence(
        owner,
        repo,
        token,
        issue_number,
        timeout,
        issue_assignee,
        issue_role,
        post_trigger_comment,
        actor_login=actor_login,
    )


def _run_discussion_handoff(owner: str, repo: str, token: str, timeout: int) -> dict:
    _ensure_discussions_enabled(owner, repo, token)
    discussion_number, discussion_url, discussion_id, _ = _create_discussion(owner, repo, token)
    trigger_body = (
        "Triggering handoff via discussion comment.\n"
        f"{NATIVE_GITHUB_HANDOFF_MENTIONS}"
    )
    trigger_ts = _create_discussion_comment(
        owner, repo, token, discussion_id, trigger_body
    )

    def fetch() -> list[dict]:
        return _fetch_discussion_comments(owner, repo, discussion_number, token)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    return {
        "thread": discussion_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


def _run_discussion_handoff_existing(
    owner: str, repo: str, token: str, discussion_number: int, timeout: int
) -> dict:
    _ensure_discussions_enabled(owner, repo, token)
    _, discussion_url, discussion_id, _ = _resolve_discussion(
        owner, repo, token, discussion_number
    )
    trigger_body = (
        "Triggering handoff via discussion comment.\n"
        f"{NATIVE_GITHUB_HANDOFF_MENTIONS}"
    )
    trigger_ts = _create_discussion_comment(
        owner, repo, token, discussion_id, trigger_body
    )

    def fetch() -> list[dict]:
        return _fetch_discussion_comments(owner, repo, discussion_number, token)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    return {
        "thread": discussion_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


def _run_pr_comment_handoff(owner: str, repo: str, token: str, pr_number: int, timeout: int) -> dict:
    trigger_body = (
        "Triggering handoff via PR comment.\n"
        f"{NATIVE_GITHUB_HANDOFF_MENTIONS}"
    )
    trigger_ts = _create_pr_comment(owner, repo, token, pr_number, trigger_body)

    def fetch() -> list[dict]:
        return _fetch_issue_comments(owner, repo, pr_number, token, since=trigger_ts)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
    return {
        "thread": pr_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


def _run_issue_handoff_presence(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    timeout: int,
    issue_assignee: str | None = None,
    issue_role: str = "software_engineer",
    post_trigger_comment: bool = False,
    actor_login: str = "n/a",
) -> dict:
    issue_url = f"https://github.com/{owner}/{repo}/issues/{issue_number}"
    if post_trigger_comment:
        trigger_body = _build_issue_trigger_comment()
        trigger_ts = _create_issue_comment(owner, repo, token, issue_number, trigger_body)

        def fetch_recent() -> list[dict]:
            return _fetch_issue_comments(owner, repo, issue_number, token, since=trigger_ts)

        recent_bot_logins = _wait_for_bot_authors(fetch_recent, trigger_ts, 1, timeout)
        all_bot_logins = _collect_bot_logins(
            _fetch_issue_comments(owner, repo, issue_number, token, since=None)
        )
    else:
        assignment_checkpoint = datetime.now(timezone.utc)
        all_bot_logins = _collect_bot_logins(
            _fetch_issue_comments(owner, repo, issue_number, token, since=None)
        )
        recent_bot_logins = set()
    assignment_checkpoint = datetime.now(timezone.utc)
    expected_actor_login = (
        actor_login
        if (not post_trigger_comment and actor_login and _normalize_login(actor_login) != "n/a")
        else None
    )
    assignment = _evaluate_issue_assignment(
        owner,
        repo,
        token,
        issue_number,
        all_bot_logins,
        issue_assignee,
        issue_role,
        wait_seconds=min(timeout, 60),
        force_reassign=not post_trigger_comment,
        assignment_started_at=assignment_checkpoint,
        expected_actor_login=expected_actor_login,
    )

    if not post_trigger_comment:
        target_assignee = assignment.get("target_assignee", "n/a")
        normalized_target = _normalize_login(str(target_assignee))
        normalized_actor = _normalize_login(actor_login)
        if (
            assignment["assignment_passed"]
            and target_assignee != "n/a"
            and normalized_target == normalized_actor
            and not _is_conventional_bot_login(str(target_assignee))
        ):
            _create_issue_comment(owner, repo, token, issue_number, _build_issue_trigger_comment())

        if assignment["assignment_passed"] and target_assignee != "n/a":
            def fetch_after_assignment() -> list[dict]:
                return _fetch_issue_comments(
                    owner,
                    repo,
                    issue_number,
                    token,
                    since=assignment_checkpoint,
                )

            recent_bot_logins = _wait_for_assignee_activity(
                fetch_after_assignment,
                assignment_checkpoint,
                target_assignee,
                timeout,
            )
        elif bool(assignment.get("assignment_fallback_mode")):
            trigger_ts = _create_issue_comment(owner, repo, token, issue_number, _build_issue_trigger_comment())

            def fetch_after_trigger() -> list[dict]:
                return _fetch_issue_comments(owner, repo, issue_number, token, since=trigger_ts)

            recent_bot_logins = _wait_for_bot_authors(fetch_after_trigger, trigger_ts, 2, timeout)

    assignment_event_seen = bool(assignment.get("assignment_event_seen"))
    assignment_event_error = str(assignment.get("assignment_event_error") or "")
    assignment_event_count = int(assignment.get("assignment_event_count") or 0)
    assignment_event_actors = list(assignment.get("assignment_event_actors") or [])
    assignment_actor_passed = bool(assignment.get("assignment_actor_passed", True))
    assignment_actor_error = str(assignment.get("assignment_actor_error") or "")
    fallback_mode = bool(assignment.get("assignment_fallback_mode"))
    if fallback_mode:
        passed = bool(recent_bot_logins)
    else:
        passed = (
            bool(recent_bot_logins)
            and bool(assignment["assignment_passed"])
            and assignment_event_seen
            and assignment_actor_passed
        )
    return {
        "thread": issue_url,
        "bot_logins": sorted(all_bot_logins),
        "recent_bot_logins": sorted(recent_bot_logins),
        "actor_login": actor_login,
        "issue_creator": "n/a",
        "creator_passed": True,
        "creator_error": "",
        "target_assignee": assignment["target_assignee"],
        "issue_assignees": assignment["issue_assignees"],
        "assignment_passed": assignment["assignment_passed"],
        "assignment_error": assignment["assignment_error"],
        "assignment_event_seen": assignment_event_seen,
        "assignment_event_count": assignment_event_count,
        "assignment_event_error": assignment_event_error,
        "assignment_event_actors": assignment_event_actors,
        "assignment_actor_passed": assignment_actor_passed,
        "assignment_actor_error": assignment_actor_error,
        "assignment_fallback_mode": fallback_mode,
        "assignment_fallback_reason": str(assignment.get("assignment_fallback_reason") or ""),
        "passed": passed,
    }


def _run_pr_handoff_presence(
    owner: str, repo: str, token: str, pr_number: int, timeout: int
) -> dict:
    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
    trigger_body = (
        "Triggering PR handoff presence check.\n"
        f"{NATIVE_GITHUB_HANDOFF_MENTIONS}"
    )
    trigger_ts = _create_pr_comment(owner, repo, token, pr_number, trigger_body)

    def fetch_recent() -> list[dict]:
        return _fetch_issue_comments(owner, repo, pr_number, token, since=trigger_ts)

    recent_bot_logins = _wait_for_bot_authors(fetch_recent, trigger_ts, 1, timeout)
    all_bot_logins = _collect_bot_logins(
        _fetch_issue_comments(owner, repo, pr_number, token, since=None)
    )
    passed = bool(recent_bot_logins) and len(all_bot_logins) >= 2
    return {
        "thread": pr_url,
        "bot_logins": sorted(all_bot_logins),
        "recent_bot_logins": sorted(recent_bot_logins),
        "passed": passed,
    }


def _run_issue_pr_handoff(
    owner: str,
    repo: str,
    token: str,
    issue_number: int,
    pr_number: int,
    timeout: int,
    issue_assignee: str | None = None,
    issue_role: str = "software_engineer",
    post_issue_trigger_comment: bool = False,
    actor_login: str = DEFAULT_ACTOR_LOGIN,
) -> dict:
    if issue_number:
        issue_results = _run_issue_handoff_presence(
            owner,
            repo,
            token,
            issue_number,
            timeout,
            issue_assignee,
            issue_role,
            post_issue_trigger_comment,
            actor_login=actor_login,
        )
    else:
        created_issue_number, issue_url, _, creator_login = _create_issue(owner, repo, token)
        issue_results = _run_issue_handoff_presence(
            owner,
            repo,
            token,
            created_issue_number,
            timeout,
            issue_assignee,
            issue_role,
            False,
            actor_login=actor_login,
        )
        issue_results["thread"] = issue_url
        creator_passed = _is_expected_actor(actor_login, creator_login)
        issue_results["issue_creator"] = creator_login or "n/a"
        issue_results["creator_passed"] = creator_passed
        issue_results["creator_error"] = (
            ""
            if creator_passed
            else f"Issue creator mismatch: expected {actor_login}, got {creator_login or 'n/a'}"
        )
        issue_results["passed"] = bool(issue_results.get("passed")) and creator_passed

    pr_results = _run_pr_handoff_presence(owner, repo, token, pr_number, timeout)
    combined_logins = sorted(
        set(issue_results.get("bot_logins", [])) | set(pr_results.get("bot_logins", []))
    )
    passed = bool(issue_results.get("passed")) and bool(pr_results.get("passed"))

    return {
        "thread": f"{issue_results.get('thread')} | {pr_results.get('thread')}",
        "bot_logins": combined_logins,
        "actor_login": issue_results.get("actor_login", actor_login),
        "issue_creator": issue_results.get("issue_creator", "n/a"),
        "creator_passed": issue_results.get("creator_passed", True),
        "creator_error": issue_results.get("creator_error", ""),
        "target_assignee": issue_results.get("target_assignee", "n/a"),
        "issue_assignees": issue_results.get("issue_assignees", []),
        "assignment_passed": issue_results.get("assignment_passed", False),
        "assignment_error": issue_results.get("assignment_error", ""),
        "assignment_event_seen": issue_results.get("assignment_event_seen", False),
        "assignment_event_count": issue_results.get("assignment_event_count", 0),
        "assignment_event_error": issue_results.get("assignment_event_error", ""),
        "assignment_event_actors": issue_results.get("assignment_event_actors", []),
        "assignment_actor_passed": issue_results.get("assignment_actor_passed", True),
        "assignment_actor_error": issue_results.get("assignment_actor_error", ""),
        "passed": passed,
        "threads": {
            "issue": issue_results,
            "pr": pr_results,
        },
    }


def _collect_thread_links(results: dict) -> list[str]:
    """Extract unique GitHub thread links from scenario results."""
    links: list[str] = []
    seen: set[str] = set()

    def _add(link: str) -> None:
        clean = link.strip()
        if clean and clean.startswith("https://github.com/") and clean not in seen:
            seen.add(clean)
            links.append(clean)

    thread = results.get("thread")
    if isinstance(thread, str):
        for candidate in thread.split("|"):
            _add(candidate)

    thread_results = results.get("threads")
    if isinstance(thread_results, dict):
        for value in thread_results.values():
            if isinstance(value, dict):
                thread_link = value.get("thread")
                if isinstance(thread_link, str):
                    _add(thread_link)

    return links


def _assignment_requirement_passed(result: dict) -> bool:
    """Return True when assignment requirement is satisfied directly or via fallback."""
    return bool(result.get("assignment_passed") or result.get("assignment_fallback_mode"))


def _write_report(scenario: str, results: dict) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"results/eval_reports/eval_github_{scenario}_{timestamp}.md"

    lines = [
        f"# GitHub Evaluation Report: {SCENARIOS[scenario]['name']}",
        "",
        f"**Scenario:** `{scenario}`",
        f"**Thread:** {results.get('thread', 'n/a')}",
        f"**Passed:** {'✅' if results.get('passed') else '❌'}",
        f"**Bot authors:** {', '.join(results.get('bot_logins', [])) or 'n/a'}",
    ]
    if "assignment_passed" in results:
        assignment_effective = _assignment_requirement_passed(results)
        assignment_suffix = (
            " (fallback satisfied)"
            if (not results.get("assignment_passed") and results.get("assignment_fallback_mode"))
            else ""
        )
        lines.append(
            f"**Issue assigned:** {'✅' if assignment_effective else '❌'}{assignment_suffix}"
        )
        lines.append(f"**Target assignee:** {results.get('target_assignee', 'n/a')}")
        lines.append(
            f"**Current assignees:** {', '.join(results.get('issue_assignees', [])) or 'n/a'}"
        )
        lines.append(
            "**Assignment event observed:** "
            f"{'✅' if results.get('assignment_event_seen') else '❌'}"
        )
        lines.append(
            f"**Assignment event count:** {results.get('assignment_event_count', 0)}"
        )
        lines.append(
            f"**Assignment event actors:** {', '.join(results.get('assignment_event_actors', [])) or 'n/a'}"
        )
        lines.append(
            "**Assignment actor check:** "
            f"{'✅' if results.get('assignment_actor_passed', True) else '❌'}"
        )
        lines.append(
            "**Recent bot authors after assignment/trigger:** "
            f"{', '.join(results.get('recent_bot_logins', [])) or 'n/a'}"
        )
        lines.append(
            "**Assignment fallback mode:** "
            f"{'✅' if results.get('assignment_fallback_mode') else '❌'}"
        )
        if results.get("assignment_fallback_reason"):
            lines.append(f"**Assignment fallback reason:** {results.get('assignment_fallback_reason')}")
    if "creator_passed" in results:
        lines.append(
            f"**Issue creator check:** {'✅' if results.get('creator_passed') else '❌'}"
        )
        lines.append(f"**Expected actor:** {results.get('actor_login', 'n/a')}")
        lines.append(f"**Issue creator:** {results.get('issue_creator', 'n/a')}")
    if results.get("assignment_error"):
        lines.append(f"**Assignment error:** {results.get('assignment_error')}")
    if results.get("assignment_event_error"):
        lines.append(f"**Assignment event error:** {results.get('assignment_event_error')}")
    if results.get("assignment_actor_error"):
        lines.append(f"**Assignment actor error:** {results.get('assignment_actor_error')}")
    if results.get("creator_error"):
        lines.append(f"**Creator error:** {results.get('creator_error')}")
    lines.append("")
    links = _collect_thread_links(results)
    lines.extend(
        [
            "## Conversation Links",
            "",
        ]
    )
    if links:
        for link in links:
            lines.append(f"- GitHub: {link}")
    else:
        lines.append("- GitHub: none")
    lines.append("")

    thread_results = results.get("threads")
    if isinstance(thread_results, dict):
        lines.extend(
            [
                "## Thread Details",
                "",
            ]
        )
        for thread_name in ("issue", "pr"):
            thread_result = thread_results.get(thread_name) or {}
            status = "✅" if thread_result.get("passed") else "❌"
            lines.extend(
                [
                    f"### {thread_name.upper()}",
                    "",
                    f"- Passed: {status}",
                    f"- Thread: {thread_result.get('thread', 'n/a')}",
                    (
                        f"- Bot authors: {', '.join(thread_result.get('bot_logins', [])) or 'n/a'}"
                    ),
                    (
                        "- Recent bot authors after assignment/trigger: "
                        f"{', '.join(thread_result.get('recent_bot_logins', [])) or 'n/a'}"
                    ),
                ]
            )
            if "assignment_passed" in thread_result:
                thread_assignment_effective = _assignment_requirement_passed(thread_result)
                thread_assignment_suffix = (
                    " (fallback satisfied)"
                    if (
                        not thread_result.get("assignment_passed")
                        and thread_result.get("assignment_fallback_mode")
                    )
                    else ""
                )
                lines.append(
                    f"- Issue assigned: {'✅' if thread_assignment_effective else '❌'}"
                    f"{thread_assignment_suffix}"
                )
                lines.append(f"- Target assignee: {thread_result.get('target_assignee', 'n/a')}")
                lines.append(
                    "- Current assignees: "
                    f"{', '.join(thread_result.get('issue_assignees', [])) or 'n/a'}"
                )
                lines.append(
                    "- Assignment event observed: "
                    f"{'✅' if thread_result.get('assignment_event_seen') else '❌'}"
                )
                lines.append(
                    f"- Assignment event count: {thread_result.get('assignment_event_count', 0)}"
                )
                lines.append(
                    "- Assignment event actors: "
                    f"{', '.join(thread_result.get('assignment_event_actors', [])) or 'n/a'}"
                )
                lines.append(
                    "- Assignment actor check: "
                    f"{'✅' if thread_result.get('assignment_actor_passed', True) else '❌'}"
                )
                lines.append(
                    "- Assignment fallback mode: "
                    f"{'✅' if thread_result.get('assignment_fallback_mode') else '❌'}"
                )
                if thread_result.get("assignment_fallback_reason"):
                    lines.append(
                        f"- Assignment fallback reason: {thread_result.get('assignment_fallback_reason')}"
                    )
            if "creator_passed" in thread_result:
                lines.append(
                    f"- Issue creator check: {'✅' if thread_result.get('creator_passed') else '❌'}"
                )
                lines.append(f"- Expected actor: {thread_result.get('actor_login', 'n/a')}")
                lines.append(f"- Issue creator: {thread_result.get('issue_creator', 'n/a')}")
            if thread_result.get("assignment_error"):
                lines.append(f"- Assignment error: {thread_result.get('assignment_error')}")
            if thread_result.get("assignment_event_error"):
                lines.append(f"- Assignment event error: {thread_result.get('assignment_event_error')}")
            if thread_result.get("assignment_actor_error"):
                lines.append(f"- Assignment actor error: {thread_result.get('assignment_actor_error')}")
            if thread_result.get("creator_error"):
                lines.append(f"- Creator error: {thread_result.get('creator_error')}")
            lines.append("")

    os.makedirs("results/eval_reports", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    return filename


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub webhook E2E eval")
    parser.add_argument("--scenario", choices=SCENARIOS.keys(), default="github_issue_handoff")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", type=int, default=DEFAULT_PR)
    parser.add_argument("--issue-assignee", default=DEFAULT_ISSUE_ASSIGNEE)
    parser.add_argument("--issue-role", choices=sorted(ROLE_DEFAULT_ASSIGNEES.keys()), default=DEFAULT_ISSUE_ROLE)
    parser.add_argument("--actor-login", default=DEFAULT_ACTOR_LOGIN)
    parser.add_argument(
        "--post-trigger-comment",
        action="store_true",
        help="Post trigger mentions on existing issue threads (default: disabled for existing issues).",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--issue", type=int, default=0, help="Existing issue number to use")
    parser.add_argument(
        "--discussion",
        type=int,
        default=0,
        help="Existing discussion number to use",
    )

    args = parser.parse_args()

    token = _require_token(args.actor_login)
    _validate_actor_login(token, args.actor_login)
    owner, repo = _split_repo(args.repo)
    resolved_issue_assignee = _resolve_issue_assignee(
        owner,
        repo,
        token,
        preferred_assignee=args.issue_assignee,
        issue_role=args.issue_role,
    )
    issue_scenarios = {"github_issue_handoff", "github_issue_pr_handoff_github"}
    if args.scenario in issue_scenarios:
        if not resolved_issue_assignee:
            raise SystemExit(
                f"No assignee resolved for role '{args.issue_role}'. Provide --issue-assignee."
            )
        if not _assignee_matches_issue_role(resolved_issue_assignee, args.issue_role):
            expected = sorted(_allowed_assignees_for_role(args.issue_role))
            raise SystemExit(
                "Issue assignee does not match required role mapping. "
                f"role={args.issue_role}, assignee={resolved_issue_assignee}, "
                f"expected one of: {', '.join(expected) or 'n/a'}"
            )
        allowed_handles = _configured_bot_handles()
        allowed_handles.add(_normalize_login(resolved_issue_assignee))
        role_default = _default_assignee_for_role(args.issue_role)
        if role_default:
            allowed_handles.add(_normalize_login(role_default))
        if not _is_bot_login(resolved_issue_assignee, extra_allowed=allowed_handles):
            raise SystemExit(
                "Issue assignee must be a bot app handle (pattern '*-bot-*' or '[bot]' "
                "or listed in explicit bot-handle config). "
                f"Got: {resolved_issue_assignee}"
            )

    scenarios_to_run = [args.scenario]
    if args.scenario == "github_threads_all":
        scenarios_to_run = [
            "github_issue_handoff",
            "github_discussion_handoff",
            "github_pr_comment_handoff",
        ]

    overall_passed = True
    for scenario in scenarios_to_run:
        if scenario == "github_issue_handoff":
            if args.issue:
                results = _run_issue_handoff_existing(
                    owner,
                    repo,
                    token,
                    args.issue,
                    args.timeout,
                    resolved_issue_assignee,
                    args.issue_role,
                    args.post_trigger_comment,
                    args.actor_login,
                )
            else:
                results = _run_issue_handoff(
                    owner,
                    repo,
                    token,
                    args.timeout,
                    resolved_issue_assignee,
                    args.issue_role,
                    args.actor_login,
                )
        elif scenario == "github_issue_pr_handoff_github":
            results = _run_issue_pr_handoff(
                owner,
                repo,
                token,
                args.issue,
                args.pr,
                args.timeout,
                resolved_issue_assignee,
                args.issue_role,
                args.post_trigger_comment,
                args.actor_login,
            )
        elif scenario == "github_discussion_handoff":
            if args.discussion:
                results = _run_discussion_handoff_existing(
                    owner, repo, token, args.discussion, args.timeout
                )
            else:
                results = _run_discussion_handoff(owner, repo, token, args.timeout)
        elif scenario == "github_pr_comment_handoff":
            results = _run_pr_comment_handoff(owner, repo, token, args.pr, args.timeout)
        else:
            raise ValueError(f"Unknown scenario: {scenario}")

        report_path = _write_report(scenario, results)
        status = "PASSED" if results.get("passed") else "FAILED"
        print(
            f"Scenario {scenario}: {status} - thread {results.get('thread')} | "
            f"bots: {', '.join(results.get('bot_logins', [])) or 'n/a'}"
            + (
                " | "
                f"assigned: {results.get('target_assignee', 'n/a')} "
                f"({'ok' if results.get('assignment_passed') else ('ok-via-fallback' if results.get('assignment_fallback_mode') else 'missing')})"
                if "assignment_passed" in results
                else ""
            )
        )
        print(f"Report saved: {report_path}")
        overall_passed = overall_passed and bool(results.get("passed"))

    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
