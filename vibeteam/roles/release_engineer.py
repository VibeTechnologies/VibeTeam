"""
Release Engineer Role - Production Monitoring, Issue Triage, Auto-Fix PRs.

Consolidates monitoring responsibilities:
- Sentry error triage and issue creation
- Langfuse LLM anomaly detection
- Service health monitoring
- Automatic GitHub issue + PR creation
- Pull request review and code analysis

Critical Rule: Every PR MUST reference a GitHub issue.
"""

import os
from typing import Any

from metagpt.actions import Action
from pydantic import Field

from vibeteam.roles.base import VibeRole

# Release Engineer Protocol - embedded in all actions
RELEASE_ENGINEER_PROTOCOL = """
## Release Engineer Protocol

You are a Release Engineer responsible for production monitoring, issue triage, and automated fixes.

### Monitoring Sources

| Source | What to Monitor | Action |
|--------|-----------------|--------|
| **Sentry** | Unresolved errors | Classify (valid/noise), create GitHub issue |
| **Langfuse** | LLM anomalies (latency, errors, tokens) | Create GitHub issue with analysis |
| **Health** | API endpoints, response times | Alert on degradation |

### Sentry Projects

- vibebrowserextension - Browser extension errors
- vibe-api-gateway - Backend API errors
- vibeteam - VibeTeam agent errors

### Important URLs

| Resource | URL |
|----------|-----|
| Sentry Extension | https://vibetechnologies.sentry.io/projects/vibebrowserextension/ |
| Sentry API | https://vibetechnologies.sentry.io/projects/vibe-api-gateway/ |
| Langfuse | https://langfuse.vibebrowser.app |
| API Prod | https://api.vibebrowser.app |
| API Dev | https://api-dev.vibebrowser.app |
| GitHub Repo | https://github.com/VibeTechnologies/VibeWebAgent |

### Issue Classification

**Valid Bug Patterns:**
- TypeError, ReferenceError, Cannot read property
- Unhandled Promise rejection
- High impact: >50 events or >10 users

**Noise Patterns (auto-resolve):**
- Failed to fetch, NetworkError, net::ERR_
- ResizeObserver loop, Script error
- AbortError, ECONNREFUSED
- Third-party extension errors

### GitHub Issue Template

```markdown
## [{source}] {title}

**Source:** {source} ({project})
**Severity:** {severity}
**Detected:** {timestamp}
**Link:** {permalink}

## Details

{details}

## Impact

- Events: {count}
- Users: {user_count}

## Suggested Fix

{analysis}

---
*Auto-created by Release Engineer Agent*
```

### PR Template (MUST reference issue)

```markdown
## Fixes #{issue_number}

## Problem

{problem_description}

## Solution

{solution_description}

## Testing

- [ ] Unit tests added/updated
- [ ] Manual verification

---
*Auto-created by Release Engineer Agent*
```

### Critical Rules

1. **Every PR MUST reference a GitHub issue** - Use "Fixes #123" in description
2. **Classify before acting** - Don't create issues for noise
3. **Quantify impact** - Include event counts, user counts
4. **Provide actionable recommendations** - What should be fixed
5. **Link to source** - Include Sentry/Langfuse permalinks
"""


class MonitorSentry(Action):
    """Monitor Sentry for unresolved issues, classify, and create GitHub issues."""

    name: str = "MonitorSentry"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer monitoring Sentry for production issues.

{protocol}

## Sentry Issues Found

{issues}

## Task

For each issue:
1. **Classify**: Is this a valid bug or noise?
2. **Decide Action**:
   - Valid bug: Create GitHub issue with full details
   - Noise: Mark for auto-resolution with reason

## Output Format

For each issue, output:

```
ISSUE: {short_id}
CLASSIFICATION: VALID_BUG | NOISE
REASON: {why this classification}
ACTION: CREATE_ISSUE | RESOLVE
GITHUB_TITLE: {if creating issue}
GITHUB_BODY: {if creating issue, use template from protocol}
```

