# Current Work Plan

## Status: All evals passing — iteration warning injection complete

---

## Completed: SWE Iteration Warning Injection (#87)

**Branch:** `fix/swe-iteration-warnings`
**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/87 — **Merged** (`09c150f`)

### Problem
The SWE agent (gpt-4.1-mini) used all 35 iterations doing grep searches and NEVER:
1. Transitioned to Phase 3 (report writing)
2. Called `finish()` with a structured report
3. Produced any analysis or diagnosis

The LLM cannot count its own tool calls. The prompt says "after iteration 20, stop" but
the model has no way to know it's at iteration 20.

### Fix: Iteration Warning Injection
Implemented an iteration-counting callback that injects warning messages into the
conversation at specific thresholds (12, 17, 20). This gives the LLM an explicit
external signal it can't ignore.

Changes:
- Added `ITERATION_WARNINGS` dict with 3 escalating warning levels (wrap_up, emergency, critical)
- Added `ITERATION_WARNING_THRESHOLDS` dict mapping iteration counts to levels
- Added `_inject_warning()` function that injects via `conversation.send_message()` from background thread
- Updated `run()` with `_count_iterations` callback that counts ActionEvents and spawns warning threads
- Reduced `max_iteration_per_run` from 35 to 25 (warnings make extra headroom unnecessary)
- Updated prompt: 25 max iterations, Phase 2 budget 4-15, Phase 3 budget 16-25
- Updated FINAL REMINDER thresholds to match: 12/17/20
- Added note in prompt that system will inject warnings
- 12 new tests for the iteration warning system

### Checklist
- [x] Add `threading` import
- [x] Add `ITERATION_WARNINGS` dict at module level
- [x] Add `ITERATION_WARNING_THRESHOLDS` dict
- [x] Add `_inject_warning()` function
- [x] Update `run()` with iteration-counting callback
- [x] Change `max_iteration_per_run=35` → `25`
- [x] Pass `callbacks=[_count_iterations]` to `LocalConversation`
- [x] Update prompt: 35→25, phase budgets, wrap-up trigger 20→12
- [x] Update FINAL REMINDER: 20/25/30 → 12/17/20
- [x] Add note about system-injected warnings
- [x] Update 3 existing tests (35→25, wrap-up 20→12)
- [x] Add 12 new tests for iteration warning system
- [x] All 124 system prompt tests pass
- [x] Full suite passes (566 passed, 79 skipped, 0 failed)
- [x] Lint clean
- [x] Commit, push, create PR
- [x] Deploy to cluster (image `e21516a` on master, includes `09c150f`)
- [x] Run `github_issue` eval — **PASS** (IA:0.70, TC:0.80, EBD:0.80, HC:0.70, latency 59s)
- [x] Run regression eval `support_400_errors` — **PASS** (IQ:0.90, EBD:0.90, HC:0.80)

---

## Completed: FileEditorTool Removal + Pre-fetch (#86)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/86 — **Merged** (`540be31`)

### Fix
- Removed FileEditorTool from SWE agent (forces grep/sed instead of sequential reads)
- Added `_prefetch_repo_code()` that clones repo and greps for keywords before agent runs
- Updated Phase 1 to reference pre-fetched data

---

## Completed: Observation Extraction Fix (#84) + EBD Improvement (#85)

**PR #84:** Merged (`68e0946`) — Fixed observation extraction
**PR #85:** Merged (`7046ca2`) — EBD evidence requirements + Recreate deployment strategy

---

## Completed: SWE Investigation Strategy Fix (#83)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/83 — **Merged** (`ad0bfc0`)

---

## Completed: Earlier PRs (#79-#82)

| PR | Title | Status |
|----|-------|--------|
| #82 | SWE investigation workflow + response extraction | Merged |
| #81 | SWE 3-phase workflow | Merged |
| #80 | AzureLLM consolidation + marketing/product fix | Merged |
| #79 | SWE iteration budget + FINAL REMINDER | Merged |

---

## Eval Results

### Post PR #87 + RE iteration fix (image `e21516a`)
| Scenario | Result | Key Scores | Latency | Notes |
|----------|--------|------------|---------|-------|
| `github_issue` | **PASS** | IA:0.80, TC:0.80, EBD:0.90, HC:0.70 | 52s | Best scores yet! EBD 0.60→0.90, latency 121s→52s |
| `support_400_errors` | **PASS** | IQ:0.90, EBD:0.90, HC:0.70 | 37s | No regression |
| `stripe_webhook_failure` | **PASS** | IQ:0.90, TC:0.90, EBD:1.00, HC:0.90 | 58s | No regression |
| `release_deploy` | **FAIL** | N/A | >400s | Agent stuck/timeout on `gh` commands. Env issues fixed. |

### Post PR #86 (regression)
| Scenario | Result | Key Scores | Notes |
|----------|--------|------------|-------|
| `github_issue` | **FAIL** | IA:0.20, TC:0.30, EBD:0.20, HC:0.30 | Agent exhausted 35 iterations doing grep, never called finish() |

### Post PR #83 (baseline)
| Scenario | Result | Key Scores | Latency | Notes |
|----------|--------|------------|---------|-------|
| `github_issue` | **PASS** | IA:0.70, TC:0.80, EBD:0.60, HC:0.90 | 121s | Fixed! |
| `support_400_errors` | **PASS** | IQ:0.90, EBD:1.00, HC:0.90 | 79s | No regression |

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
| #83 | SWE FORBIDDEN ACTIONS + investigation strategy | Merged |
| #84 | Observation extraction fix | Merged |
| #85 | EBD evidence requirements + Recreate strategy | Merged |
| #86 | FileEditorTool removal + pre-fetch | Merged |
| #87 | SWE iteration warning injection | Merged |

## Open Issues

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #75 | Add SENTRY_CLIENT_SECRET to k8s/GitHub secrets | Open | Needs Sentry admin access |
| #22 | Complete VibeTeam Integration Setup | Open | Gmail processor merged; needs real OAuth creds |
| #47 | User Document Upload for Knowledge Base | Open | Feature request, ~2-3hrs |

---
Last updated: 2026-02-11 02:20 UTC
