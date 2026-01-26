# VibeTeam

LiteLLM-based autonomous AI team for VibeBrowser SaaS operations.

## Agent Overview

VibeTeam provides **two types of AI agents**:

### 1. Interactive Agents (On-Demand)

Invoke these agents via Slack, GitHub, or Web UI for immediate assistance:

| Channel | How to Invoke | Use Case |
|---------|---------------|----------|
| **Slack** | `@vibeteam <request>` | Ask questions, request code changes, get help |
| **GitHub** | Add `fix-me` label OR comment `@openhands-agent` | Auto-fix issues, implement features |
| **Web UI** | Visit [team.vibebrowser.app](https://team.vibebrowser.app) | Interactive chat with full IDE capabilities |

### 2. Autonomous Agents (Scheduled)

These specialized agents run automatically as Kubernetes CronJobs:

| Agent | Name | Schedule | Responsibility |
|-------|------|----------|----------------|
| **Reliability Engineer** | Hawking | Every 5 min | Health checks, endpoint monitoring, incident analysis |
| **Support Engineer** | Nightingale | Every 15 min | Process customer support emails, draft responses |
| **Product Manager** | Curie | Every 2 hours | Analyze Langfuse for feature requests, write PRDs |
| **Software Engineer** | Turing | Every 4 hours | Analyze GitHub issues, implement fixes |
| **Release Engineer** | Einstein | Daily 9 AM | Track merged PRs, validate releases, monitor Sentry |
| **Marketer** | Feynman | On-demand | Create announcements, social posts, content |

---

## Using Interactive Agents

### Slack (@vibeteam)

Mention `@vibeteam` in any channel where the bot is installed:

```
@vibeteam Can you help me fix the login timeout issue in VibeWebAgent?

@vibeteam Implement a dark mode toggle for the extension popup

@vibeteam Review the latest PR in vibe-mcp and suggest improvements
```

The agent will:
1. Acknowledge your request
2. Work on the task (may take a few minutes for complex tasks)
3. Reply with results, code snippets, or a link to a created PR

### GitHub (@openhands-agent)

**Method 1: Label-based (Recommended)**

1. Open or create an issue describing the bug/feature
2. Add the `fix-me` label
3. OpenHands will automatically:
   - Analyze the issue
   - Create a branch with the fix
   - Open a PR for review
   - Comment on the issue with progress

**Method 2: Comment-based**

Comment `@openhands-agent` on any issue to trigger the agent:

```
@openhands-agent Please implement this feature

@openhands-agent Can you investigate why this test is failing?
```

### Supported Repositories

Interactive agents are available in:
- `VibeTechnologies/VibeWebAgent` - Chrome extension
- `VibeTechnologies/vibe-mcp` - MCP servers
- `VibeTechnologies/VibeBrowserAppPage` - Landing page
- `VibeTechnologies/VibeTeam` - This repository

See [OpenHands Integration Guide](docs/openhands-integration.md) for setup details.

---

## Using Autonomous Agents

### Installation

```bash
pip install -e .
```

### CLI Usage

```bash
# Run a task with auto-routing
vibeteam run "Check API health"

# Run with specific agent (pm, swe, sre, support, release, marketer)
vibeteam run "Analyze user feedback" --agent pm
vibeteam run "Fix the login bug in auth.ts" --agent swe
vibeteam run "Check production health" --agent sre

# Show team status
vibeteam status

# List available agents
vibeteam agents

# Get detailed info about an agent
vibeteam info pm

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

## Connecting to Your GitHub Org/Repo

VibeTeam can work with any GitHub organization and repository.

### Using CLI

```bash
# Run SWE agent on your repo
vibeteam scheduled swe-issues --repo YourOrg/YourRepo --label auto-fix

# Run release check on your repo
vibeteam run "Check for pending releases in YourOrg/YourRepo" --agent release
```

### Using GitHub App (Recommended)

1. Create a GitHub App for your org at `https://github.com/organizations/YOUR_ORG/settings/apps/new`
2. Configure permissions: Contents, Issues, Pull Requests (read/write), Metadata (read)
3. Install the app on your repositories
4. Store credentials as secrets

See [GitHub App Authentication](docs/github-app-auth.md) for full setup guide.

### Using Personal Access Token

```bash
# Set token with repo access
export GITHUB_TOKEN="ghp_your_token_here"

# Run agents
vibeteam scheduled swe-issues --repo YourOrg/YourRepo
```

### Kubernetes Configuration

Update the CronJob manifests to target your repo:

```yaml
# k8s/base/software-engineer.yaml
command:
  - vibeteam
  - scheduled
  - swe-issues
  - --repo
  - YourOrg/YourRepo  # Change this
  - --label
  - auto-fix
```

## Slack App Installation

To enable the `@vibeteam` Slack bot, you need to install the Slack app, configure OAuth tokens, and set up Event Subscriptions.

### 1. Install the App to Your Workspace

Visit the install page for your Slack app:
```
https://api.slack.com/apps/A0AAZGWEAVA/install-on-team
```

Click **"Install to Workspace"** and authorize the app.

### 2. Get the Bot User OAuth Token

After installation, go to the OAuth & Permissions page:
```
https://api.slack.com/apps/A0AAZGWEAVA/oauth
```

Copy the **Bot User OAuth Token** (starts with `xoxb-...`) from the "OAuth Tokens for Your Workspace" section.

### 3. Configure Event Subscriptions

Go to the Event Subscriptions page:
```
https://api.slack.com/apps/A0AAZGWEAVA/event-subscriptions
```

1. **Enable Events**: Toggle "Enable Events" to ON

2. **Set Request URL**:
   ```
   https://webhook.team.vibebrowser.app/slack/events
   ```
   Slack will send a challenge request - the webhook server handles this automatically.

3. **Subscribe to Bot Events**: Click "Add Bot User Event" and add:
   - `app_mention` - Triggers when someone mentions @vibeteam
   - `message.im` - Triggers when someone DMs the bot

4. Click **"Save Changes"**

5. **Reinstall the App** (required after adding new event scopes):
   - Go to: https://api.slack.com/apps/A0AAZGWEAVA/install-on-team
   - Click "Reinstall to Workspace"

### 4. Configure Secrets

Update `.secrets/slack.json` with the token:
```json
{
  "SLACK_BOT_TOKEN": "xoxb-your-token-here",
  "SLACK_SIGNING_SECRET": "your-signing-secret",
  "SLACK_APP_ID": "A0AAZGWEAVA"
}
```

For Kubernetes deployment, add to the vibeteam-secrets:
```bash
kubectl create secret generic vibeteam-secrets \
  --from-literal=SLACK_BOT_TOKEN=xoxb-your-token \
  --from-literal=SLACK_SIGNING_SECRET=your-signing-secret \
  ... \
  -n vibeteam
```

### 5. Verify the Integration

Test that everything is working:

```bash
# Check webhook is responding
curl -s https://webhook.team.vibebrowser.app/health

# Check webhook logs for incoming events
kubectl logs -n vibeteam -l app=vibeteam-webhook -f

# Then mention @vibeteam in Slack and watch for:
# "Received Slack event: app_mention"
```

See [Slack App Setup Guide](docs/slack-app-setup.md) for detailed configuration.

## Documentation

- [OpenHands Integration Guide](docs/openhands-integration.md) - Slack, GitHub, and Web UI setup
- [Slack App Setup Guide](docs/slack-app-setup.md) - Create and configure the Slack bot
- [GitHub App Authentication](docs/github-app-auth.md) - Secure bot identity
- [Support Engineer](docs/support-engineer.md) - Email processing flow
- [Readiness Playbook](readiness/playbook.md) - Production verification
- [Design: OpenHands Migration](docs/design-openhands-migration.md) - Architecture decisions

## License

MIT
