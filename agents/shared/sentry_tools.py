"""
Shared Sentry tool functions for all agent frameworks.

Standalone implementation that doesn't depend on vibeteam.connectors.
Can be used by AutoGen, CrewAI, and OpenHands agents.

Environment Variables:
    SENTRY_AUTH_TOKEN: Sentry API auth token (required)
    SENTRY_ORG: Sentry organization slug (default: vibetechnologies)
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# Sentry API base URL
SENTRY_API_BASE = "https://sentry.io/api/0"

# Default organization
DEFAULT_ORG = os.environ.get("SENTRY_ORG", "vibetechnologies")

# Projects we monitor
DEFAULT_PROJECTS = [
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


class SentryClient:
    """
    Lightweight Sentry API client.

    Usage:
        client = SentryClient()
        issues = client.fetch_unresolved_issues(hours=24)
    """

    def __init__(
        self,
        auth_token: str | None = None,
        org: str | None = None,
        timeout: float = 10.0,
    ):
        """
        Initialize Sentry client.

        Args:
            auth_token: Sentry API auth token (or from SENTRY_AUTH_TOKEN env)
            org: Sentry organization slug (or from SENTRY_ORG env)
            timeout: Request timeout in seconds (default: 10s)
        """
        self.auth_token = auth_token or os.environ.get("SENTRY_AUTH_TOKEN")
        self.org = org or DEFAULT_ORG
        self.timeout = timeout

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
        response = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _put(self, endpoint: str, data: dict) -> Any:
        """Make PUT request to Sentry API."""
        url = f"{SENTRY_API_BASE}{endpoint}"
        response = requests.put(url, headers=self._headers(), json=data, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Sentry API."""
        url = f"{SENTRY_API_BASE}{endpoint}"
        response = requests.post(url, headers=self._headers(), json=data, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _hours_to_stats_period(self, hours: int) -> str:
        """Convert hours to valid Sentry statsPeriod value."""
        if hours <= 24:
            return "24h"
        else:
            return "14d"

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
            count=int(data.get("count", 0) or 0),
            user_count=int(data.get("userCount", 0) or 0),
            project=project,
            permalink=data.get("permalink", ""),
            metadata=data.get("metadata", {}),
        )

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
        projects = [project] if project else DEFAULT_PROJECTS
        all_issues = []
        stats_period = self._hours_to_stats_period(hours)

        for proj in projects:
            endpoint = f"/projects/{self.org}/{proj}/issues/"
            params = {
                "query": "is:unresolved",
                "statsPeriod": stats_period,
                "limit": limit,
            }

            try:
                issues_data = self._get(endpoint, params)
                for issue in issues_data:
                    all_issues.append(self._parse_issue(issue, proj))
            except requests.HTTPError as e:
                # Log but continue with other projects
                pass
            except requests.Timeout:
                # Timeout - continue with other projects
                pass

        # Sort by count (most frequent first)
        all_issues.sort(key=lambda x: x.count, reverse=True)
        return all_issues[:limit]

    def get_issue_details(self, issue_id: str) -> dict:
        """Get detailed information about an issue."""
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

    def add_comment(self, issue_id: str, text: str) -> dict:
        """Add a comment to an issue."""
        endpoint = f"/issues/{issue_id}/comments/"
        return self._post(endpoint, {"text": text})

    def resolve_issue(self, issue_id: str) -> dict:
        """Resolve an issue."""
        endpoint = f"/issues/{issue_id}/"
        return self._put(endpoint, {"status": "resolved"})


# ============================================================================
# Tool Functions for Agents
# ============================================================================


