# VibeTeam Requirements

## Overview

VibeTeam routes work via `@RoleName` or `/RoleName` mentions across Slack, GitHub, and Sentry. The gateway resolves which agent framework to use from `agents.yaml`. The canonical architecture lives in [design.md](design.md).

## Agents and Frameworks

| Role | Mention | Default Framework | Primary Responsibilities | Tools |
|------|---------|-------------------|--------------------------|-------|
| **SoftwareEngineer** | `@SoftwareEngineer` | OpenHands | Code, tests, PRs | Shell, Git, GitHub, Chrome DevTools MCP |
| **ReleaseEngineer** | `@ReleaseEngineer` | OpenHands | Deployments, k8s, CI/CD | kubectl, GitHub, Langfuse, Chrome DevTools MCP |
| **SupportEngineer** | `@SupportEngineer` | OpenHands | Customer support, incident analysis | Sentry, Gmail, GitHub, Chrome DevTools MCP |
| **ProductManager** | `@ProductManager` | OpenClaw | PRDs, roadmap, backlog | GitHub, Chrome DevTools skill |
| **MarketingManager** | `@MarketingManager` | OpenHands | Announcements, content | Chrome DevTools MCP |

Framework mapping is configured in `agents.yaml` (override with `AGENTS_CONFIG_PATH`).

Example:

```yaml
agents:
  product_manager:
    framework: openclaw
    openclaw_agent_id: product-manager
    slack_handle: ProductManager
    prompt_path: agents/ProductManager/AGENTS.md
  support_engineer:
    framework: openhands
    slack_handle: SupportEngineer
    prompt_path: agents/SupportEngineer/AGENTS.md
```

## Browser Automation

- **OpenHands / CrewAI / AutoGen**: use Chrome DevTools MCP via Browserless.
  - Requires `CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000`.
  - MCP tools are exposed as `mcp__chrome-devtools__*`.
- **OpenClaw**: uses the Chrome DevTools *skill* (not MCP).
  - OpenClaw does not support MCP tools directly.

## LLM Model

All agents use Azure OpenAI `gpt-5.2` via LiteLLM.

| Setting | Value |
|---------|-------|
| Provider | Azure OpenAI |
| Deployment | `gpt-5.2` |
| API version | `2024-08-01-preview` (default) |
| LiteLLM model string | `azure/gpt-5.2` |

Responses-only models (e.g., `gpt-5.2-codex`) require:
- `AZURE_ALLOW_RESPONSES_MODELS=true`
- `AZURE_API_VERSION >= 2025-03-01-preview`

## Environment Variables and Secrets

### Azure + LiteLLM

```bash
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-5.2
AZURE_ALLOW_RESPONSES_MODELS=false
VIBETEAM_MODEL=azure/gpt-5.2
VIBETEAM_TEMPERATURE=0.3
VIBETEAM_MAX_TOKENS=4096

# OpenClaw LiteLLM (in-namespace)
LITELLM_BASE_URL=http://litellm:4000
LITELLM_API_KEY=
LITELLM_MASTER_KEY=
```

### GitHub + Sentry

```bash
GITHUB_TOKEN=
SENTRY_AUTH_TOKEN=
```

**Required**: OpenHands/OpenClaw services fail fast if these are missing.

### Slack

```bash
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_TRIGGER_SECRET=
```

### Gmail (File-Based Secrets)

Gmail credentials are mounted as files and referenced by path:

```bash
GMAIL_CREDENTIALS_PATH=/gmail/gmail-credentials.json
GMAIL_TOKEN_PATH=/gmail/gmail-token.json
```

Create the secret:

```bash
kubectl create secret generic gmail-oauth-secret -n vibeteam \
  --from-file=gmail-credentials.json=.secrets/gmail-credentials.json \
  --from-file=gmail-token.json=.secrets/gmail-token.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

**Required**: OpenHands/OpenClaw services fail fast if these files are missing.

### Gateway / Services

```bash
OPENHANDS_SERVICE_URL=http://openhands-svc:8080
CREWAI_SERVICE_URL=http://crewai-svc:8080
AUTOGEN_SERVICE_URL=http://autogen-svc:8080
OPENCLAW_SERVICE_URL=http://openclaw-svc:8080
SCHEDULER_SERVICE_URL=http://scheduler-svc:8080
DEFAULT_FRAMEWORK=openhands
CALLBACK_SECRET=
CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000
```

### OpenClaw

```bash
OPENCLAW_GATEWAY_URL=http://openclaw-gateway:18789
OPENCLAW_GATEWAY_TOKEN=
AGENTS_CONFIG_PATH=agents.yaml
```

## Evaluation

Use `scripts/eval_slack_e2e.py` to run end-to-end Slack evaluations. Reports are saved under `results/eval_reports/`.

## Gmail Processor

The `gmail-processor` deployment polls Gmail and shares the same `gmail-oauth-secret` as the agent services. If Gmail secrets are missing, the processor will fail or stay in init.

## Discord Integration

Discord is supported via standalone polling scripts (`scripts/run_discord_bot.py`). It is not wired into the gateway webhook flow.
