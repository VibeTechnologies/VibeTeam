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

## Deferred: PR #25 (Documentation Knowledge Base)

**PR:** https://github.com/VibeTechnologies/VibeTeam/pull/25
**Branch:** `feat/docs-knowledge-base`
**Status:** OPEN with major conflicts

### What PR #25 adds
- `vibeteam/tools/docs.py` - DocsTool for agent documentation search
- `vibeteam/connectors/docs.py` - DocsConnector for indexing
- Git repo auto-sync for documentation
- Docs sync CLI command

### Why it has conflicts
Master was restructured: `vibeteam/roles/` was deleted in favor of `agents/` directory.
The PR diff shows 69 files changed with deletions of old role files.

### Recommended approach
1. Cherry-pick the new docs files from PR #25
2. Adapt them to current codebase structure
3. Close PR #25 and open fresh PR

---
Last updated: 2026-02-09
