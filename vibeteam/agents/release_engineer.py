"""
Release Engineer Agent - Production monitoring, issue triage, and automated fixes.

This agent uses OpenHands to perform real software engineering tasks:
- Clone repositories
- Analyze code and fix bugs
- Create pull requests
- Run tests

It integrates with:
- Sentry: Error monitoring and triage
- GitHub: Issue tracking and PR management
- Langfuse: LLM observability

Critical Rule: Every PR MUST reference a GitHub issue.
"""

from dataclasses import dataclass
from typing import Any

from vibeteam.agents.openhands_base import OpenHandsAgent
from vibeteam.connectors.github import GitHubConnector
from vibeteam.connectors.sentry import SentryConnector, SentryIssue

# System prompt for the Release Engineer
RELEASE_ENGINEER_PROMPT = """
You are a Release Engineer responsible for production monitoring, issue triage, and automated fixes.

## Your Responsibilities

1. **Monitor Production** - Track errors from Sentry, anomalies from Langfuse
2. **Triage Issues** - Classify issues as valid bugs or noise
3. **Create Fixes** - Clone repos, implement fixes, run tests, create PRs
4. **Code Review** - Review PRs for correctness, security, and best practices

## Important URLs

| Resource | URL |
|----------|-----|
| Sentry Extension | https://vibetechnologies.sentry.io/projects/vibebrowserextension/ |
| Sentry API | https://vibetechnologies.sentry.io/projects/vibe-api-gateway/ |
| Langfuse | https://langfuse.vibebrowser.app |
| API Prod | https://api.vibebrowser.app |
| API Dev | https://api-dev.vibebrowser.app |
| GitHub Repo | https://github.com/VibeTechnologies/VibeWebAgent |

## Issue Classification

**Valid Bug Patterns:**
- TypeError, ReferenceError, Cannot read property
- Unhandled Promise rejection
- High impact: >50 events or >10 users

**Noise Patterns (auto-resolve):**
- Failed to fetch, NetworkError, net::ERR_
- ResizeObserver loop, Script error
- AbortError, ECONNREFUSED
- Third-party extension errors

## Critical Rules

1. **Every PR MUST reference a GitHub issue** - Use "Fixes #123" in PR description
2. **Classify before acting** - Don't create issues for noise
3. **Quantify impact** - Include event counts, user counts
4. **Run tests before creating PR** - Ensure CI will pass
5. **Link to source** - Include Sentry/Langfuse permalinks

## Available Tools

You have access to:
- Terminal: Run shell commands (git, npm, python, etc.)
- FileEditor: Create and edit files
- TaskTracker: Track your progress on complex tasks

## Workflow for Fixing Bugs

1. Clone the repository (if not already cloned)
2. Create a new branch: `fix/{issue_number}-{short-desc}`
3. Analyze the code and understand the bug
4. Implement the fix
5. Run tests to verify
6. Commit with message referencing the issue
7. Push and create PR

Always be thorough and methodical. Quality over speed.
"""


@dataclass
class TriageResult:
    """Result of triaging a Sentry issue."""

    issue_id: str
    short_id: str
    classification: str  # VALID_BUG, NOISE, NEEDS_INVESTIGATION
    reason: str
    action: str  # CREATE_ISSUE, RESOLVE, INVESTIGATE
    github_issue_number: int | None = None
    github_issue_url: str | None = None


@dataclass
class FixResult:
    """Result of attempting to fix an issue."""

    success: bool
    issue_number: int
    pr_number: int | None = None
    pr_url: str | None = None
    branch: str | None = None
    error: str | None = None
    cost: float = 0.0


