# Current Work Plan

## Status: PR pending — SWE investigation strategy fix (branch: fix/swe-investigation-strategy)

---

## In Progress: SWE Investigation Strategy Fix

**Branch:** `fix/swe-investigation-strategy`
**PR:** Pending

### Problem
The `github_issue` eval fails because the SWE agent reads files sequentially (method-by-method, lines 1-40, 41-80, etc.) instead of using grep to find target code. Even with 35 iterations, it exhausts them all reading one file without producing a diagnosis.

### Fix
- Added FORBIDDEN ACTIONS section with 4 explicit anti-patterns and concrete GOOD vs BAD investigation examples
- Limited file exploration to 3 files max, 30 lines per read without grep-targeted line numbers
- Trigger wrap-up at iteration 20 (was 25) to ensure finish() is called sooner
- Improved 3-phase workflow with explicit iteration budgets per phase (8/17/10)
- 4 new tests for FORBIDDEN ACTIONS enforcement

### Checklist
- [x] Add FORBIDDEN ACTIONS section to software_engineer.py
- [x] Add GOOD vs BAD investigation examples
- [x] Update 3-phase workflow iteration budgets
- [x] Update FINAL REMINDER thresholds (wrap at 20, emergency at 25, critical at 30)
- [x] Add 4 new tests (forbidden actions section, sequential reading, file limits, examples)
- [x] Update existing test for new wrap-up threshold (25 -> 20)
- [x] All 96 system prompt tests pass
- [x] Full suite passes (537 passed, 78 skipped, 0 failed)
- [x] Lint clean (fixed `\|` escape sequence)
- [ ] Commit and push
- [ ] Create PR
- [ ] CI checks pass
- [ ] Merge
- [ ] Deploy and run `github_issue` eval
- [ ] Run `support_400_errors` regression eval

---

## Completed: SWE Investigation Workflow & Response Extraction (#82)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/82 — **Merged** (`0ee5ffb`)

---

## Completed: SWE 3-Phase Workflow (#81)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/81 — **Merged** (`02100ba`)

---

## Completed: AzureLLM Consolidation (#80)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/80 — **Merged** (`d3e8dea`)

### Fix
- Created `agents/shared/llm.py` as single source of truth for AzureLLM
- Updated all 5 agent files to import from shared module
- Fixed marketing_manager and product_manager to use AzureLLM (was base LLM causing 404)
- 23 new tests in `TestAzureLLMConsolidation`

---

## Completed: SWE Iteration Budget (#79)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/79 — **Merged** (`ae162bb`)

### Fix
- Increased `max_iteration_per_run` from 25 to 35 for SWE agent
- Added FINAL REMINDER section at end of prompt with escalating urgency
- Added ITERATION CHECK step to GitHub Issue Investigation workflow
- 8 new tests in `TestSoftwareEngineerIterationBudget`

---

## Eval Results (2026-02-10)

| Scenario | Result | Key Scores | Notes |
|----------|--------|------------|-------|
| `support_400_errors` | PASS | IQ:0.90, EBD:0.90, HC:0.80 | Post AzureLLM consolidation |
| `stripe_webhook_failure` | PASS | IQ:0.90, TC:0.90, EBD:0.90, HC:0.90 | Strong pass |
| `support_notify_check` | PASS | NO:1.00 | Perfect score |
| `github_issue` (stale pod) | FAIL | All 0.20 | Agent read files sequentially, ran out of iterations |
| `github_issue` (35 iter pod) | TIMEOUT | N/A | No response in 600s — agent still reading files |
| `release_deploy` | BLOCKED | N/A | Pod killed mid-request by other sessions |

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
| #76 | Type annotation fixes (pyright) | Merged |
| #77 | Sentry routing + deploy secrets | Merged |
| #78 | Eval timeouts + agent prompt improvements | Merged |
| #79 | SWE iteration budget + FINAL REMINDER | Merged |
| #80 | AzureLLM consolidation + marketing/product fix | Merged |
| #81 | SWE 3-phase workflow | Merged |
| #82 | SWE investigation workflow + response extraction | Merged |

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

## Next Steps (after current PR)

1. Deploy and run `github_issue` eval to verify FORBIDDEN ACTIONS fix
2. Run `support_400_errors` regression eval
3. If `github_issue` still fails, consider runtime iteration counting in agent code
4. Fix `release_deploy` eval reliability (infrastructure contention)

---
Last updated: 2026-02-11 UTC
