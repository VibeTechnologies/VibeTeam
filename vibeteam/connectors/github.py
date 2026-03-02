"""
GitHub Connector - API integration for GitHub issues and pull requests.

Provides functionality to:
- Get and update issues
- Create and manage pull requests
- Review code and add comments
- Search issues and PRs
- Manage labels

API Docs: https://docs.github.com/en/rest
"""

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"

# Default repository
DEFAULT_OWNER = "VibeTechnologies"
DEFAULT_REPO = "VibeWebAgent"

# Customer Requests tracking issue number
CUSTOMER_REQUESTS_ISSUE = 322


@dataclass
class GitHubIssue:
    """Represents a GitHub issue."""

    number: int
    title: str
    body: str
    state: str
    labels: list[str]
    created_at: str
    updated_at: str
    html_url: str
    user: str

    @property
    def age_days(self) -> float:
        """Days since created."""
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        now = datetime.now(created.tzinfo)
        return (now - created).total_seconds() / 86400


@dataclass
class GitHubPR:
    """Represents a GitHub pull request."""

    number: int
    title: str
    body: str
    state: str
    draft: bool
    head_ref: str
    base_ref: str
    html_url: str
    user: str
    created_at: str
    updated_at: str
    mergeable: bool | None
    additions: int
    deletions: int
    changed_files: int


@dataclass
class PRReview:
    """Represents a PR review."""

    id: int
    user: str
    state: str  # APPROVED, CHANGES_REQUESTED, COMMENTED, PENDING
    body: str
    submitted_at: str