Analyze and classify:
"""

    async def run(self, issues: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(protocol=RELEASE_ENGINEER_PROTOCOL, issues=issues)
        rsp = await self._aask(prompt)
        return rsp


class MonitorLangfuse(Action):
    """Monitor Langfuse for LLM anomalies and create GitHub issues."""

    name: str = "MonitorLangfuse"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer monitoring Langfuse for LLM performance issues.

{protocol}

## Langfuse Stats (Last {hours}h)

{stats}

## Detected Anomalies

{anomalies}

## Task

1. **Analyze** each anomaly for root cause
2. **Determine severity** (warning vs critical)
3. **Create GitHub issue** if action needed
4. **Suggest fix** if possible

## Output Format

```
ANOMALY: {type}
SEVERITY: {warning|critical}
ROOT_CAUSE: {analysis}
ACTION: CREATE_ISSUE | MONITOR | IGNORE
GITHUB_TITLE: {if creating issue}
GITHUB_BODY: {if creating issue}
SUGGESTED_FIX: {what to do}
```

Analyze anomalies:
"""

    async def run(self, stats: str, anomalies: str, hours: int = 1) -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            stats=stats,
            anomalies=anomalies,
            hours=hours,
        )
        rsp = await self._aask(prompt)
        return rsp


class MonitorHealth(Action):
    """Monitor service health and create alerts."""

    name: str = "MonitorHealth"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer monitoring production service health.

{protocol}

## Health Check Results

{health_data}

## Alerts

{alerts}

## Task

1. **Assess overall status** - healthy, degraded, or down
2. **Prioritize issues** - which need immediate attention
3. **Create GitHub issue** for persistent problems
4. **Recommend actions** - restart, rollback, investigate

## Output Format

```markdown
## Health Status Report

**Overall:** {healthy|degraded|down}
**Timestamp:** {timestamp}

### Service Status

| Service | Status | Latency | Notes |
|---------|--------|---------|-------|
| ... | ... | ... | ... |

### Issues Requiring Action

1. {issue and recommended action}

### GitHub Issues to Create

{if any persistent issues need tracking}
```

Analyze health:
"""

    async def run(self, health_data: str, alerts: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            health_data=health_data,
            alerts=alerts,
        )
        rsp = await self._aask(prompt)
        return rsp


class TriageSentryIssue(Action):
    """Deep-dive analysis of a specific Sentry issue."""

    name: str = "TriageSentryIssue"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer performing deep analysis of a Sentry issue.

{protocol}

## Issue Details

{issue}

## Stack Trace

{stacktrace}

## Recent Events

{events}

## Task

1. **Root Cause Analysis** - What's causing this error?
2. **Impact Assessment** - How many users affected? Critical path?
3. **Fix Recommendation** - Code change needed
4. **Create GitHub Issue** - Full details for developer

## Output Format

```markdown
## Sentry Issue Analysis: {short_id}

### Summary
{one sentence}

### Root Cause
{technical explanation}

### Impact
- Users affected: {count}
- Frequency: {events per hour}
- Severity: {low|medium|high|critical}

### Recommended Fix

```{language}
// Before
{problematic code}

// After
{fixed code}
```

### GitHub Issue

**Title:** [Sentry] {title}
**Labels:** bug, sentry, {severity}
**Body:**
{full issue body using template}
```

Analyze issue:
"""

    async def run(self, issue: str, stacktrace: str = "", events: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            issue=issue,
            stacktrace=stacktrace,
            events=events,
        )
        rsp = await self._aask(prompt)
        return rsp


class CreateFixPR(Action):
    """Create a PR to fix an issue. MUST reference GitHub issue."""

    name: str = "CreateFixPR"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer creating a fix PR.

{protocol}

## GitHub Issue

{issue}

## Codebase Context

{context}

## Task

