# Current Work Plan

## Status: PR ready — SWE response extraction fix + Gmail processor deployment

**Branch:** `fix/swe-agent-response-extraction`
**Base:** `c5b15eb` (master with PRs #68-#70 merged)

---

## Goals

### 1. Fix SWE agent response extraction (DONE)
SoftwareEngineer and ReleaseEngineer agents only extracted responses from `MessageEvent`,
missing `FinishAction`/`AgentFinishAction`. Created shared `extract_response_from_events()`
in `agents/openhands/utils.py` and wired all 3 agents to use it.

### 2. Gmail email processor K8s deployment (DONE)
Added K8s Deployment for automated support email processing (closes last gap in Issue #22).
Uses init container + emptyDir pattern for writable OAuth token refresh.

## Checklist

- [x] Analyze response extraction code across all 3 agentic agents
- [x] Identify root cause: SWE/RE missing FinishAction extraction
- [x] Create shared `extract_response()` function in `agents/openhands/utils.py`
- [x] Update SoftwareEngineer to use shared extraction
- [x] Update ReleaseEngineer to use shared extraction
- [x] Update SupportEngineer to use shared extraction (DRY)
- [x] Add debug logging to response extraction for better diagnostics
- [x] Write tests for the shared extraction function (36 tests)
- [x] Add Gmail processor K8s Deployment (`k8s/base/gmail-processor.yaml`)
- [x] Add Gmail secrets template (`k8s/base/gmail-secrets.yaml`)
- [x] Add Gmail processor to kustomization resources
- [x] Write Gmail processor tests (35 tests)
- [x] Run full test suite (469 passed, 79 skipped, 0 failures)
- [x] Run ruff lint (clean)
- [x] Commit all changes
- [ ] Push branch and create PR
- [ ] Deploy and run `github_issue` eval
- [ ] Run regression evals (support_400_errors, release_deploy)

---

## Open Issues

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #22 | Complete VibeTeam Integration Setup | Open | Gmail processor closes the LAST gap |
| #47 | User Document Upload for Knowledge Base | Open | Feature request, ~2-3hrs |

## Blocked

| Item | Blocker |
|------|---------|
| Slack webhook delivery | Needs human with Slack admin access to update URLs |

---
Last updated: 2026-02-10
