# VibeTeam System Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              External Platforms                              │
│                                                                              │
│   Slack Events    GitHub Webhooks    Sentry Webhooks    Gmail   REST /api/*   │
└──────────┬────────────────┬──────────────────┬───────────┬───────────┬──────┘
           │                │                  │           │           │
           ▼                ▼                  ▼           ▼           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                GATEWAY (FastAPI)                              │
│                                                                              │
│   POST /slack/events      POST /webhook        POST /webhook/sentry          │
│   POST /slack/trigger     POST /api/run        POST /callback/agent          │
│                                                                              │
│   - Normalizes events → UnifiedMessage                                       │
│   - Routes by @RoleName or keyword fallback                                  │
│   - Handoff detection from bot replies                                       │
│   - Framework selection via agents/agents.yaml                               │
│   - Sync or async callbacks                                                  │
└──────────┬───────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AGENT SERVICES (FastAPI)                            │
│                                                                              │
│   openhands-svc   openclaw-svc   autogen-svc   crewai-svc   scheduler-svc     │
│                                                                              │
│   - openhands-svc: tool-enabled sessions, MCP, kubectl, Sentry, Gmail        │
│   - openclaw-svc: proxy to OpenClaw gateway (WebSocket)                      │
│   - autogen/crewai: optional frameworks (currently disabled)                │
│   - scheduler-svc: background/cron tasks                                     │
│                                                                              │
└──────────┬───────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SUPPORTING SERVICES                                 │
│                                                                              │
│   OpenClaw Gateway (Node) → LiteLLM (in-namespace) → Azure OpenAI            │
│   Postgres (session store)                                                   │
│   Gmail Processor (polling daemon)                                           │
│   Browserless (CDP endpoint for MCP agents)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Routing and Framework Selection

### Role Resolution

- Role mentions and keyword routing are centralized in `agent_service/shared/role_resolver.py`.
- Slack, GitHub, and other sources parse `@RoleName` and `/RoleName` mentions.
- If no role is mentioned, a keyword-based fallback selects a default role.

### Framework Resolution

- The gateway resolves which framework to use per role using `agents/agents.yaml`.
- `agents/agents.yaml` is the single source of truth for role → framework mapping, Slack handle,
  and agent directory references (AGENTS.md resolves from the directory).
- Example:

The gateway does not prefetch or inject monitoring context; it only routes messages.

```yaml
agents:
  product_manager:
    framework: openclaw
    openclaw_agent_id: product-manager
    slack_handle: ProductManager
    agent_dir: agents/ProductManager
  support_engineer:
    framework: openhands
    slack_handle: SupportEngineer
    agent_dir: agents/SupportEngineer
  software_engineer:
    framework: openhands
    slack_handle: SoftwareEngineer
    agent_dir: agents/SoftwareEngineer
```

## OpenClaw Flow

See [openclaw-introduction.md](openclaw-introduction.md) for a focused OpenClaw overview.

1. Gateway routes ProductManager (or other OpenClaw roles) to `openclaw-svc`.
2. `openclaw-svc` connects to the OpenClaw gateway over WebSocket.
3. OpenClaw gateway loads:
   - `openclaw.json` (ConfigMap `openclaw-config`, generated from `agents/agents.yaml`)
   - Agent prompts from `openclaw-agent-prompts` (ConfigMap)
4. OpenClaw uses LiteLLM in-namespace (`litellm` service) to reach Azure OpenAI.

## Agent Services and Sessions

- OpenHands maintains per-thread sessions and persists them in Postgres.
- Session keys include framework + role + source + thread ID for isolation.
- Async mode uses `/run/async → /callback/agent` for long-running tasks.
- AutoGen and CrewAI deployments are disabled for now (replicas set to 0).

## Browser Automation

- **OpenHands / CrewAI / AutoGen**: use Chrome DevTools MCP via Browserless.
  - `CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000`
- **OpenClaw**: uses the Chrome DevTools *skill* (not MCP).
  - OpenClaw does not support MCP tools directly.

## Gmail Processing

- A `gmail-processor` deployment polls Gmail and writes to the database.
- Agent services read the same Gmail OAuth files (mounted secrets).

## Key API Endpoints

- `POST /slack/events` — Slack webhook receiver
- `POST /slack/trigger` — Programmatic trigger for evals and tests
- `POST /callback/agent` — Async callback receiver
- `POST /api/run` — Direct agent execution
- `GET /health` — Gateway health

## GitHub Webhooks

Gateway supports GitHub webhooks for:
- `issues` (assignment)
- `issue_comment` (role mentions)
- `pull_request_review_comment`
- `discussion` and `discussion_comment`

Discussion comments are posted via GraphQL and require GitHub App discussions
permissions to avoid `Resource not accessible by integration` failures.

## LLM Configuration

- Default model: Azure OpenAI `gpt-5.2`.
- OpenClaw uses the in-namespace LiteLLM service.
- OpenHands calls Azure OpenAI directly (using `AZURE_*` settings).

For environment variables and secrets, see [requirements.md](requirements.md).
