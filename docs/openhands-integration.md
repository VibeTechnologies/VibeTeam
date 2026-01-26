# OpenHands Integration Guide

This document describes how to use the **interactive AI agents** available via Slack, GitHub, and Web UI.

## How It Relates to VibeTeam Agents

VibeTeam has **two types of agents**:

| Type | Examples | How They Run |
|------|----------|--------------|
| **Interactive (this guide)** | OpenHands via Slack/GitHub/Web | On-demand, user-triggered |
| **Autonomous** | Curie (PM), Turing (SWE), Hawking (SRE), etc. | Scheduled CronJobs |

The **interactive agents** (covered in this guide) are powered by OpenHands and respond to direct requests. The **autonomous agents** run on schedules and perform background tasks like health monitoring, email support, and release validation.

## Overview

OpenHands provides AI-powered code assistance through three channels:

| Channel | URL/Trigger | Description |
|---------|-------------|-------------|
| **Web UI** | [team.vibebrowser.app](https://team.vibebrowser.app) | Interactive chat with IDE capabilities |
| **Slack** | `@vibeteam` mention | Team collaboration and quick requests |
| **GitHub** | `fix-me` label or `@openhands-agent` | Automated issue resolution |

---

## Using the Slack Bot (@vibeteam)

### Basic Usage

Mention `@vibeteam` in any channel to get AI assistance:

```
@vibeteam What's the current status of the VibeWebAgent build?

@vibeteam Help me understand how the MCP server authentication works

@vibeteam Can you create a PR to fix the typo in README.md?
```

### Supported Tasks

| Task Type | Example |
|-----------|---------|
| Code questions | `@vibeteam How does the tab manager work in VibeWebAgent?` |
| Bug fixes | `@vibeteam The popup isn't loading - can you investigate?` |
| Feature requests | `@vibeteam Add a keyboard shortcut for quick capture` |
| Code review | `@vibeteam Review PR #42 in vibe-mcp` |
| Documentation | `@vibeteam Update the API docs for the new endpoint` |

### Best Practices

1. **Be specific** - Include file names, error messages, or issue numbers
2. **One task at a time** - Complex requests work better as separate messages
3. **Provide context** - Mention the repository if not obvious
4. **Be patient** - Complex tasks may take 2-5 minutes

### Channels

The bot is available in:
- `#engineering` - General development questions
- `#vibeteam-alerts` - Automated notifications
- Direct messages - Private requests

### Setup

To configure the Slack bot for a new workspace, see [Slack App Setup Guide](slack-app-setup.md).

---

## Using GitHub Integration

### Method 1: Label-Based Triggers (Recommended)

Add the `fix-me` label to any issue to trigger automatic resolution:

1. **Create or open an issue** with a clear description
2. **Add the `fix-me` label**
3. **Wait for the agent** to analyze and create a PR

The agent will:
- Comment "Working on this..." when it starts
- Create a feature branch
- Implement the fix/feature
- Open a PR with the changes
- Add the `openhands-resolved` label when done

### Method 2: Comment-Based Triggers

Comment `@openhands-agent` on any issue to invoke the agent:

```markdown
@openhands-agent Please fix this bug. The issue is that the authentication
token expires after 1 hour but we need it to last 24 hours.
```

### Writing Effective Issues

Good issues lead to better results:

```markdown
## Bad Example
Fix the login bug

## Good Example
### Problem
Users are logged out unexpectedly after 1 hour of inactivity.

### Expected Behavior
Session should persist for 24 hours as specified in config.

### Relevant Files
- src/auth/session.ts
- src/config/defaults.ts

### Additional Context
Error in console: "Token expired at timestamp X"
```

### Labels

| Label | Meaning |
|-------|---------|
| `fix-me` | Triggers OpenHands to work on this issue |
| `openhands-resolved` | Agent completed work, PR created |
| `openhands-failed` | Agent encountered an error |

---

## Using the Web UI

Visit [team.vibebrowser.app](https://team.vibebrowser.app) for an interactive IDE experience.

### Features

- **Chat interface** - Natural language interaction
- **File browser** - View and navigate code
- **Terminal** - Run commands in a sandboxed environment
- **Code editor** - Make and preview changes
- **Git integration** - Create branches and PRs

### Starting a Session

1. Navigate to team.vibebrowser.app
2. Select a repository or start fresh
3. Describe your task in the chat
4. Review and approve suggested changes

---

## Architecture

```
                          User Interfaces
                     +-----------------------+
                     |                       |
              +------+------+    +-----------+----------+
              |   Slack     |    |   GitHub Actions     |
              |  @vibeteam  |    |   fix-me label       |
              +------+------+    +-----------+----------+
                     |                       |
                     v                       v
          +----------+----------+   +--------+--------+
          |  Slack Webhook Bot  |   |  OpenHands      |
          |  (K8s Deployment)   |   |  Resolver GHA   |
          +----------+----------+   +--------+--------+
                     |                       |
                     v                       v
              +------+------+    +-----------+----------+
              |  OpenHands  |<---+   OpenHands Action   |
              |   Server    |    |   (GitHub-hosted)    |
              +------+------+    +----------------------+
                     |
                     v
          +----------+----------+
          |   Azure OpenAI     |
          |   (gpt-4.1)        |
          +--------------------+
```

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| OpenHands Server | K8s: `team.vibebrowser.app` | Web UI and API |
| Slack Webhook Bot | K8s: `vibeteam` namespace | Process @vibeteam mentions |
| GitHub Resolver | GitHub Actions | Automated issue resolution |
| Microagent Configs | `.openhands/microagents/repo.md` | Repository-specific context |

---

## Repository Setup

To enable OpenHands on a new repository:

### 1. Add GitHub Workflow

Copy the workflow file to your repository:

```bash
# From the VibeTeam repo
cp templates/github-workflows/openhands-resolver.yml \
   /path/to/your-repo/.github/workflows/
```

Or create `.github/workflows/openhands-resolver.yml`:

```yaml
name: OpenHands Issue Resolver

on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  resolve-issue:
    if: |
      (github.event_name == 'issues' && github.event.label.name == 'fix-me') ||
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@openhands-agent'))
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: all-hands-ai/openhands-resolver@main
        with:
          issue_number: ${{ github.event.issue.number }}
          llm_model: "azure/gpt-4.1"
          llm_api_key: ${{ secrets.LLM_API_KEY }}
          llm_base_url: "https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/"
          max_iterations: 50
          auto_pr: true
          comment_on_issue: true
```

### 2. Add Repository Secret

Add `LLM_API_KEY` secret to your repository:
1. Go to Settings > Secrets and variables > Actions
2. Click "New repository secret"
3. Name: `LLM_API_KEY`
4. Value: Your Azure OpenAI API key

### 3. Create Microagent Configuration

Create `.openhands/microagents/repo.md` with repository-specific context:

```markdown
---
name: repo
agent: CodeActAgent
triggers:
  - keyword: ""
---

# Your Repository Name

Brief description of your project.

## Tech Stack
- Language: TypeScript/Python/etc.
- Framework: React/FastAPI/etc.
- Package Manager: npm/pip/etc.

## Development Commands
\`\`\`bash
npm install
npm test
npm run build
\`\`\`

## Code Style Guidelines
- Your conventions here

## Important Files
- src/main.ts - Entry point
- etc.
```

See `templates/openhands-microagents/` for examples.

---

## Deployment & CI/CD

### GitHub Actions Secrets

The following secrets must be configured in [GitHub repository settings](https://github.com/VibeTechnologies/VibeTeam/settings/secrets/actions):

| Secret | Description | Required For |
|--------|-------------|--------------|
| `KUBECONFIG` | Kubernetes cluster config (base64 encoded) | K8s deployment |
| `PAT_TOKEN` | GitHub PAT with `repo` and `packages` scope | Image push, K8s secrets |
| `AZURE_API_KEY` | Azure OpenAI API key | LLM calls |
| `AZURE_API_BASE` | Azure OpenAI endpoint URL | LLM calls |
| `SENTRY_AUTH_TOKEN` | Sentry authentication token | Error tracking |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | Observability |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | Observability |
| `GMAIL_CREDENTIALS_JSON` | Gmail OAuth credentials (JSON) | Support agent |
| `GMAIL_TOKEN_JSON` | Gmail OAuth token (JSON) | Support agent |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) | Slack integration |
| `SLACK_SIGNING_SECRET` | Slack App Signing Secret | Slack webhook verification |
| `LLM_API_KEY` | Azure OpenAI key (for other repos) | OpenHands resolver action |

### Setting Secrets

```bash
# Via GitHub CLI
gh secret set SLACK_BOT_TOKEN --body "xoxb-..."
gh secret set SLACK_SIGNING_SECRET --body "..."

# Or via web UI
# https://github.com/VibeTechnologies/VibeTeam/settings/secrets/actions
```

### Local Development Secrets

For local development, secrets are stored in `.secrets/` (git-ignored):

```bash
# VibeTeam/.secrets/
├── README.md           # This documentation
├── slack.json          # Slack credentials
├── gmail-credentials.json
├── gmail-token.json
└── langfuse.json
```

See `.secrets/README.md` for setup instructions.

### Deployment Workflow

The `deploy.yml` workflow automatically:

1. Builds and pushes Docker image to `ghcr.io/vibetechnologies/vibeteam`
2. Creates K8s namespace and secrets
3. Deploys all CronJobs and the OpenHands server
4. Creates these K8s secrets:
   - `vibeteam-secrets` - Core credentials (Azure, GitHub, Langfuse, Sentry)
   - `slack-bot-secrets` - Slack integration
   - `gmail-oauth-secrets` - Support engineer email access
   - `ghcr-pull-secret` - Container registry auth

---

## Troubleshooting

### Slack Bot Not Responding

1. Ensure the bot is in the channel (invite with `/invite @vibeteam`)
2. Check bot status in Slack App settings
3. View logs: `kubectl logs -n vibeteam -l app=slack-webhook-bot`

### GitHub Action Failing

1. Check workflow run in Actions tab
2. Verify `LLM_API_KEY` secret is set
3. Ensure issue has clear description
4. Check if label was added correctly

### Web UI Inaccessible

1. Verify ingress: `kubectl get ingress -n vibeteam`
2. Check pod health: `kubectl get pods -n vibeteam -l app=openhands`
3. View logs: `kubectl logs -n vibeteam -l app=openhands`

---

## Configuration Reference

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_KEY` | Azure OpenAI API key | Yes |
| `LLM_BASE_URL` | Azure endpoint | Yes |
| `LLM_MODEL` | Model name (azure/gpt-4.1) | Yes |
| `GITHUB_TOKEN` | GitHub PAT for PR creation | Yes |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token | For Slack |
| `SLACK_SIGNING_SECRET` | Slack request verification | For Slack |

### Kubernetes Resources

```bash
# View all OpenHands resources
kubectl get all -n vibeteam -l app=openhands

# Scale deployment
kubectl scale deployment openhands -n vibeteam --replicas=2

# View config
kubectl get configmap openhands-config -n vibeteam -o yaml
```

---

## Security Considerations

1. **Secrets** - Never commit API keys; use Kubernetes secrets or GitHub secrets
2. **Permissions** - GitHub workflow has write access; review PRs before merging
3. **Sandboxing** - OpenHands runs in isolated containers
4. **Audit** - All actions are logged in Langfuse

---

## Related Documentation

- [Slack App Setup Guide](slack-app-setup.md) - Create and configure the Slack bot
- [GitHub App Authentication](github-app-auth.md) - Secure bot identity for GitHub
- [Design: OpenHands Migration](design-openhands-migration.md) - Architecture decisions
- [OpenHands Official Docs](https://docs.all-hands.dev) - Upstream documentation
