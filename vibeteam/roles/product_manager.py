"""
Product Manager Role - Defines requirements, roadmap, and user stories.

Inspired by opencode agents pattern with MetaGPT integration.
"""

import json
import os
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


class ProcessFeatureRequest(Action):
    """
    Analyze customer feature request and update tracking issue.

    This action:
    1. Analyzes the request using LLM
    2. Scores priority (P0-P3)
    3. Extracts key details
    4. Updates the Customer Requests GitHub issue table
    5. Returns analysis summary
    """

    name: str = "ProcessFeatureRequest"

    PROMPT_TEMPLATE: str = """
You are a Product Manager for VibeBrowser, an AI-powered browser automation extension.

Analyze this customer feature request:

## Request
{request}

## Source
{source}

## VibeBrowser Context
VibeBrowser is a Chrome extension that:
- Uses AI to understand natural language commands
- Automates browser tasks (clicking, typing, navigation)
- Integrates with external tools via MCP (Model Context Protocol)
- Supports voice input for hands-free operation

## Your Task
Analyze this request and provide:

1. **Priority** (choose one):
   - P0: Critical - blocks major use cases, many users affected
   - P1: High - significant user value, clear demand
   - P2: Medium - nice to have, moderate user value
   - P3: Low - future consideration, limited demand

2. **Short Summary** (max 50 chars): Brief description for the tracking table

3. **Analysis** (2-3 sentences): Why this priority? What's the user need? Implementation complexity?

4. **Status**: Always "Analyzing" for new requests

Respond in this exact JSON format:
```json
{{
    "priority": "P1",
    "summary": "Notion.so integration for note sync",
    "analysis": "High value integration. Notion is popular among power users. Moderate complexity via API.",
    "status": "Analyzing"
}}
```
"""

    async def run(self, request: str, source: str = "docs-chat") -> dict:
        """
        Process a feature request.

        Args:
            request: The feature request text
            source: Where it came from (docs-chat, email, etc.)

        Returns:
            Dict with priority, summary, analysis, status
        """
        prompt = self.PROMPT_TEMPLATE.format(request=request, source=source)
        rsp = await self._aask(prompt)

        # Parse JSON from response
        try:
            # Extract JSON from markdown code block if present
            if "```json" in rsp:
                json_str = rsp.split("```json")[1].split("```")[0].strip()
            elif "```" in rsp:
                json_str = rsp.split("```")[1].split("```")[0].strip()
            else:
                json_str = rsp.strip()

            result = json.loads(json_str)
            return result
        except (json.JSONDecodeError, IndexError):
            # Fallback if parsing fails
            return {
                "priority": "P2",
                "summary": request[:50],
                "analysis": rsp[:200],
                "status": "Analyzing",
            }


class ProductManager(VibeRole):
    """
    Product Manager role - owns product vision and requirements.

    Responsibilities:
    - Write PRDs from high-level requirements
    - Create detailed user stories
    - Prioritize backlog
    - Process customer feature requests
    - Define success metrics
    - Communicate with stakeholders
    """

    name: str = Field(default="Curie")
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
        self.set_actions(
            [WritePRD, WriteUserStories, PrioritizeBacklog, ProcessFeatureRequest]
        )
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

    async def process_feature_request(
        self,
        request: str,
        source: str = "docs-chat",
        update_github: bool = True,
    ) -> dict:
        """
        Process a customer feature request.

        Args:
            request: The feature request text
            source: Where it came from (docs-chat, email, support, etc.)
            update_github: Whether to update the GitHub tracking issue

        Returns:
            Dict with analysis results
        """
        # Run the analysis action
        action = ProcessFeatureRequest()
        result = await action.run(request, source)

        # Update GitHub issue if enabled
        if update_github and os.environ.get("GITHUB_TOKEN"):
            try:
                from vibeteam.connectors.github import GitHubConnector

                gh = GitHubConnector()
                gh.add_customer_request(
                    request=result.get("summary", request[:50]),
                    source=source,
                    priority=result.get("priority", "P2"),
                    status=result.get("status", "Analyzing"),
                    analysis=result.get("analysis", "")[:100],  # Truncate for table
                )
                result["github_updated"] = True
            except Exception as e:
                result["github_updated"] = False
                result["github_error"] = str(e)

        return result
