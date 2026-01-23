"""
Reliability Engineer Role - Monitors production, handles incidents.

Embeds the full Production Engineering Protocol with health checks,
deployment verification, K8s commands, and incident response procedures.
Based on opencode prod-eng agent pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from pydantic import Field

from vibeteam.roles.base import VibeRole

# The Production Engineering Protocol - embedded in all SRE actions
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
| GitHub Actions | https://github.com/VibeTechnologies/VibeWebAgent/actions |
| Stripe Dashboard | https://dashboard.stripe.com |

### Quick Health Check Commands

```bash
# All APIs health check
echo "=== API Health ===" && \\
curl -s https://api.vibebrowser.app/health && echo && \\
curl -s https://api-dev.vibebrowser.app/health && echo && \\
curl -s https://docs.vibebrowser.app/api/health && echo && \\
echo "=== Portal Status ===" && \\
curl -s -o /dev/null -w "portal.vibebrowser.app: %{http_code}\\n" https://portal.vibebrowser.app
```

### GitHub Actions Status

```bash
# CI/CD Pipeline status
gh run list --repo VibeTechnologies/VibeWebAgent --workflow="CI/CD Pipeline" --limit 5

# Subscription service deployments
gh run list --repo VibeTechnologies/VibeWebAgent --workflow="Deploy Subscription Services" --limit 5

# Docs portal deployments
gh run list --repo VibeTechnologies/VibeWebAgent --workflow="Docs Deploy" --limit 5
```

### Sentry Error Check

```bash
# Check for unresolved errors (requires SENTRY_AUTH_TOKEN)
sentry-cli issues list --project vibebrowserextension --query "is:unresolved age:-24h"
sentry-cli issues list --project vibe-api-gateway --query "is:unresolved age:-24h"
```

### Kubernetes Commands

```bash
export KUBECONFIG=~/.kube/k3s-config

# Pod status
kubectl -n vibe get pods
kubectl -n vibe-dev get pods

# Recent logs
kubectl -n vibe logs deployment/stripe-service --tail=100

# Resource usage
kubectl -n vibe top pods
```

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
| LLM API with valid key | 200 + response |
| Extension E2E test | PASSED |

### LLM API Authentication Test

```bash
# Test actual LLM API (not just health endpoint)
curl -s "https://api.vibebrowser.app/v1/chat/completions" \\
  -H "Authorization: Bearer USER_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-5-mini","messages":[{"role":"user","content":"hi"}]}'
```

### Status Report Format

```markdown
# Production Status Report

**Timestamp:** YYYY-MM-DD HH:MM UTC

## Health Check Summary

| Service | Status | Response |
|---------|--------|----------|
| api.vibebrowser.app | OK/FAIL | 200/401/500 |
| api-dev.vibebrowser.app | OK/FAIL | 200/401/500 |
| portal.vibebrowser.app | OK/FAIL | 200/500 |
| docs.vibebrowser.app | OK/FAIL | 200/500 |

## Deployment Status

| Workflow | Last Run | Status | Time |
|----------|----------|--------|------|
| CI/CD Pipeline | #12345 | success/failure | 5m ago |

## Errors (Last 24h)

| Project | Unresolved Issues |
|---------|-------------------|
| vibebrowserextension | 0 |
| vibe-api-gateway | 0 |

## Issues Found
1. Issue description

## Recommendations
1. Action to take
```

### Critical Rules

1. **Always check docs/quality.md first** - Most up-to-date commands
2. **Report facts, not assumptions** - Run commands, report actual output
3. **Include timestamps** - All reports should have timestamps
4. **Quantify issues** - "3 errors in last 24h" not "some errors"
5. **Provide actionable recommendations** - What should be done next
"""


class CheckSystemHealth(Action):
    """Check system health following Production Engineering Protocol."""

    name: str = "CheckSystemHealth"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer following the Production Engineering Protocol.

{protocol}

## Health Check Data
{health_data}

## Endpoints to Check
{endpoints}

## Analysis Required

1. **Overall Status**: Healthy / Degraded / Down
2. **Component Status**: Each service status with response codes
3. **Latency Analysis**: Response times (flag if > 500ms)
4. **Error Rates**: Current error percentages
5. **Resource Usage**: CPU, memory, disk if available
6. **Recommendations**: Immediate actions if needed

## Output Format

