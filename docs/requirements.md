# VibeTeam Requirements

## Overview

VibeTeam is a multi-agent AI system that automates VibeBrowser SaaS operations. Agents collaborate via `/RoleName` mentions in Discord/Slack channels, ensuring human visibility into all activities.

## Agents

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `/SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `/ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `/SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `/ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | `/MarketingManager` | Social media, announcements, content | Chrome DevTools MCP |

## Message Routing

### Thread-Based Subscription Model

When `@VibeTeam` is mentioned in a message, the router tracks that thread and routes to agents based on `/RoleName` mentions.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MESSAGE FLOW                                    │
│                                                                              │
│  User: "@VibeTeam /SoftwareEngineer fix bug #345"                           │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ROUTER                                                              │    │
│  │  1. Detect @VibeTeam → track this thread                            │    │
│  │  2. Parse /SoftwareEngineer → subscribe agent to thread             │    │
│  │  3. React with :eyes: emoji (acknowledged)                          │    │
│  │  4. Forward to Agent Service with context                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  AGENT SERVICE                                                       │    │
│  │  1. Get or create session for (slack, thread_id, software_engineer) │    │
│  │  2. Create agent with pre-configured send_message tool              │    │
│  │  3. Agent processes message and responds                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                      │
│       ▼                                                                      │
│  Agent calls send_message("/ReleaseEngineer please deploy PR #457")         │
│       │                                                                      │
│       ▼                                                                      │
│  Posted to Slack: "[SoftwareEngineer] /ReleaseEngineer please deploy..."    │
│       │                                                                      │
│       ▼                                                                      │
│  Router sees /ReleaseEngineer in bot message → subscribes ReleaseEngineer   │
│  Router forwards to ReleaseEngineer agent                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Routing Rules

1. **Thread Activation**: A thread becomes "active" when `@VibeTeam` is mentioned
2. **Agent Subscription**: `/RoleName` mentions subscribe that agent to the thread
3. **Persistent Subscription**: Once subscribed, agent receives ALL subsequent messages in that thread
4. **Handoffs**: Agents mention `/OtherAgent` in responses to bring them into the thread
5. **Bot Messages**: Router processes bot's own messages to detect handoffs

### Thread Subscription Table

```sql
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,        -- slack, discord, github_issue, github_pr
    thread_id VARCHAR(255) NOT NULL,    -- thread_ts, message_id, issue_number
    agent_role VARCHAR(50) NOT NULL,    -- software_engineer, release_engineer, etc.
    session_id UUID NOT NULL,           -- link to agent session
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
```

### Thread ID Formats

| Source | Thread ID Format | Example |
|--------|------------------|---------|
| Slack | `{thread_ts}` | `1234567890.123456` |
| Discord | `{channel_id}:{message_id}` | `123456789:987654321` |
| GitHub Issue | `{repo}:{issue_number}` | `VibeTechnologies/VibeWebAgent:345` |
| GitHub PR | `{repo}:pr:{pr_number}` | `VibeTechnologies/VibeWebAgent:pr:123` |

## Agent Sessions

Each agent maintains a session per thread with:

- **Conversation history**: All messages in the thread
- **Workspace**: Persistent directory for file operations (7-day TTL)
- **Tools**: Pre-configured `send_message` tool for responding

### Session Key Format

```
{framework}:{role}:{source}:{thread_id}
```

Example: `openhands:software_engineer:slack:1234567890.123456`

### send_message Tool

Every agent receives a pre-configured `send_message` tool that:

1. Prefixes messages with `[RoleName]` for identification
2. Posts to the correct thread using stored tokens
3. Triggers router to process any `/RoleName` mentions in the response

```python
# Agent's perspective
send_message("Fixed the bug in PR #457. /ReleaseEngineer ready for staging.")

# Posted to Slack as:
# [SoftwareEngineer] Fixed the bug in PR #457. /ReleaseEngineer ready for staging.
```

## Integrations

### Slack

- **Single app**: `@VibeTeam` bot handles all agent roles
- **Role identification**: `[RoleName]` prefix in messages
- **Threading**: All agent responses go to the original thread
- **Acknowledgment**: :eyes: emoji reaction when message is received

### Discord

- **Single bot**: `@VibeTeam` bot handles all agent roles
- **Role identification**: `[RoleName]` prefix in messages
- **Threading**: Responses in the same thread/channel
- **Acknowledgment**: :eyes: emoji reaction when message is received

### GitHub

- **Issue comments**: Agents respond in issue threads
- **PR comments**: Agents respond in PR threads
- **Webhooks**: Issue/PR events trigger agent processing

### Sentry

- **Error alerts**: Webhook triggers `/SupportEngineer` or `/ReleaseEngineer`
- **Auto-routing**: Based on error severity and type

### Gmail

- **Customer emails**: Processed by `/SupportEngineer`
- **Push notifications**: Real-time email handling

## Agent Frameworks

VibeTeam currently supports OpenHands framework:

| Framework | Status | Notes |
|-----------|--------|-------|
| **OpenHands** | Active | Full tool support, session persistence |
| CrewAI | Planned | Multi-agent orchestration |
| AutoGen | Planned | Conversational agents |
| OpenCode | Experimental | CLI-based, limited tool injection |

## Environment Variables

```bash
# Required - LLM
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview

# Required - GitHub
GITHUB_TOKEN=

# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Discord
DISCORD_BOT_TOKEN=

# Database
DATABASE_URL=postgresql://...

# Optional
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

## Evaluation

Agents are evaluated using DeepEval with G-Eval metrics:

| Metric | Threshold | Description |
|--------|-----------|-------------|
| TaskCompletion | 0.7 | Was the request fully addressed |
| HandoffQuality | 0.7 | Context preservation in handoffs |
| ResponseTime | < 60s | Time to first response |
| Professionalism | 0.7 | Clear, concise communication |

Run tests:
```bash
pytest tests/e2e/test_team_eval.py -v -s
```
