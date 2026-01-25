"""
SoftwareEngineer Agent - Implements features, fixes bugs, writes tests.

Embeds the Torvalds Protocol - a strict 17-step workflow for feature development.
OpenHands-based replacement for the MetaGPT SoftwareEngineer role.
"""

from typing import Any

from vibeteam.agents.base import BaseVibeAgent
from vibeteam.tools.github import GitHubTool

# The Torvalds Protocol - embedded in all SWE actions
TORVALDS_PROTOCOL = """
## The Torvalds Protocol

You MUST follow this workflow for every task. No exceptions.

### 17-Phase Workflow

1. **THINK** - Understand the task, read related files, identify scope
2. **ISSUE** - Create/find GitHub issue for tracking
3. **BRANCH** - Create feature branch from latest master
4. **IMPLEMENT** - Write code and tests with TodoWrite tracking
5. **COMMIT** - Stage and commit with conventional format
6. **PUSH** - Push to remote
7. **PR** - Create pull request with proper description
8. **REVIEW** - Self-review the diff
9. **REFLECT** - Quality check: simplest solution? edge cases?
10. **PR-CI** - Wait for PR CI to pass
11. **APPROVAL** - Request user merge approval (NEVER merge without)
12. **MERGE** - Squash-merge after approval
13. **MASTER-CI** - Wait for master CI to pass
14. **DEPLOY** - Verify deployments succeed
15. **HEALTH** - Run health checks
16. **CLOSE** - Close issue and cleanup
17. **REPORT** - Final status report

### Critical Rules

1. NEVER skip the Think phase - Understand before coding
2. NEVER push directly to master - Always use branches and PRs
3. NEVER merge with failing CI - Fix first, merge second
4. NEVER leave debugging code - Clean up before commit
5. ALWAYS wait for user approval before merge
6. ALWAYS wait for master CI after merge
7. ALWAYS verify deployments

### Commit Message Format

- `feat(scope):` - New feature
- `fix(scope):` - Bug fix
- `docs(scope):` - Documentation
- `test(scope):` - Tests
- `chore(scope):` - Maintenance
- `refactor(scope):` - Code restructure

### Branch Naming

- `issue-{N}-description` - For tracked issues
- `feat/description` - For features without issues
- `fix/description` - For bug fixes
"""


class SoftwareEngineerAgent(BaseVibeAgent):
    """
    Software Engineer agent - implements features with the Torvalds Protocol.

    Follows a strict 17-step workflow:
    Think -> Issue -> Branch -> Implement -> Commit -> Push -> PR ->
    Review -> Reflect -> PR-CI -> Approval -> Merge -> Master-CI ->
    Deploy -> Health -> Close -> Report

    Philosophy:
    > "Talk is cheap. Show me the code." - Linus Torvalds
    > "Given enough eyeballs, all bugs are shallow."
    > "Bad programmers worry about the code. Good programmers worry about data structures."
    """

    name = "Turing"
    profile = "Software Engineer"
    goal = "Write high-quality, maintainable code through a rigorous 17-step workflow"
    model = "azure/gpt-5-2"
    temperature = 0.2  # Low temp for precise code

    def __init__(self, **kwargs: Any):
        import os

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
        """Custom system prompt with Torvalds Protocol."""
        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

{TORVALDS_PROTOCOL}

Available tools: {', '.join(t.name for t in self.tools) if self.tools else 'None'}
"""

    async def write_code(self, task: str, context: str = "") -> str:
        """
        Write production code following Torvalds Protocol.

        Args:
            task: The coding task
            context: Additional context about the codebase

        Returns:
            Implementation code and explanation
        """
        prompt = f"""Write production code following the Torvalds Protocol.

## Current Task
{task}

## Context
{context}

## Implementation Guidelines

1. **Read First** - Understand existing code before writing
2. **Small Changes** - One logical change per commit
3. **Tests Required** - Write tests for new functionality
4. **Clean Code** - No debugging artifacts, no commented code
5. **Error Handling** - Handle edge cases gracefully
6. **Type Hints** - Include types for all functions
7. **Docstrings** - Document complex logic

## Before Writing Code, Answer:

1. What files need to change?
2. What tests exist that I should update?
3. What edge cases should I handle?
4. Is there existing code I can reuse?

Now write the implementation:"""

        return await self.run(prompt)

    async def write_tests(self, code: str) -> str:
        """
        Write comprehensive tests following Torvalds Protocol.

        Args:
            code: The code to test

        Returns:
            Test code
        """
        prompt = f"""Write comprehensive tests following the Torvalds Protocol.

## Code to Test
{code}

## Testing Requirements

1. **Coverage** - Test happy path AND error conditions
2. **Isolation** - Each test should be independent
3. **Clarity** - Descriptive test names that explain intent
4. **AAA Pattern** - Arrange, Act, Assert
5. **Mocking** - Mock external dependencies
6. **Edge Cases** - Empty inputs, nulls, boundaries

## Test Categories

1. **Unit Tests** - Test individual functions in isolation
2. **Integration Tests** - Test component interactions
3. **E2E Tests** - Test complete user flows

Now write the tests:"""

        return await self.run(prompt)

    async def review_code(self, code: str) -> str:
        """
        Review code following Torvalds Protocol quality standards.

        Args:
            code: The code to review

        Returns:
            Code review feedback
        """
        prompt = f"""Review this code following the Torvalds Protocol.

## Code to Review
{code}

## Review Checklist (ALL must pass)

### Correctness
- [ ] Logic is correct and handles edge cases
- [ ] Error handling is appropriate
- [ ] No off-by-one errors

### Quality
- [ ] Code is clean and readable
- [ ] No debugging artifacts (console.log, print statements)
- [ ] No commented-out code
- [ ] Functions are small and focused

### Security
- [ ] No hardcoded secrets
- [ ] Input validation present
- [ ] No SQL/command injection risks

### Performance
- [ ] No obvious performance issues
- [ ] Appropriate data structures used

### Tests
- [ ] Tests cover the new code
- [ ] Tests are meaningful (not just coverage)
- [ ] Edge cases tested

Provide review with verdict: APPROVE, REQUEST_CHANGES, or COMMENT:"""

        return await self.run(prompt)

    async def fix_bug(self, bug_report: str, code: str = "") -> str:
        """
        Analyze and fix bugs following Torvalds Protocol.

        Args:
            bug_report: Description of the bug
            code: Relevant code if available

        Returns:
            Bug analysis and fix
        """
        prompt = f"""Analyze and fix this bug following the Torvalds Protocol.

## Bug Report
{bug_report}

## Relevant Code
{code}

## Debugging Process (FOLLOW EXACTLY)

### Step 1: Reproduce
- Can I reproduce the issue?
- What are the exact steps?
- What's expected vs actual behavior?

### Step 2: Isolate
- Which component is failing?
- What changed recently?
- Is this a regression?

### Step 3: Root Cause
- WHY is it failing, not just WHERE
- Use 5 Whys technique if needed

### Step 4: Fix
- Minimal change that fixes the issue
- Don't refactor unrelated code
- Consider side effects

### Step 5: Verify
- Does the fix actually work?
- Did I break anything else?
- Write a test to prevent regression

### Step 6: Document
- What was the root cause?
- How was it fixed?
- How to prevent similar issues?

Analyze and fix:"""

        return await self.run(prompt)