Use the Status Report Format from the protocol.
Include actual response codes and times, not assumptions.

Provide health report:
"""

    async def run(self, health_data: str, endpoints: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL, health_data=health_data, endpoints=endpoints
        )
        rsp = await self._aask(prompt)
        return rsp


class VerifyDeployment(Action):
    """Verify deployment success following Production Engineering Protocol."""

    name: str = "VerifyDeployment"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer verifying a deployment following the Production Engineering Protocol.

{protocol}

## Deployment Info
{deployment_info}

## Workflow Status
{workflow_status}

## Verification Checklist

1. **Workflow Status**
   - [ ] GitHub Actions workflow completed successfully
   - [ ] No failed jobs in the pipeline
   - [ ] Artifacts uploaded (if applicable)

2. **Health Checks**
   - [ ] All endpoints responding
   - [ ] Response times normal
   - [ ] No new errors in Sentry

3. **Functional Verification**
   - [ ] Core features working
   - [ ] API responses correct
   - [ ] No regressions detected

4. **Rollback Readiness**
   - [ ] Previous version available
   - [ ] Rollback procedure documented

## Output Format

```markdown
## Deployment Verification Report

**Deployment:** [service name]
**Timestamp:** YYYY-MM-DD HH:MM UTC
**Status:** SUCCESS / FAILED / PARTIAL

### Workflow
- Run ID: #12345
- Duration: Xm Ys
- Result: success/failure

### Health Checks
| Endpoint | Status | Response Time |
|----------|--------|---------------|
| ... | ... | ... |

### Issues Found
1. Issue (if any)

### Recommendation
[Next action]
```

Verify the deployment:
"""

    async def run(self, deployment_info: str, workflow_status: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL,
            deployment_info=deployment_info,
            workflow_status=workflow_status,
        )
        rsp = await self._aask(prompt)
        return rsp


class AnalyzeIncident(Action):
    """Analyze production incident following Production Engineering Protocol."""

    name: str = "AnalyzeIncident"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer analyzing an incident following the Production Engineering Protocol.

{protocol}

## Incident Details
{incident}

## Logs and Metrics
{logs}

## Incident Analysis Framework

### Step 1: Establish Timeline
- When did it start? (exact timestamp)
- When was it detected?
- When was it resolved?

### Step 2: Measure Impact
- Users affected (number)
- Revenue impact (if measurable)
- Duration of impact

### Step 3: Root Cause Analysis (5 Whys)
1. Why did [symptom] happen?
2. Why did [cause 1] happen?
3. Why did [cause 2] happen?
4. Why did [cause 3] happen?
5. Why did [cause 4] happen?

### Step 4: Contributing Factors
- What made detection slow?
- What made recovery slow?
- What made impact worse?

### Step 5: Prevention
- Immediate fixes
- Long-term improvements
- Monitoring gaps to fill

## Output Format

```markdown
## Incident Analysis

**Incident:** [Brief description]
**Severity:** SEV1/SEV2/SEV3
**Duration:** Xh Ym

### Timeline
- HH:MM - Event 1
- HH:MM - Event 2

### Impact
- X users affected
- Y minutes of downtime

### Root Cause
[One sentence summary]

### 5 Whys Analysis
1. ...
2. ...

### Action Items
| Priority | Action | Owner | Due |
|----------|--------|-------|-----|
| P0 | ... | ... | ... |
```

Analyze the incident:
"""

    async def run(self, incident: str, logs: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL, incident=incident, logs=logs
        )
        rsp = await self._aask(prompt)
        return rsp


class WritePostmortem(Action):
    """Write incident postmortem following Production Engineering Protocol."""

    name: str = "WritePostmortem"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer writing a postmortem following the Production Engineering Protocol.

{protocol}

## Incident Summary
{summary}

## Investigation Findings
{findings}

## Postmortem Template

```markdown
# Incident Postmortem: [Title]

**Date:** YYYY-MM-DD
**Author:** [Name]
**Status:** Draft / Final

## Executive Summary

[2-3 sentences: what happened, impact, resolution]

## Impact

| Metric | Value |
|--------|-------|
| Duration | Xh Ym |
| Users Affected | N |
| Revenue Impact | $X (if applicable) |
| SLA Breached | Yes/No |

## Timeline (All times UTC)

| Time | Event |
|------|-------|
| HH:MM | ... |

## Root Cause

[Technical explanation of what went wrong]

## Contributing Factors

1. Factor 1
2. Factor 2

## What Went Well

1. Good thing 1
2. Good thing 2

## What Went Wrong

1. Bad thing 1
2. Bad thing 2

## Action Items

| Priority | Action | Owner | Status | Due Date |
|----------|--------|-------|--------|----------|
| P0 | ... | ... | ... | ... |

## Lessons Learned

1. Lesson 1
2. Lesson 2

## Appendix

[Links to dashboards, logs, etc.]
```

Write the postmortem:
"""

    async def run(self, summary: str, findings: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL, summary=summary, findings=findings
        )
        rsp = await self._aask(prompt)
        return rsp