Create a PR that:
1. **References the issue** - "Fixes #123" in description
2. **Implements the fix** - Minimal, focused change
3. **Includes tests** - If applicable
4. **Documents the change** - Clear PR description

## Output Format

```markdown
## PR Details

**Branch:** fix/{issue_number}-{short_description}
**Title:** fix: {description} (Fixes #{issue_number})

### Description

Fixes #{issue_number}

## Problem

{what was wrong}

## Solution

{what this PR does}

## Changes

- `path/to/file.ts`: {what changed}

## Testing

- [ ] Unit tests
- [ ] Manual verification

### Code Changes

```{language}
// File: {path}
{code diff or new code}
```
```

Create PR:
"""

    async def run(self, issue: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            issue=issue,
            context=context,
        )
        rsp = await self._aask(prompt)
        return rsp


class WriteChangelog(Action):
    """Write changelog from commits/PRs."""

    name: str = "WriteChangelog"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Write a changelog.

## Commits/PRs
{changes}

## Previous Version
{previous_version}

## Changelog Format (Keep a Changelog)
### [version] - date
#### Added
- New features

#### Changed
- Changes to existing features

#### Fixed
- Bug fixes

#### Security
- Security fixes

Write changelog:
"""

    async def run(self, changes: str, previous_version: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(changes=changes, previous_version=previous_version)
        rsp = await self._aask(prompt)
        return rsp


class ValidateRelease(Action):
    """Validate release readiness."""

    name: str = "ValidateRelease"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer. Validate release readiness.

{protocol}

## Release Checklist
{checklist}

## Current System State
{system_state}

## Validation Criteria
1. **CI/CD**: All workflows passing
2. **Health**: All endpoints responding
3. **Errors**: No critical unresolved Sentry issues
4. **Tests**: All passing, coverage adequate
5. **Documentation**: Updated for changes

Provide validation report with READY or NOT READY verdict:
"""

    async def run(self, checklist: str, system_state: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            checklist=checklist,
            system_state=system_state,
        )
        rsp = await self._aask(prompt)
        return rsp


class RunReadinessPlaybook(Action):
    """Clone VibeWebAgent repo and execute the production readiness playbook."""

    name: str = "RunReadinessPlaybook"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer executing the Production Readiness Playbook.

{protocol}

## Playbook Location

The playbook is at: docs/readinessPlaybook.md in the VibeWebAgent repository.

## Execution Results

The following checks have been executed:

### Health Endpoints
{health_results}

### LLM API Test
{llm_results}

### E2E Test Results
{e2e_results}

### Kubernetes Status
{k8s_results}

### CI/CD Status
{ci_results}

### Sentry Errors (24h)
{sentry_results}

## Task

Based on the execution results:

1. **Assess overall readiness** - GREEN, YELLOW, or RED
2. **Identify blocking issues** - What must be fixed before release
3. **Identify warnings** - Non-blocking but concerning
4. **Provide recommendations** - Actions to take

## Output Format

```markdown
# Production Readiness Report

**Date:** {date}
**Status:** [GREEN/YELLOW/RED]

## Summary

{one paragraph assessment}

## Checks Performed

| Check | Status | Details |
|-------|--------|---------|
| Health Endpoints | OK/WARN/FAIL | {details} |
| LLM API | OK/WARN/FAIL | {details} |
| E2E Tests | OK/WARN/FAIL | {details} |
| Kubernetes | OK/WARN/FAIL | {details} |
| CI/CD | OK/WARN/FAIL | {details} |
| Sentry | OK/WARN/FAIL | {details} |

## Blocking Issues

{list of issues that prevent release, or "None"}

## Warnings

{list of non-blocking concerns, or "None"}

## Recommendations

1. {action items}

---
*Generated by VibeTeam ReleaseEngineer*
```

Generate the readiness report:
"""

    async def run(
        self,
        health_results: str,
        llm_results: str,
        e2e_results: str,
        k8s_results: str,
        ci_results: str,
        sentry_results: str,
    ) -> str:
        from datetime import datetime

        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            health_results=health_results,
            llm_results=llm_results,
            e2e_results=e2e_results,
            k8s_results=k8s_results,
            ci_results=ci_results,
            sentry_results=sentry_results,
            date=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        )
        rsp = await self._aask(prompt)
        return rsp


