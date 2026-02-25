# VibeTeam Requirements

## Overview

VibeTeam is a multi-agent system that routes work via `@RoleName` or `/RoleName` mentions in Slack, GitHub, and Sentry. The canonical architecture lives in [design.md](design.md).

## Agents

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `@SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub, Chrome DevTools MCP |
| **ReleaseEngineer** | `@ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub, Chrome DevTools MCP |
| **SupportEngineer** | `@SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse, Chrome DevTools MCP |
| **ProductManager** | `@ProductManager` | PRDs, backlog prioritization, user stories | GitHub, Chrome DevTools MCP |
| **MarketingManager** | `@MarketingManager` | Social media, announcements, content | Chrome DevTools MCP |

## LLM Model

All agents use **Azure OpenAI `gpt-5.2`** via LiteLLM. The deployment name is `gpt-5.2` (dot notation, not dash).

| Setting | Value |
|---------|-------|
| Provider | Azure OpenAI |
| Deployment | `gpt-5.2` |
| Model version | `gpt-5.2-2025-12-11` |
| API version | `2024-08-01-preview` |
| Default max tokens | 4096 |
| LiteLLM model string | `azure/gpt-5.2` |

The model is configured via the `AZURE_OPENAI_DEPLOYMENT` K8s secret. GPT-5+ models require `max_completion_tokens` instead of `max_tokens` — the codebase handles this automatically.

## Routing and Sessions

- Threads activate on `@VibeTeam` and persist agent subscriptions.
- Role mentions in bot messages trigger handoffs.
- Details and data models: [design.md](design.md) and [webhook-routing.md](webhook-routing.md).

## Agent Frameworks

| Framework | Status | Notes |
|-----------|--------|-------|
| **OpenHands** | Active | Full tool support, session persistence |
| CrewAI | Optional | Available via `crewai-svc` when deployed |
| AutoGen | Optional | Available via `autogen-svc` when deployed |
| OpenCode | Experimental | CLI-based, limited tool injection |

## Browser Automation (Chrome DevTools MCP)

All agent roles can use Chrome DevTools MCP when a CDP browser is available. In production, this connects to the shared Browserless service via the `CHROME_DEVTOOLS_BROWSER_URL` environment variable. Agent containers require Node.js (for `npx chrome-devtools-mcp@latest`).

## Environment Variables (Required)

```bash
# LLM
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview

# GitHub
GITHUB_TOKEN=
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_INSTALLATION_ID=

# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_TRIGGER_SECRET=

# Discord
DISCORD_BOT_TOKEN=

# Gmail OAuth (see Gmail Integration section below)
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=
GMAIL_USER_EMAIL=support@vibebrowser.app

# Gateway/Services
OPENHANDS_SERVICE_URL=http://openhands-svc:8080
CREWAI_SERVICE_URL=http://crewai-svc:8080
AUTOGEN_SERVICE_URL=http://autogen-svc:8080
SCHEDULER_SERVICE_URL=http://scheduler-svc:8080
DEFAULT_FRAMEWORK=openhands
CALLBACK_SECRET=
CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000

# Database
DATABASE_URL=postgresql://...
```

## Evaluation

See [eval-architecture.md](eval-architecture.md) for scenarios, scoring, and run instructions.

## Gmail Integration

The SupportEngineer agent triages incoming support emails via a Gmail processor daemon (`k8s/base/gmail-processor.yaml`). This requires OAuth2 credentials.

### Setup

1. **Create OAuth credentials** in [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
   - Application type: "Desktop app"
   - Enable the Gmail API
   - Download the client secret JSON

2. **Generate a refresh token** using the OAuth consent flow:
   ```bash
   # Use the google-auth-oauthlib helper
   python -c "
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_secrets_file(
       'client_secret.json',
       scopes=['https://www.googleapis.com/auth/gmail.readonly',
               'https://www.googleapis.com/auth/gmail.modify']
   )
   creds = flow.run_local_server(port=8090)
   print('Refresh token:', creds.refresh_token)
   "
   ```

3. **Create the K8s secret** (required for gmail-processor pods):
   ```bash
   kubectl create secret generic gmail-oauth-secret -n vibeteam \
     --from-literal=GMAIL_CLIENT_ID="..." \
     --from-literal=GMAIL_CLIENT_SECRET="..." \
     --from-literal=GMAIL_REFRESH_TOKEN="..." \
     --from-literal=GMAIL_USER_EMAIL="support@vibebrowser.app" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

4. **Restart the gmail-processor**:
   ```bash
   kubectl rollout restart deployment/gmail-processor -n vibeteam
   ```

The template at `k8s/base/gmail-secrets.yaml` shows the expected secret structure.

## Discord Integration

| Component | Status |
|-----------|--------|
| Connector code | Complete (`vibeteam/connectors/discord.py`, 661 lines) |
| Bot script | Complete (`scripts/run_discord_bot.py`) — polling-based |
| Gateway webhook route | Not implemented |
| K8s deployment | Not implemented |

Discord currently works only via the standalone polling bot script. It is **not** integrated into the gateway webhook-routing architecture and has no K8s deployment. To use Discord as a production integration channel, a gateway route and K8s deployment would need to be added.
