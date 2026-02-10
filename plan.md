# Current Work Plan

## Active: Slack Webhook URL Fix

**Status:** Blocked on manual Slack app configuration update.
**PR:** #54 (fix/slack-webhook-url)

**Root Cause:** Slack app webhook URL was misconfigured:
- Wrong: `https://team.vibebrowser.app/slack/events` (routes to OpenHands, doesn't handle Slack)
- Correct: `https://webhook.team.vibebrowser.app/slack/events` (routes to vibeteam-gateway)

### Remaining Manual Steps

1. Go to https://api.slack.com/apps/A0AAZGWEAVA/event-subscriptions
2. Change **Request URL** to: `https://webhook.team.vibebrowser.app/slack/events`
3. Go to https://api.slack.com/apps/A0AAZGWEAVA/interactivity
4. Change **Request URL** to: `https://webhook.team.vibebrowser.app/slack/interactive`
5. Verify: `kubectl logs -f deployment/vibeteam-gateway -n vibeteam | grep -i slack`

### Ingress Routing Reference

| Hostname | Service | Port | Purpose |
|----------|---------|------|---------|
| `team.vibebrowser.app` | openhands-svc | 3000 | OpenHands web UI |
| `webhook.team.vibebrowser.app` | vibeteam-gateway | 8080 | Slack/Discord webhooks |

---

## Open PRs

| PR | Title | Status | Notes |
|----|-------|--------|-------|
| #55 | feat: add Documentation Knowledge Base tool | Ready for review | Cherry-pick of closed #25 |
| #54 | fix(slack): correct webhook URLs | Ready for review | Blocked on manual Slack config |
| #53 | [WIP] GitHub App auth + Sentry webhooks | Draft | Replacement for closed #50 |
| #51 | feat: User Document Upload for Knowledge Base | Ready for review | Depends on #55 |

---

## Architecture Reference

### End-to-End Flow Diagram

```mermaid
sequenceDiagram
    participant Slack
    participant GW as vibeteam-gateway (FastAPI :8080)
    participant Router as Router
    participant OH as openhands-svc (FastAPI :3000)
    participant Team as OpenHandsTeam
    participant Agent as Agent (e.g. SupportEngineer)
    participant SDK as OpenHands SDK (LocalConversation)

    Note over Slack,GW: 1. WEBHOOK INGRESS
    Slack->>GW: POST /slack/events<br/>(app_mention or message.im)
    GW->>GW: Verify Slack signature (HMAC-SHA256)
    GW->>GW: Filter bot messages without @Role mentions

    Note over GW,Router: 2. ROUTING
    GW->>Router: parse_role_mentions(text)
    Router-->>GW: ["support_engineer"] (or empty)
    alt No role mentions
        GW->>GW: Keyword fallback routing<br/>(slack.py:290-301)
    end
    GW->>Slack: Add reaction

    Note over GW,OH: 3. AGENT INVOCATION
    GW->>GW: Build task prompt with<br/>investigation instructions<br/>(slack.py:372-439)
    GW->>OH: POST /run {task, role, context_type, context_id}<br/>(3 retries, 600s timeout)
    OH->>Team: team.run(task, context_type, context_id)

    Note over Team,Agent: 4. AGENT ROUTING (openhands-svc)
    Team->>Team: parse_mention(task) → role<br/>(team.py:48-87)
    alt No @mention found
        Team->>Team: route_by_keywords(task)<br/>(team.py:89-189)
    end
    Team->>Agent: agent.run(task, context_type, context_id)

    Note over Agent,SDK: 5. CONTEXT INJECTION + EXECUTION
    Agent->>Agent: Inject context (Sentry, kubectl,<br/>Gmail, Langfuse, Calendar, Docs)
    Agent->>SDK: conversation.send_message(task)<br/>+ conversation.run()
    loop Agentic Loop (max 10 iterations)
        SDK->>SDK: LLM call → tool use → observe
    end
    SDK-->>Agent: Final response text

    Note over Agent,OH: 6. SESSION SAVE
    Agent-->>OH: {response, role, metadata}
    OH->>OH: Save to PostgreSQL<br/>(sessions + task_results)
    OH-->>GW: JSON response

    Note over GW,Slack: 7. RESPONSE + HANDOFF
    GW->>GW: Split long messages (>3000 chars)
    GW->>Slack: Post [RoleName] response in thread
    GW->>GW: parse_role_mentions(response)
    alt Handoff detected (depth < 3)
        GW->>GW: Build handoff task prompt
        GW->>OH: POST /run (next agent)
        Note over GW,Slack: Recurse steps 3-7<br/>(max depth 3)
    end
```

### Agent Architecture

| Agent | Persona | Execution Model | Tools | Context Injection |
|-------|---------|----------------|-------|-------------------|
| **SupportEngineer** | Grace | `send_message()` + `run()` (agentic loop, max 10 iters) | TerminalTool, FileEditorTool | Sentry, kubectl, Gmail, Calendar, Langfuse, Docs (keyword-conditional) |
| **ReleaseEngineer** | Einstein | `send_message()` + `run()` (agentic loop, max 10 iters) | TerminalTool, FileEditorTool | kubectl (always) |
| **SoftwareEngineer** | Alan | `send_message()` + `run()` (agentic loop, max 10 iters) | TerminalTool, FileEditorTool | GitHub issues (if `#NNN`), kubectl (if infra keywords) |
| **ProductManager** | Maya | `ask_agent()` (single LLM call) | None | None |
| **MarketingManager** | Ada | `ask_agent()` (single LLM call) | None (MCP config exists) | Browser context (URL fetch, web search) |

**Key difference:** `send_message()` + `run()` = full agentic loop with tool access. `ask_agent()` = single LLM call, text-only output.

### Role Resolution

Consolidated into `agents/shared/role_resolver.py` (PR #59). Single source of truth for all role mention parsing. Supports full names, short forms (swe/pm), persona names (einstein/grace/ada), and extras (dev/product/marketer/supervisor). 37 unit tests.

### kubectl Context (Parallelized)

`agents/shared/kubectl_tools.py` uses two-phase approach (PR #59):
1. Fetch pods first (~1s) to discover existing deployments
2. Fetch events, logs, rollout history in parallel via `ThreadPoolExecutor`
3. Non-existent deployments auto-skipped

Reduced from worst-case 210s (sequential) to ~11s (parallel).

---

## Completed Work

| PR | Title | Key Changes |
|----|-------|-------------|
| #59 | refactor: consolidate role parsing, parallelize kubectl, merge eval scripts | RoleResolver module, ThreadPoolExecutor kubectl, deleted eval_slack_agent.py |
| #57 | fix: secure /slack/trigger endpoint, fix dead code, align role mentions | SLACK_TRIGGER_SECRET, dead code cleanup |
| #56 | fix(eval): improve Azure credential handling | Credential warnings, all 5 eval scenarios pass |
| #52 | fix(ci): ruff lint errors | CI lint fixes |

### Eval Results (all passing)

| Scenario | InvestigationQuality | TaskCompletion |
|----------|---------------------|----------------|
| support_400_errors | 0.90 | - |
| support_notify_check | - (NotificationOnly: 1.00) | - |
| github_issue | - (IssueAnalysis: 0.70) | 0.80 |
| release_deploy | - (DeploymentExecution: 0.90) | 1.00 |
| stripe_webhook_failure | 0.90 | 0.90 |

### Design Notes

- `/slack/trigger` endpoint is correct design for eval/programmatic triggering (Slack bots can't receive their own messages as webhook events)
- PR #58 (remove /slack/trigger) was correctly closed
- PR #25 closed (superseded by #55 cherry-pick)
- PR #50 closed (superseded by #53 WIP rewrite)

---
Last updated: 2026-02-10