class ReviewPR(Action):
    """Review a pull request for code quality, bugs, and best practices."""

    name: str = "ReviewPR"

    PROMPT_TEMPLATE: str = """
You are a Release Engineer reviewing a pull request.

{protocol}

## Pull Request

**Title:** {pr_title}
**Author:** {pr_author}
**Branch:** {head_ref} -> {base_ref}
**Files Changed:** {changed_files}

## PR Description

{pr_body}

## Diff

{diff}

## Task

Perform a thorough code review:

1. **Correctness**: Does the code do what it claims?
2. **Bugs**: Any potential bugs, edge cases, or null pointer issues?
3. **Security**: Any security concerns (injection, XSS, secrets)?
4. **Performance**: Any performance issues or unnecessary operations?
5. **Style**: Does it follow project conventions?
6. **Tests**: Are changes adequately tested?
7. **Issue Reference**: Does PR reference a GitHub issue?

## Output Format

```markdown
## PR Review: {pr_title}

### Summary
{one sentence verdict: APPROVE, REQUEST_CHANGES, or COMMENT}

### Strengths
- {what's good about this PR}

### Issues Found

| Severity | File | Line | Issue |
|----------|------|------|-------|
| {high/medium/low} | {file} | {line} | {description} |

### Suggestions

{code suggestions if any}

### Verdict

**{APPROVE/REQUEST_CHANGES/COMMENT}**: {reason}
```

Review the PR:
"""

    async def run(
        self,
        pr_title: str,
        pr_body: str,
        pr_author: str,
        head_ref: str,
        base_ref: str,
        changed_files: int,
        diff: str,
    ) -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=RELEASE_ENGINEER_PROTOCOL,
            pr_title=pr_title,
            pr_body=pr_body,
            pr_author=pr_author,
            head_ref=head_ref,
            base_ref=base_ref,
            changed_files=changed_files,
            diff=diff[:10000],  # Truncate large diffs
        )
        rsp = await self._aask(prompt)
        return rsp


