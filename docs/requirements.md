# VibeTeam Requirements

## Overview

VibeTeam is a multi-agent AI system that automates VibeBrowser SaaS operations. Agents collaborate via natural @mentions in Discord/Slack channels, ensuring human visibility into all activities.

## Agents

| Role | Function | Tools |
|------|----------|-------|
| **SoftwareEngineer** | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | Social media, announcements, content | Chrome DevTools MCP |

## Message Processing

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Discord   │     │   Webhook   │     │   Agents    │     │  Response   │
│   Slack     │────▶│   Router    │────▶│  Evaluate   │────▶│   Posted    │
│   GitHub    │     │             │     │  & Claim    │     │   Back      │
│   Gmail     │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

1. **Webhook receives** message from Discord/Slack/GitHub/Gmail
2. **Normalize** to UnifiedMessage format
3. **Broadcast** to all agents simultaneously
4. **Each agent evaluates**: "Is this my responsibility?"
5. **Claiming agents** begin working and respond via platform

## Handoff Protocol

Agents use natural @mentions in their responses to hand off tasks:

```
SoftwareEngineer: Fixed login bug in PR #457.
                  @ReleaseEngineer ready for staging deployment.
```

The system detects the @mention and routes to ReleaseEngineer.

**Handoff Rules:**
- Direct @mention = immediate routing to target agent
- Keyword matching = proactive responsibility detection
- Multiple agents can claim related tasks (e.g., Support + Release for outage)

## Integrations

### Discord (Primary)

- **Role-based mentions**: Single bot with 5 roles (`@SoftwareEngineer`, etc.)
- **Webhooks**: Each agent responds with distinct identity (name/avatar)
- **Threading**: Conversations preserved in threads

### Slack (Secondary)

- **Multi-app architecture**: 5 separate Slack apps
- **Channel-based**: Agents communicate in `#ai-team` channel

### GitHub

- **Issue comments**: Agents discuss in issue threads
- **PRs**: SoftwareEngineer creates, ReleaseEngineer merges
- **Webhooks**: Trigger agents on issue/PR events

### Sentry

- **Error monitoring**: SupportEngineer receives alerts
- **Weekly digests**: Automated error summaries
- **Root cause analysis**: Agent investigates stack traces

### Gmail

- **Customer support**: SupportEngineer reads/responds to emails
- **Push notifications**: Real-time email processing

## Evaluation

Agents are evaluated using DeepEval with G-Eval metrics:

| Metric | Description |
|--------|-------------|
| TeamCoordination | How well agents work together |
| ResponsibilityDetection | Correct task ownership claims |
| HandoffQuality | Context preservation in handoffs |
| TaskCompletion | Was the request fully addressed |
| Professionalism | Clear, concise communication |

Run tests:
```bash
pytest tests/e2e/test_team_eval.py -v -s
```

## Environment Variables

```bash
# Required
AZURE_API_KEY=
AZURE_API_BASE=
GITHUB_TOKEN=

# Discord
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_CHANNEL_ID=
DISCORD_WEBHOOK_SWE=
DISCORD_WEBHOOK_RELEASE=
DISCORD_WEBHOOK_SUPPORT=
DISCORD_WEBHOOK_PM=
DISCORD_WEBHOOK_MARKETING=

# Optional
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
SLACK_BOT_TOKEN=
```
