"""
ReleaseEngineer Agent - Production Monitoring, Issue Triage, Auto-Fix PRs.

Consolidates monitoring responsibilities:
- Sentry error triage and issue creation
- Langfuse LLM anomaly detection
- Service health monitoring
- Automatic GitHub issue + PR creation
- Pull request review and code analysis

OpenHands-based replacement for the MetaGPT ReleaseEngineer role.
"""

import os
from typing import Any

from vibeteam.agents.base import BaseVibeAgent
from vibeteam.tools.github import GitHubTool
from vibeteam.tools.health import HealthCheckTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.sentry import SentryTool
from vibeteam.tools.transfer import get_transfer_tools_for_agent

# Release Engineer Protocol
RELEASE_ENGINEER_PROTOCOL = """
## Release Engineer Protocol

You are a Release Engineer responsible for production monitoring, issue triage, and automated fixes.

### Monitoring Sources

| Source | What to Monitor | Action |
|--------|-----------------|--------|
| **Sentry** | Unresolved errors | Classify (valid/noise), create GitHub issue |
| **Langfuse** | LLM anomalies (latency, errors, tokens) | Create GitHub issue with analysis |
| **Health** | API endpoints, response times | Alert on degradation |

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

### Critical Rules

1. **Every PR MUST reference a GitHub issue** - Use "Fixes #123" in description
2. **Classify before acting** - Don't create issues for noise
3. **Quantify impact** - Include event counts, user counts
4. **Provide actionable recommendations** - What should be fixed
5. **Link to source** - Include Sentry/Langfuse permalinks
"""


class ReleaseEngineerAgent(BaseVibeAgent):
    """
    Release Engineer agent - Production monitoring and automated fixes.

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

    name = "ReleaseEngineer"
    profile = "Release Engineer"
    goal = "Monitor production, triage issues, create fixes with proper issue tracking"

    def __init__(self, **kwargs: Any):
        from vibeteam.agents.base import BaseTool

        tools: list[BaseTool] = []

        # Add available tools based on environment
        if os.environ.get("GITHUB_TOKEN"):
            try:
                tools.append(GitHubTool())
            except Exception:
                pass

        if os.environ.get("SENTRY_AUTH_TOKEN"):
            try:
                tools.append(SentryTool())
            except Exception:
                pass

        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                tools.append(LangfuseTool())
            except Exception:
                pass

        # Health check tool doesn't need env vars
        tools.append(HealthCheckTool())

        # Transfer tools for handoffs to other agents
        tools.extend(get_transfer_tools_for_agent("release"))

        super().__init__(
            name=kwargs.get("name", self.name),
            profile=self.profile,
            goal=self.goal,
            model=kwargs.get("model", self.model),
            temperature=kwargs.get("temperature", self.temperature),
            tools=tools,
        )

    def _get_system_prompt(self) -> str:
        """Custom system prompt with Release Engineer Protocol."""
        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

{RELEASE_ENGINEER_PROTOCOL}

## TEAM COLLABORATION

When you need help or have completed a deployment, use the transfer tools:
- **transfer_to_supervisor**: Report deployment status, ask for prioritization
- **transfer_to_swe**: Request bug fixes before deployment, escalate code issues
- **transfer_to_support**: Notify about deployments that affect customers

When you transfer, include:
1. Deployment/release details
2. Any issues or risks identified
3. Health check results

Available tools: {", ".join(t.name for t in self.tools) if self.tools else "None"}
"""

    async def monitor_sentry(self, hours: int = 24) -> str:
        """
        Monitor Sentry for unresolved issues and classify them.

        Args:
            hours: Time window in hours

        Returns:
            Analysis of Sentry issues
        """
        prompt = f"""Monitor Sentry for production issues.

Use the sentry tool to fetch unresolved issues from the last {hours} hours.

For each issue:
1. **Classify**: Is this a valid bug or noise?
2. **Decide Action**:
   - Valid bug: Recommend creating GitHub issue
   - Noise: Recommend auto-resolution with reason

Use the noise patterns from the protocol to classify.
Include event counts, user counts, and severity in your analysis."""

        return await self.run(prompt)

    async def monitor_langfuse(self, hours: int = 1) -> str:
        """
        Monitor Langfuse for LLM anomalies.

        Args:
            hours: Time window in hours

        Returns:
            Analysis of Langfuse anomalies
        """
        prompt = f"""Monitor Langfuse for LLM performance issues.

Use the langfuse tool to:
1. Get stats for the last {hours} hours
2. Detect anomalies

For each anomaly:
1. **Analyze** root cause
2. **Determine severity** (warning vs critical)
3. **Recommend action** (create issue, monitor, or ignore)
4. **Suggest fix** if possible"""

        return await self.run(prompt)

    async def check_health(self) -> str:
        """
        Check health of all services.

        Returns:
            Health status report
        """
        prompt = """Check the health of all production services.

Use the health_check tool to:
1. Check all endpoints
2. Get any alerts

Provide a status report with:
- Overall status (healthy, degraded, down)
- Status of each service
- Any issues requiring action
- Recommendations"""

        return await self.run(prompt)

    async def review_pr(self, pr_number: int) -> str:
        """
        Review a pull request.

        Args:
            pr_number: PR number to review

        Returns:
            Code review analysis
        """
        prompt = f"""Review pull request #{pr_number}.

Use the github tool to get PR details.

Perform a thorough code review checking:
1. **Correctness**: Does the code do what it claims?
2. **Bugs**: Any potential bugs, edge cases, or null pointer issues?
3. **Security**: Any security concerns (injection, XSS, secrets)?
4. **Performance**: Any performance issues?
5. **Style**: Does it follow project conventions?
6. **Tests**: Are changes adequately tested?
7. **Issue Reference**: Does PR reference a GitHub issue?

Provide verdict: APPROVE, REQUEST_CHANGES, or COMMENT with reasoning."""

        return await self.run(prompt)

    async def create_fix_pr(self, issue_number: int, fix_description: str) -> str:
        """
        Create a PR to fix an issue.

        Args:
            issue_number: GitHub issue number to fix
            fix_description: Description of the fix

        Returns:
            PR creation guidance
        """
        prompt = f"""Create a PR to fix issue #{issue_number}.

Fix description: {fix_description}

The PR MUST:
1. Reference the issue - "Fixes #{issue_number}" in description
2. Implement minimal, focused change
3. Include tests if applicable
4. Document the change clearly

Provide:
1. Suggested branch name
2. PR title
3. PR description
4. Key code changes needed"""

        return await self.run(prompt)

    async def validate_release(self) -> str:
        """
        Validate release readiness.

        Returns:
            Release readiness report
        """
        prompt = """Validate release readiness.

Check all criteria:

### Workflow Status (ALL must be success)
- CI/CD Pipeline (master)
- Deploy Subscription
- Docs Deploy

### Health Checks (ALL must be healthy)
- api.vibebrowser.app
- api-dev.vibebrowser.app
- portal.vibebrowser.app
- docs.vibebrowser.app

Use available tools to check status.
Provide verdict: READY or NOT READY with detailed reasoning."""

        return await self.run(prompt)
