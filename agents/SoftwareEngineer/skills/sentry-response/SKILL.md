---
name: sentry-response
description: Handle Sentry issues end-to-end for SoftwareEngineer (investigate, fix, PR, and close).
---

# Sentry Response (SoftwareEngineer)

## When To Use
- A task includes a Sentry issue URL/ID.
- SupportEngineer escalates a Sentry bug for code fixes.
- A request says "check Sentry" and deliver a code change.

## Preconditions
- `SENTRY_AUTH_TOKEN` is set.
- GitHub access is available.
- You have repo context for the failing service.

## Tool Selection
- Prefer **Sentry MCP tools** if they exist (e.g., `mcp__sentry__*`).
- If MCP is not available, use **sentry-cli** to pull issue data.
- Always query Sentry directly for current issue status and details.

### Sentry MCP (Preferred)
- List unresolved issues.
- Fetch issue details and stack trace.
- Add a comment linking the PR.
- Resolve the issue after merge.

### Sentry CLI (Fallback)
```bash
# Unresolved issues in last 24h
sentry-cli issues list --project <PROJECT_SLUG> --query "is:unresolved age:-24h"

# Inspect a specific issue
sentry-cli issues info ISSUE_ID

# Resolve after merge
sentry-cli issues resolve ISSUE_ID
```

If only a Sentry URL is provided, extract the numeric issue ID from it.

## Workflow
1. **Identify the Sentry issue**
- Use MCP or `sentry-cli` to fetch the issue details and stack trace.
- Record the issue URL/ID in your notes and echo it back in your response.

2. **Analyze the codebase**
- Locate the failing file/function from the stack trace.
- Reproduce or write a failing test if feasible.
- Identify the minimal fix with clear blast radius.

3. **Implement the fix**
- Create a feature branch.
- Apply the code change.
- Add or update tests where appropriate.

4. **Create a PR**
- Include the Sentry issue URL in the PR description.
- Summarize the fix and test coverage.
- Make the PR title clear and scoped.

5. **Link Sentry issue to the PR**
- Ensure the PR description includes the Sentry issue URL/ID.
- If MCP tools are available, add a brief Sentry comment referencing the PR link.

6. **Resolve the Sentry issue (after merge)**
- Only mark the Sentry issue resolved once the PR is merged.
- If not merged yet, state that resolution is pending merge.

7. **Report back**
- Post the PR link.
- Include the Sentry issue URL/ID.
- Note whether the issue is resolved or pending merge.

## Response Checklist
- Sentry issue URL/ID included.
- PR link included.
- Clear status: "merged and resolved" or "pending merge".
- If MCP not available, explicitly state that `sentry-cli` was used.
