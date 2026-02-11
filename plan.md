# Current Work Plan

## Status: PR pending — SWE iteration budget fix (branch: fix/swe-iteration-budget)

**Branch:** `fix/swe-iteration-budget` (based on `master` at `874ba07`)

---

## Current Fix: SWE Iteration Budget (github_issue eval)

### Problem
The `github_issue` eval fails with all 0.00 scores because the SoftwareEngineer agent:
1. Uses all 25 iterations searching code (grep, find, cat) without producing a summary
2. Never calls `finish()`, so the response is empty
3. The fallback extraction chain (ThinkAction, ActionEvent.thought, event summaries) from commit `874ba07` still returns empty because gpt-4.1-mini doesn't populate thought fields

### Root Cause
- 25 iterations is insufficient for code search tasks (clone + search + read + fix + verify)
- The iteration warning at the TOP of the prompt (lines 62-73) gets lost during the agent's investigation loop
- No reminder near the END of the prompt catches the agent before it exhausts iterations

### Fix (Two Parts)

**Part 1: Prompt Changes** (`agents/openhands/software_engineer.py`)
- Updated STRICT ITERATION LIMIT: 25→35 max, wrap up at ~25 (was 25/15)
- Added ITERATION CHECK step to GitHub Issue Investigation workflow (step 7)
- Added **FINAL REMINDER** section at the END of the prompt with escalating urgency:
  - After 25 calls: STOP investigation, begin summary
  - After 30 calls: EMERGENCY mode, call finish() immediately
  - Includes checklist of what to include in finish()

**Part 2: Config Change** (`agents/openhands/software_engineer.py`)
- Changed `max_iteration_per_run` from 25 to 35 (SWE only)
- SupportEngineer and ReleaseEngineer remain at 25 (they finish in 10-15 iterations)

### Tests Added (`tests/test_system_prompt.py`)
- `TestSoftwareEngineerIterationBudget`: 9 tests
  - FINAL REMINDER exists in last 30% of prompt
  - FINAL REMINDER mentions finish()
  - FINAL REMINDER has escalating urgency (EMERGENCY/IMMEDIATELY)
  - STRICT ITERATION LIMIT says 35
  - Wrap-up at ~25 iterations
  - max_iteration_per_run=35 in code
  - GitHub Issue workflow has ITERATION CHECK
  - Other agents still use 25 iterations

### Checklist
- [x] Create feature branch `fix/swe-iteration-budget`
- [x] Update STRICT ITERATION LIMIT numbers (25→35, 15→25)
- [x] Add FINAL REMINDER section at end of prompt
- [x] Add ITERATION CHECK step to GitHub Issue Investigation workflow
- [x] Change max_iteration_per_run from 25 to 35
- [x] Add 9 tests for iteration budget
- [x] Full test suite passes (506 passed, 79 skipped)
- [x] Lint clean
- [ ] Commit and push
- [ ] Create PR
- [ ] CI checks pass
- [ ] Merge and deploy
- [ ] Run `github_issue` eval to verify fix
- [ ] Run `support_400_errors` regression eval

---

## Previous Eval Results (2026-02-10 23:51 UTC)

| Scenario | Result | Key Scores | Latency | Notes |
|----------|--------|------------|---------|-------|
| `support_400_errors` | PASS | IQ:0.90, EBD:1.00, HC:0.70 | 68s | Regression check passed |
| `stripe_webhook_failure` | PASS | IQ:0.90, TC:0.90, EBD:0.90, HC:0.90 | 74s | New scenario, strong pass |
| `support_notify_check` | PASS | NO:1.00 | 21s | Perfect score |
| `github_issue` | FAIL | All 0.00 | 132s | Agent used all 25 iterations, empty response |
| `release_deploy` | BLOCKED | N/A | 900s x4 | Pod killed mid-request by other sessions |

---

## All Merged PRs

| PR | Title | Status |
|----|-------|--------|
| #69 | Async Agent Callback Architecture | Merged |
| #70 | Namespace Awareness | Merged |
| #71 | Shared Response Extraction | Merged |
| #72 | Gmail Processor K8s Deployment | Merged |
| #73 | Wire CALLBACK_SECRET to K8s | Merged |
| #74 | `--use-async` flag for eval/trigger | Merged |
| #76 | Type annotation fixes (pyright) | Merged (`be61bb2`) |
| #77 | Sentry routing + deploy secrets | Merged (`6ed158f`) |
| #78 | Eval timeouts + agent prompt improvements | Merged (`5c0b634`) |

## Open Issues

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #75 | Add SENTRY_CLIENT_SECRET to k8s/GitHub secrets | Open | Needs Sentry admin access |
| #22 | Complete VibeTeam Integration Setup | Open | Gmail processor merged; needs real OAuth creds |
| #47 | User Document Upload for Knowledge Base | Open | Feature request, ~2-3hrs |

## Blocked

| Item | Blocker |
|------|---------|
| Eval reliability (release_deploy) | Multiple sessions saturating/restarting single openhands-svc pod |
| SENTRY_CLIENT_SECRET | Needs Sentry admin to retrieve from dashboard |
| Issue #22 full closure | Needs Gmail OAuth credentials deployed to cluster |

---
Last updated: 2026-02-11 00:20 UTC
