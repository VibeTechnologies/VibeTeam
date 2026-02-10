# Current Work Plan

## Status: Fix SWE agent response extraction + improve response reliability

**Branch:** `fix/swe-agent-response-extraction`
**Base:** `c5b15eb` (master with PRs #68-#70 merged)

---

## Goal

Fix the `github_issue` eval scenario where the SoftwareEngineer agent never responds
(600s timeout, 0 messages from agent).

## Root Cause Analysis

**Finding:** The SoftwareEngineer and ReleaseEngineer agents only extract responses
from `MessageEvent` with `source=="agent"`. The SupportEngineer (which works reliably)
also checks for `ActionEvent` with `FinishAction`/`AgentFinishAction`.

When the OpenHands agent completes via `finish()` (which creates a `FinishAction`),
the SWE/RE code misses it entirely and returns `response = ""`.

**Additional factors:**
1. The eval's 600s timeout may be too short for the SWE agentic loop (clone repo, grep, etc.)
2. The `conversation.run()` could hang if the agent gets stuck in loops
3. No max iteration enforcement in code (only mentioned in prompt)

## Checklist

- [x] Analyze response extraction code across all 3 agentic agents
- [x] Identify root cause: SWE/RE missing FinishAction extraction
- [x] Create shared `extract_response()` function in `agents/openhands/utils.py`
- [x] Update SoftwareEngineer to use shared extraction
- [x] Update ReleaseEngineer to use shared extraction  
- [x] Update SupportEngineer to use shared extraction (DRY)
- [x] Add debug logging to response extraction for better diagnostics
- [x] Write tests for the shared extraction function
- [x] Run full test suite
- [x] Run ruff lint
- [ ] Create PR
- [ ] Deploy and run `github_issue` eval
- [ ] Run regression evals (support_400_errors, release_deploy)

---

## Open Issues

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #47 | User Document Upload for Knowledge Base | Open | Feature request |
| #22 | Complete VibeTeam Integration Setup | Open | Umbrella issue |

## Blocked

| Item | Blocker |
|------|---------|
| Slack webhook delivery | Needs human with Slack admin access to update URLs |

---
Last updated: 2026-02-10
