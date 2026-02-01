# VibeTeam Agent Instructions

Instructions for AI agents working on the VibeTeam repository.

## Agent Roles and Responsibilities

Each agent has specific service ownership and handoff responsibilities. See individual agent instructions for details:

| Agent | Persona | Instructions | Primary Services |
|-------|---------|--------------|------------------|
| **SupportEngineer** | Grace | [agents/SupportEngineer/AGENTS.md](agents/SupportEngineer/AGENTS.md) | Gmail, Sentry, Customer Requests |
| **ReleaseEngineer** | Einstein | [agents/ReleaseEngineer/AGENTS.md](agents/ReleaseEngineer/AGENTS.md) | API endpoints, k3s cluster, CI/CD |
| **SoftwareEngineer** | Alex | [agents/SoftwareEngineer/AGENTS.md](agents/SoftwareEngineer/AGENTS.md) | VibeBrowser repos, code review |
| **ProductManager** | Jordan | [agents/ProductManager/AGENTS.md](agents/ProductManager/AGENTS.md) | GitHub Issues, PRDs, roadmap |
| **MarketingManager** | Sam | [agents/MarketingManager/AGENTS.md](agents/MarketingManager/AGENTS.md) | Status page, docs, announcements |

## Service Ownership Matrix

| Service | Primary Owner | Escalation Path |
|---------|--------------|-----------------|
| **api.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **api-dev.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **portal.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **GenAI Gateway** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **Gmail (support@)** | SupportEngineer | → ProductManager (roadmap questions) |
| **Sentry** | SupportEngineer | → ReleaseEngineer (infra) / SoftwareEngineer (code) |
| **Langfuse** | SupportEngineer | → SoftwareEngineer (LLM issues) |
| **GitHub Issues** | ProductManager | → SoftwareEngineer (implementation) |
| **GitHub Actions CI/CD** | ReleaseEngineer | → SoftwareEngineer (test failures) |
| **Customer Requests (#322)** | SupportEngineer | → ProductManager (prioritization) |
| **Status Page** | MarketingManager | ← ReleaseEngineer (incident info) |
| **Documentation** | MarketingManager | ← SoftwareEngineer (technical review) |

## Handoff Decision Tree

When an agent receives a request, they should use this decision tree:

```
Is this a customer email/complaint?
  → SupportEngineer handles initially
  
Is this an infrastructure outage (API down, 5xx, health check failing)?
  → ReleaseEngineer investigates
  
Is this a code bug or feature request?
  → SoftwareEngineer implements
  
Is this a prioritization or roadmap question?
  → ProductManager decides
  
Does this need public communication?
  → MarketingManager drafts
```

## System Readiness

Before running VibeTeam agents or after infrastructure changes, verify system readiness by following the playbook:

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
    lib/               # Test harness for multi-agent scenarios
  readiness/           # System readiness checks
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
