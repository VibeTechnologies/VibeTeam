"""
Reliability Engineer Role - Monitors production, handles incidents.

Based on opencode prod-eng agent pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class CheckSystemHealth(Action):
    """Check system health status."""

    name: str = "CheckSystemHealth"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer. Analyze system health.

## Health Check Data
{health_data}

## Endpoints to Check
{endpoints}

## Analysis Required
1. **Overall Status**: Healthy / Degraded / Down
2. **Component Status**: Each service status
3. **Latency Analysis**: Response times
4. **Error Rates**: Current error percentages
5. **Resource Usage**: CPU, memory, disk
6. **Recommendations**: Immediate actions if needed

Provide health report:
"""

    async def run(self, health_data: str, endpoints: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(health_data=health_data, endpoints=endpoints)
        rsp = await self._aask(prompt)
        return rsp


class AnalyzeIncident(Action):
    """Analyze production incident."""

    name: str = "AnalyzeIncident"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer. Analyze this incident.

## Incident Details
{incident}

## Logs and Metrics
{logs}

## Incident Analysis
1. **Timeline**: When did it start, key events
2. **Impact**: Users affected, severity
3. **Root Cause**: What caused the issue
4. **Contributing Factors**: What made it worse
5. **Mitigation**: How to stop the bleeding
6. **Prevention**: How to prevent recurrence

Provide incident analysis:
"""

    async def run(self, incident: str, logs: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(incident=incident, logs=logs)
        rsp = await self._aask(prompt)
        return rsp


class WritePostmortem(Action):
    """Write incident postmortem."""

    name: str = "WritePostmortem"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer. Write an incident postmortem.

## Incident Summary
{summary}

## Investigation Findings
{findings}

## Postmortem Format
1. **Executive Summary**: Brief overview
2. **Impact**: Duration, users affected, business impact
3. **Timeline**: Detailed sequence of events
4. **Root Cause Analysis**: 5 Whys or similar
5. **Lessons Learned**: What we discovered
6. **Action Items**: Specific, assigned, with deadlines
7. **Metrics to Track**: How we measure improvement

Write postmortem:
"""

    async def run(self, summary: str, findings: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(summary=summary, findings=findings)
        rsp = await self._aask(prompt)
        return rsp


class CreateRunbook(Action):
    """Create operational runbook."""

    name: str = "CreateRunbook"

    PROMPT_TEMPLATE: str = """
You are a Reliability Engineer. Create a runbook.

## Scenario
{scenario}

## System Context
{context}

## Runbook Format
1. **Title**: Clear, searchable name
2. **Purpose**: When to use this runbook
3. **Prerequisites**: Required access, tools
4. **Steps**: Numbered, specific actions
5. **Verification**: How to confirm success
6. **Rollback**: How to undo if needed
7. **Escalation**: When and who to contact

Write runbook:
"""

    async def run(self, scenario: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(scenario=scenario, context=context)
        rsp = await self._aask(prompt)
        return rsp


class ReliabilityEngineer(VibeRole):
    """
    Reliability Engineer role - keeps production healthy.
    
    Responsibilities:
    - Monitor system health
    - Analyze and respond to incidents
    - Write postmortems
    - Create runbooks
    - Improve reliability metrics
    """

    name: str = Field(default="Eve")
    profile: str = Field(default="Reliability Engineer")
    goal: str = Field(default="Maintain 99.9% uptime and minimize incident impact")
    constraints: str = Field(
        default="Prioritize user impact, document everything, learn from failures"
    )
    temperature: float = Field(default=0.2)  # Low temp for precise analysis

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([
            CheckSystemHealth,
            AnalyzeIncident,
            WritePostmortem,
            CreateRunbook,
        ])
        self._watch([])
