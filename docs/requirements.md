# VibeTeam Multi-Agent System - Product Requirements

## 1. Overview

VibeTeam is a multi-agent system where autonomous AI agents collaborate to manage software development operations. Agents communicate through **Slack** and **GitHub issue comments**, ensuring human visibility into all agent activities.

### 1.1 Agents

| Agent | Primary Function | Key Integrations |
|-------|------------------|------------------|
| **ProductManager** | PRDs, user stories, backlog prioritization | GitHub, Langfuse |
| **SoftwareEngineer** | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | Deployments, k3s cluster, CI/CD, releases | Shell, kubectl, GitHub |
| **SupportEngineer** | Customer support, error analysis, documentation | Sentry, Langfuse, Gmail, GitHub |
| **MarketingManager** | Social media posting, content creation, web research | Chrome DevTools MCP |

### 1.2 Design Principles

1. **Human Visibility**: All agent communication happens in Slack or GitHub comments - never hidden
2. **Context Isolation**: Each agent maintains separate conversation history per channel/issue
3. **Hybrid Coordination**: Direct @mentions for simple handoffs, ProductManager for complex orchestration
4. **Specialized Tools**: Each agent has purpose-specific capabilities (no universal access)

---

## 2. Agent Specifications

### 2.1 ProductManager

**Responsibilities:**
- Process feature requests from customers
- Write PRDs and user stories
- Prioritize product backlog
- Coordinate multi-agent tasks requiring orchestration
- Resolve conflicts between agents

**Tools:**

