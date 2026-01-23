"""
Support Engineer Role - Handles user issues, documentation, and FAQ.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class AnalyzeUserIssue(Action):
    """Analyze and categorize user issue."""

    name: str = "AnalyzeUserIssue"

    PROMPT_TEMPLATE: str = """
You are a Support Engineer. Analyze this user issue.

## User Report
{issue}

## Analysis Required
1. **Category**: Bug / Feature Request / Question / Documentation Gap
2. **Severity**: Critical / High / Medium / Low
3. **Affected Component**: Which part of the system
4. **Root Cause Hypothesis**: What might be causing this
5. **Immediate Workaround**: If any
6. **Recommended Action**: Next steps

Provide analysis:
"""

    async def run(self, issue: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(issue=issue)
        rsp = await self._aask(prompt)
        return rsp


class WriteUserResponse(Action):
    """Write helpful response to user."""

    name: str = "WriteUserResponse"

    PROMPT_TEMPLATE: str = """
You are a Support Engineer. Write a helpful response.

## User Issue
{issue}

## Analysis
{analysis}

## Response Guidelines
- Acknowledge the issue
- Be empathetic and professional
- Provide clear steps or solutions
- Set expectations for resolution
- Offer alternatives if needed

Write response:
"""

    async def run(self, issue: str, analysis: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(issue=issue, analysis=analysis)
        rsp = await self._aask(prompt)
        return rsp


class WriteDocumentation(Action):
    """Write or update documentation."""

    name: str = "WriteDocumentation"

    PROMPT_TEMPLATE: str = """
You are a Support Engineer. Write clear documentation.

## Topic
{topic}

## Context
{context}

## Documentation Standards
- Clear, concise language
- Step-by-step instructions
- Include examples
- Note common pitfalls
- Add troubleshooting tips

Write documentation:
"""

    async def run(self, topic: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(topic=topic, context=context)
        rsp = await self._aask(prompt)
        return rsp


class CreateFAQEntry(Action):
    """Create FAQ entry from common issues."""

    name: str = "CreateFAQEntry"

    PROMPT_TEMPLATE: str = """
You are a Support Engineer. Create a FAQ entry.

## Common Issue Pattern
{pattern}

## Example Cases
{examples}

## FAQ Format
- **Question**: Clear, searchable question
- **Short Answer**: One-sentence summary
- **Detailed Answer**: Full explanation with steps
- **Related Topics**: Links to related docs

Create FAQ entry:
"""

    async def run(self, pattern: str, examples: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(pattern=pattern, examples=examples)
        rsp = await self._aask(prompt)
        return rsp


class SupportEngineer(VibeRole):
    """
    Support Engineer role - bridge between users and engineering.
    
    Responsibilities:
    - Analyze user issues
    - Write helpful responses
    - Create/update documentation
    - Build FAQ from patterns
    - Escalate critical issues
    """

    name: str = Field(default="Diana")
    profile: str = Field(default="Support Engineer")
    goal: str = Field(default="Help users succeed and improve product through feedback")
    constraints: str = Field(
        default="Be empathetic, respond promptly, document patterns for improvement"
    )
    temperature: float = Field(default=0.4)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([
            AnalyzeUserIssue,
            WriteUserResponse,
            WriteDocumentation,
            CreateFAQEntry,
        ])
        self._watch([])