class ReleaseEngineer(VibeRole):
    """
    Release Engineer role - Production monitoring and automated fixes.

    Consolidates monitoring from all sources:
    - Sentry: Error triage, classification, issue creation
    - Langfuse: LLM anomaly detection
    - Health: Service availability monitoring
    - GitHub: PR creation, review, and merging

    Philosophy:
    > "Every PR MUST reference a GitHub issue."
    > "Classify before acting - don't create noise."
    > "Quantify impact - events, users, severity."
    """

    name: str = Field(default="Einstein")
    profile: str = Field(default="Release Engineer")
    goal: str = Field(
        default="Monitor production, triage issues, create fixes with proper issue tracking"
    )
    constraints: str = Field(
        default="Every PR must reference an issue. Classify issues before acting. Never ignore critical alerts."
    )
    temperature: float = Field(default=0.3)  # Low temp for precise analysis

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions(
            [
                MonitorSentry,
                MonitorLangfuse,
                MonitorHealth,
                TriageSentryIssue,
                CreateFixPR,
                WriteChangelog,
                ValidateRelease,
                ReviewPR,
            ]
        )
        self._watch([])

    # =====================
    # GitHub Helper Methods
    # =====================

    def _get_github_connector(self):
        """Get GitHub connector instance."""
        if not os.environ.get("GITHUB_TOKEN"):
            raise ValueError("GITHUB_TOKEN environment variable required")
        from vibeteam.connectors.github import GitHubConnector

        return GitHubConnector()

    async def create_github_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        """
        Create a GitHub issue.

        Args:
            title: Issue title
            body: Issue body (markdown)
            labels: Optional labels

        Returns:
            Created issue data with 'number' and 'html_url'
        """
        gh = self._get_github_connector()
        endpoint = f"/repos/{gh.owner}/{gh.repo}/issues"
        data: dict[str, Any] = {"title": title, "body": body}
        if labels:
            data["labels"] = labels
        return gh._post(endpoint, data)

    async def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "master",
        draft: bool = False,
    ) -> dict:
        """
        Create a pull request.

        Args:
            title: PR title (should include "Fixes #123")
            body: PR description (should include "Fixes #123")
            head: Source branch
            base: Target branch
            draft: Create as draft PR

        Returns:
            Created PR data
        """
        gh = self._get_github_connector()
        pr = gh.create_pr(title=title, body=body, head=head, base=base, draft=draft)
        return {
            "number": pr.number,
            "html_url": pr.html_url,
            "title": pr.title,
        }

    async def review_pr(
        self,
        pr_number: int,
        auto_submit: bool = False,
    ) -> dict:
        """
        Review a pull request.

        Args:
            pr_number: PR number to review
            auto_submit: Whether to submit the review to GitHub

        Returns:
            Review analysis and optionally submission result
        """
        gh = self._get_github_connector()

        # Get PR details
        pr = gh.get_pr(pr_number)
        diff = gh.get_pr_diff(pr_number)

        # Run review action
        action = ReviewPR()
        review_text = await action.run(
            pr_title=pr.title,
            pr_body=pr.body,
            pr_author=pr.user,
            head_ref=pr.head_ref,
            base_ref=pr.base_ref,
            changed_files=pr.changed_files,
            diff=diff,
        )

        result = {
            "pr_number": pr_number,
            "review": review_text,
            "submitted": False,
        }

        # Submit review if requested
        if auto_submit:
            # Parse verdict from review
            verdict = "COMMENT"
            if "**APPROVE**" in review_text or "APPROVE:" in review_text:
                verdict = "APPROVE"
            elif "**REQUEST_CHANGES**" in review_text or "REQUEST_CHANGES:" in review_text:
                verdict = "REQUEST_CHANGES"

            gh.create_review(
                pr_number=pr_number,
                body=review_text,
                event=verdict,
            )
            result["submitted"] = True
            result["verdict"] = verdict

        return result

    async def find_bugs_in_pr(self, pr_number: int) -> list[dict]:
        """
        Analyze a PR for potential bugs.

        Args:
            pr_number: PR number to analyze

        Returns:
            List of potential bugs found
        """
        gh = self._get_github_connector()

        # Get PR diff
        diff = gh.get_pr_diff(pr_number)
        files = gh.get_pr_files(pr_number)

        # Run review focused on bugs
        action = ReviewPR()
        pr = gh.get_pr(pr_number)

        review = await action.run(
            pr_title=pr.title,
            pr_body=pr.body,
            pr_author=pr.user,
            head_ref=pr.head_ref,
            base_ref=pr.base_ref,
            changed_files=pr.changed_files,
            diff=diff,
        )

        # Parse bugs from review (simple extraction)
        bugs = []
        if "Issues Found" in review:
            lines = review.split("\n")
            in_table = False
            for line in lines:
                if "| Severity |" in line:
                    in_table = True
                    continue
                if in_table and line.startswith("|") and "---" not in line:
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 4 and parts[0]:
                        bugs.append(
                            {
                                "severity": parts[0],
                                "file": parts[1],
                                "line": parts[2],
                                "issue": parts[3],
                            }
                        )
                elif in_table and not line.startswith("|"):
                    break

        return bugs

    async def merge_pr(
        self,
        pr_number: int,
        merge_method: str = "squash",
    ) -> dict:
        """
        Merge a pull request.

        Args:
            pr_number: PR number to merge
            merge_method: "merge", "squash", or "rebase"

        Returns:
            Merge result
        """
        gh = self._get_github_connector()
        return gh.merge_pr(pr_number, merge_method=merge_method)