| Tool | Capability |
|------|------------|
| GitHub API | Manage issues, project boards, labels |
| Langfuse API | Analyze user behavior patterns, trace analysis |
| Customer Requests Table | Track feature requests (GitHub Issue #322) |

**Coordination Role:**
- Acts as supervisor for complex multi-step workflows
- Routes ambiguous tasks to appropriate agents
- Provides tie-breaking when agents disagree

---

### 2.2 SoftwareEngineer

**Responsibilities:**
- Implement features from user stories
- Fix bugs reported by SupportEngineer
- Write and maintain tests
- Code review and refactoring
- Create pull requests

**Tools:**

| Tool | Capability |
|------|------------|
| Shell Execution | Run tests, build commands, dev scripts |
| File Read/Write/Edit | Code modifications, config changes |
| Git CLI | Branching, commits, merges, rebases |
| GitHub API | Create PRs, request reviews, manage issues |

**Trigger:**
- GitHub issue assigned to `software-engineer` or `vibeteam-bot` with code-related labels
- @SoftwareEngineer mention in Slack or issue comments

---

### 2.3 ReleaseEngineer

**Responsibilities:**
- Deploy applications to k3s Kubernetes cluster
- Create GitHub releases and changelogs
- Manage CI/CD pipelines
- Execute infrastructure scripts
- Monitor deployment health
- Review and merge PRs (with approval workflows)

**Tools:**

| Tool | Capability |
|------|------------|
| Shell Execution | Run deployment commands, scripts |
| File Read/Write | Edit configs, manifests, scripts |
| kubectl / k3s | Kubernetes cluster management |
| GitHub API | Create releases, merge PRs, manage tags |

**Communication Patterns:**
- Posts deployment status to Slack
- Tags @SupportEngineer if deployment affects customers
- Tags @MarketingManager for public releases
- Notifies @SoftwareEngineer of failed deployments

---

### 2.4 SupportEngineer

**Responsibilities:**
- Respond to customer support emails
- Analyze errors from Sentry
- Monitor LLM performance via Langfuse
- Answer questions using product documentation
- Create GitHub issues for bug reports
- Escalate complex technical issues

**Tools:**

| Tool | Capability |
|------|------------|
| Sentry API | Query errors, view stack traces, add comments, link to GitHub |
| Langfuse API | Trace analysis, latency stats, error rates, token usage |
| Gmail API | Read support emails, send replies, manage labels |
| GitHub API (read-only) | Search code, read issues, reference documentation |
| Product Docs Search | Keyword search tool - agent calls when it needs documentation |

**Escalation Paths:**
- Complex bugs → @SoftwareEngineer (creates GitHub issue)
- Infrastructure issues → @ReleaseEngineer
- Feature requests → @ProductManager
- Public-facing issues → @MarketingManager (for comms)

---

### 2.5 MarketingManager

**Responsibilities:**
- Create and post social media content (Twitter/X, LinkedIn)
- Monitor brand sentiment and mentions
- Web research for market analysis
- Draft product announcements
- Engage with customers on social platforms
- Coordinate release communications

**Tools:**

| Tool | Capability |
|------|------------|
| Chrome DevTools MCP | Full browser automation for social media posting |
| Web Search | Research competitors, trends, news |
| Web Fetch | Scrape pages for content analysis |
| Sentiment Analysis | Monitor brand mentions and reactions |

**Full Posting Capability:**
- Can log in and post to Twitter/X, LinkedIn
- Can respond to customer comments
- Can schedule posts via native platform features

**Collaboration:**
- Requests technical details from @SupportEngineer
- Coordinates release timing with @ReleaseEngineer
- Gets feature messaging from @ProductManager

---

## 3. Communication Architecture

### 3.1 Primary Channel: Slack

**Channel:** `#ai-team` (configurable per deployment)

**Features:**
- All agent-to-agent communication visible to humans
- @mentions route tasks: `@ReleaseEngineer deploy v1.2.3 to production`
- Human can override or redirect at any time
- Thread-based conversations preserve context

**Message Format:**
```
[@AgentName]: <action taken or response>

Context: <relevant details>
Next: <what happens next or who to contact>
```

### 3.2 Secondary Channel: GitHub Issue Comments

When a GitHub issue is **assigned to an agent**:

1. Agent receives webhook with issue context
2. Agent acknowledges in issue comments
3. If collaboration needed, agents discuss **in issue comments** using @mentions
4. All work (commits, PRs) references the issue number (`Fixes #123`)
5. Final status posted as comment before closing

**Comment Format:**
```markdown
**[@AgentName]**

<action or question>

---
_Automated by VibeTeam_
```

### 3.3 Routing Rules

| Trigger | Channel | Routing Logic |
|---------|---------|---------------|
| Issue assigned to `vibeteam-bot` | GitHub | Analyze labels/content → route to agent |
| Issue assigned to specific agent label | GitHub | Direct to that agent |
| @AgentName mention | Slack | Direct to mentioned agent |
| @vibeteam mention | Slack | ProductManager triages |
| CronJob (email) | Internal | SupportEngineer |
| CronJob (health) | Internal | ReleaseEngineer |

---

## 4. Session Management

### 4.1 Context-Based Session Isolation

Each agent maintains **separate conversation history per context**. When a webhook arrives, the service looks up the correct session based on the agent and context.

**Session Key Format:**
```
{agent}:{context_type}:{context_id}

Examples:
  release_engineer:slack:C0123456789
  release_engineer:issue:456
  support_engineer:slack:C0123456789
  support_engineer:email:msg-abc123
  marketing_manager:slack:C0123456789
```

**Key Principle:** The same Slack channel has **separate sessions per agent**. This allows each agent to maintain its own context and memory for that channel.

### 4.2 Webhook → Session Lookup Flow

```
┌──────────────────────────────────────────────────────────────┐
│                     Slack Webhook Received                    │
│            channel_id=C0123456789, thread_ts=...             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Parse @mention from text                   │
│                   → Determines target agent                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Construct session key:                           │
│        {agent}:slack:{channel_id}                             │
│        e.g., "release_engineer:slack:C0123456789"            │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Lookup session from session store                │
│        - If exists: load conversation history                 │
│        - If new: create fresh session                         │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Execute agent with session context               │
│        - Previous messages included in prompt                 │
│        - Response saved to session                            │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 Session Persistence

**Requirements:**
- Conversation history survives pod restarts
- Sessions can be resumed after hours/days
- Cross-reference possible via Langfuse `session_id`
- Session expiry after configurable TTL (default: 7 days)

**Storage Options:**
- Redis for fast access
- PostgreSQL for durability
- S3 for long-term archival

### 4.4 Context Types

| Context Type | ID Format | Source |
|--------------|-----------|--------|
| `slack` | Channel ID (C0123456789) | Slack webhook |
| `issue` | Issue number (123) | GitHub webhook |
| `email` | Message ID (msg-xxx) | Gmail polling |
| `ephemeral` | UUID | CLI / one-off tasks |

---

## 5. Coordination Model

### 5.1 Hybrid Delegation

```
┌─────────────────────────────────────────────────────────────────┐
│                       ProductManager                             │
│                    (Supervisor Role)                             │
│   - Complex multi-agent tasks                                    │
│   - Strategic decisions                                          │
│   - Conflict resolution                                          │
│   - Ambiguous routing                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
   │  Software   │    │   Release    │    │   Support    │
   │  Engineer   │◄──►│   Engineer   │◄──►│   Engineer   │
   └─────────────┘    └──────────────┘    └──────────────┘
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                              ▼
                    ┌──────────────┐
                    │  Marketing   │
                    │   Manager    │
                    └──────────────┘

────────────────────────────────────────────────────────────────────
                    Direct @mention handoffs
```

### 5.2 Delegation Rules

| Scenario | Routing |
|----------|---------|
| Simple handoff ("@ReleaseEngineer please deploy") | Direct agent-to-agent |
| Multi-step workflow | ProductManager coordinates |
| Conflict between agents | ProductManager decides |
| Unclear which agent needed | ProductManager triages |
| Human escalation | Any agent can flag for human |


Benchmark Model/Framework
From scripts/benchmark_handoffs.py:
- Judge Model: Azure OpenAI gpt-5-2 (line 58-59)
- Frameworks tested: AutoGen, CrewAI, OpenHands (line 184)
- Evaluation: LLM-as-judge using the same Azure endpoint
The Key Issue You're Raising
The current benchmark tests internal handoff (transfer tools) but your architecture uses Slack-based message handoff:
1. Current approach: Agents have transfer_to_* tools that return HANDOFF:agent:context strings internally
2. Your desired approach: Agents post messages to Slack mentioning other agents (e.g., @SoftwareEngineer please fix...), and those agents pick up the messages via their Slack listeners
How Slack-Based Handoff Should Work
From docs/requirements.md and the plan:
┌─────────────────────────────────────────────────────────────────┐
│  Human: @VibeTeam there's a bug in login                       │
│      │                                                          │
│      └──► SupportEngineer picks up (via Slack listener)         │
│              │                                                  │
│              ▼ Posts to Slack:                                  │
│  [@SupportEngineer]: I've analyzed this. It's a code issue.    │
│                 @SoftwareEngineer please fix the login          │
│              │                                                  │
│              └──► SoftwareEngineer picks up (via Slack listener)│
└─────────────────────────────────────────────────────────────────┘
All agents subscribe to the same Slack channel. When one agent mentions another, that agent's listener detects it and starts working.

### 5.3 Human Override

At any point, a human can:
- Directly message any agent via @mention
- Cancel an ongoing task
- Redirect work to different agent
- Take over manually

---

## 6. Example Workflows

### 6.1 Bug Report from Customer Email

```
1. [SupportEngineer] Receives email via Gmail CronJob
2. [SupportEngineer] Checks Sentry for related errors
3. [SupportEngineer] Searches codebase for relevant context
4. [SupportEngineer] Creates GitHub issue with details
5. [SupportEngineer] Posts in Slack: "Created issue #789 for auth bug"
6. [SupportEngineer] @mentions SoftwareEngineer in issue comments
7. [SoftwareEngineer] Investigates, creates fix PR
8. [SoftwareEngineer] @mentions ReleaseEngineer when PR merged
9. [ReleaseEngineer] Deploys fix to production
10. [ReleaseEngineer] @mentions SupportEngineer that fix is live
11. [SupportEngineer] Replies to customer email
```

### 6.2 Public Release Announcement

```
1. [ProductManager] Decides release is ready, creates release issue
2. [ProductManager] Assigns issue to ReleaseEngineer
3. [ReleaseEngineer] Runs deployment to production
4. [ReleaseEngineer] Creates GitHub release with changelog
5. [ReleaseEngineer] Comments on issue: "v1.5.0 deployed"
6. [ReleaseEngineer] @mentions MarketingManager for announcement
7. [MarketingManager] Drafts Twitter/X post, posts in Slack for review
8. [MarketingManager] Posts to Twitter/X and LinkedIn
9. [MarketingManager] Monitors initial reactions, reports back
10. [MarketingManager] Comments on issue: "Announced on social"
```

### 6.3 Customer Question on Social Media

```
1. [MarketingManager] Sees customer question on Twitter/X
2. [MarketingManager] Posts in Slack: "Technical question from @user"
3. [MarketingManager] @mentions SupportEngineer for technical details
4. [SupportEngineer] Provides technical answer in Slack thread
5. [MarketingManager] Crafts customer-friendly response
6. [MarketingManager] Replies on Twitter/X
```

---

## 7. Security & Access Control

### 7.1 Tool Permissions Matrix

| Agent | Shell | File Write | GitHub Write | GitHub Read | Social Media | Sentry | Langfuse | Gmail |
|-------|-------|------------|--------------|-------------|--------------|--------|----------|-------|
| ProductManager | - | - | Yes | Yes | - | - | Yes | - |
| SoftwareEngineer | Yes | Yes | Yes | Yes | - | - | - | - |
| ReleaseEngineer | Yes | Yes | Yes | Yes | - | - | - | - |
| SupportEngineer | - | - | - | Yes | - | Yes | Yes | Yes |
| MarketingManager | - | - | - | - | Yes | - | - | - |

### 7.2 Authentication Methods

| Service | Method | Storage |
|---------|--------|---------|
| GitHub | GitHub App (`vibeteam-bot`) | K8s Secret |
| Slack | Bot OAuth Token | K8s Secret |
| Gmail | OAuth2 with refresh token | K8s Secret |
| Sentry | Auth Token | K8s Secret |
| Langfuse | Public/Secret key pair | K8s Secret |
| Social Media | Stored browser sessions | Encrypted volume |

### 7.3 Security Guardrails

1. **No PII in social media posts** - Agent validates before posting
2. **No secrets in commits** - Pre-commit hooks + agent awareness
3. **No force pushes to main** - GitHub branch protection
4. **Human approval for destructive operations** - Agent posts to Slack and waits
5. **Rate limiting** - Respect API limits on all integrations
6. **Audit logging** - All actions traced in Langfuse

---

## 8. Deployment Architecture

### 8.1 Infrastructure

| Component | Technology |
|-----------|------------|
| Runtime | k3s Kubernetes cluster |
| Secrets | Kubernetes Secrets (sealed) |
| Session Store | Redis / PostgreSQL |
| Observability | Langfuse at langfuse.vibebrowser.app |
| Domain | team.vibebrowser.app |

### 8.2 Entry Points

| Entry Point | Type | Agents Activated |
|-------------|------|------------------|
| Slack webhook | HTTP POST | Routed by @mention |
| GitHub webhook (issue assigned) | HTTP POST | Assigned agent |
| GitHub webhook (issue comment) | HTTP POST | @mentioned agent |
| Email CronJob | Every 5 min | SupportEngineer |
| Health CronJob | Every 15 min | ReleaseEngineer |

### 8.3 Kubernetes Resources

```
k8s/
├── base/
│   ├── slack-webhook-deployment.yaml
│   ├── github-webhook-deployment.yaml
│   ├── email-cronjob.yaml
│   ├── health-cronjob.yaml
│   ├── session-store.yaml
│   └── secrets/
│       ├── github-app-secret.yaml
│       ├── slack-oauth-secret.yaml
│       ├── gmail-oauth-secret.yaml
│       ├── sentry-token-secret.yaml
│       └── langfuse-keys-secret.yaml
└── overlays/
    ├── dev/
    └── prod/
```

---

## 9. Observability

### 9.1 Langfuse Integration

All LLM calls traced with metadata:

| Field | Value |
|-------|-------|
| `session_id` | Session key (agent:context_type:context_id) |
| `user_id` | Agent name |
| `tags` | Task type, outcome, channel |
| `metadata` | Tool calls, tokens used, latency |

### 9.2 Slack Activity Visibility

Every significant agent action posts to Slack:

- Task received acknowledgment
- Actions taken (summarized)
- Outcome or next steps
- Errors with actionable context

**Example:**
```
[@ReleaseEngineer]: Deployed v1.5.0 to production

- Pods: 3/3 running
- Health check: passing
- Rollback available: v1.4.9

Next: @MarketingManager to announce
```

### 9.3 GitHub Audit Trail

All agent work traceable via GitHub:
- Issue comments show agent discussions
- Commits reference issues (`Fixes #123`)
- PRs linked to issues
- Releases document changes

---

## 10. Success Criteria

### 10.1 Functional Requirements

- [ ] All 5 agents can be triggered via Slack @mentions
- [ ] GitHub issue assignment routes to correct agent
- [ ] Agents communicate in Slack with visible @mentions
- [ ] GitHub issue comments show agent collaboration
- [ ] MarketingManager can post to Twitter/X and LinkedIn via browser automation
- [ ] SupportEngineer can query Sentry for errors
- [ ] SupportEngineer can query Langfuse for traces
- [ ] SupportEngineer can read/reply to Gmail
- [ ] SupportEngineer can search product documentation
- [ ] ReleaseEngineer can deploy to k3s cluster
- [ ] ReleaseEngineer can create GitHub releases
- [ ] SoftwareEngineer can create PRs from issues
- [ ] ProductManager can coordinate multi-agent workflows
- [ ] Session isolation works per (agent, context) pair
- [ ] Sessions persist across pod restarts

### 10.2 Non-Functional Requirements

- [ ] All LLM calls traced in Langfuse with session_id
- [ ] < 5 second acknowledgment for Slack mentions
- [ ] < 30 second acknowledgment for GitHub webhooks
- [ ] Session resumption after pod restart
- [ ] No credential exposure in logs or traces
- [ ] Rate limits respected on all APIs
- [ ] Human can override any agent action

---

## 11. Related Issues

| Issue | Description |
|-------|-------------|
| #18 | GitHub App authentication for agents |
| #21 | RFC: Supervisor Agent Architecture |
| #22 | Complete VibeTeam Integration Setup |
| #29 | Multi-Framework Agent Experiment |

---

## 12. Glossary

| Term | Definition |
|------|------------|
| **Agent** | Autonomous AI worker with specific role and tools |
| **Session** | Conversation history for one agent in one context |
| **Context** | The channel/issue/thread where conversation happens |
| **Handoff** | When one agent delegates work to another |
| **Supervisor** | Agent (ProductManager) that coordinates complex workflows |
| **MCP** | Model Context Protocol - standard for tool integration |

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-27 | 1.0 | Initial requirements document |
