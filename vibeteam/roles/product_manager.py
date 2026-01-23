"""
Product Manager Role - Defines requirements, roadmap, and user stories.

Inspired by opencode agents pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class WritePRD(Action):
    """Write Product Requirements Document."""

    name: str = "WritePRD"

    PROMPT_TEMPLATE: str = """
You are a Product Manager. Based on the requirement, write a detailed PRD.

## Requirement
{requirement}

## PRD Format
1. **Overview**: Brief description of the feature/product
2. **Goals**: What we want to achieve
3. **User Stories**: As a [user], I want [feature], so that [benefit]
4. **Requirements**: Detailed functional requirements
5. **Non-functional Requirements**: Performance, security, scalability
6. **Success Metrics**: How we measure success
7. **Timeline**: Estimated phases and milestones

Write a comprehensive PRD:
"""

    async def run(self, requirement: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(requirement=requirement)
        rsp = await self._aask(prompt)
        return rsp


class WriteUserStories(Action):
    """Write detailed user stories from requirements."""

    name: str = "WriteUserStories"

    PROMPT_TEMPLATE: str = """
You are a Product Manager. Create detailed user stories from this PRD.

## PRD
{prd}

## User Story Format
For each story include:
- **ID**: US-XXX
- **Title**: Brief description
- **As a**: [user type]
- **I want**: [feature]
- **So that**: [benefit]
- **Acceptance Criteria**: Specific testable criteria
- **Priority**: High/Medium/Low
- **Story Points**: 1/2/3/5/8/13

Create user stories:
"""

    async def run(self, prd: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(prd=prd)
        rsp = await self._aask(prompt)
        return rsp


class PrioritizeBacklog(Action):
    """Prioritize and organize the product backlog."""

    name: str = "PrioritizeBacklog"

    PROMPT_TEMPLATE: str = """
You are a Product Manager. Prioritize these user stories for the next sprint.

## User Stories
{stories}

## Prioritization Criteria
- Business value
- User impact
- Technical dependencies
- Effort vs value ratio

Provide prioritized backlog with reasoning:
"""

    async def run(self, stories: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(stories=stories)
        rsp = await self._aask(prompt)
        return rsp


class ProductManager(VibeRole):
    """
    Product Manager role - owns product vision and requirements.

    Responsibilities:
    - Write PRDs from high-level requirements
    - Create detailed user stories
    - Prioritize backlog
    - Define success metrics
    - Communicate with stakeholders
    """

    name: str = Field(default="Alice")
    profile: str = Field(default="Product Manager")
    goal: str = Field(
        default="Define clear product requirements and roadmap that deliver user value"
    )
    constraints: str = Field(
        default="Focus on user needs, be data-driven, communicate clearly with engineering"
    )
    temperature: float = Field(default=0.4)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([WritePRD, WriteUserStories, PrioritizeBacklog])
        self._watch([])  # PM typically initiates work

    async def _act(self) -> Message:
        """Execute product management action."""
        todo = self.rc.todo

        if isinstance(todo, WritePRD):
            requirement = self.rc.memory.get_by_role("User")[-1].content
            result = await todo.run(requirement)
            msg = Message(content=result, role=self.profile, cause_by=type(todo))
            self.rc.memory.add(msg)
            return msg

        return await super()._act()
