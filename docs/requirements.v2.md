# VibeTeam Multi-Agent System - Requirements v2.0

## 1. Overview

VibeTeam is a multi-agent system where autonomous AI agents collaborate to manage software development operations. Agents communicate through **Discord** (primary) and **Slack** (secondary), ensuring human visibility into all agent activities.

### 1.1 Key Change from v1: Discord-First Architecture

**Why Discord over Slack for agent handoffs:**

| Aspect | Slack (v1) | Discord (v2) |
|--------|------------|--------------|
| Apps/Bots needed | 5 separate Slack Apps | 1 Discord Bot |
| Tokens to manage | 10 (5 bot + 5 app tokens) | 1 bot token |
| Agent mentions | Requires separate app per `@AgentName` | Role-based: `@SoftwareEngineer` role |
| Setup complexity | High | Low |
| Response identity | Each app = different sender | Webhooks for custom name/avatar |

Discord allows **role-based mentions** where a single bot can respond to multiple roles (e.g., `@SoftwareEngineer`, `@ReleaseEngineer`). This dramatically simplifies the architecture.

### 1.2 Agents

| Agent | Role Name | Primary Function | Key Integrations |
|-------|-----------|------------------|------------------|
| **ProductManager** | @ProductManager | PRDs, user stories, backlog prioritization | GitHub, Langfuse |
| **SoftwareEngineer** | @SoftwareEngineer | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | @ReleaseEngineer | Deployments, k3s cluster, CI/CD, releases | Shell, kubectl, GitHub |
| **SupportEngineer** | @SupportEngineer | Customer support, error analysis, documentation | Sentry, Langfuse, Gmail, GitHub |
| **MarketingManager** | @MarketingManager | Social media posting, content creation | Chrome DevTools MCP |

### 1.3 Design Principles

1. **Human Visibility**: All agent communication happens in Discord/Slack channels - never hidden
2. **Role-Based Routing**: Discord roles enable direct @mentions like `@SoftwareEngineer`
3. **Single Bot Architecture**: One Discord bot handles all agents via role detection
4. **Webhook Responses**: Agents respond via webhooks for distinct identities (custom name/avatar per agent)
5. **Platform Agnostic**: Support both Discord (primary) and Slack (secondary)

---

## 2. Discord Architecture

### 2.1 Role-Based Mention System

