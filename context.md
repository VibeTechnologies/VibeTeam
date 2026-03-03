# VibeTeam Context Document

> **Last Updated:** 2026-02-05
> **Current Focus:** OpenHands Agent E2E Evaluation
> **Status:** BLOCKED - Gateway timeout issue

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [E2E Evaluation System](#e2e-evaluation-system)
4. [Current Blocker](#current-blocker)
5. [Completed Work](#completed-work)
6. [TODO List](#todo-list)
7. [Key Files Reference](#key-files-reference)
8. [Environment & Configuration](#environment--configuration)
9. [Useful Commands](#useful-commands)

---

## Project Overview

VibeTeam is a multi-agent system that handles tasks via Slack, GitHub, and other integrations. It supports multiple agent frameworks:

- **OpenHands** (current focus) - SDK-based agents with tool support
- **CrewAI** - Crew-based multi-agent orchestration
- **AutoGen** - Microsoft's multi-agent framework

The system routes messages from Slack to appropriate agents based on `@RoleName` mentions (e.g., `@SupportEngineer`, `@ReleaseEngineer`).

### Agent Roles

| Role | Responsibilities | Tools |
|------|------------------|-------|
| **SupportEngineer** | Incident triage, Sentry analysis, customer emails | Sentry, Gmail, Calendar, Langfuse |
| **SoftwareEngineer** | Code bugs, feature implementation, PR reviews | GitHub, Terminal, FileEditor |
| **ReleaseEngineer** | Deployments, rollbacks, infrastructure | Kubernetes, Shell, GitHub |
| **ProductManager** | Product decisions, prioritization | Docs, Calendar |
| **MarketingManager** | Content, announcements, social media | Browser, Docs |

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              KUBERNETES CLUSTER                              │
│                              (vibeteam namespace)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────┐         ┌─────────────────────┐                   │
│   │   vibeteam-gateway  │────────▶│    openhands-svc    │                   │
│   │   (FastAPI)         │         │    (FastAPI)        │                   │
│   │                     │         │                     │                   │
│   │  - /slack/events    │         │  - /run             │                   │
│   │  - /slack/trigger   │         │  - /health          │                   │
│   │  - /github/webhook  │         │                     │                   │
│   │  - /health          │         │  Agents:            │                   │
│   └─────────────────────┘         │  - SupportEngineer  │                   │
│            │                      │  - SoftwareEngineer │                   │
│            │                      │  - ReleaseEngineer  │                   │
│            ▼                      │  - ProductManager   │                   │
│   ┌─────────────────────┐         │  - MarketingManager │                   │
│   │   scheduler-svc     │         └─────────────────────┘                   │
│   │   (Task scheduling) │                   │                               │
│   └─────────────────────┘                   │                               │
│            │                                ▼                               │
│            │                      ┌─────────────────────┐                   │
│            └─────────────────────▶│     postgres-0      │                   │
│                                   │   (Session store)   │                   │
│                                   └─────────────────────┘                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

External Services:
  - Slack API (messages, reactions)
  - Azure OpenAI (LLM: gpt-5.2)
  - Sentry (error monitoring)
  - GitHub (issues, PRs)
  - Langfuse (LLM observability)
```

### Message Flow

```
1. User posts "@SupportEngineer investigate 400 errors" to Slack
2. Gateway receives via /slack/events webhook (or /slack/trigger for eval)
3. Gateway parses @RoleName, routes to openhands-svc /run endpoint
4. OpenHands agent:
   a. Injects context (Sentry issues, Gmail, etc.)
   b. Runs LLM with tools (Terminal, FileEditor)
   c. Returns response
5. Gateway posts [SupportEngineer] response to Slack thread
6. If response contains @AnotherRole, handoff chain continues (max depth: 3)
```

---

## E2E Evaluation System

### Purpose

Test that agents actually work end-to-end: from Slack message → agent processing → Slack response.

### Evaluation Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  EVAL SCRIPT (scripts/eval_slack_e2e.py)                                     │
│                                                                              │
│  1. POST message to Slack ──────────────────────▶ Slack API                  │
│     "@SupportEngineer investigate 400 errors"                                │
│                                                                              │
│  2. Trigger gateway ────────────────────────────▶ /slack/trigger             │
│     {channel, thread_ts, text}                                               │
│                                                                              │
│  3. Poll for replies ◀──────────────────────────  Slack API                  │
│     Every 5s for up to 180s                        (thread messages)         │
│                                                                              │
│  4. Evaluate with G-Eval ───────────────────────▶ Azure OpenAI (GPT-5)       │
│     - InvestigationQuality (threshold: 0.60)                                 │
│     - TaskCompletion (threshold: 0.60)                                       │
│                                                                              │
│  5. Generate report ────────────────────────────▶ results/eval_reports/      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Test Scenarios

| Scenario | Agent | Description | Metrics |
|----------|-------|-------------|---------|
| `support_400_errors` | SupportEngineer | Investigate API 400 errors from ACME Corp | InvestigationQuality, TaskCompletion |
| `github_issue` | SoftwareEngineer | Triage GitHub issue #42 (extension crash) | IssueAnalysis, TaskCompletion |
| `release_deploy` | ReleaseEngineer | Deploy PR #123 to staging | DeploymentExecution, TaskCompletion |

### Scoring Criteria

```
InvestigationQuality:
  0.0-0.2: No investigation or all tools failed
  0.2-0.4: Tools failed but reasonable external observations
  0.4-0.6: Some tools worked, partial findings
  0.6-0.8: Tools worked, root cause identified          ← THRESHOLD
  0.8-1.0: Full investigation with resolution

TaskCompletion:
  0.0-0.2: Nothing resolved, circular handoffs
  0.2-0.4: Diagnostic info but no progress
  0.4-0.6: Root cause hypothesized but not confirmed
  0.6-0.8: Root cause confirmed, fix identified         ← THRESHOLD
  0.8-1.0: Issue resolved or fix deployed
```

---

## Current Blocker

### Problem: Gateway Timeout Before Agent Responds

**Symptom:** Evaluation fails with "No agent response received" - only 1 message in conversation (the user's message).

**Error in Gateway Logs:**
```
Failed to connect to http://openhands-svc:8080 after 3 attempts: [ReadTimeout]
```

### Timing Analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TIMING BREAKDOWN                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Gateway HTTP Timeout: 120 seconds                                           │
│                                                                              │
│  OpenHands Agent Execution:                                                  │
│  ├── Module imports + Agent creation: ~24s (cold start)                     │
│  ├── Sentry context fetch: ~25s (fails but blocks)                          │
│  ├── LLM call + tool setup: ~5-10s                                          │
│  ├── Agent run loop: ~10-60s+ (varies by task complexity)                   │
│  └── TOTAL: 60-120s+ for real tasks                                         │
│                                                                              │
│  ⚠️  Complex tasks with tools exceed 120s → ReadTimeout                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Root Causes

| Cause | Impact | Status |
|-------|--------|--------|
| Gateway timeout too short (120s) | Agent can't finish before timeout | **NEEDS FIX** |
| Cold start overhead (~24s) | First request always slow | **NEEDS FIX** |
| Sentry context fetch blocks (~25s) | Wastes time even when failing | **NEEDS FIX** |
| `vibeteam.connectors.sentry` missing in container | Import fails slowly | **NEEDS FIX** |

### Evidence

1. **Agent works when tested directly in pod:**
   ```bash
   kubectl exec -n vibeteam deployment/openhands-svc -- python -c "
   from agents.openhands.support_engineer import OpenHandsSupportEngineer
   agent = OpenHandsSupportEngineer()
   result = agent.run(task='Say hello', use_tools=True)
   print(result['response'])  # Output: Hello — Grace here from VibeTeam Support.
   "
   # Completes in ~28s
   ```

2. **But HTTP request times out:**
   ```bash
   kubectl exec -n vibeteam deployment/vibeteam-gateway -- \
     curl -X POST http://openhands-svc:8080/run \
     -H "Content-Type: application/json" \
     -d '{"task":"Say hello","role":"support_engineer"}' \
     --max-time 30
   # Exit code 28 (timeout)
   ```

---

## Completed Work

### Session 1: Critical Bug Fixes (All Committed)

| Commit | Fix | Description |
|--------|-----|-------------|
| `f5a723d` | Token Overflow | Added `max_iter=15` to all CrewAI agents |
| `f314ad5` | Missing thread_ts | Fixed ValueError in `/slack/trigger` endpoint |
| `f314ad5` | Wrong Default Framework | Changed to `crewai` from `openhands` |
| `2200a9a` | Role Mention Syntax | Unified to `@RoleName` everywhere |
| `9c3d93c` | Stricter Eval Criteria | Updated eval to fail when tools don't work |

### Session 2: K8s Access & CrewAI Dev Mode

| Commit | Fix | Description |
|--------|-----|-------------|
| `89c0494` | ShellTool KUBECONFIG | Added k8s access to release_engineer.py and software_engineer.py |
| `89c0494` | K8s ServiceAccount | Added `serviceAccountName: vibeteam-agent` to framework deployments |
| `89c0494` | Slack Event Loop Fix | Changed `asyncio.get_event_loop()` to `asyncio.run()` in slack_tools.py |
| `5cfa7a7` | CrewAI Dev Mode | Dockerfile.dev + entrypoint that pulls code from GitHub on restart |
| `ef4dc6e` | CrewAI Dev Mode | Additional dev mode improvements |
| `fe6e99b` | Kustomize Fix | Use `commonAnnotations` instead of `commonLabels` (selectors immutable) |

### Session 3: OpenHands Slack Tools & Dev Mode

| Commit | Fix | Description |
|--------|-----|-------------|
| `d2c7388` | slack_sdk Missing | Added `slack_sdk>=3.21.0` to `agents/openhands/requirements.txt` |
| `f19b0bf` | OpenHands Dev Mode | Created `Dockerfile.dev` and `entrypoint-dev.sh` for OpenHands |
| `6679f8b` | Permission Fix | Fixed `/app/code` directory permissions in OpenHands dev Dockerfile |
| `8c593bd` | Asyncio Fix | Wrapped blocking `agent.run()` in `asyncio.to_thread()` |

---

## TODO List

### Immediate (Unblock Evaluation)

- [ ] **Increase gateway timeout to 300s**
  - File: `vibeteam/gateway/server.py`
  - Change: `httpx.Timeout(300.0, connect=30.0)` (was 120s)

- [ ] **Fix Sentry context fetch blocking**
  - File: `agents/openhands/support_engineer.py`
  - Add timeout to import attempt
  - Or make import fail-fast with proper try/except

- [ ] **Add vibeteam.connectors to OpenHands container**
  - File: `agents/openhands/Dockerfile` or `requirements.txt`
  - Install vibeteam package or copy connectors module

### Short-term (Performance)

- [ ] **Pre-warm agents on startup**
  - File: `agents/openhands/server.py`
  - In `lifespan()`, force-create all agent instances
  - Reduces first-request latency by ~24s

- [ ] **Persist DEFAULT_FRAMEWORK=openhands in kustomize**
  - File: `k8s/overlays/dev/kustomization.yaml`
  - Currently set via `kubectl set env`, resets on restart

### Medium-term (Reliability)

- [ ] **Add request timeout handling in agent server**
  - Return partial response if timeout approaching
  - Log warning for slow requests

- [ ] **Improve health check to include readiness**
  - Add `/ready` endpoint that checks agent warm state
  - Kubernetes can route traffic only when ready

### Long-term (Observability)

- [ ] **Add metrics for agent execution time**
  - Track cold start vs warm execution
  - Alert on requests approaching timeout

- [ ] **Structured logging for agent lifecycle**
  - Log when agent starts, LLM calls, tool usage, completion

---

## Key Files Reference

### Gateway

| File | Purpose |
|------|---------|
| `vibeteam/gateway/server.py` | Main FastAPI app, `call_agent_service()`, HTTP client config |
| `vibeteam/gateway/routes/slack.py` | Slack event handlers, `/slack/trigger`, message routing |
| `vibeteam/router/__init__.py` | Role mention parsing, keyword routing |

### OpenHands Agents

| File | Purpose |
|------|---------|
| `agents/openhands/server.py` | FastAPI server for OpenHands, `/run` endpoint |
| `agents/openhands/team.py` | Team orchestration, agent routing |
| `agents/openhands/support_engineer.py` | SupportEngineer agent with Sentry/Gmail context |
| `agents/openhands/software_engineer.py` | SoftwareEngineer agent |
| `agents/openhands/release_engineer.py` | ReleaseEngineer agent with K8s tools |
| `agent_service/config.py` | Agent configuration, LLM settings |

### Shared Tools

| File | Purpose |
|------|---------|
| `agent_service/shared/slack_tools.py` | Slack API interactions |
| `agent_service/shared/gmail_tools.py` | Gmail API interactions |
| `agent_service/shared/calendar_tools.py` | Google Calendar API |
| `agent_service/shared/langfuse_tools.py` | Langfuse observability |

### Evaluation

| File | Purpose |
|------|---------|
| `scripts/eval_slack_e2e.py` | E2E evaluation script |
| `results/eval_reports/` | Generated evaluation reports |

### Kubernetes

| File | Purpose |
|------|---------|
| `k8s/base/` | Base Kubernetes manifests |
| `k8s/overlays/dev/` | Dev environment overrides |
| `agents/openhands/Dockerfile` | Production image |
| `agents/openhands/Dockerfile.dev` | Dev image with git clone |

---

## Environment & Configuration

### Cluster State (Current)

```
NAME                               READY   STATUS    
openhands-svc-6d9556bb58-gz295     1/1     Running   
postgres-0                         1/1     Running   
scheduler-svc-6db68d8f56-vxmk2     1/1     Running   
vibeteam-gateway-db8dcdcbc-d7txw   1/1     Running   
```

### Environment Variables (Gateway)

| Variable | Value |
|----------|-------|
| `DEFAULT_FRAMEWORK` | `openhands` |
| `OPENHANDS_SERVICE_URL` | `http://openhands-svc:8080` |
| `SLACK_BOT_TOKEN` | (secret) |
| `SLACK_SIGNING_SECRET` | (secret) |

### Environment Variables (OpenHands)

| Variable | Value |
|----------|-------|
| `AZURE_API_KEY` | (secret) |
| `AZURE_API_BASE` | `https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/` |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5.2` |
| `AZURE_API_VERSION` | `2024-08-01-preview` |

### Slack Configuration

| Setting | Value |
|---------|-------|
| Channel ID | `C0AATPSADB8` (`#all-vibetechnologies`) |
| Bot Member | Yes |

---

## Useful Commands

### Check Cluster Status

```bash
# Pods
kubectl get pods -n vibeteam

# Logs
kubectl logs -n vibeteam deployment/vibeteam-gateway --tail=50
kubectl logs -n vibeteam deployment/openhands-svc --tail=50

# Gateway env
kubectl exec -n vibeteam deployment/vibeteam-gateway -- env | grep DEFAULT_FRAMEWORK

# OpenHands image version
kubectl get pods -n vibeteam -l app=openhands-svc -o jsonpath='{.items[0].spec.containers[0].image}'
```

### Test Agent Directly

```bash
# Test in pod
kubectl exec -n vibeteam deployment/openhands-svc -- python -c "
from agents.openhands.support_engineer import OpenHandsSupportEngineer
agent = OpenHandsSupportEngineer()
result = agent.run(task='Say hello', use_tools=False)
print(result['response'])
"
```

### Run Evaluation

```bash
# Run evaluation
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8

# List scenarios
uv run python scripts/eval_slack_e2e.py --list-scenarios
```

### Set Gateway Framework

```bash
# Set to openhands (doesn't persist across restarts)
kubectl set env deployment/vibeteam-gateway -n vibeteam DEFAULT_FRAMEWORK=openhands

# Restart to pick up changes
kubectl rollout restart deployment/vibeteam-gateway -n vibeteam
```

### Port Forward for Local Testing

```bash
pkill -f "port-forward.*vibeteam-gateway" 2>/dev/null
kubectl port-forward svc/vibeteam-gateway 8000:8080 -n vibeteam &
sleep 3
curl -s http://localhost:8000/health | jq .
```

---

## Git Log (Recent Commits)

```
8c593bd fix: use asyncio.to_thread for blocking agent.run() to keep event loop responsive
6679f8b fix: create /app/code directory with proper permissions in OpenHands dev image
f19b0bf feat: add dev mode for OpenHands with Slack tools support
d2c7388 fix: add slack_sdk to OpenHands requirements for Slack tools
fe6e99b fix: use commonAnnotations instead of commonLabels in dev overlay
5cfa7a7 feat: add CrewAI dev mode with git clone on startup
ef4dc6e feat: CrewAI dev mode improvements
89c0494 fix: add KUBECONFIG and serviceAccount for K8s access
9c3d93c fix: stricter evaluation criteria for tool failures
2200a9a fix: unify role mention syntax to @RoleName
f314ad5 fix: missing thread_ts and wrong default framework
f5a723d fix: add max_iter to prevent token overflow
```

---

## Next Steps

1. **Fix gateway timeout** → Increase to 300s
2. **Re-run evaluation** → Verify agent responds
3. **If still slow** → Add agent pre-warming
4. **If Sentry fails** → Fix connector or mock it
5. **Document results** → Update this file

---

*This document should be updated as work progresses. Keep the TODO list current.*
