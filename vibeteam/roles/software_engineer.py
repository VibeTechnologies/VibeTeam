"""
Software Engineer Role - Implements features, fixes bugs, writes tests.

Embeds the Torvalds Protocol - a strict 17-step workflow for feature development.
Based on opencode torvalds agent with MetaGPT integration.
"""

from __future__ import annotations

from typing import Any

from metagpt.actions import Action
from pydantic import Field

from vibeteam.roles.base import VibeRole

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


class WriteCode(Action):
    """Write production code following Torvalds Protocol."""

    name: str = "WriteCode"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer following the Torvalds Protocol.

{protocol}

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

Now write the implementation:
"""

    async def run(self, task: str, context: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(protocol=TORVALDS_PROTOCOL, task=task, context=context)
        rsp = await self._aask(prompt)
        return rsp


class WriteTests(Action):
    """Write comprehensive tests following Torvalds Protocol."""

    name: str = "WriteTests"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer writing tests following the Torvalds Protocol.

{protocol}

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

## Before Writing Tests, Answer:

1. What are the critical paths to test?
2. What can go wrong?
3. What are the boundary conditions?
4. What external dependencies need mocking?

Now write the tests:
"""

    async def run(self, code: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(protocol=TORVALDS_PROTOCOL, code=code)
        rsp = await self._aask(prompt)
        return rsp


class ReviewCode(Action):
    """Review code following Torvalds Protocol quality standards."""

    name: str = "ReviewCode"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer doing code review following the Torvalds Protocol.

{protocol}

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
- [ ] No unnecessary loops or allocations

### Tests
- [ ] Tests cover the new code
- [ ] Tests are meaningful (not just coverage)
- [ ] Edge cases tested

### Documentation
- [ ] Complex logic is documented
- [ ] Public APIs have docstrings
- [ ] README updated if needed

## Review Output Format

```
## Review Summary

**Verdict:** APPROVE / REQUEST_CHANGES / COMMENT

## Issues Found

1. **[SEVERITY]** Description
   - Location: file:line
   - Suggestion: How to fix

## Positive Notes

- What was done well

## Required Changes

1. Change description
2. Change description
```

Now review the code:
"""

    async def run(self, code: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(protocol=TORVALDS_PROTOCOL, code=code)
        rsp = await self._aask(prompt)
        return rsp


class FixBug(Action):
    """Analyze and fix bugs following Torvalds Protocol."""

    name: str = "FixBug"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer debugging an issue following the Torvalds Protocol.

{protocol}

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
- What changed recently? (check git log)
- Is this a regression?

### Step 3: Root Cause
- WHY is it failing, not just WHERE
- Use 5 Whys technique if needed
- Check for similar issues in codebase

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
- What should we do to prevent similar issues?

## Output Format

```
## Bug Analysis

**Root Cause:** One sentence explanation

**Investigation:**
1. Step taken
2. Step taken

**Fix:**
```code
// The fix
```

**Test to Prevent Regression:**
```code
// Test code
```

**Prevention Recommendation:** How to avoid similar bugs
```

Now analyze and fix:
"""

    async def run(self, bug_report: str, code: str = "") -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            protocol=TORVALDS_PROTOCOL, bug_report=bug_report, code=code
        )
        rsp = await self._aask(prompt)
        return rsp


class CreatePR(Action):
    """Create a pull request following Torvalds Protocol."""

    name: str = "CreatePR"

    PROMPT_TEMPLATE: str = """
You are a Senior Software Engineer creating a PR following the Torvalds Protocol.

{protocol}

## Changes Made
{changes}

## PR Template

Create a PR with this exact structure:

```markdown
## Summary

Brief description of what this PR does (1-2 sentences).

## Changes

- Change 1 with context
- Change 2 with context
- Change 3 with context

## Testing

- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing done

## Checklist

- [ ] Code follows project style
- [ ] No debugging artifacts
- [ ] Tests added/updated
- [ ] Documentation updated (if needed)

## Screenshots

(if applicable)

Closes #ISSUE_NUMBER
```

## Before Creating PR

1. Did I self-review the diff?
2. Did I run tests locally?
3. Did I update documentation?
4. Is the commit message clear?

Now create the PR description:
"""

    async def run(self, changes: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(protocol=TORVALDS_PROTOCOL, changes=changes)
        rsp = await self._aask(prompt)
        return rsp


class SoftwareEngineer(VibeRole):
    """
    Software Engineer role - implements features with the Torvalds Protocol.

    Follows a strict 17-step workflow:
    Think -> Issue -> Branch -> Implement -> Commit -> Push -> PR ->
    Review -> Reflect -> PR-CI -> Approval -> Merge -> Master-CI ->
    Deploy -> Health -> Close -> Report

    Philosophy:
    > "Talk is cheap. Show me the code." - Linus Torvalds
    > "Given enough eyeballs, all bugs are shallow."
    > "Bad programmers worry about the code. Good programmers worry about data structures."
    """

    name: str = Field(default="Torvalds")
    profile: str = Field(default="Software Engineer")
    goal: str = Field(
        default="Write high-quality, maintainable code through a rigorous 17-step workflow"
    )
    constraints: str = Field(
        default="Follow Torvalds Protocol strictly. Never skip steps. Never merge without approval. Never leave debugging code."
    )
    temperature: float = Field(default=0.2)  # Low temp for precise code

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_actions([WriteCode, WriteTests, ReviewCode, FixBug, CreatePR])
        # Deferred import to avoid circular dependency
        from vibeteam.roles.product_manager import WritePRD

        self._watch([WritePRD])  # Watch for PRDs from PM
