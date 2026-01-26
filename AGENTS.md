# VibeTeam Agent Instructions

Instructions for AI agents working on the VibeTeam repository.

## Available Agents

VibeTeam has two types of agents:

### Interactive Agents (On-Demand)

| Channel | How to Invoke | Use Case |
|---------|---------------|----------|
| **Slack** | `@vibeteam <request>` | Quick questions, code changes |
| **GitHub** | `fix-me` label or `@openhands-agent` | Auto-fix issues |
| **Web UI** | [team.vibebrowser.app](https://team.vibebrowser.app) | Interactive IDE |

### Autonomous Agents (Scheduled)

| Agent | Codename | CLI Key | Schedule | Purpose |
|-------|----------|---------|----------|---------|
| Product Manager | Curie | `pm` | Every 2h | Feature requests, PRDs, roadmap |
| Software Engineer | Turing | `swe` | Every 4h | Code fixes, implementations |
| Support Engineer | Nightingale | `support` | Every 15min | Email support, responses |
| Reliability Engineer | Hawking | `sre` | Every 5min | Health checks, incidents |
| Release Engineer | Einstein | `release` | Daily 9AM | Release validation, Sentry |
| Marketer | Feynman | `marketer` | On-demand | Content, announcements |

**CLI usage:**
```bash
vibeteam run "your task" --agent <key>   # e.g., --agent pm, --agent swe
vibeteam agents                           # List all agents
vibeteam info <key>                       # Agent details
```

See [docs/openhands-integration.md](docs/openhands-integration.md) for interactive agent usage guide.

## Readiness Check

Before running VibeTeam agents or after infrastructure changes, verify system readiness.

### Option 1: Run Script (Fast)

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python readiness/check.py
```

| Flag | Use Case |
|------|----------|
| (none) | Standard checks: endpoints, LLM, GitHub |
| `--quick` | Endpoints only (for cron) |
| `--full` | Everything including k8s, Sentry, Langfuse |
| `--json` | Machine-readable output |

Exit codes: 0=GREEN, 1=YELLOW, 2=RED

### Option 2: Follow Playbook (Thorough)

For detailed investigation or incident analysis:

1. Read the playbook: `readiness/playbook.md`
2. Execute each check command
3. Interpret results using the evaluation criteria
4. Produce a report using the template at the end

The playbook allows for intelligent judgment on ambiguous cases.

## Repository Structure

```
VibeTeam/
  vibeteam/           # Main package
    connectors/       # External service integrations
    agents/           # Agent implementations (ProductManager, SoftwareEngineer, etc.)
    team.py           # Team orchestration
  k8s/                # Kubernetes manifests
    base/openhands/   # OpenHands server deployment
  templates/          # GitHub workflow & microagent templates
  readiness/          # System readiness checks
    check.py          # Automated script
    playbook.md       # GenAI evaluation playbook
  scripts/            # Utility scripts
  tests/              # Test files
  docs/               # Documentation
```

## Key Connectors

| Connector | Purpose |
|-----------|---------|
| `GitHubConnector` | Issues, PRs, code review |
| `SentryConnector` | Error tracking |
| `LangfuseConnector` | LLM observability |
| `HealthConnector` | Endpoint monitoring |
| `GmailConnector` | Email processing |

## Environment Variables

Required in `.env`:
```
AZURE_API_KEY=
AZURE_API_BASE=https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/
AZURE_API_VERSION=2024-08-01-preview
GITHUB_TOKEN=
```

Optional:
```
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

## Model Configuration

VibeTeam uses Azure OpenAI. The model name format is `azure/gpt-5-2` (hyphen, not dot).

## Customer Requests

Feature requests are tracked in GitHub Issue #322 (VibeTechnologies/VibeWebAgent).
Use `GitHubConnector.get_customer_requests_table()` to read/update.
