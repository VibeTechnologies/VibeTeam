# How Do AI Agents Talk to Each Other?

*And should humans be able to see the conversation?*

---

## TL;DR

We're building an AI team where agents have different tools, different knowledge, and hand off work to each other. After evaluating 8 frameworks, we found: **none natively support human-visible communication**. 

Our proposal: **OpenHands for agents** (skills, MCP, sessions, 77.6% SWE-Bench) + **Slack/GitHub for communication** (human-visible) + **context-aware sessions** (per issue/PR/thread).

**Still figuring this out.** [What do you think?](#what-do-you-think)

---

## The Problem

We're building VibeTeam - an AI team where specialized agents collaborate:

| Agent | Tools | Knowledge |
|-------|-------|-----------|
| **SoftwareEngineer** | GitHub, Bash, Code | Codebase, architecture |
| **ReleaseEngineer** | GitHub, Sentry, Deploy | Release process |
| **ProductManager** | GitHub Issues, Langfuse | Roadmap, customer requests |
| **MarketingManager** | Chrome DevTools, Twitter | Brand, announcements |

### Requirements

1. **Different tools per agent** - SWE needs Bash, PM doesn't
2. **Different knowledge** - Each knows their domain
3. **Handoffs** - SWE says "@ReleaseEngineer deploy this"
4. **Session memory** - Agent remembers previous work on same issue
5. **Human-visible** - All agent chat observable in Slack/GitHub

### The Transparency Requirement

```
#ai-team channel:

Turing (SWE): Fixed login bug. PR #45 ready. @ReleaseEngineer deploy.
CEO: Wait, add the password reset fix first.
Turing (SWE): Done. PR #45 updated. @ReleaseEngineer ready now.
Einstein (Release): Deploying PR #45 to staging...
```

Humans need to **see**, **intervene**, and **audit**.

---

## Framework Comparison

| Framework | MCP | Skills | Sessions | Sub-agents | Built-in Tools |
|-----------|-----|--------|----------|------------|----------------|
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | ✅ | ✅ | ✅ | ✅ | ✅ Bash, File, Glob |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | ✅ | ❌ | ❌ | ✅ | ❌ |
| [LangGraph](https://github.com/langchain-ai/langgraph) | ❌ | ❌ | ✅ | ✅ | ❌ |
| [AutoGen](https://github.com/microsoft/autogen) | ❌ | ❌ | ✅ | ✅ | ❌ |
| [CrewAI](https://github.com/crewAIInc/crewAI) | ❌ | ❌ | ❌ | ✅ | ✅ 40+ |

**Key insight**: Only OpenHands has all four: MCP + Skills + Sessions + Built-in tools.

### What About External Tools (Gmail, Chrome DevTools)?

Both OpenHands and PydanticAI support **MCP (Model Context Protocol)** - they can connect to any MCP server:

```python
# OpenHands
agent = Agent(
    llm=llm,
    mcp_config={
        "mcpServers": {
            "chrome": {"command": "npx", "args": ["@anthropic/mcp-server-chrome-devtools"]},
            "gmail": {"command": "npx", "args": ["@anthropic/mcp-server-gmail"]},
        }
    }
)

# PydanticAI
from pydantic_ai.mcp import MCPServerStdio
chrome = MCPServerStdio('npx', args=['@anthropic/mcp-server-chrome-devtools'])
agent = Agent('azure:gpt-4.1', toolsets=[chrome])
```

**Both can use Gmail, Chrome DevTools, Notion, Slack, etc. via MCP.**

---

## The Gap: Human-Visible Communication

| Framework | Communication Pattern | Human-Visible? |
|-----------|----------------------|----------------|
| OpenHands | DelegateTool (internal) | ❌ |
| PydanticAI | Tool call (internal) | ❌ |
| LangGraph | Shared state (internal) | ❌ |
| AutoGen | Pub-Sub (internal) | ❌ |
| CrewAI | Delegation (internal) | ❌ |

**None expose agent-to-agent messages to humans.**

### Our Solution: External Channels

Route all communication through Slack/GitHub:

```
         Slack #ai-team / GitHub Issues
                    │
                    ▼
         ┌──────────────────────┐
         │   VibeTeam Router    │
         │  - Watches @mentions │
         │  - Resolves sessions │
         │  - Posts responses   │
         └──────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌───────┐       ┌───────┐       ┌───────┐
│  SWE  │       │  PM   │       │Release│
│ Agent │       │ Agent │       │ Agent │
└───────┘       └───────┘       └───────┘
[bash,git]      [langfuse]      [sentry]
[github]        [github]        [github]
```

**The framework runs agents. Slack/GitHub handles communication.**

---

## Context-Aware Sessions

When `/SoftwareEngineer` is invoked, which session do we load? The agent needs different context for different issues.

### Session Key Design

```
session_key = {role}:{context_type}:{context_id}

Examples:
  swe:issue:123           # SWE on Issue #123
  swe:pr:45               # SWE on PR #45  
  release:issue:123       # Release on same issue (shares context)
  pm:slack:C0123-T456     # PM in Slack thread
```

### Architecture

```
                    Request: "/SoftwareEngineer fix issue #123"
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                        VibeTeam Router                           │
│                                                                  │
│  1. Parse: agent=SWE, issue=123, channel=C0123                   │
│  2. Build key: "swe:issue:123"                                   │
│  3. Check session store                                          │
└──────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
             Session Exists                      Create New
                    │                                   │
                    ▼                                   ▼
┌────────────────────────────────┐    ┌────────────────────────────────┐
│  Resume from S3/local:         │    │  Initialize:                   │
│  sessions/swe:issue:123/       │    │  - Load agent skills           │
│    ├── metadata.json           │    │  - Inject issue context        │
│    ├── agent_state.pkl         │    │  - Configure MCP tools         │
│    └── events/0.json, 1.json   │    │                                │
│                                │    │                                │
│  Agent remembers:              │    │                                │
│  "Last time I edited auth.py"  │    │                                │
│  "PR #45 has 2 commits"        │    │                                │
└────────────────────────────────┘    └────────────────────────────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                     OpenHands Agent Execution                    │
│                                                                  │
│  conversation_id = "swe:issue:123"                               │
│  # Full history from previous work on this issue                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                           Post response to Slack
```

### Session Resolution Priority

| Priority | Context | Key | Example |
|----------|---------|-----|---------|
| 1 | Issue mentioned | `{role}:issue:{id}` | "fix issue #123" |
| 2 | PR mentioned | `{role}:pr:{id}` | "review PR #45" |
| 3 | Slack thread | `{role}:slack:{ch}-{ts}` | Thread-specific |
| 4 | Slack channel | `{role}:slack:{ch}` | Channel-level |
| 5 | None | `{role}:ephemeral:{uuid}` | One-off |

### Cross-Agent Context

When SWE hands off to Release on the same issue:

```
Issue #123 Context (shared):
├── swe:issue:123     → "Edited auth.py, created PR #45"
└── release:issue:123 → "Deployed PR #45 to staging"
                         (knows what SWE did)
```

---

## Proposed Stack

| Layer | Technology | Why |
|-------|------------|-----|
| **Agents** | OpenHands | Skills, MCP, sessions, 77.6% SWE-Bench |
| **External Tools** | MCP servers | Gmail, Chrome DevTools, Notion, etc. |
| **Sessions** | S3 / Local | Per issue/PR/thread context |
| **Communication** | Slack + GitHub | Human-visible, auditable |
| **Router** | VibeTeam | Resolves sessions, routes @mentions |

---

## What Do You Think?

Open questions:

1. **OpenHands vs PydanticAI?** - OpenHands has more batteries, PydanticAI is lighter
2. **Session expiry?** - Keep until issue closed? 7 days? Forever?
3. **Cross-agent inheritance?** - Should Release see full SWE history or just summary?
4. **Parallel agents?** - Two agents on same issue simultaneously?

**We'd love your input:**
- [GitHub Discussions](https://github.com/AnomalyCo/VibeTeam/discussions)
- [@AnomalyCo](https://twitter.com/AnomalyCo)

---

## References

**Papers:**
[AutoGen](https://arxiv.org/abs/2308.08155) ·
[CAMEL](https://arxiv.org/abs/2303.17760) ·
[CoELA](https://arxiv.org/abs/2307.02485) ·
[Generative Agents](https://arxiv.org/abs/2304.03442) ·
[μACP](https://arxiv.org/abs/2601.00219)

**Frameworks:**
[OpenHands](https://github.com/All-Hands-AI/OpenHands) ·
[PydanticAI](https://github.com/pydantic/pydantic-ai) ·
[LangGraph](https://github.com/langchain-ai/langgraph) ·
[AutoGen](https://github.com/microsoft/autogen) ·
[CrewAI](https://github.com/crewAIInc/crewAI)

---

*Last updated: January 2026*
