---
name: sentry-triage
description: >
  Guidelines for triaging Sentry errors and classifying them as NOISE or VALID_BUG.
  Used by the Release Engineer agent.
license: MIT
triggers:
  - sentry
  - error
  - exception
  - bug
  - crash
  - production
  - monitoring
metadata:
  author: VibeTechnologies
  version: "1.0"
---

# Sentry Issue Triage

You are the Release Engineer responsible for triaging Sentry errors.

## Classification Patterns

### NOISE (Auto-resolve, don't create GitHub issue)

- `Failed to fetch`, `NetworkError`, `net::ERR_*`
- `ResizeObserver loop`
- `Script error.` (third-party, no stack trace)
- `AbortError`, `ECONNREFUSED`
- `chrome-extension://` errors (except our extension ID: ajfjlohdpfgngdjfafhhcnpmijbbdgln)
- Errors with < 5 events AND < 3 users

### VALID_BUG (Create GitHub issue)

- `TypeError`, `ReferenceError`, `Cannot read property`
- `is not a function`, `undefined is not`
- `Unhandled Promise rejection` with stack trace in our code
- Errors with >= 50 events OR >= 10 users
- Errors in critical paths (auth, payment, core features)

## Triage Workflow

1. **Analyze the error**
   - Read the stack trace
   - Check if it's in our code vs third-party
   - Count events and affected users

2. **Classify**
   - NOISE -> Log and skip (optionally resolve in Sentry)
   - VALID_BUG -> Continue to step 3
   - NEEDS_INVESTIGATION -> Flag for human review

3. **Create GitHub Issue** (for VALID_BUG only)
   ```markdown
   ## Bug Report from Sentry
   
   **Error:** {error_title}
   **Events:** {count} | **Users:** {user_count}
   **First seen:** {first_seen}
   
   ### Stack Trace
   ```
   {stack_trace}
   ```
   
   ### Sentry Link
   {permalink}
   
   ### Suggested Fix
   {your_analysis}
   ```

4. **If you can fix it**
   - Clone the repo
   - Create branch: `fix/sentry-{issue_id}-{short_desc}`
   - Implement fix
   - Run tests
   - Create PR referencing the GitHub issue

## Sentry Projects

| Project | Description |
|---------|-------------|
| vibebrowserextension | Chrome extension |
| vibe-api-gateway | Backend API |
| vibeteam | This AI team system |

## Example Triage

**Input:** TypeError: Cannot read property 'id' of undefined (150 events, 25 users)

**Output:**
- Classification: VALID_BUG (TypeError in our code, high impact)
- Action: Create GitHub issue with stack trace
- Next step: Analyze code to find root cause
