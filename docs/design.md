# VibeTeam System Design

## Architecture Overview

```text
External Integrations
  - Slack Events / Slack Trigger API
  - GitHub Webhooks
  - Sentry Webhooks
  - Direct REST API

        |
        v
+---------------------------------------------+
| vibeteam-gateway (FastAPI)                  |
| - Normalizes incoming events                |
| - Resolves role mentions / keyword fallback |
| - Resolves framework per role               |
| - Dispatches sync or async runs             |
+----------------------+----------------------+
                       |
                       | framework from agents/agents.yaml
                       |
         +-------------+-------------+
         |                           |
         v                           v
+------------------------+   +------------------------+
| openhands-svc          |   | openclaw-svc           |
| (FastAPI runtime)      |   | (FastAPI WS proxy)     |
+-----------+------------+   +-----------+------------+
            |                            |
            | OpenHands SDK              | WebSocket RPC
            v                            v
   +--------------------+        +----------------------+
   | Generic class Agent|        | openclaw-gateway     |
   | per role           |        | (Node runtime)       |
   +---------+----------+        +-----+----------+-----+
             |                         |          |
             |                         |          +--> Browserless (CDP)
             |                         +--> LiteLLM --> Azure OpenAI
             v
      Azure OpenAI

Shared services:
  - Postgres (session persistence)
  - Scheduler service (background jobs)
  - Gmail processor (polling + ingestion)
```

## Shared Agent Configuration Storage

The `agents-config` PVC is mounted by multiple services.

```text
GitHub repo (agents/*)
      |
      | initContainer: agents-sync
      v
+---------------------------+
| agents-config PVC (RWX)   |
+------------+--------------+
             |
   +---------+---------+---------------------------+
   |                   |                           |
   v                   v                           v
vibeteam-gateway   openhands-svc              openclaw-gateway
/app/agents        /app/agents                /app/agents
(read routing cfg) (read/write prompts+cfg)   (read/write prompts+cfg)

openclaw-svc also mounts /app/agents to manage role config coherently
with the gateway path.
```

## Configuration Sources

### 1. Role-to-framework routing

Single source of truth: `agents/agents.yaml`

- `framework` (`openhands` or `openclaw`)
- `slack_handle`
- `agent_dir`
- `openclaw_agent_id` (for OpenClaw roles)

Current shape:

```yaml
agents:
  product_manager:
    framework: openclaw
    openclaw_agent_id: product-manager
    slack_handle: ProductManager
    agent_dir: ProductManager
  support_engineer:
    framework: openhands
    slack_handle: SupportEngineer
    agent_dir: SupportEngineer
  release_engineer:
    framework: openhands
    slack_handle: ReleaseEngineer
    agent_dir: ReleaseEngineer
  software_engineer:
    framework: openhands
    slack_handle: SoftwareEngineer
    agent_dir: SoftwareEngineer
  marketing_manager:
    framework: openhands
    slack_handle: MarketingManager
    agent_dir: MarketingManager
```

### 2. OpenHands instructions/runtime config

For role `X`, OpenHands loads:

- `agents/shared/AGENTS.md`
- `agents/<AgentDir>/AGENTS.md`
- `agents/<AgentDir>/config.json` (optional; supports MCP config dialects)

OpenHands execution uses one generic role runtime class (`class Agent`) and preloads configured roles at service startup.

### 3. OpenClaw config

OpenClaw gateway uses `openclaw-config.json`, generated from:

- `k8s/base/openclaw-config.base.json`
- `agents/agents.yaml`
- script: `scripts/render_openclaw_config.py`

Prompt files are sourced from shared agents content under `/home/node/.openclaw/agents/<agent-id>/agent/AGENTS.md`.

## Knowledgebase Design

VibeTeam uses a layered knowledge model instead of a single vector database.

### Layer 1: Canonical agent configuration and instructions (filesystem)