class CreateRunbook(Action):
    """Create operational runbook following Production Engineering Protocol."""

    name: str = "CreateRunbook"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer creating a runbook following the Production Engineering Protocol.

{protocol}

## Scenario
{scenario}

## System Context
{context}

## Runbook Template

```markdown
# Runbook: [Title]

**Last Updated:** YYYY-MM-DD
**Owner:** [Team/Person]
**Review Cadence:** Quarterly

## Purpose

When to use this runbook:
- Trigger condition 1
- Trigger condition 2

## Prerequisites

- [ ] Access to [system]
- [ ] Tools installed: [list]
- [ ] Credentials available for [service]

## Steps

### 1. [First Step Name]

**Purpose:** Why we do this

**Command:**
```bash
# Actual command
```

**Expected Output:**
```
What success looks like
```

**If Failed:** Go to Troubleshooting section

### 2. [Second Step Name]
...

## Verification

How to confirm the runbook succeeded:

1. Check [metric/endpoint]
2. Verify [condition]
3. Confirm [state]

## Rollback

If something goes wrong:

1. Step 1
2. Step 2

## Escalation

If runbook fails or situation unclear:

| Severity | Contact | Method |
|----------|---------|--------|
| SEV1 | On-call | PagerDuty |
| SEV2 | Team Lead | Slack |

## Troubleshooting

### Issue: [Common Problem 1]
**Solution:** [How to fix]

### Issue: [Common Problem 2]
**Solution:** [How to fix]

## Related Runbooks

- [Link to related runbook 1]
- [Link to related runbook 2]
```

Create the runbook:
"""

    async def run(self, scenario: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL, scenario=scenario, context=context
        )
        rsp = await self._aask(prompt)
        return rsp


class CheckReleaseReadiness(Action):
    """Check if system is ready for release following Production Engineering Protocol."""

    name: str = "CheckReleaseReadiness"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer checking release readiness following the Production Engineering Protocol.

{protocol}

## Current System State
{system_state}

## Pending Changes
{changes}

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

### Authentication Test
- [ ] LLM API accepts valid user key
- [ ] Returns actual response (not just 200)

### E2E Test
- [ ] Extension loads in browser
- [ ] User can authenticate
- [ ] Agent can execute tools

## Output Format

```markdown
# Release Readiness Report

**Timestamp:** YYYY-MM-DD HH:MM UTC
**Verdict:** READY / NOT READY

## Checklist Status

| Check | Status | Notes |
|-------|--------|-------|
| CI/CD Pipeline | PASS/FAIL | ... |
| Deploy Subscription | PASS/FAIL | ... |
| ... | ... | ... |

## Blocking Issues

1. [Issue if any]

## Recommendation

[PROCEED / HOLD - with reason]
```

Check release readiness:
"""

    async def run(self, system_state: str, changes: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=PROD_ENG_PROTOCOL, system_state=system_state, changes=changes
        )
        rsp = await self._aask(prompt)
        return rsp


class ReliabilityEngineer(VibeRole):
    """
    Reliability Engineer role - keeps production healthy.

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

    name: str = Field(default="Hawking")
    profile: str = Field(default="Reliability Engineer")
    goal: str = Field(default="Maintain 99.9% uptime and minimize incident impact")
    constraints: str = Field(
        default="Report facts not assumptions, quantify everything, always verify before declaring ready"
    )
    temperature: float = Field(default=0.2)  # Low temp for precise analysis

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions(
            [
                CheckSystemHealth,
                VerifyDeployment,
                AnalyzeIncident,
                WritePostmortem,
                CreateRunbook,
                CheckReleaseReadiness,
            ]
        )
        self._watch([])