def get_sentry_context(hours: int = 24, limit: int = 10) -> str:
    """
    Fetch Sentry issues and format as context for agents.

    This is the main function called by agents to get Sentry data.
    Fast-fails if SENTRY_AUTH_TOKEN is not set.

    Args:
        hours: Look back period in hours (default: 24)
        limit: Maximum issues to return (default: 10)

    Returns:
        Formatted string with Sentry issues or error message
    """
    auth_token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not auth_token:
        return "Sentry: SENTRY_AUTH_TOKEN not configured."

    try:
        client = SentryClient(auth_token=auth_token, timeout=10.0)
        issues = client.fetch_unresolved_issues(hours=hours, limit=limit)

        if not issues:
            return f"Sentry: No unresolved issues found in the last {hours} hours."

        result = f"## Current Sentry Issues (last {hours}h)\n\n"
        for issue in issues:
            result += f"### [{issue.project}] {issue.short_id}\n"
            result += f"**{issue.title}**\n"
            result += f"- Level: {issue.level} | Count: {issue.count} | Users: {issue.user_count}\n"
            result += f"- First seen: {issue.first_seen[:10]} | Last seen: {issue.last_seen[:10]}\n"
            result += f"- URL: {issue.permalink}\n\n"

        return result

    except ValueError as e:
        return f"Sentry: Configuration error - {e}"
    except requests.Timeout:
        return "Sentry: Request timed out after 10 seconds."
    except requests.HTTPError as e:
        return f"Sentry: API error - {e}"
    except Exception as e:
        return f"Sentry: Unexpected error - {e}"


async def list_sentry_issues(hours: int = 24, limit: int = 10) -> str:
    """
    Async wrapper for listing Sentry issues.

    Used by AutoGen and other async frameworks.
    """
    return get_sentry_context(hours=hours, limit=limit)


async def get_sentry_issue_details(issue_id: str) -> str:
    """
    Get detailed information about a specific Sentry issue.

    Args:
        issue_id: Sentry issue ID

    Returns:
        Formatted issue details or error message
    """
    auth_token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not auth_token:
        return "Sentry: SENTRY_AUTH_TOKEN not configured."

    try:
        client = SentryClient(auth_token=auth_token, timeout=10.0)
        details = client.get_issue_details(issue_id)

        result = f"## Sentry Issue Details: {details.get('shortId', issue_id)}\n\n"
        result += f"**{details.get('title', 'Unknown')}**\n\n"
        result += f"- Status: {details.get('status', 'unknown')}\n"
        result += f"- Level: {details.get('level', 'unknown')}\n"
        result += f"- Count: {details.get('count', 0)}\n"
        result += f"- Users Affected: {details.get('userCount', 0)}\n"
        result += f"- First Seen: {details.get('firstSeen', 'unknown')}\n"
        result += f"- Last Seen: {details.get('lastSeen', 'unknown')}\n"
        result += f"- URL: {details.get('permalink', 'N/A')}\n"

        # Include stacktrace if available
        latest_event = details.get("latestEvent")
        if latest_event:
            entries = latest_event.get("entries", [])
            for entry in entries:
                if entry.get("type") == "exception":
                    result += "\n### Stacktrace\n```\n"
                    values = entry.get("data", {}).get("values", [])
                    for exc in values:
                        result += f"{exc.get('type', 'Exception')}: {exc.get('value', '')}\n"
                        stacktrace = exc.get("stacktrace", {})
                        frames = stacktrace.get("frames", [])[-5:]  # Last 5 frames
                        for frame in reversed(frames):
                            filename = frame.get("filename", "?")
                            lineno = frame.get("lineNo", "?")
                            function = frame.get("function", "?")
                            result += f"  at {function} ({filename}:{lineno})\n"
                    result += "```\n"
                    break

        return result

    except requests.Timeout:
        return "Sentry: Request timed out."
    except requests.HTTPError as e:
        return f"Sentry: API error - {e}"
    except Exception as e:
        return f"Sentry: Error fetching details - {e}"


async def resolve_sentry_issue(issue_id: str, comment: str | None = None) -> str:
    """
    Resolve a Sentry issue, optionally adding a comment.

    Args:
        issue_id: Sentry issue ID
        comment: Optional comment to add before resolving

    Returns:
        Success or error message
    """
    auth_token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not auth_token:
        return "Sentry: SENTRY_AUTH_TOKEN not configured."

    try:
        client = SentryClient(auth_token=auth_token, timeout=10.0)

        if comment:
            client.add_comment(issue_id, comment)

        client.resolve_issue(issue_id)
        return f"Sentry: Issue {issue_id} resolved successfully."

    except requests.HTTPError as e:
        return f"Sentry: Failed to resolve issue - {e}"
    except Exception as e:
        return f"Sentry: Error - {e}"