```
┌─────────────────────────────────────────────────────────────────┐
│                    Discord Server: VibeTeam                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Roles (all mentionable, assigned to bot):                      │
│    @SoftwareEngineer  ─┐                                        │
│    @ReleaseEngineer   ─┼─► Bot listens for these role mentions  │
│    @SupportEngineer   ─┤                                        │
│    @ProductManager    ─┤                                        │
│    @MarketingManager  ─┘                                        │
│                                                                  │
│  Bot: VibeTeam                                                  │
│    - Has all 5 agent roles assigned                             │
│    - Receives events when any role is @mentioned                │
│    - Routes to appropriate agent logic                          │
│    - Responds via agent-specific webhook                        │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Channel Webhooks (for response identity):                      │
│    webhook_swe      → Posts as "SoftwareEngineer" with avatar   │
│    webhook_release  → Posts as "ReleaseEngineer" with avatar    │
│    webhook_support  → Posts as "SupportEngineer" with avatar    │
│    webhook_pm       → Posts as "ProductManager" with avatar     │
│    webhook_marketing→ Posts as "MarketingManager" with avatar   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Message Flow

```
User: @SoftwareEngineer please fix the login validation bug
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Discord Gateway Event                                         │
│   message.content: "<@&ROLE_ID> please fix the login..."     │
│   message.mention_roles: [SoftwareEngineer_ROLE_ID]          │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ VibeTeam Bot                                                  │
│   1. Detect role mention: SoftwareEngineer                   │
│   2. Extract task: "please fix the login validation bug"     │
│   3. Route to SWE agent logic                                 │
│   4. Process with LLM                                         │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Agent Response (via webhook)                                  │
│   POST to webhook_swe URL                                     │
│   username: "SoftwareEngineer"                               │
│   avatar_url: "https://.../swe-avatar.png"                   │
│   content: "I'll investigate the login issue..."             │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
Discord shows message from "SoftwareEngineer" (custom identity)
```

### 2.3 Agent-to-Agent Handoff

When an agent needs to delegate to another agent, it @mentions the target role:

```
SoftwareEngineer: I've fixed the login bug in PR #457.
                  @ReleaseEngineer ready for deployment.
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ VibeTeam Bot detects @ReleaseEngineer role mention           │
│   - Previous speaker: SoftwareEngineer                       │
│   - New target: ReleaseEngineer                              │
│   - Context: "ready for deployment, PR #457"                 │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
ReleaseEngineer agent picks up and processes
```

---

## 3. Agent Specifications

### 3.1 ProductManager (@ProductManager)

**Responsibilities:**
- Process feature requests from customers
- Write PRDs and user stories
- Prioritize product backlog
- Coordinate multi-agent tasks requiring orchestration
- Resolve conflicts between agents

**Tools:**
- GitHub API: Manage issues, project boards, labels
- Langfuse API: Analyze user behavior patterns
- Customer Requests Table: Track feature requests (GitHub Issue #322)

**Handoff Triggers:**
- Implementation needed → @SoftwareEngineer
- Deployment needed → @ReleaseEngineer
- Customer communication → @SupportEngineer
- Announcement needed → @MarketingManager

---

### 3.2 SoftwareEngineer (@SoftwareEngineer)

**Responsibilities:**
- Implement features from user stories
- Fix bugs reported by SupportEngineer
- Write and maintain tests
- Code review and refactoring
- Create pull requests

**Tools:**
- Shell Execution: Run tests, build commands
- File Read/Write/Edit: Code modifications
- Git CLI: Branching, commits, merges
- GitHub API: Create PRs, manage issues

**Handoff Triggers:**
- PR ready for deployment → @ReleaseEngineer
- Needs requirements clarification → @ProductManager
- Bug affects customers → @SupportEngineer

---

### 3.3 ReleaseEngineer (@ReleaseEngineer)

**Responsibilities:**
- Deploy applications to k3s Kubernetes cluster
- Create GitHub releases and changelogs
- Manage CI/CD pipelines
- Execute infrastructure scripts
- Monitor deployment health

**Tools:**
- Shell Execution: Deployment commands
- kubectl / k3s: Kubernetes cluster management
- GitHub API: Create releases, merge PRs

**Handoff Triggers:**
- Deployment complete, announce → @MarketingManager
- Deployment affects customers → @SupportEngineer
- Deployment failed, needs fix → @SoftwareEngineer

---

### 3.4 SupportEngineer (@SupportEngineer)

**Responsibilities:**
- Respond to customer support emails
- Analyze errors from Sentry
- Monitor LLM performance via Langfuse
- Create GitHub issues for bug reports
- Escalate complex technical issues

**Tools:**
- Sentry API: Query errors, view stack traces
- Langfuse API: Trace analysis, latency stats
- Gmail API: Read/send support emails
- GitHub API (read-only): Search code, reference docs

**Handoff Triggers:**
- Bug identified → @SoftwareEngineer
- Infrastructure issue → @ReleaseEngineer
- Feature request → @ProductManager

---

### 3.5 MarketingManager (@MarketingManager)

**Responsibilities:**
- Create and post social media content
- Monitor brand sentiment
- Draft product announcements
- Coordinate release communications

**Tools:**
- Chrome DevTools MCP: Browser automation for social media
- Web Search/Fetch: Research and content analysis

**Handoff Triggers:**
- Technical details needed → @SupportEngineer
- Release timing → @ReleaseEngineer
- Feature messaging → @ProductManager

---

## 4. Communication Channels

### 4.1 Primary: Discord

**Server:** VibeTeam
**Main Channel:** #ai-team (configurable)

**Features:**
- Role mentions route tasks: `@SoftwareEngineer fix the login bug`
- Thread-based conversations preserve context
- Webhook responses give each agent unique identity
- Human can override or redirect at any time

**Message Format (via webhook):**
```
[SoftwareEngineer]: <response>

Context: <relevant details>
Next: @ReleaseEngineer for deployment
```

### 4.2 Secondary: Slack

Slack remains supported for organizations that prefer it. Uses the existing multi-app architecture (5 Slack apps).

### 4.3 GitHub Issue Comments

When a GitHub issue is assigned to an agent:
1. Agent receives webhook with issue context
2. Agent acknowledges in issue comments
3. Agents discuss in issue comments using @mentions
4. All work references the issue number (`Fixes #123`)

---

## 5. Environment Configuration

### 5.1 Discord Environment Variables

```bash
# Discord Bot Configuration
DISCORD_BOT_TOKEN=          # Bot token from Developer Portal
DISCORD_GUILD_ID=           # Server ID
DISCORD_CHANNEL_ID=         # Main channel for agent communication

# Role IDs (created in server, assigned to bot)
DISCORD_ROLE_SWE=
DISCORD_ROLE_RELEASE=
DISCORD_ROLE_SUPPORT=
DISCORD_ROLE_PM=
DISCORD_ROLE_MARKETING=

# Webhook URLs (for agent response identities)
DISCORD_WEBHOOK_SWE=
DISCORD_WEBHOOK_RELEASE=
DISCORD_WEBHOOK_SUPPORT=
DISCORD_WEBHOOK_PM=
DISCORD_WEBHOOK_MARKETING=
```

### 5.2 Slack Environment Variables (Secondary)

```bash
# Slack Multi-Bot Tokens (if using Slack)
SLACK_BOT_TOKEN=
SLACK_AGENT_SWE=
SLACK_AGENT_RELEASE=
SLACK_AGENT_SUPPORT=
SLACK_AGENT_PM=
SLACK_AGENT_MARKETING=
```

---

## 6. Deployment Architecture

### 6.1 Discord Agent Deployment

Unlike Slack (which needs 5 separate pods), Discord needs only 1:

```yaml
# k8s/base/discord-agents/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: discord-agent
  namespace: vibeteam
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: agent
        image: ghcr.io/vibetechnologies/vibeteam:latest
        command: ["python", "scripts/run_discord_agent.py"]
        env:
        - name: DISCORD_BOT_TOKEN
          valueFrom:
            secretKeyRef:
              name: discord-secrets
              key: bot-token
        # ... other env vars
```

### 6.2 Gateway Webhook Endpoint

Add Discord interactions endpoint to the gateway:

```
POST /webhook/discord
  - Receives Discord Gateway events (if using webhook mode)
  - Routes to appropriate agent
  - Returns response for Discord to display
```

---

## 7. Setup Steps

### 7.1 Discord Setup (One-Time)

1. **Create Discord Application**
   - Go to https://discord.com/developers/applications
   - Create new application: "VibeTeam"
   - Add Bot, copy token
   - Enable intents: MESSAGE_CONTENT, GUILD_MEMBERS

2. **Create Discord Server**
   - Create server named "VibeTeam"
   - Create #ai-team channel

3. **Invite Bot to Server**
   - OAuth2 → URL Generator
   - Scopes: bot, applications.commands
   - Permissions: Read/Send Messages, Mention Everyone
   - Use URL to invite

4. **Create Roles**
   - Server Settings → Roles
   - Create 5 mentionable roles
   - Assign all roles to bot

5. **Create Webhooks**
   - Channel Settings → Integrations → Webhooks
   - Create 5 webhooks with agent names/avatars

6. **Save Configuration**
   - Copy all IDs and URLs to .env

---

## 8. Success Criteria

### 8.1 Functional Requirements

- [ ] Single Discord bot responds to 5 different role mentions
- [ ] Each agent responds with its own identity (via webhooks)
- [ ] Agent-to-agent handoff works via role mentions
- [ ] Thread context is preserved across handoffs
- [ ] Human can @mention any agent directly
- [ ] Human can redirect: "No, @ReleaseEngineer handle this"
- [ ] Slack integration still works (parallel support)

### 8.2 Non-Functional Requirements

- [ ] Bot responds within 5 seconds of mention
- [ ] All LLM calls traced in Langfuse
- [ ] Graceful handling of Discord rate limits
- [ ] Pod restarts don't lose active conversations

### 8.3 Evaluation Tests

#### Discord Handoff Evaluation Test

Located at: `tests/e2e/test_discord_handoff_eval.py`

This test validates multi-agent collaboration through a realistic customer support scenario:

**Scenario:** Customer reports API Gateway 404 errors

| Phase | Agent | Action |
|-------|-------|--------|
| 1 | SupportEngineer | Receives customer email, posts to Discord, @mentions ReleaseEngineer |
| 2 | ReleaseEngineer | Investigates, fixes issue, @mentions SupportEngineer |
| 3 | SupportEngineer | Sends resolution email to customer |

**G-Eval Criteria (LLM-as-Judge with Azure GPT-5.2):**

| Criterion | Description | Score |
|-----------|-------------|-------|
| handoff_detection | Did agents correctly identify and respond to @mentions? | 0-5 |
| task_completion | Was the customer ultimately notified of the fix? | 0-5 |
| communication | Was information passed clearly between agents? | 0-5 |
| tool_usage | Were Gmail and Discord tools used appropriately? | 0-5 |
| overall | Overall quality of multi-agent collaboration | 0-5 |

**Total Score:** 0-25 points

**Run the test:**
```bash
# Full comparison across all frameworks
pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "compare_all"

# Individual framework
pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "autogen"
pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "crewai"
pytest tests/e2e/test_discord_handoff_eval.py -v -s -k "openhands"
```

**Success Threshold:** Score >= 10/25

---

## 9. Migration from v1

### 9.1 What Changes

| Component | v1 (Slack) | v2 (Discord) |
|-----------|------------|--------------|
| Primary platform | Slack | Discord |
| Bot architecture | 5 apps | 1 bot + 5 roles |
| K8s deployments | 5 pods | 1 pod |
| Tokens | 10 | 1 + 5 webhooks |
| Mention format | `@SlackBotName` | `@RoleName` |

### 9.2 What Changes (v2 Handoffs)

**Transfer Tools Removed:**

In v2, agents no longer call `transfer_to_swe()`, `transfer_to_release()`, etc. Instead, they use natural @mentions in their responses:

```python
# OLD (v1): Agent calls a transfer tool
response = transfer_to_swe(task="Fix login bug", context="...")

# NEW (v2): Agent writes @mention naturally
response = "I've identified the issue. @SoftwareEngineer please fix the login bug in auth.py"
```

**Benefits:**
- No special tools required
- Human-readable handoffs visible in channel history
- Simpler agent prompts (backstory includes @mention instructions)
- No SwarmOrchestrator needed for in-memory handoffs

### 9.3 What Stays the Same

- Agent logic (ProductManagerAgent, etc.)
- GitHub integration
- Sentry/Langfuse integration
- LLM configuration (Azure OpenAI)

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-27 | 1.0 | Initial requirements (Slack-based) |
| 2026-01-31 | 2.0 | Discord-first architecture, role-based mentions |
| 2026-01-31 | 2.1 | Removed transfer tools, added natural @mention handoffs, added G-Eval evaluation tests |
