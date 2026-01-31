# VibeTeam Agent Instructions

Instructions for AI agents working on the VibeTeam repository.

## System Readiness

Before running VibeTeam agents or after infrastructure changes, verify system readiness.

### Option 1: Run Script (Quick)

```bash
python readiness/check.py           # Standard checks
python readiness/check.py --quick   # Health endpoints only
python readiness/check.py --full    # Everything including k8s, Sentry, Langfuse
```

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
  agents/              # Multi-framework agent implementations
    autogen/           # AutoGen agents (planned)
    crewai/            # CrewAI agents (planned)
    openhands/         # OpenHands agents (active)
    opencode/          # OpenCode agents (experimental)
  vibeteam/            # Main package
    connectors/        # External service integrations
    team/              # Team orchestration and test harness
  readiness/           # System readiness checks
    check.py           # Automated script
    playbook.md        # GenAI evaluation playbook
  docs/                # Documentation
    requirements.md    # System requirements and agent roles
    design.md          # Architecture and design decisions
  scripts/             # Utility scripts
  tests/               # Test files
  config/              # Configuration files
```

## Documentation

- **[docs/requirements.md](docs/requirements.md)** - System requirements, agent roles, and responsibilities
- **[docs/design.md](docs/design.md)** - Architecture, routing logic, and design decisions

## Key Connectors

| Connector | Purpose |
|-----------|---------|
| `GitHubConnector` | Issues, PRs, code review |
| `SlackConnector` | Slack messaging and threads |
| `DiscordConnector` | Discord messaging and threads |
| `SentryConnector` | Error tracking |
| `LangfuseConnector` | LLM observability |
| `HealthConnector` | Endpoint monitoring |
| `GmailConnector` | Email processing |

## Environment Variables

Required in `.env`:
```
# LLM
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview

# GitHub
GITHUB_TOKEN=
```

Optional:
```
# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Discord
DISCORD_BOT_TOKEN=

# Database
DATABASE_URL=postgresql://...

# Monitoring
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

## Model Configuration

VibeTeam uses Azure OpenAI. The model name format is `azure/gpt-5-2` (hyphen, not dot).

## Customer Requests

Feature requests are tracked in GitHub Issue #322 (VibeTechnologies/VibeWebAgent).
Use `GitHubConnector.get_customer_requests_table()` to read/update.

## Current Work

**Active Issue: #38** - Deploy VibeTeam to Kubernetes and verify integrations
https://github.com/VibeTechnologies/VibeTeam/issues/38