class GitHubConnector:
    """
    GitHub API connector for issues and pull requests.

    Usage:
        connector = GitHubConnector()

        # Get issue
        issue = connector.get_issue(322)

        # Update issue body
        connector.update_issue(322, body="New body content")

        # Create PR
        pr = connector.create_pr(
            title="feat: add feature",
            body="Description",
            head="feature-branch",
            base="master"
        )

        # Review PR
        connector.create_review(
            pr_number=123,
            body="LGTM",
            event="APPROVE"
        )
    """

    def __init__(
        self,
        token: str | None = None,
        owner: str = DEFAULT_OWNER,
        repo: str = DEFAULT_REPO,
        app_id: str | None = None,
        private_key: str | None = None,
        installation_id: str | None = None,
        agent_role: str | None = None,
    ):
        """
        Initialize GitHub connector.

        Supports both Personal Access Token (PAT) and GitHub App authentication.
        GitHub App authentication is preferred for production use due to:
        - Short-lived tokens (1 hour)
        - Higher rate limits
        - Fine-grained permissions

        Args:
            token: GitHub PAT (or from GITHUB_TOKEN env). Used if App credentials not provided.
            owner: Repository owner
            repo: Repository name
            app_id: GitHub App ID (or from GITHUB_APP_ID env)
            private_key: GitHub App private key in PEM format (or from GITHUB_APP_PRIVATE_KEY env)
            installation_id: GitHub App installation ID (or from GITHUB_APP_INSTALLATION_ID env)
        """
        self.owner = owner
        self.repo = repo

        # GitHub App credentials (preferred)
        role = agent_role or os.environ.get("VIBETEAM_AGENT_ROLE")
        role_app_id = None
        role_private_key = None
        role_installation_id = None
        if role:
            try:
                from vibeteam.utils.github_app import get_role_app_credentials

                role_app_id, role_private_key, role_installation_id = get_role_app_credentials(role)
            except Exception:
                role_app_id = role_private_key = role_installation_id = None

        self.app_id = app_id or role_app_id or os.environ.get("GITHUB_APP_ID")
        self.private_key = (
            private_key
            or role_private_key
            or os.environ.get("GITHUB_APP_PRIVATE_KEY")
        )
        self.installation_id = (
            installation_id
            or role_installation_id
            or os.environ.get("GITHUB_APP_INSTALLATION_ID")
        )

        # Token management
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self._token_expiry: float = 0  # Unix timestamp when token expires
        self._use_app_auth = bool(self.app_id and self.private_key and self.installation_id)

        # Validate we have at least one auth method
        if not self._use_app_auth and not self.token:
            raise ValueError(
                "GitHub authentication required. Either provide:\n"
                "  1. GitHub App credentials (app_id, private_key, installation_id), or\n"
                "  2. Personal Access Token (token or GITHUB_TOKEN env var)"
            )

    def _ensure_token(self) -> str:
        """
        Ensure we have a valid token, generating a new one if needed.

        Returns:
            Valid GitHub token
        """
        if self._use_app_auth:
            # Check if token is expired or will expire soon (5 minute buffer)
            now = time.time()
            if not self.token or now >= (self._token_expiry - 300):
                self._refresh_app_token()
            return self.token or ""

        # PAT doesn't expire, just return it
        return self.token or ""

    def _refresh_app_token(self) -> None:
        """Generate a new installation token from GitHub App credentials."""
        try:
            from vibeteam.utils.github_app import get_installation_token

            self.token = get_installation_token(
                str(self.app_id),
                str(self.private_key),
                str(self.installation_id),
            )
            # Installation tokens are valid for 1 hour
            self._token_expiry = time.time() + 3600
        except Exception as e:
            raise RuntimeError(f"Failed to refresh GitHub App token: {e}") from e

    def _headers(self) -> dict:
        """Get request headers with auth."""
        token = self._ensure_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        """Make GET request to GitHub API."""
        url = f"{GITHUB_API_BASE}{endpoint}"
        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to GitHub API."""
        url = f"{GITHUB_API_BASE}{endpoint}"
        response = requests.post(url, headers=self._headers(), json=data)
        response.raise_for_status()
        return response.json()

    def _patch(self, endpoint: str, data: dict) -> dict:
        """Make PATCH request to GitHub API."""
        url = f"{GITHUB_API_BASE}{endpoint}"
        response = requests.patch(url, headers=self._headers(), json=data)
        response.raise_for_status()
        return response.json()

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Make a GraphQL request to GitHub."""
        response = requests.post(
            f"{GITHUB_API_BASE}/graphql",
            headers=self._headers(),
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
        return payload.get("data", {})

    # =====================
    # Issue Operations
    # =====================

    def get_issue(self, issue_number: int) -> GitHubIssue:
        """Get a single issue by number."""
        endpoint = f"/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        data = self._get(endpoint)
        return self._parse_issue(data)

    def _parse_issue(self, data: dict) -> GitHubIssue:
        """Parse API response into GitHubIssue."""
        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            state=data["state"],
            labels=[lbl["name"] for lbl in data.get("labels", [])],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            html_url=data["html_url"],
            user=data["user"]["login"],
        )

    def update_issue(
        self,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> GitHubIssue:
        """
        Update an issue.

        Args:
            issue_number: Issue number
            title: New title (optional)
            body: New body (optional)
            state: "open" or "closed" (optional)
            labels: New labels (optional)
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if body is not None:
            data["body"] = body
        if state is not None:
            data["state"] = state
        if labels is not None:
            data["labels"] = labels

        result = self._patch(endpoint, data)
        return self._parse_issue(result)

    def add_issue_comment(self, issue_number: int, body: str) -> dict:
        """Add a comment to an issue."""
        endpoint = f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments"
        return self._post(endpoint, {"body": body})

    def add_discussion_comment(self, discussion_number: int, body: str) -> dict:
        """Add a comment to a discussion."""
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            discussion(number: $number) { id }
          }
        }
        """
        data = self._graphql(
            query,
            {"owner": self.owner, "repo": self.repo, "number": discussion_number},
        )
        discussion = (data.get("repository") or {}).get("discussion") or {}
        discussion_id = discussion.get("id")
        if not discussion_id:
            raise RuntimeError("Discussion not found or missing ID")

        mutation = """
        mutation($discussionId: ID!, $body: String!) {
          addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
            comment { id body createdAt }
          }
        }
        """
        data = self._graphql(mutation, {"discussionId": discussion_id, "body": body})
        comment = (data.get("addDiscussionComment") or {}).get("comment") or {}
        if not comment:
            raise RuntimeError("Failed to create discussion comment")
        return comment

    def search_issues(
        self,
        query: str,
        state: str = "open",
        labels: list[str] | None = None,
        limit: int = 30,
        sort: str = "created",
        order: str = "desc",
    ) -> list[GitHubIssue]:
        """
        Search issues in the repository.

        Args:
            query: Search query (in title/body)
            state: "open", "closed", or "all"
            labels: Filter by labels
            limit: Max results
            sort: Sort by "created", "updated", or "comments" (default: created)
            order: Sort order "asc" or "desc" (default: desc)
        """
        q = f"{query} repo:{self.owner}/{self.repo} is:issue state:{state}"
        if labels:
            q += " " + " ".join(f"label:{lbl}" for lbl in labels)

        endpoint = "/search/issues"
        params = {"q": q, "per_page": limit, "sort": sort, "order": order}
        data = self._get(endpoint, params)
        return [self._parse_issue(item) for item in data.get("items", [])]

    # =====================
    # Customer Requests Table Operations
    # =====================

    def get_customer_requests_table(self) -> tuple[str, list[dict]]:
        """
        Get the Customer Requests table from the tracking issue.

        Returns:
            Tuple of (full issue body, list of request dicts)
        """
        issue = self.get_issue(CUSTOMER_REQUESTS_ISSUE)
        body = issue.body

        # Parse table rows
        requests = []
        lines = body.split("\n")
        in_table = False

        for line in lines:
            line = line.strip()
            if line.startswith("| Date"):
                in_table = True
                continue
            if line.startswith("|---"):
                continue
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 6 and parts[0]:  # Skip empty rows
                    requests.append(
                        {
                            "date": parts[0],
                            "source": parts[1],
                            "request": parts[2],
                            "priority": parts[3],
                            "status": parts[4],
                            "analysis": parts[5] if len(parts) > 5 else "",
                        }
                    )
            elif in_table and not line.startswith("|"):
                break  # End of table

        return body, requests

    def add_customer_request(
        self,
        request: str,
        source: str,
        priority: str,
        status: str = "New",
        analysis: str = "",
    ) -> GitHubIssue:
        """
        Add a new row to the Customer Requests table.

        Args:
            request: Short description of the request
            source: Where it came from (docs-chat, email, etc.)
            priority: P0, P1, P2, or P3
            status: New, Analyzing, Approved, Rejected, Implemented
            analysis: PM analysis notes
        """
        issue = self.get_issue(CUSTOMER_REQUESTS_ISSUE)
        body = issue.body

        # Find the table and add a new row
        date = datetime.now().strftime("%Y-%m-%d")
        new_row = f"| {date} | {source} | {request} | {priority} | {status} | {analysis} |"

        # Insert after header row
        lines = body.split("\n")
        new_lines = []
        inserted = False

        for _idx, line in enumerate(lines):
            new_lines.append(line)
            # Insert after the |---| separator line
            if line.strip().startswith("|---") and not inserted:
                new_lines.append(new_row)
                inserted = True

        if not inserted:
            # Fallback: append to end of table section
            new_lines.append(new_row)

        new_body = "\n".join(new_lines)
        return self.update_issue(CUSTOMER_REQUESTS_ISSUE, body=new_body)

    def update_customer_request(
        self,
        request_text: str,
        priority: str | None = None,
        status: str | None = None,
        analysis: str | None = None,
    ) -> GitHubIssue:
        """
        Update an existing request in the Customer Requests table.

        Args:
            request_text: Text to match (partial match)
            priority: New priority (optional)
            status: New status (optional)
            analysis: New analysis (optional)
        """
        issue = self.get_issue(CUSTOMER_REQUESTS_ISSUE)
        body = issue.body
        lines = body.split("\n")
        new_lines = []

        for line in lines:
            if request_text.lower() in line.lower() and line.strip().startswith("|"):
                parts = [p.strip() for p in line.split("|")]
                # parts[0] is empty, parts[1:7] are the columns
                if len(parts) >= 7:
                    if priority:
                        parts[4] = priority
                    if status:
                        parts[5] = status
                    if analysis:
                        parts[6] = analysis
                    line = "| " + " | ".join(parts[1:7]) + " |"
            new_lines.append(line)

        new_body = "\n".join(new_lines)
        return self.update_issue(CUSTOMER_REQUESTS_ISSUE, body=new_body)

    # =====================
    # Pull Request Operations
    # =====================

    def get_pr(self, pr_number: int) -> GitHubPR:
        """Get a single pull request by number."""
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
        data = self._get(endpoint)
        return self._parse_pr(data)

    def _parse_pr(self, data: dict) -> GitHubPR:
        """Parse API response into GitHubPR."""
        return GitHubPR(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            state=data["state"],
            draft=data.get("draft", False),
            head_ref=data["head"]["ref"],
            base_ref=data["base"]["ref"],
            html_url=data["html_url"],
            user=data["user"]["login"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            mergeable=data.get("mergeable"),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
        )

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "master",
        draft: bool = False,
    ) -> GitHubPR:
        """
        Create a new pull request.

        Args:
            title: PR title
            body: PR description
            head: Head branch name
            base: Base branch name (default: master)
            draft: Create as draft PR
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        result = self._post(endpoint, data)
        return self._parse_pr(result)

    def list_prs(
        self,
        state: str = "open",
        base: str | None = None,
        limit: int = 30,
    ) -> list[GitHubPR]:
        """
        List pull requests.

        Args:
            state: "open", "closed", or "all"
            base: Filter by base branch
            limit: Max results
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls"
        params: dict[str, Any] = {"state": state, "per_page": limit}
        if base:
            params["base"] = base

        data = self._get(endpoint, params)
        return [self._parse_pr(pr) for pr in data]

    def get_pr_diff(self, pr_number: int) -> str:
        """Get the diff for a pull request."""
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
        headers = self._headers()
        headers["Accept"] = "application/vnd.github.diff"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def get_pr_files(self, pr_number: int) -> list[dict]:
        """Get list of files changed in a PR."""
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/files"
        return self._get(endpoint)

    # =====================
    # Code Review Operations
    # =====================

    def create_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict] | None = None,
    ) -> dict:
        """
        Create a review on a pull request.

        Args:
            pr_number: PR number
            body: Review summary
            event: APPROVE, REQUEST_CHANGES, or COMMENT
            comments: List of inline comments [{"path": "file.py", "line": 10, "body": "..."}]
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/reviews"
        data: dict[str, Any] = {
            "body": body,
            "event": event,
        }
        if comments:
            data["comments"] = comments

        return self._post(endpoint, data)

    def add_pr_comment(self, pr_number: int, body: str) -> dict:
        """Add a general comment to a PR."""
        # PR comments use the issues endpoint
        endpoint = f"/repos/{self.owner}/{self.repo}/issues/{pr_number}/comments"
        return self._post(endpoint, {"body": body})

    def add_line_comment(
        self,
        pr_number: int,
        body: str,
        path: str,
        line: int,
        commit_id: str,
    ) -> dict:
        """
        Add an inline comment to a specific line in a PR.

        Args:
            pr_number: PR number
            body: Comment text
            path: File path relative to repo root
            line: Line number in the diff
            commit_id: The SHA of the commit to comment on
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/comments"
        data = {
            "body": body,
            "path": path,
            "line": line,
            "commit_id": commit_id,
        }
        return self._post(endpoint, data)

    def get_pr_reviews(self, pr_number: int) -> list[PRReview]:
        """Get all reviews on a PR."""
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/reviews"
        data = self._get(endpoint)
        return [
            PRReview(
                id=r["id"],
                user=r["user"]["login"],
                state=r["state"],
                body=r.get("body") or "",
                submitted_at=r.get("submitted_at") or "",
            )
            for r in data
        ]

    def merge_pr(
        self,
        pr_number: int,
        commit_title: str | None = None,
        merge_method: str = "squash",
    ) -> dict:
        """
        Merge a pull request.

        Args:
            pr_number: PR number
            commit_title: Custom commit title (optional)
            merge_method: "merge", "squash", or "rebase"
        """
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{pr_number}/merge"
        data: dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            data["commit_title"] = commit_title

        url = f"{GITHUB_API_BASE}{endpoint}"
        response = requests.put(url, headers=self._headers(), json=data)
        response.raise_for_status()
        return response.json()

    # =====================
    # Git Operations (via CLI)
    # =====================

    @staticmethod
    def git_create_branch(branch_name: str, base: str = "origin/master") -> bool:
        """Create and checkout a new branch."""
        try:
            subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(
                ["git", "switch", "-c", branch_name, base],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def git_push(branch_name: str, set_upstream: bool = True) -> bool:
        """Push branch to origin."""
        try:
            cmd = ["git", "push"]
            if set_upstream:
                cmd.extend(["-u", "origin", branch_name])
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def git_commit(message: str, files: list[str] | None = None) -> bool:
        """Stage files and commit."""
        try:
            if files:
                subprocess.run(["git", "add"] + files, check=True, capture_output=True)
            else:
                subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False


def cli_list_prs() -> None:
    """CLI helper to list open PRs."""
    import argparse

    parser = argparse.ArgumentParser(description="List GitHub PRs")
    parser.add_argument("--state", default="open", help="PR state (default: open)")
    parser.add_argument("--limit", type=int, default=10, help="Max PRs (default: 10)")

    args = parser.parse_args()

    try:
        connector = GitHubConnector()
    except ValueError as e:
        print(f"Error: {e}")
        print("Set GITHUB_TOKEN environment variable.")
        return

    prs = connector.list_prs(state=args.state, limit=args.limit)

    if not prs:
        print("No pull requests found.")
        return

    print(f"\nFound {len(prs)} pull requests:\n")
    for pr in prs:
        status = "[DRAFT]" if pr.draft else ""
        print(f"#{pr.number} {status} {pr.title}")
        print(f"  {pr.head_ref} -> {pr.base_ref}")
        print(f"  +{pr.additions} -{pr.deletions} ({pr.changed_files} files)")
        print(f"  {pr.html_url}")
        print()


if __name__ == "__main__":
    cli_list_prs()
