# VibeTeam

LiteLLM-based autonomous AI team for VibeBrowser SaaS operations.

## Overview

VibeTeam provides specialized agents that run as Kubernetes CronJobs:

| Agent | Schedule | Responsibility |
|-------|----------|----------------|
| **Reliability Engineer** | Every 5 min | Health checks, endpoint monitoring |
| **Support Engineer** | Every 15 min | Process customer support emails |
| **Product Manager** | Every 2 hours | Analyze Langfuse for feature requests |
| **Software Engineer** | Every 4 hours | Analyze GitHub issues, suggest fixes |
| **Release Engineer** | Daily 9 AM | Track merged PRs, release readiness |

## Installation

```bash
pip install -e .
```

## CLI Usage

```bash
# Run a task with auto-routing
vibeteam run "Check API health"

# Run with specific agent
vibeteam run "Analyze user feedback" --agent pm

# Show team status
vibeteam status

# List available agents
vibeteam agents

# Scheduled commands (used by k8s CronJobs)
vibeteam scheduled sre-health
vibeteam scheduled pm-analyze --hours 2
vibeteam scheduled support-emails --max-emails 20
vibeteam scheduled swe-issues --label auto-fix --repo VibeTechnologies/VibeWebAgent
vibeteam scheduled release-check
```

## Configuration

Uses LiteLLM for model routing with Azure OpenAI as primary provider.

### Environment Variables

```bash
# Azure OpenAI (required)
export AZURE_API_KEY="your-azure-api-key"
export AZURE_API_BASE="https://your-endpoint.cognitiveservices.azure.com/"
export AZURE_API_VERSION="2024-06-01"

# Langfuse observability (optional)
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_BASE_URL="https://langfuse.vibebrowser.app"

# GitHub (for issue creation)
export GITHUB_TOKEN="ghp_..."

# Gmail (for support-engineer)
export GMAIL_CREDENTIALS_PATH="/secrets/gmail-credentials.json"
export GMAIL_TOKEN_PATH="/secrets/gmail-token.json"
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    VibeTeam Orchestrator                │
│                      (vibeteam.orchestrator)            │
└─────────────────────┬───────────────────────────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ ReliabilityEng│ │ SupportEng    │ │ ProductManager│
│ (sre-health)  │ │ (emails)      │ │ (langfuse)    │
└───────────────┘ └───────────────┘ └───────────────┘
        │                 │                 │
        ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                      LiteLLM                            │
│  - Azure OpenAI (gpt-4.1, gpt-5-2)                      │
│  - Fallback providers                                   │
└─────────────────────────────────────────────────────────┘
```

### Components

- **Agents** (`vibeteam/agents/`): Specialized roles with system prompts and tools
- **Connectors** (`vibeteam/connectors/`): Gmail, GitHub integrations
- **Orchestrator** (`vibeteam/orchestrator.py`): Routes tasks to appropriate agent
- **CLI** (`vibeteam/cli.py`): Command-line interface

## Kubernetes Deployment

Agents run as CronJobs in the `vibeteam` namespace:

```bash
# Check status
kubectl get cronjobs -n vibeteam
kubectl get pods -n vibeteam

# View logs
kubectl logs -n vibeteam -l app=reliability-engineer --tail=50

# Manual trigger
kubectl create job --from=cronjob/reliability-engineer test-sre -n vibeteam
```

### Required Secrets

```bash
# GHCR pull secret
kubectl create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username=<user> \
  --docker-password=<pat> \
  -n vibeteam

# Gmail OAuth
kubectl create secret generic gmail-oauth-secrets \
  --from-file=gmail-credentials.json=.secrets/gmail-credentials.json \
  --from-file=gmail-token.json=.secrets/gmail-token.json \
  -n vibeteam

# Environment secrets
kubectl create secret generic vibeteam-secrets \
  --from-literal=AZURE_API_KEY=<key> \
  --from-literal=LANGFUSE_PUBLIC_KEY=<key> \
  --from-literal=LANGFUSE_SECRET_KEY=<key> \
  --from-literal=GITHUB_TOKEN=<token> \
  -n vibeteam
```

## Development

```bash
# Clone repo
git clone https://github.com/VibeTechnologies/VibeTeam.git
cd VibeTeam

# Install dev dependencies
pip install -e .[dev]

# Run tests
pytest tests/ -v

# Lint
ruff check .
black --check .
mypy vibeteam
```

## Documentation

- [Support Engineer](docs/support-engineer.md) - Email processing flow
- [Readiness Playbook](readiness/playbook.md) - Production verification

## License

MIT
