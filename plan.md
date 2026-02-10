# Current Work Plan

## Status: Eval & prompt improvements in progress

**Branch:** `fix/eval-and-prompt-improvements`
**Base:** `6abbd33` (master with PRs #69-#74 merged)

---

## Goals

### 1. Per-scenario timeout overrides in eval script (DONE)
- Added `"timeout": 900` to `release_deploy` scenario in SCENARIOS dict
- `run_evaluation()` checks for per-scenario timeout when CLI uses default (600)
- Updated CLI help text to document per-scenario override behavior

### 2. SWE agent prompt: code-first investigation (DONE)
- Added "INVESTIGATION PRIORITY: CODE FIRST, INFRA SECOND" section right after
  PRIMARY REPOSITORY section (before PRE-FETCHED DATA) so agent sees it early
- Lists common browser extension directories to search (extension/, chrome/, popup/, content/)
- Includes `find` command example for locating TypeScript/JavaScript files
- Tells agent to SKIP infra checks for UI/extension bugs
- Enhanced GitHub Issue Investigation workflow to include `find` alongside `grep`

### 3. RE agent prompt: combine kubectl commands (DONE)
- Added "EFFICIENCY: COMBINE COMMANDS TO SAVE TOOL CALLS" section with good/bad examples
- Consolidated deploy steps from 7 individual commands to 6 combined ones
  (pre-deploy check: 1 command instead of 4; post-deploy: 1 instead of 2)
- Updated "Check Current State" section to show combined read-only commands

### 4. Tests (DONE)
- `TestSoftwareEngineerCodeFirstInvestigation`: 7 tests verifying code-first prompts
- `TestPerScenarioTimeout`: 5 tests verifying per-scenario timeout override
- `TestReleaseEngineerSafetyGuardrails`: 2 new tests for command combining
- All 491 tests pass, 79 skipped, lint clean

## Checklist

- [x] Create feature branch `fix/eval-and-prompt-improvements`
- [x] Add per-scenario timeout overrides (release_deploy → 900s)
- [x] Improve SWE prompt: code-first investigation
- [x] Optimize RE prompt: combine kubectl commands
- [x] Write tests for all changes (14 new tests)
- [x] Full test suite passes (491 passed, 79 skipped)
- [x] Lint clean
- [x] Update plan.md
- [ ] Commit and push
- [ ] Create PR
- [ ] Run evals to verify improvements:
  - [ ] `github_issue` — IssueAnalysis target: 0.40 → 0.60+
  - [ ] `release_deploy` — should complete within 900s
  - [ ] `support_400_errors` — regression check

---

## Previously Completed (Earlier Sessions)

| PR | Title | Status |
|----|-------|--------|
| #69 | Async Agent Callback Architecture | Merged |
| #70 | Namespace Awareness | Merged |
| #71 | Shared Response Extraction | Merged |
| #72 | Gmail Processor K8s Deployment | Merged |
| #73 | Wire CALLBACK_SECRET to K8s | Merged |
| #74 | `--use-async` flag for eval/trigger | Merged |

## Open Issues

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #75 | Add SENTRY_CLIENT_SECRET to k8s/GitHub secrets | Open | Needs Sentry admin access |
| #22 | Complete VibeTeam Integration Setup | Open | Gmail processor merged; needs real OAuth creds |
| #47 | User Document Upload for Knowledge Base | Open | Feature request, ~2-3hrs |

## Known Flakiness (Before This PR)

| Eval | Issue | Fix in This PR |
|------|-------|----------------|
| `release_deploy` | RE agent's kubectl+gh workflow can exceed 600s | Per-scenario 900s timeout + combined kubectl commands |
| `github_issue` | IssueAnalysis 0.40 — SWE checks infra not code | Code-first investigation prompt |

## Blocked

| Item | Blocker |
|------|---------|
| Slack webhook delivery | Needs human with Slack admin access to update URLs |
| SENTRY_CLIENT_SECRET | Needs Sentry admin to retrieve from dashboard |
| Issue #22 full closure | Needs Gmail OAuth credentials deployed to cluster |

---
Last updated: 2026-02-10
