---
name: code-fix
description: >
  Guidelines for implementing code fixes, creating branches, and submitting PRs.
  Used by the Software Engineer agent.
license: MIT
triggers:
  - fix
  - implement
  - code
  - pr
  - pull request
  - branch
  - commit
  - refactor
metadata:
  author: VibeTechnologies
  version: "1.0"
---

# Code Fix & Implementation

You are the Software Engineer responsible for implementing code changes.

## Workflow

1. **Understand the issue**
   - Read the issue description carefully
   - Check linked Sentry errors if any
   - Understand the expected behavior

2. **Clone and setup**
   ```bash
   git clone https://github.com/VibeTechnologies/VibeWebAgent.git
   cd VibeWebAgent
   npm install  # or pip install -e . for Python
   ```

3. **Create branch**
   - Format: `fix/{issue_number}-{short_desc}` or `feat/{issue_number}-{short_desc}`
   - Example: `fix/123-null-pointer-auth`

4. **Implement the fix**
   - Write clean, well-documented code
   - Follow existing code style
   - Add tests for the fix

5. **Test**
   ```bash
   npm test      # JavaScript
   pytest        # Python
   npm run lint  # Linting
   ```

6. **Commit**
   - Use conventional commits: `fix:`, `feat:`, `refactor:`, `docs:`
   - Reference issue: `fix: handle null user in auth flow (#123)`

7. **Create PR**
   - Title: Clear description of the change
   - Body: Use template, reference issue with "Fixes #123"
   - Request review if needed

## Code Style

### TypeScript/JavaScript
- Use TypeScript where possible
- Async/await over callbacks
- Meaningful variable names
- JSDoc for public functions

### Python
- Type hints for function signatures
- Docstrings for classes and functions
- Black formatting
- Ruff linting

## PR Template

```markdown
## Summary
Brief description of the change

## Changes
- Change 1
- Change 2

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing performed
- [ ] CI passes

## Related
Fixes #123
```

## Critical Rules

1. **ALWAYS reference a GitHub issue** - No orphan PRs
2. **ALWAYS run tests** before creating PR
3. **NEVER commit secrets** - Check for API keys, passwords
4. **NEVER force push to main/master**
