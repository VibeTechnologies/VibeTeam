# Current Work Plan: Slack Webhook Fix

## Goal
Fix Slack webhook routing so messages to @VibeTeam/@ReleaseEngineer are received by the gateway and routed to agents.

## Status: Blocked on Manual Action

## Background

User reported that Slack messages to `@ReleaseEngineer` weren't getting responses.

**Root Cause:** Slack app webhook URL was misconfigured:
- Wrong: `https://team.vibebrowser.app/slack/events` (routes to OpenHands, doesn't handle Slack)
- Correct: `https://webhook.team.vibebrowser.app/slack/events` (routes to vibeteam-gateway)

## Checklist

- [x] Diagnose why Slack messages aren't being received
- [x] Identify correct webhook endpoint (`webhook.team.vibebrowser.app`)
- [x] Verify gateway responds to Slack challenge verification
- [x] Update `templates/slack-app/manifest.yaml` with correct URLs
- [x] Verify Kubernetes cluster is healthy (all pods running)
- [x] Commit manifest.yaml fix to git (1b71032)
- [x] Create PR for Slack fix: https://github.com/VibeTechnologies/VibeTeam/pull/54
- [ ] **MANUAL:** Update Slack app Event Subscriptions URL
- [ ] **MANUAL:** Update Slack app Interactivity URL  
- [ ] Verify Slack events arrive at gateway (check logs)
- [ ] Test end-to-end: mention @VibeTeam and confirm response

## Manual Steps Required

### Update Slack App Configuration

1. Go to: https://api.slack.com/apps/A0AAZGWEAVA/event-subscriptions

2. Change **Request URL** to:
   ```
   https://webhook.team.vibebrowser.app/slack/events
   ```

3. Click **Save Changes** - Slack will verify the endpoint

4. Go to: https://api.slack.com/apps/A0AAZGWEAVA/interactivity

5. Change **Request URL** to:
   ```
   https://webhook.team.vibebrowser.app/slack/interactive
   ```

6. Click **Save Changes**

### Verify the Fix

```bash
# Watch gateway logs for incoming Slack events
kubectl logs -f deployment/vibeteam-gateway -n vibeteam | grep -i slack

# In another terminal, send a test message in Slack mentioning @VibeTeam
```

## Ingress Routing Reference

| Hostname | Service | Port | Purpose |
|----------|---------|------|---------|
| `team.vibebrowser.app` | openhands-svc | 3000 | OpenHands web UI |
| `webhook.team.vibebrowser.app` | vibeteam-gateway | 8080 | Slack/Discord webhooks |

---

## Completed: PR #25 Cherry-Pick (Documentation Knowledge Base)

**Original PR:** https://github.com/VibeTechnologies/VibeTeam/pull/25 (has major conflicts)
**New PR:** https://github.com/VibeTechnologies/VibeTeam/pull/55

### What was done
- [x] Cherry-picked `vibeteam/connectors/docs.py` from PR #25
- [x] Cherry-picked `vibeteam/tools/docs.py` from PR #25
- [x] Fixed lint errors (unused imports, f-string)
- [x] Updated `__init__.py` files to export new classes
- [x] Verified imports work correctly
- [x] Created PR #55 as replacement for PR #25

### Next steps for PR #25
- PR #25 can be closed after PR #55 is merged
- The CLI command (`vibeteam docs sync`) from PR #25 was not cherry-picked (lower priority)

---

## Open PRs

| PR | Title | Status |
|----|-------|--------|
| #54 | fix(slack): correct webhook URLs | Ready for review |
| #55 | feat: add Documentation Knowledge Base tool | Ready for review |
| #25 | feat: Documentation Knowledge Base (original) | Can close after #55 merges |

---

## Completed: OpenHands Agent Evaluation Fix (2026-02-10)

All agent evaluation scenarios now pass. The final verification was completed on 2026-02-10.

### github_issue Scenario Results

| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
| IssueAnalysis | 0.70 | 0.60 | ✅ Pass |
| TaskCompletion | 0.80 | 0.60 | ✅ Pass |
| EvidenceBasedDecision | 0.70 | 0.60 | ✅ Pass |
| HandoffCompletion | 0.90 | 0.60 | ✅ Pass |

### Key Fixes Applied

1. **Dev overlay with git-sync**: Applied `k8s/overlays/dev` to enable hot reload of agent code
2. **Strict iteration limit**: Max 10 tool calls to prevent stuck loops
3. **Anti-looping instructions**: Agents stop if viewing same file twice
4. **Mandatory gh output redirection**: Prevents terminal hanging

### Running Evaluations

```bash
# Unset any shell env vars that might override .env
unset AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_API_BASE AZURE_API_KEY

# Load from .env and run
export $(grep -v '^#' .env | grep -E '^AZURE_' | xargs)
uv run python scripts/eval_slack_e2e.py --scenario github_issue --channel C0AATPSADB8 --timeout 180
```

---
Last updated: 2026-02-10
