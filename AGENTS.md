# VibeTeam Agent Instructions

Instructions for AI agents working on the VibeTeam repository.

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
    roles/            # Agent roles (ProductManager, ReleaseEngineer, etc.)
    team.py           # Team orchestration
  readiness/          # System readiness checks
    check.py          # Automated script
    playbook.md       # GenAI evaluation playbook
  scripts/            # Utility scripts
  tests/              # Test files
  config/             # Configuration files
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
