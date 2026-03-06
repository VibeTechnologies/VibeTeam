# VibeTeam Requirements

## Overview

VibeTeam routes work via `@RoleName` or `/RoleName` mentions across Slack, GitHub, and Sentry. The gateway resolves which agent framework to use from `agents/agents.yaml`. The canonical architecture lives in [design.md](design.md). For OpenClaw-specific context, see [openclaw-introduction.md](openclaw-introduction.md).

## Agents and Frameworks

| Role | Mention | Default Framework | Primary Responsibilities | Tools |
|------|---------|-------------------|--------------------------|-------|
| **SoftwareEngineer** | `@SoftwareEngineer` | OpenHands | Code, tests, PRs | Shell, Git, GitHub, Chrome DevTools MCP |
| **ReleaseEngineer** | `@ReleaseEngineer` | OpenHands | Deployments, k8s, CI/CD | kubectl, GitHub, Langfuse, Chrome DevTools MCP |
| **SupportEngineer** | `@SupportEngineer` | OpenHands | Customer support, incident analysis | Sentry, Gmail, GitHub, Chrome DevTools MCP |
| **ProductManager** | `@ProductManager` | OpenClaw | PRDs, roadmap, backlog | GitHub, Chrome DevTools skill |
| **MarketingManager** | `@MarketingManager` | OpenHands | Announcements, content | Chrome DevTools MCP |

**Note:** AutoGen and CrewAI are currently disabled (deployments run with `replicas: 0`).

Framework mapping is configured in `agents/agents.yaml` (override with `AGENTS_CONFIG_PATH`).

Example:

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

The gateway only routes messages; it does not prefetch or inject monitoring context.

## Browser Automation

- **OpenHands / CrewAI / AutoGen**: use Chrome DevTools MCP via Browserless.
  - Requires `CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000`.
  - MCP tools are exposed as `mcp__chrome-devtools__*`.
- **OpenClaw**: uses the Chrome DevTools *skill* (not MCP).
  - OpenClaw does not support MCP tools directly.

## LLM Model

OpenHands calls Azure OpenAI directly. OpenClaw routes requests through the
in-namespace LiteLLM service. Both default to `gpt-5.2`.

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

### Azure (OpenHands) + LiteLLM (OpenClaw)

```bash
AZURE_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-5.2
AZURE_ALLOW_RESPONSES_MODELS=false
VIBETEAM_MODEL=azure/gpt-5.2
VIBETEAM_TEMPERATURE=0.3
VIBETEAM_MAX_TOKENS=4096
OPENHANDS_DISABLE_PROMPT_CACHE_RETENTION=true

# OpenClaw LiteLLM (in-namespace)
LITELLM_BASE_URL=http://litellm:4000
LITELLM_API_KEY=
LITELLM_MASTER_KEY=
```

### GitHub + Sentry

```bash
GITHUB_TOKEN=  # optional: local eval post-checks only (gateway webhook path uses GitHub App tokens)
GITHUB_APP_ID_SOFTWARE_ENGINEER=
GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER=
GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER=
GITHUB_APP_ID_SUPPORT_ENGINEER=
GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER=
GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER=
GITHUB_APP_ID_RELEASE_ENGINEER=
GITHUB_APP_INSTALLATION_ID_RELEASE_ENGINEER=
GITHUB_APP_PRIVATE_KEY_RELEASE_ENGINEER=
GITHUB_APP_ID_PRODUCT_MANAGER=
GITHUB_APP_INSTALLATION_ID_PRODUCT_MANAGER=
GITHUB_APP_PRIVATE_KEY_PRODUCT_MANAGER=
GITHUB_APP_ID_MARKETING_MANAGER=
GITHUB_APP_INSTALLATION_ID_MARKETING_MANAGER=
GITHUB_APP_PRIVATE_KEY_MARKETING_MANAGER=
SENTRY_AUTH_TOKEN=
```

Role-scoped GitHub App credentials are preferred and used to attribute PRs to the role bot.
In Kubernetes, agent pods load these from the `github-app-role-secrets` secret via `envFrom`.
**Required**: OpenHands/OpenClaw services fail fast if GitHub or Sentry credentials are missing.

Private keys can be supplied as PEM strings with `\n` newlines. For local `.env` usage
with `export $( < .env )`, replace spaces with underscores:
`BEGIN_RSA_PRIVATE_KEY` / `END_RSA_PRIVATE_KEY`.

### Slack

```bash
SLACK_BOT_TOKEN=
SLACK_ASSISTANT_TOKEN=
SLACK_ASSISTANT_STATUS_TEXT=
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
AGENTS_CONFIG_PATH=agents/agents.yaml
```

## Evaluation

Use `scripts/eval_slack_e2e.py` to run end-to-end Slack evaluations. Reports are saved under `results/eval_reports/`.
Requirement: cross-channel GitHub handoff evals MUST use native role mentions
(`@SoftwareEngineer`, `@SupportEngineer`, etc.) in Slack and GitHub trigger text.
Do not use slash-role mentions (`/SoftwareEngineer`) in these eval scenarios.
Verification must confirm role GitHub App bot responses in the target issue/PR threads.
The `software_engineer_github_app_hello_world` scenario targets
`VibeTechnologies/vibeteam-eval-hello-world` and validates PR creation plus bot
attribution, so the SoftwareEngineer GitHub App must be installed on that repo.
Post-checks also require `GITHUB_TOKEN` (or `GH_TOKEN`) to verify PR metadata.
The `github_issue_pr_handoff_slack` scenario validates issue + PR handoff comments in
the same eval repo. Use `github_issue_pr_handoff_github` in `eval_github_e2e.py`
to validate the same issue+PR handoff semantics from GitHub webhooks.
Discussion handoffs remain covered via `github_threads_all`.

Use `scripts/eval_github_e2e.py` to validate GitHub webhook routing and multi-agent
handoffs over issues, discussions, and PR comments. This requires:
- GitHub webhooks enabled for `issues`, `issue_comment`, `pull_request_review_comment`,
  `discussion`, and `discussion_comment` events.
- Discussions enabled on `VibeTechnologies/vibeteam-eval-hello-world`.
- Role GitHub Apps granted Discussions read/write permission (otherwise discussion
  comments fail with `Resource not accessible by integration`).
- `GITHUB_TOKEN` (or `GH_TOKEN`) with issue/discussion write permissions.

## Gmail Processor

The `gmail-processor` deployment polls Gmail and shares the same `gmail-oauth-secret` as the agent services. If Gmail secrets are missing, the processor will fail or stay in init.

## Discord Integration

Discord is supported via standalone polling scripts (`scripts/run_discord_bot.py`). It is not wired into the gateway webhook flow.
