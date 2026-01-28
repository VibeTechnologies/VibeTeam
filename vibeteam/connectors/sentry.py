"""
Sentry Connector - API integration for Sentry error tracking.

Provides functionality to:
- Fetch unresolved issues from Sentry projects
- Get issue details and events
- Add comments to issues
- Resolve/ignore issues
- Link issues to GitHub

Sentry Organization: vibetechnologies
Projects:
- vibebrowserextension (Chrome extension)
- vibe-api-gateway (Backend API)

API Docs: https://docs.sentry.io/api/
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# Sentry API base URL
SENTRY_API_BASE = "https://sentry.io/api/0"

# Default organization
DEFAULT_ORG = "vibetechnologies"

# Projects we monitor
PROJECTS = [
    "vibebrowserextension",
    "vibe-api-gateway",
]


@dataclass
class SentryIssue:
    """Represents a Sentry issue."""

    id: str
    short_id: str
    title: str
    culprit: str
    level: str
    status: str
    first_seen: str
    last_seen: str
    count: int
    user_count: int
    project: str
    permalink: str
    metadata: dict

    @property
    def age_hours(self) -> float:
        """Hours since first seen."""
        first = datetime.fromisoformat(self.first_seen.replace("Z", "+00:00"))
        now = datetime.now(first.tzinfo)
        return (now - first).total_seconds() / 3600

    @property
    def is_new(self) -> bool:
        """Is this issue less than 24 hours old?"""
        return self.age_hours < 24

    @property
    def is_frequent(self) -> bool:
        """Has this issue occurred more than 10 times?"""
        return self.count > 10


@dataclass
class SentryEvent:
    """Represents a single error event."""

    id: str
    event_id: str
    title: str
    message: str
    platform: str
    timestamp: str
    tags: dict
    context: dict
    stacktrace: str | None
    user: dict | None


class SentryConnector:
    """
    Sentry API connector for error tracking.

    Usage:
        connector = SentryConnector()

        # Fetch unresolved issues from last 24h
        issues = connector.fetch_unresolved_issues(hours=24)

        # Get issue details with latest event
        details = connector.get_issue_details(issue.id)

        # Add comment
        connector.add_comment(issue.id, "Investigating...")

        # Resolve issue
        connector.resolve_issue(issue.id)
    """

    def __init__(
        self,
        auth_token: str | None = None,
        org: str = DEFAULT_ORG,
    ):
        """
        Initialize Sentry connector.

        Args:
            auth_token: Sentry API auth token (or from SENTRY_AUTH_TOKEN env)
            org: Sentry organization slug
        """
        self.auth_token = auth_token or os.environ.get("SENTRY_AUTH_TOKEN")
        self.org = org

        if not self.auth_token:
            raise ValueError(
                "Sentry auth token required. Set SENTRY_AUTH_TOKEN env var or pass auth_token."
            )

    def _headers(self) -> dict:
        """Get request headers with auth."""
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        """Make GET request to Sentry API."""
        url = f"{SENTRY_API_BASE}{endpoint}"
        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()

    def _put(self, endpoint: str, data: dict) -> Any:
        """Make PUT request to Sentry API."""
        url = f"{SENTRY_API_BASE}{endpoint}"
        response = requests.put(url, headers=self._headers(), json=data)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Sentry API."""
        url = f"{SENTRY_API_BASE}{endpoint}"
        response = requests.post(url, headers=self._headers(), json=data)
        response.raise_for_status()
        return response.json()

    def fetch_unresolved_issues(
        self,
        project: str | None = None,
        hours: int = 24,
        limit: int = 25,
    ) -> list[SentryIssue]:
        """
        Fetch unresolved issues from Sentry.

        Args:
            project: Specific project or None for all projects
            hours: Only issues with activity in last N hours
            limit: Maximum issues to return

        Returns:
            List of SentryIssue objects
        """
        projects = [project] if project else PROJECTS
        all_issues = []

        for proj in projects:
            endpoint = f"/projects/{self.org}/{proj}/issues/"
            params = {
                "query": "is:unresolved",
                "statsPeriod": f"{hours}h",
                "limit": limit,
            }

            try:
                issues_data = self._get(endpoint, params)
                for issue in issues_data:
                    all_issues.append(self._parse_issue(issue, proj))
            except requests.HTTPError as e:
                print(f"Error fetching issues from {proj}: {e}")

        # Sort by count (most frequent first)
        all_issues.sort(key=lambda x: x.count, reverse=True)
        return all_issues[:limit]

    def _parse_issue(self, data: dict, project: str) -> SentryIssue:
        """Parse API response into SentryIssue."""
        return SentryIssue(
            id=data["id"],
            short_id=data.get("shortId", ""),
            title=data.get("title", ""),
            culprit=data.get("culprit", ""),
            level=data.get("level", "error"),
            status=data.get("status", "unresolved"),
            first_seen=data.get("firstSeen", ""),
            last_seen=data.get("lastSeen", ""),
            count=data.get("count", 0),
            user_count=data.get("userCount", 0),
            project=project,
            permalink=data.get("permalink", ""),
            metadata=data.get("metadata", {}),
        )

    def get_issue_details(self, issue_id: str) -> dict:
        """
        Get detailed information about an issue.

        Returns issue data with latest event and full stacktrace.
        """
        endpoint = f"/issues/{issue_id}/"
        issue = self._get(endpoint)

        # Get latest event
        events_endpoint = f"/issues/{issue_id}/events/latest/"
        try:
            latest_event = self._get(events_endpoint)
            issue["latestEvent"] = latest_event
        except requests.HTTPError:
            issue["latestEvent"] = None

        return issue

    def get_issue_events(self, issue_id: str, limit: int = 10) -> list[dict]:
        """Get recent events for an issue."""
        endpoint = f"/issues/{issue_id}/events/"
        params = {"limit": limit}
        return self._get(endpoint, params)

    def add_comment(self, issue_id: str, text: str) -> dict:
        """
        Add a comment to an issue.

        Args:
            issue_id: Sentry issue ID
            text: Comment text (supports markdown)

        Returns:
            Created comment data
        """
        endpoint = f"/issues/{issue_id}/comments/"
        return self._post(endpoint, {"text": text})

    def resolve_issue(self, issue_id: str, resolution: str = "resolved") -> dict:
        """
        Resolve or ignore an issue.

        Args:
            issue_id: Sentry issue ID
            resolution: "resolved", "ignored", or "unresolved"

        Returns:
            Updated issue data
        """
        endpoint = f"/issues/{issue_id}/"
        return self._put(endpoint, {"status": resolution})

    def ignore_issue(
        self,
        issue_id: str,
        ignore_duration: int | None = None,
        ignore_count: int | None = None,
    ) -> dict:
        """
        Ignore an issue with optional conditions.

        Args:
            issue_id: Sentry issue ID
            ignore_duration: Ignore for N minutes
            ignore_count: Ignore until N more occurrences
        """
        endpoint = f"/issues/{issue_id}/"
        data: dict[str, Any] = {"status": "ignored"}

        if ignore_duration:
            data["statusDetails"] = {"ignoreDuration": ignore_duration}
        elif ignore_count:
            data["statusDetails"] = {"ignoreCount": ignore_count}

        return self._put(endpoint, data)

    def link_to_github(
        self,
        issue_id: str,
        repo: str,
        github_issue_number: int,
    ) -> dict:
        """
        Link Sentry issue to GitHub issue.

        Args:
            issue_id: Sentry issue ID
            repo: GitHub repo (e.g., "VibeTechnologies/VibeWebAgent")
            github_issue_number: GitHub issue number
        """
        # This uses Sentry's GitHub integration
        endpoint = f"/issues/{issue_id}/external-issues/"
        return self._post(
            endpoint,
            {
                "integration": "github",
                "repo": repo,
                "issueId": str(github_issue_number),
            },
        )

    def get_issue_tags(self, issue_id: str) -> list[dict]:
        """Get tags/facets for an issue (browser, OS, user, etc.)."""
        endpoint = f"/issues/{issue_id}/tags/"
        return self._get(endpoint)

    def get_project_stats(self, project: str, hours: int = 24) -> dict:
        """Get error statistics for a project."""
        endpoint = f"/projects/{self.org}/{project}/stats/"
        params = {"stat": "received", "resolution": "1h", "statsPeriod": f"{hours}h"}
        return self._get(endpoint, params)


def list_issues_cli() -> None:
    """CLI helper to list unresolved issues."""
    import argparse

    parser = argparse.ArgumentParser(description="List Sentry Issues")
    parser.add_argument(
        "--project",
        type=str,
        help="Specific project (default: all)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Issues from last N hours (default: 24)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max issues to show (default: 25)",
    )

    args = parser.parse_args()

    try:
        connector = SentryConnector()
    except ValueError as e:
        print(f"Error: {e}")
        print("Set SENTRY_AUTH_TOKEN environment variable.")
        return

    print(f"Fetching unresolved issues from last {args.hours}h...")
    issues = connector.fetch_unresolved_issues(
        project=args.project,
        hours=args.hours,
        limit=args.limit,
    )

    if not issues:
        print("No unresolved issues found.")
        return

    print(f"\nFound {len(issues)} unresolved issues:\n")
    for issue in issues:
        print(f"[{issue.project}] {issue.short_id}: {issue.title}")
        print(f"  Count: {issue.count} | Users: {issue.user_count} | Level: {issue.level}")
        print(f"  First: {issue.first_seen[:10]} | Last: {issue.last_seen[:10]}")
        print(f"  URL: {issue.permalink}")
        print()


if __name__ == "__main__":
    list_issues_cli()
