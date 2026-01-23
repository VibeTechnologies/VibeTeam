"""
Release Engineer Role - Production Monitoring, Issue Triage, Auto-Fix PRs.

Consolidates monitoring responsibilities:
- Sentry error triage and issue creation
- Langfuse LLM anomaly detection
- Service health monitoring
- Automatic GitHub issue + PR creation

Critical Rule: Every PR MUST reference a GitHub issue.
"""

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


class ReleaseEngineer(VibeRole):
    """
    Release Engineer role - Production monitoring and automated fixes.

    Consolidates monitoring from all sources:
    - Sentry: Error triage, classification, issue creation
    - Langfuse: LLM anomaly detection
    - Health: Service availability monitoring

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
            ]
        )
        self._watch([])
