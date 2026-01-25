"""
ProductManager Agent - Defines requirements, roadmap, and user stories.

OpenHands-based replacement for the MetaGPT ProductManager role.
"""

import json
import os
from typing import Any

from vibeteam.agents.base import BaseTool, BaseVibeAgent, ToolResult
from vibeteam.tools.github import GitHubTool


class ProcessFeatureRequestTool(BaseTool):
    """Tool for analyzing and processing feature requests."""

    name = "process_feature_request"
    description = "Analyze customer feature request and determine priority"

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "The feature request text",
                        },
                        "source": {
                            "type": "string",
                            "description": "Where the request came from (docs-chat, email, etc.)",
                        },
                    },
                    "required": ["request"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Process feature request - returns structured analysis."""
        request = kwargs.get("request", "")
        source = kwargs.get("source", "unknown")

        # This tool provides the prompt template for analysis
        # The actual LLM call happens through the agent
        return ToolResult(
            success=True,
            output=json.dumps(
                {
                    "request": request,
                    "source": source,
                    "instruction": "Analyze this feature request and provide priority (P0-P3), summary, and analysis.",
                }
            ),
        )


class ProductManagerAgent(BaseVibeAgent):
    """
    Product Manager agent - owns product vision and requirements.

    Responsibilities:
    - Write PRDs from high-level requirements
    - Create detailed user stories
    - Prioritize backlog
    - Process customer feature requests
    - Define success metrics
    - Communicate with stakeholders
    """

    name = "Curie"
    profile = "Product Manager"
    goal = "Define clear product requirements and roadmap that deliver user value"
    model = "azure/gpt-5-2"
    temperature = 0.4

    # Feature request analysis prompt
    FEATURE_REQUEST_PROMPT = """
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

    def __init__(self, **kwargs: Any):
        # Initialize with GitHub tool
        tools = []
        if os.environ.get("GITHUB_TOKEN"):
            try:
                tools.append(GitHubTool())
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
        """Custom system prompt for Product Manager."""
        return f"""You are {self.name}, a {self.profile} for VibeBrowser.

Goal: {self.goal}

You are part of the VibeTeam, an autonomous AI team for SaaS development.

Your responsibilities:
1. Write PRDs from high-level requirements
2. Create detailed user stories with acceptance criteria
3. Prioritize the product backlog
4. Process and analyze customer feature requests
5. Define success metrics for features
6. Communicate clearly with engineering

Guidelines:
- Focus on user needs and value delivery
- Be data-driven in prioritization decisions
- Write clear, actionable requirements
- Consider technical feasibility when scoping

Available tools: {', '.join(t.name for t in self.tools) if self.tools else 'None'}
"""

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
        # Build the analysis prompt
        prompt = self.FEATURE_REQUEST_PROMPT.format(request=request, source=source)

        # Run through the agent
        response = await self.run(prompt)

        # Parse JSON from response
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()

            result = json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            result = {
                "priority": "P2",
                "summary": request[:50],
                "analysis": response[:200],
                "status": "Analyzing",
            }

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
                    analysis=result.get("analysis", "")[:100],
                )
                result["github_updated"] = True
            except Exception as e:
                result["github_updated"] = False
                result["github_error"] = str(e)

        return result

    async def write_prd(self, requirement: str) -> str:
        """
        Write a Product Requirements Document.

        Args:
            requirement: High-level requirement description

        Returns:
            PRD document as markdown
        """
        prompt = f"""Based on this requirement, write a detailed PRD.

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

Write a comprehensive PRD:"""

        return await self.run(prompt)

    async def write_user_stories(self, prd: str) -> str:
        """
        Write detailed user stories from a PRD.

        Args:
            prd: Product Requirements Document

        Returns:
            User stories as markdown
        """
        prompt = f"""Create detailed user stories from this PRD.

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

Create user stories:"""

        return await self.run(prompt)

    async def prioritize_backlog(self, stories: str) -> str:
        """
        Prioritize user stories for the next sprint.

        Args:
            stories: List of user stories

        Returns:
            Prioritized backlog as markdown
        """
        prompt = f"""Prioritize these user stories for the next sprint.

## User Stories
{stories}

## Prioritization Criteria
- Business value
- User impact
- Technical dependencies
- Effort vs value ratio

Provide prioritized backlog with reasoning:"""

        return await self.run(prompt)
