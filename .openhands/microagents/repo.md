# VibeTeam Repository Context

You are an AI agent working on the VibeTeam project - an autonomous AI team for SaaS development.

## Repository Structure

```
VibeTeam/
  vibeteam/           # Main Python package
    agents/           # Agent implementations
    connectors/       # External service integrations (GitHub, Slack, Gmail, Sentry, etc.)
    tools/            # Agent tools
    webhook/          # Webhook server for event handling
  k8s/                # Kubernetes manifests
    base/             # Base manifests
    openhands/        # OpenHands server deployment
  .openhands/         # OpenHands configuration
    microagents/      # Agent skill definitions (you are here)
  tests/              # Test files
  docs/               # Documentation
```

## Key Services

| Service | URL | Purpose |
|---------|-----|---------|
| API Prod | https://api.vibebrowser.app | Production API |
| API Dev | https://api-dev.vibebrowser.app | Development API |
| Portal | https://portal.vibebrowser.app | User portal |
| Sentry | https://vibetechnologies.sentry.io | Error tracking |
| Langfuse | https://langfuse.vibebrowser.app | LLM observability |
| GitHub | https://github.com/VibeTechnologies/VibeWebAgent | Main codebase |

## Critical Rules

1. **Every PR MUST reference a GitHub issue** - Use "Fixes #123" in PR description
2. **Run tests before creating PR** - Ensure CI will pass
3. **Link to source** - Include Sentry/Langfuse permalinks when relevant
4. **Quantify impact** - Include event counts, user counts for issues

## Environment

- Python 3.10+
- Azure OpenAI (model: azure/gpt-5-2)
- Kubernetes cluster for deployments
