#!/usr/bin/env python3
"""
End-to-end GitHub webhook evaluation.

Scenarios create GitHub issues/discussions/PR comments containing /RoleName
mentions and then verify that multiple agent bots respond in the thread.

Usage:
  uv run python scripts/eval_github_e2e.py --scenario github_issue_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_discussion_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_pr_comment_handoff
  uv run python scripts/eval_github_e2e.py --scenario github_threads_all
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable

import httpx

DEFAULT_REPO = os.environ.get("GITHUB_TEST_REPO", "VibeTechnologies/vibeteam-eval-hello-world")
DEFAULT_PR = int(os.environ.get("GITHUB_TEST_PR", "1"))

SCENARIOS = {
    "github_issue_handoff": {
        "name": "GitHub Issue Handoff (Webhook)",
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


def _require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")
    return token


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


def _graphql_request(token: str, query: str, variables: dict[str, str]) -> dict:
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
            if _parse_ts(c.get("created_at", "1970-01-01T00:00:00Z")) >= since
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
    return str(repository["id"]), str(categories[0]["id"])


def _create_issue(owner: str, repo: str, token: str) -> tuple[int, str, datetime]:
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
    return int(data["number"]), data["html_url"], _parse_ts(data["created_at"])


def _create_issue_comment(
    owner: str, repo: str, token: str, number: int, body: str
) -> datetime:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"body": body})
        response.raise_for_status()
        data = response.json()
    return _parse_ts(data["created_at"])


def _fetch_issue_comments(owner: str, repo: str, number: int, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token), params={"per_page": 100})
        response.raise_for_status()
        return response.json()


def _create_discussion(owner: str, repo: str, token: str) -> tuple[int, str, datetime]:
    repo_id, category_id = _get_repo_and_category_id(owner, repo, token)
    title = f"Eval GitHub discussion handoff {uuid.uuid4().hex[:8]}"
    body = "Eval discussion to test agent handoff via GitHub discussion comments."
    mutation = """
    mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
      createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
        discussion { number url createdAt }
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
    return int(discussion["number"]), discussion["url"], _parse_ts(discussion["createdAt"])


def _create_discussion_comment(
    owner: str, repo: str, token: str, number: int, body: str
) -> datetime:
    url = f"https://api.github.com/repos/{owner}/{repo}/discussions/{number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"body": body})
        response.raise_for_status()
        data = response.json()
    return _parse_ts(data["created_at"])


def _fetch_discussion_comments(owner: str, repo: str, number: int, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/discussions/{number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(url, headers=_headers(token), params={"per_page": 100})
        response.raise_for_status()
        return response.json()


def _create_pr_comment(owner: str, repo: str, token: str, pr_number: int, body: str) -> datetime:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, headers=_headers(token), json={"body": body})
        response.raise_for_status()
        data = response.json()
    return _parse_ts(data["created_at"])


def _run_issue_handoff(owner: str, repo: str, token: str, timeout: int) -> dict:
    issue_number, issue_url, _ = _create_issue(owner, repo, token)
    trigger_body = "Triggering handoff via issue comment.\n/SoftwareEngineer /SupportEngineer"
    trigger_ts = _create_issue_comment(owner, repo, token, issue_number, trigger_body)

    def fetch() -> list[dict]:
        return _fetch_issue_comments(owner, repo, issue_number, token)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    return {
        "thread": issue_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


def _run_issue_handoff_existing(
    owner: str, repo: str, token: str, issue_number: int, timeout: int
) -> dict:
    issue_url = f"https://github.com/{owner}/{repo}/issues/{issue_number}"
    trigger_body = "Triggering handoff via issue comment.\n/SoftwareEngineer /SupportEngineer"
    trigger_ts = _create_issue_comment(owner, repo, token, issue_number, trigger_body)

    def fetch() -> list[dict]:
        return _fetch_issue_comments(owner, repo, issue_number, token)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    return {
        "thread": issue_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


def _run_discussion_handoff(owner: str, repo: str, token: str, timeout: int) -> dict:
    _ensure_discussions_enabled(owner, repo, token)
    discussion_number, discussion_url, _ = _create_discussion(owner, repo, token)
    trigger_body = "Triggering handoff via discussion comment.\n/SoftwareEngineer /SupportEngineer"
    trigger_ts = _create_discussion_comment(
        owner, repo, token, discussion_number, trigger_body
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
    trigger_body = "Triggering handoff via PR comment.\n/SoftwareEngineer /SupportEngineer"
    trigger_ts = _create_pr_comment(owner, repo, token, pr_number, trigger_body)

    def fetch() -> list[dict]:
        return _fetch_issue_comments(owner, repo, pr_number, token)

    bot_logins = _wait_for_bot_authors(fetch, trigger_ts, 2, timeout)
    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
    return {
        "thread": pr_url,
        "bot_logins": sorted(bot_logins),
        "passed": len(bot_logins) >= 2,
    }


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
        "",
    ]

    os.makedirs("results/eval_reports", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    return filename


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub webhook E2E eval")
    parser.add_argument("--scenario", choices=SCENARIOS.keys(), default="github_issue_handoff")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", type=int, default=DEFAULT_PR)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--issue", type=int, default=0, help="Existing issue number to use")

    args = parser.parse_args()

    token = _require_token()
    owner, repo = _split_repo(args.repo)

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
                    owner, repo, token, args.issue, args.timeout
                )
            else:
                results = _run_issue_handoff(owner, repo, token, args.timeout)
        elif scenario == "github_discussion_handoff":
            results = _run_discussion_handoff(owner, repo, token, args.timeout)
        elif scenario == "github_pr_comment_handoff":
            results = _run_pr_comment_handoff(owner, repo, token, args.pr, args.timeout)
        else:
            raise ValueError(f"Unknown scenario: {scenario}")

        report_path = _write_report(scenario, results)
        status = "PASSED" if results.get("passed") else "FAILED"
        print(
            f"Scenario {scenario}: {status} - thread {results.get('thread')} | bots: {', '.join(results.get('bot_logins', [])) or 'n/a'}"
        )
        print(f"Report saved: {report_path}")
        overall_passed = overall_passed and bool(results.get("passed"))

    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