- Routing/source-of-truth metadata: `agents/agents.yaml`
- Shared policy/instructions: `agents/shared/AGENTS.md`
- Role policy/instructions: `agents/<AgentDir>/AGENTS.md`
- Optional per-role runtime/tool config: `agents/<AgentDir>/config.json`
- Skills: `agents/<AgentDir>/skills/*/SKILL.md`

This layer is shared into pods via the RWX `agents-config` PVC.

### Layer 2: Documentation retrieval (local indexed search)

- Product docs search: `agent_service/shared/docs_tools.py`
  - BM25 index over local markdown files (`docs/`, `readiness/`, root markdown)
  - fallback keyword search when BM25 dependency is unavailable
- Infra docs search: `docs/infra-llms.txt` via `search_infra_docs()`

This is local retrieval, not remote vector RAG.

### Layer 3: Live operational evidence tools

Agents are expected to gather real-time evidence directly from systems:

- Kubernetes: `agent_service/shared/kubectl_tools.py`
- Sentry API: `agent_service/shared/sentry_tools.py`
- Slack thread/channel context: `agent_service/shared/slack_tools.py`
- Gmail context: `agent_service/shared/gmail_tools.py`
- Browser/context fetch: `agent_service/shared/browser_tools.py`

This layer is the primary source for incident triage and production-state answers.

### Layer 4: Session memory

- Session messages/results persist in Postgres via `agent_service/shared/db.py`
- Session keys are framework/role/context scoped

This is conversation memory, not semantic long-term document memory.

### Freshness and cache behavior

- File edits on `agents-config` PVC are immediately visible to mounted pods.
- Prompt context (`AGENTS.md`) for OpenHands is composed at run time, so prompt text updates are picked up on subsequent runs.
- Role/framework mapping from `agents/agents.yaml` is cached in-process (`vibeteam/agents_config.py`, `agent_service/shared/role_resolver.py`), so routing-handle changes require process restart to take effect.
- OpenHands per-role `config.json` is loaded when the role agent object is created; changes may require agent/service restart to fully apply.

## Runtime Request Flow

### Slack path

1. Slack event arrives at `POST /slack/events` (gateway).
2. Gateway resolves target role.
3. Gateway resolves framework from `agents/agents.yaml`.
4. Gateway calls the selected service (`/run` sync or `/run/async` async).
5. Service response is sent back to Slack (or callback path for async).

### GitHub/Sentry path

1. Webhook arrives at gateway route (`/webhook`, `/webhook/sentry`).
2. Gateway derives role via mention/routing rules.
3. Framework is resolved from `agents/agents.yaml`.
4. Agent service executes and returns result.

## OpenHands Runtime Notes

- Tool-enabled runs use OpenHands SDK with `TerminalTool` + `FileEditorTool`.
- Role-specific GitHub App token injection is applied per request.
- `KUBECONFIG` is initialized in-container for cluster access.
- Sessions are persisted to Postgres using composite session keys.

## OpenClaw Runtime Notes

- `openclaw-svc` resolves `openclaw_agent_id` then communicates with `openclaw-gateway` over WS.
- `openclaw-gateway` reads model/provider config from `openclaw-config.json`.
- LiteLLM is used in-namespace as provider endpoint for OpenClaw.
- Browser automation is provided through Browserless/CDP integration.

## Self-Modifying Configuration Capability

Current behavior supports runtime self-modification when requested:

- OpenHands can read/write `/app/agents` (shared PVC).
- OpenClaw gateway can read/write `/app/agents` and mapped prompt paths.
- OpenClaw service can read/write `/app/agents`.

This allows controlled agent-side updates to prompts/config files under `agents/` (subject to task instructions and guardrails).

## Key Endpoints

Gateway:

- `POST /slack/events`
- `POST /slack/trigger`
- `POST /api/run`
- `POST /callback/agent`
- `POST /callback/agent/progress`
- `GET /health`

Agent services:

- `POST /run`
- `POST /run/async`
- `POST /run/stream`
- `GET /health`

## Related Docs

- [requirements.md](requirements.md)
- [openclaw-introduction.md](openclaw-introduction.md)
