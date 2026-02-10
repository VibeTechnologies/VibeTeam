# Current Work Plan

## In Progress: Fix release_deploy eval — system prompt template (Issue A)

**Status:** Code changes complete, needs commit, deploy, and eval verification.
**Branch:** master (uncommitted changes)

### Problem
The `release_deploy` eval failed because agents narrate what they'd do instead of actually running kubectl commands. Root cause: `system_prompt_kwargs` with `agent_context` was silently dropped because no custom `system_prompt_filename` was provided. The default OpenHands template (`system_prompt.j2`) ignores unknown kwargs.

### Fix Applied
- [x] Created `agents/openhands/prompts/agent_system.j2` — custom Jinja2 template that renders `{{ agent_context }}` (the agent persona/instructions) into the system prompt
- [x] Wired `system_prompt_filename` in all 5 agent constructors:
  - `release_engineer.py` — `system_prompt_filename=os.path.join(os.path.dirname(__file__), "prompts", "agent_system.j2")`
  - `software_engineer.py` — same
  - `support_engineer.py` — same
  - `marketing_manager.py` — same
  - `product_manager.py` — same
- [x] Enhanced ReleaseEngineer context: added deployment playbook, deployment response format, clearer context block preamble
- [x] Added deployment-specific task template in `slack.py` with explicit step-by-step kubectl instructions
- [x] Added `tests/test_task_routing.py` (301 lines) for task routing/detection logic

### Remaining Steps
- [ ] Commit all changes
- [ ] Deploy to cluster (build Docker image, push, restart deployments)
- [ ] Run `release_deploy` eval: `uv run python scripts/eval_slack_e2e.py --scenario release_deploy --channel C0AATPSADB8 --timeout 600`
- [ ] Verify no regression: run `support_400_errors` and `stripe_webhook_failure` evals
- [ ] Update eval results table below

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
        GW->>GW: route_by_keywords(text)<br/>(from role_resolver.py)
    end
    GW->>Slack: Add reaction

    Note over GW,OH: 3. AGENT INVOCATION
    GW->>GW: Build task prompt with<br/>investigation instructions<br/>(slack.py:372-439)
    GW->>OH: POST /run {task, role, context_type, context_id}<br/>(3 retries, 600s timeout)
    OH->>Team: team.run(task, context_type, context_id)

    Note over Team,Agent: 4. AGENT ROUTING (openhands-svc)
    Team->>Team: parse_mention(task) → role<br/>(team.py uses role_resolver)
    alt No @mention found
        Team->>Team: route_by_keywords(task)<br/>(from role_resolver.py)
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

### Role Resolution & Keyword Routing

Consolidated into `agents/shared/role_resolver.py`:
- **Role mention parsing** (PR #59) — Supports full names, short forms (swe/pm), persona names (einstein/grace/ada), and extras (dev/product/marketer/supervisor). 37 unit tests.
- **Keyword routing** (`652cfc6`) — Single `route_by_keywords()` function used by both gateway and openhands-svc. Word-boundary regex prevents false positives. ~50 parametrized tests covering all 5 roles.

### kubectl Context (Parallelized)

`agents/shared/kubectl_tools.py` uses two-phase approach (PR #59):
1. Fetch pods first (~1s) to discover existing deployments
2. Fetch events, logs, rollout history in parallel via `ThreadPoolExecutor`
3. Non-existent deployments auto-skipped

Reduced from worst-case 210s (sequential) to ~11s (parallel).

---

## Completed Work

| PR/Commit | Title | Key Changes |
|-----------|-------|-------------|
| #60 | fix(eval): rescore mode, handoff timeout, agent verification | `--thread-ts` rescore, `--handoff-timeout`, SWE anti-hallucination guardrails, 27 new tests |
| #53 | feat: GitHub App auth + Sentry webhook routing | GitHubConnector App auth, Sentry classification, webhook routing, 33 integration tests |
| `687f328` | docs: update plan.md | keyword routing done, close PR #51, track PR #53 |
| `652cfc6` | refactor: consolidate keyword routing into role_resolver | Single `route_by_keywords()` in role_resolver.py, word-boundary regex |
| #59 | refactor: consolidate role parsing, parallelize kubectl, merge eval scripts | RoleResolver module, ThreadPoolExecutor kubectl, deleted eval_slack_agent.py |
| #55 | feat: add Documentation Knowledge Base tool for agents | Docs tools for agent knowledge base |
| #54 | fix(slack): correct webhook URLs to use webhook.team subdomain | Manifest fix (blocked on manual Slack config) |
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

---
Last updated: 2026-02-10