class ReleaseEngineerAgent(OpenHandsAgent):
    """
    Release Engineer Agent for production monitoring and automated fixes.

    This agent can:
    - Fetch and triage Sentry issues
    - Create GitHub issues for valid bugs
    - Implement fixes and create PRs
    - Review existing PRs

    Usage:
        agent = ReleaseEngineerAgent(workspace_path="/path/to/repo")

        # Triage Sentry issues
        results = await agent.triage_sentry_issues(hours=24)

        # Fix a specific issue
        result = await agent.fix_issue(issue_number=123)

        # Review a PR
        review = await agent.review_pr(pr_number=456)
    """

    def __init__(
        self,
        workspace_path: str | None = None,
        use_docker: bool = False,
        **kwargs,
    ):
        """
        Initialize the Release Engineer agent.

        Args:
            workspace_path: Path to the workspace/repository
            use_docker: Whether to run in Docker container (for isolation)
            **kwargs: Additional arguments passed to OpenHandsAgent
        """
        super().__init__(
            system_prompt=RELEASE_ENGINEER_PROMPT,
            workspace_path=workspace_path,
            **kwargs,
        )
        self.use_docker = use_docker

        # Initialize connectors (lazy - only if tokens are available)
        self._github: GitHubConnector | None = None
        self._sentry: SentryConnector | None = None

    @property
    def github(self) -> GitHubConnector:
        """Get or create GitHub connector."""
        if self._github is None:
            self._github = GitHubConnector()
        return self._github

    @property
    def sentry(self) -> SentryConnector:
        """Get or create Sentry connector."""
        if self._sentry is None:
            self._sentry = SentryConnector()
        return self._sentry

    # =====================
    # Sentry Operations
    # =====================

    async def fetch_sentry_issues(
        self,
        hours: int = 24,
        limit: int = 25,
    ) -> list[SentryIssue]:
        """
        Fetch unresolved issues from Sentry.

        Args:
            hours: Only issues with activity in last N hours
            limit: Maximum issues to return

        Returns:
            List of SentryIssue objects
        """
        return self.sentry.fetch_unresolved_issues(hours=hours, limit=limit)

    async def triage_sentry_issue(
        self,
        issue: SentryIssue,
        auto_create_github: bool = True,
    ) -> TriageResult:
        """
        Triage a single Sentry issue.

        Uses the OpenHands agent to analyze the issue and determine
        if it's a valid bug that needs a GitHub issue.

        Args:
            issue: SentryIssue to triage
            auto_create_github: Whether to automatically create GitHub issue

        Returns:
            TriageResult with classification and action taken
        """
        # Get issue details
        details = self.sentry.get_issue_details(issue.id)

        # Build context for the agent
        task = f"""
Analyze this Sentry issue and classify it:

## Issue Details

- **ID:** {issue.short_id}
- **Title:** {issue.title}
- **Culprit:** {issue.culprit}
- **Level:** {issue.level}
- **Count:** {issue.count} events
- **Users Affected:** {issue.user_count}
- **Project:** {issue.project}
- **First Seen:** {issue.first_seen}
- **Last Seen:** {issue.last_seen}
- **Permalink:** {issue.permalink}

## Metadata

{details.get('metadata', {})}

## Latest Event

{details.get('latestEvent', {}).get('message', 'No message')}

## Task

1. Classify this issue: VALID_BUG, NOISE, or NEEDS_INVESTIGATION
2. Explain your reasoning
3. If VALID_BUG, draft a GitHub issue title and body

Respond with:
CLASSIFICATION: <type>
REASON: <your reasoning>
ACTION: <CREATE_ISSUE|RESOLVE|INVESTIGATE>
GITHUB_TITLE: <if creating issue>
GITHUB_BODY: <if creating issue, use markdown>
"""

        # Execute analysis
        result = await self.execute(task)

        # Parse response (simple extraction)
        response_text = str(result.get("events", []))

        # Default values
        classification = "NEEDS_INVESTIGATION"
        reason = "Unable to parse agent response"
        action = "INVESTIGATE"
        github_issue_number = None
        github_issue_url = None

        if "CLASSIFICATION: VALID_BUG" in response_text:
            classification = "VALID_BUG"
            action = "CREATE_ISSUE"
        elif "CLASSIFICATION: NOISE" in response_text:
            classification = "NOISE"
            action = "RESOLVE"

        if "REASON:" in response_text:
            reason_start = response_text.find("REASON:") + 7
            reason_end = response_text.find("ACTION:", reason_start)
            if reason_end > reason_start:
                reason = response_text[reason_start:reason_end].strip()

        # Create GitHub issue if valid bug and auto_create is enabled
        if classification == "VALID_BUG" and auto_create_github:
            try:
                # Extract title and body from response or use defaults
                title = f"[Sentry] {issue.title}"
                body = f"""
## Sentry Issue: {issue.short_id}

**Source:** Sentry ({issue.project})
**Severity:** {issue.level}
**Link:** {issue.permalink}

## Details

- **Error:** {issue.title}
- **Location:** {issue.culprit}
- **Events:** {issue.count}
- **Users Affected:** {issue.user_count}
- **First Seen:** {issue.first_seen}
- **Last Seen:** {issue.last_seen}

## Analysis

{reason}

---
*Auto-created by Release Engineer Agent*
"""
                gh_issue = self.github._post(
                    f"/repos/{self.github.owner}/{self.github.repo}/issues",
                    {"title": title, "body": body, "labels": ["bug", "sentry"]},
                )
                github_issue_number = gh_issue.get("number")
                github_issue_url = gh_issue.get("html_url")

                # Add comment to Sentry issue
                self.sentry.add_comment(
                    issue.id,
                    f"GitHub issue created: {github_issue_url}",
                )
            except Exception as e:
                reason += f"\n\nFailed to create GitHub issue: {e}"

        # Resolve noise issues
        if classification == "NOISE":
            try:
                self.sentry.resolve_issue(issue.id, resolution="ignored")
            except Exception:
                pass

        return TriageResult(
            issue_id=issue.id,
            short_id=issue.short_id,
            classification=classification,
            reason=reason,
            action=action,
            github_issue_number=github_issue_number,
            github_issue_url=github_issue_url,
        )

    async def triage_sentry_issues(
        self,
        hours: int = 24,
        limit: int = 10,
        auto_create_github: bool = True,
    ) -> list[TriageResult]:
        """
        Fetch and triage multiple Sentry issues.

        Args:
            hours: Only issues with activity in last N hours
            limit: Maximum issues to triage
            auto_create_github: Whether to automatically create GitHub issues

        Returns:
            List of TriageResult objects
        """
        issues = await self.fetch_sentry_issues(hours=hours, limit=limit)
        results = []

        for issue in issues:
            result = await self.triage_sentry_issue(
                issue, auto_create_github=auto_create_github
            )
            results.append(result)

        return results

    # =====================
    # GitHub Issue Fixing
    # =====================

    async def fix_issue(
        self,
        issue_number: int,
        run_tests: bool = True,
        create_pr: bool = True,
    ) -> FixResult:
        """
        Attempt to fix a GitHub issue.

        The agent will:
        1. Read the issue details
        2. Create a branch
        3. Analyze the codebase
        4. Implement a fix
        5. Run tests (if enabled)
        6. Create a PR (if enabled)

        Args:
            issue_number: GitHub issue number to fix
            run_tests: Whether to run tests before creating PR
            create_pr: Whether to create a PR

        Returns:
            FixResult with PR details or error
        """
        # Get issue details
        issue = self.github.get_issue(issue_number)

        # Build task for the agent
        task = f"""
Fix GitHub issue #{issue_number}: {issue.title}

## Issue Details

{issue.body}

## Instructions

1. First, understand the issue by reading relevant code
2. Create a new branch: `fix/{issue_number}-{issue.title[:20].lower().replace(' ', '-')}`
3. Implement the fix
4. {"Run `npm test` or equivalent to verify" if run_tests else "Skip tests"}
5. Commit with message: "fix: {issue.title} (Fixes #{issue_number})"
6. {"Create PR with description that includes 'Fixes #{issue_number}'" if create_pr else "Stop after committing"}

Important:
- Every PR MUST include "Fixes #{issue_number}" in the description
- Be thorough but focused - only change what's necessary
- If you're unsure about something, investigate before making changes
"""

        # Execute the fix
        result = await self.execute(task)

        if not result.get("success"):
            return FixResult(
                success=False,
                issue_number=issue_number,
                error=result.get("error", "Unknown error"),
                cost=result.get("cost", 0),
            )

        # If we got here, the agent completed. Try to find the PR
        pr_number = None
        pr_url = None
        branch = f"fix/{issue_number}"

        if create_pr:
            # Check for recently created PRs
            try:
                prs = self.github.list_prs(state="open", limit=5)
                for pr in prs:
                    if str(issue_number) in pr.title or str(issue_number) in pr.body:
                        pr_number = pr.number
                        pr_url = pr.html_url
                        branch = pr.head_ref
                        break
            except Exception:
                pass

        return FixResult(
            success=True,
            issue_number=issue_number,
            pr_number=pr_number,
            pr_url=pr_url,
            branch=branch,
            cost=result.get("cost", 0),
        )

    # =====================
    # PR Review
    # =====================

    async def review_pr(
        self,
        pr_number: int,
        auto_submit: bool = False,
    ) -> dict[str, Any]:
        """
        Review a pull request.

        Args:
            pr_number: PR number to review
            auto_submit: Whether to submit the review to GitHub

        Returns:
            Review result with findings and verdict
        """
        # Get PR details
        pr = self.github.get_pr(pr_number)
        diff = self.github.get_pr_diff(pr_number)

        # Build task for the agent
        task = f"""
Review this pull request:

## PR #{pr_number}: {pr.title}

**Author:** {pr.user}
**Branch:** {pr.head_ref} -> {pr.base_ref}
**Files Changed:** {pr.changed_files}
**Additions:** +{pr.additions}
**Deletions:** -{pr.deletions}

## Description

{pr.body}

## Diff

```diff
{diff[:20000]}
```

## Review Checklist

1. **Correctness** - Does the code do what it claims?
2. **Bugs** - Any potential bugs, edge cases, or null pointer issues?
3. **Security** - Any security concerns (injection, XSS, secrets)?
4. **Performance** - Any performance issues?
5. **Tests** - Are changes adequately tested?
6. **Issue Reference** - Does PR reference a GitHub issue?

Provide your review with:
- VERDICT: APPROVE, REQUEST_CHANGES, or COMMENT
- Summary of findings
- Specific issues found (file, line, description)
- Suggestions for improvement
"""

        result = await self.execute(task)

        # Parse verdict from response
        response_text = str(result.get("events", []))
        verdict = "COMMENT"
        if "APPROVE" in response_text:
            verdict = "APPROVE"
        elif "REQUEST_CHANGES" in response_text:
            verdict = "REQUEST_CHANGES"

        review_result = {
            "pr_number": pr_number,
            "verdict": verdict,
            "review": response_text,
            "submitted": False,
            "cost": result.get("cost", 0),
        }

        # Submit review if requested
        if auto_submit:
            try:
                self.github.create_review(
                    pr_number=pr_number,
                    body=f"## Automated Review\n\n{response_text[:4000]}",
                    event=verdict,
                )
                review_result["submitted"] = True
            except Exception as e:
                review_result["submit_error"] = str(e)

        return review_result

    # =====================
    # Health Monitoring
    # =====================

    async def check_health(self, endpoints: list[str] | None = None) -> dict[str, Any]:
        """
        Check health of production endpoints.

        Args:
            endpoints: List of URLs to check (default: production APIs)

        Returns:
            Health status for each endpoint
        """
        if endpoints is None:
            endpoints = [
                "https://api.vibebrowser.app/health",
                "https://api-dev.vibebrowser.app/health",
            ]

        task = f"""
Check the health of these endpoints:

{chr(10).join(f'- {url}' for url in endpoints)}

For each endpoint:
1. Make a request and check the response
2. Note the status code and response time
3. Flag any issues

Provide a summary with:
- Overall status: HEALTHY, DEGRADED, or DOWN
- Details for each endpoint
"""

        result = await self.execute(task)

        return {
            "success": result.get("success", False),
            "endpoints": endpoints,
            "result": str(result.get("events", [])),
            "cost": result.get("cost", 0),
        }
