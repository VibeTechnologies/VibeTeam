# VibeTeam Requirements

## Overview

VibeTeam is a multi-agent system that routes work via `@RoleName` or `/RoleName` mentions in Slack, GitHub, and Sentry. The canonical architecture lives in [design.md](design.md).

## Agents

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `@SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `@ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `@SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `@ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
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

# Gateway/Services
OPENHANDS_SERVICE_URL=http://openhands-svc:8080
CREWAI_SERVICE_URL=http://crewai-svc:8080
AUTOGEN_SERVICE_URL=http://autogen-svc:8080
SCHEDULER_SERVICE_URL=http://scheduler-svc:8080
DEFAULT_FRAMEWORK=openhands
CALLBACK_SECRET=

# Database
DATABASE_URL=postgresql://...
```

## Evaluation

See [eval-architecture.md](eval-architecture.md) for scenarios, scoring, and run instructions.