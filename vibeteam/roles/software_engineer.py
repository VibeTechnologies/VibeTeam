"""
Software Engineer Role - Implements features, fixes bugs, writes tests.

Based on opencode torvalds agent pattern with MetaGPT integration.
"""

from typing import Any

from metagpt.actions import Action
from metagpt.schema import Message
from pydantic import Field

from vibeteam.roles.base import VibeRole


class WriteCode(Action):
    """Write production code based on requirements."""

    name: str = "WriteCode"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer. Write clean, production-ready code.

## Task
{task}

## Context
{context}

## Guidelines
1. Write clean, readable code with proper naming
2. Follow SOLID principles
3. Add appropriate error handling
4. Include type hints (Python) or types (TypeScript)
5. Write docstrings/comments for complex logic
6. Consider edge cases

Write the implementation:
"""

    async def run(self, task: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(task=task, context=context)
        rsp = await self._aask(prompt)
        return rsp


class WriteTests(Action):
    """Write comprehensive tests for code."""

    name: str = "WriteTests"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer. Write comprehensive tests.

## Code to Test
{code}

## Testing Guidelines
1. Test happy path scenarios
2. Test edge cases and error conditions
3. Use descriptive test names
4. Follow AAA pattern (Arrange, Act, Assert)
5. Mock external dependencies
6. Aim for high coverage

Write the tests:
"""

    async def run(self, code: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(code=code)
        rsp = await self._aask(prompt)
        return rsp


class ReviewCode(Action):
    """Review code for quality and improvements."""

    name: str = "ReviewCode"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer doing code review.

## Code to Review
{code}

## Review Checklist
1. Code correctness and logic
2. Error handling
3. Performance considerations
4. Security issues
5. Code style and readability
6. Test coverage
7. Documentation

Provide detailed review with actionable feedback:
"""

    async def run(self, code: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(code=code)
        rsp = await self._aask(prompt)
        return rsp


class FixBug(Action):
    """Analyze and fix bugs in code."""

    name: str = "FixBug"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer debugging an issue.

## Bug Report
{bug_report}

## Relevant Code
{code}

## Debugging Process
1. Understand the expected vs actual behavior
2. Identify root cause
3. Propose fix with explanation
4. Consider regression risks
5. Suggest tests to prevent recurrence

Provide analysis and fix:
"""

    async def run(self, bug_report: str, code: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(bug_report=bug_report, code=code)
        rsp = await self._aask(prompt)
        return rsp


class SoftwareEngineer(VibeRole):
    """
    Software Engineer role - implements features and maintains code quality.
    
    Responsibilities:
    - Write production-ready code
    - Write comprehensive tests
    - Review code from peers
    - Fix bugs and issues
    - Refactor for maintainability
    
    Follows Linus Torvalds philosophy:
    "Talk is cheap. Show me the code."
    """

    name: str = Field(default="Bob")
    profile: str = Field(default="Software Engineer")
    goal: str = Field(default="Write high-quality, maintainable code that solves real problems")
    constraints: str = Field(
        default="Follow coding standards, write tests, never push broken code"
    )
    temperature: float = Field(default=0.2)  # Lower temp for precise code

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([WriteCode, WriteTests, ReviewCode, FixBug])
        self._watch([WritePRD])  # Watch for PRDs from PM


# Import WritePRD for watching
from vibeteam.roles.product_manager import WritePRD
