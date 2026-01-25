"""
ReliabilityEngineer Agent - Monitors production, handles incidents.

Embeds the full Production Engineering Protocol with health checks,
deployment verification, K8s commands, and incident response procedures.
OpenHands-based replacement for the MetaGPT ReliabilityEngineer role.
"""

from typing import Any

from vibeteam.agents.base import BaseVibeAgent
from vibeteam.tools.health import HealthCheckTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.sentry import SentryTool

# The Production Engineering Protocol
PROD_ENG_PROTOCOL = """
## Production Engineering Protocol

You are a Production Engineer responsible for system health, deployments, and incident response.

### Important URLs

| Resource | URL |
|----------|-----|
| Prod API | https://api.vibebrowser.app |
| Dev API | https://api-dev.vibebrowser.app |
| User Portal | https://portal.vibebrowser.app |
| Docs | https://docs.vibebrowser.app |
| Sentry Extension | https://vibetechnologies.sentry.io/projects/vibebrowserextension/ |
| Sentry API | https://vibetechnologies.sentry.io/projects/vibe-api-gateway/ |

### Release Readiness Criteria

ALL must pass for release:

| Check | Required Status |
|-------|-----------------|
| CI/CD Pipeline (master) | success |
| Deploy Subscription | success |
| Docs Deploy | success |
| api.vibebrowser.app | healthy |
| api-dev.vibebrowser.app | healthy |
| portal.vibebrowser.app | 200 |
| docs.vibebrowser.app | 200 |

### Critical Rules

1. **Always check docs/quality.md first** - Most up-to-date commands
2. **Report facts, not assumptions** - Run commands, report actual output
3. **Include timestamps** - All reports should have timestamps
4. **Quantify issues** - "3 errors in last 24h" not "some errors"
5. **Provide actionable recommendations** - What should be done next
"""


class ReliabilityEngineerAgent(BaseVibeAgent):
    """
    Reliability Engineer agent - keeps production healthy.

    Follows the Production Engineering Protocol with:
    - Health check commands and endpoints
    - GitHub Actions verification
    - Kubernetes commands
    - Sentry error monitoring
    - Release readiness criteria
    - Incident analysis framework

    Philosophy:
    > "Report facts, not assumptions."
    > "Quantify issues - '3 errors' not 'some errors'."
    > "Always provide actionable recommendations."
    """

    name = "Hawking"
    profile = "Reliability Engineer"
    goal = "Maintain 99.9% uptime and minimize incident impact"
    model = "azure/gpt-4.1"
    temperature = 0.2

    def __init__(self, **kwargs: Any):
        import os

        from vibeteam.agents.base import BaseTool

        tools: list[BaseTool] = []

        # Health check tool
        tools.append(HealthCheckTool())

        # Sentry for error monitoring
        if os.environ.get("SENTRY_AUTH_TOKEN"):
            try:
                tools.append(SentryTool())
            except Exception:
                pass

        # Langfuse for LLM monitoring
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                tools.append(LangfuseTool())
            except Exception:
                pass

        super().__init__(
            name=kwargs.get("name", self.name),
            profile=self.profile,
            goal=self.goal,
            model=kwargs.get("model", self.model),
            temperature=kwargs.get("temperature", self.temperature),
            tools=tools,
        )

    def _get_system_prompt(self) -> str:
        """Custom system prompt with Production Engineering Protocol."""
        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

{PROD_ENG_PROTOCOL}

Available tools: {', '.join(t.name for t in self.tools) if self.tools else 'None'}
"""

    async def check_system_health(self) -> str:
        """
        Check system health following Production Engineering Protocol.

        Returns:
            Health report with status of all services
        """
        prompt = """Check system health following the Production Engineering Protocol.

Use the health_check tool to check all endpoints.

Provide a status report with:
1. **Overall Status**: Healthy / Degraded / Down
2. **Component Status**: Each service with response codes
3. **Latency Analysis**: Response times (flag if > 500ms)
4. **Recommendations**: Immediate actions if needed

Use the Status Report Format from the protocol.
Include actual response codes and times, not assumptions."""

        return await self.run(prompt)

    async def verify_deployment(self, deployment_info: str) -> str:
        """
        Verify deployment success.

        Args:
            deployment_info: Information about the deployment

        Returns:
            Deployment verification report
        """
        prompt = f"""Verify this deployment following the Production Engineering Protocol.

## Deployment Info
{deployment_info}

## Verification Checklist

1. **Workflow Status**
   - GitHub Actions workflow completed successfully
   - No failed jobs in the pipeline

2. **Health Checks**
   - All endpoints responding
   - Response times normal
   - No new errors

3. **Functional Verification**
   - Core features working
   - API responses correct

4. **Rollback Readiness**
   - Previous version available
   - Rollback procedure documented

Provide verification report with SUCCESS / FAILED / PARTIAL status."""

        return await self.run(prompt)

    async def analyze_incident(self, incident: str, logs: str = "") -> str:
        """
        Analyze production incident.

        Args:
            incident: Description of the incident
            logs: Relevant logs if available

        Returns:
            Incident analysis
        """
        prompt = f"""Analyze this incident following the Production Engineering Protocol.

## Incident Details
{incident}

## Logs and Metrics
{logs}

## Incident Analysis Framework

### Step 1: Establish Timeline
- When did it start?
- When was it detected?
- When was it resolved?

### Step 2: Measure Impact
- Users affected
- Revenue impact (if measurable)
- Duration of impact

### Step 3: Root Cause Analysis (5 Whys)
1. Why did [symptom] happen?
2. Why did [cause 1] happen?
... continue

### Step 4: Contributing Factors
- What made detection slow?
- What made recovery slow?

### Step 5: Prevention
- Immediate fixes
- Long-term improvements
- Monitoring gaps to fill

Provide incident analysis:"""

        return await self.run(prompt)

    async def write_postmortem(self, summary: str, findings: str = "") -> str:
        """
        Write incident postmortem.

        Args:
            summary: Incident summary
            findings: Investigation findings

        Returns:
            Postmortem document
        """
        prompt = f"""Write a postmortem following the Production Engineering Protocol.

## Incident Summary
{summary}

## Investigation Findings
{findings}

## Postmortem Template

Include:
- Executive Summary (2-3 sentences)
- Impact (duration, users, revenue)
- Timeline (with UTC timestamps)
- Root Cause
- Contributing Factors
- What Went Well
- What Went Wrong
- Action Items (with priority, owner, due date)
- Lessons Learned

Write the postmortem:"""

        return await self.run(prompt)

    async def check_release_readiness(self, system_state: str = "") -> str:
        """
        Check if system is ready for release.

        Args:
            system_state: Current system state if known

        Returns:
            Release readiness report
        """
        prompt = f"""Check release readiness following the Production Engineering Protocol.

## Current System State
{system_state}

## Release Readiness Checklist

### Workflow Status (ALL must be success)
- [ ] CI/CD Pipeline (master)
- [ ] Deploy Subscription
- [ ] Docs Deploy

### Health Checks (ALL must be healthy)
- [ ] api.vibebrowser.app returns healthy
- [ ] api-dev.vibebrowser.app returns healthy
- [ ] portal.vibebrowser.app returns 200
- [ ] docs.vibebrowser.app returns 200

Use available tools to check status.
Provide verdict: READY or NOT READY with detailed reasoning."""

        return await self.run(prompt)
