# Feature: Independent Agent Architecture with Natural @Mention Handoffs

Issue: N/A (architecture refactor)
Branch: `master`
Started: 2026-01-31

## Goal

Refactor VibeTeam from transfer-tool-based handoffs to independent parallel agents that communicate via natural @mentions in Discord/Slack. One process serves multiple agent sessions, routing messages based on role mentions.

## Architecture

### Multi-Session Bot Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Discord/Slack Bot Process                             │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     Message Router                                   ││
│  │                                                                      ││
│  │  Incoming message → Detect @mention → Route to agent session        ││
│  │                                                                      ││
│  │  @SoftwareEngineer → SWE Session (autogen/crewai/openhands)         ││
│  │  @ReleaseEngineer  → Release Session                                ││
│  │  @SupportEngineer  → Support Session                                ││
│  │  @ProductManager   → PM Session                                     ││
│  │  @MarketingManager → Marketing Session                              ││
│  │                                                                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     Agent Sessions                                   ││
│  │                                                                      ││
│  │  Each session is independent and stateful:                          ││
│  │  - Maintains conversation history                                   ││
│  │  - Has its own tools (GitHub, Shell, etc.)                          ││
│  │  - Can be backed by any framework (AutoGen, CrewAI, OpenHands)      ││
│  │                                                                      ││
│  │  Framework selection is per-agent via config or env var:            ││
│  │  AGENT_FRAMEWORK=crewai  # or autogen, openhands                    ││
│  │                                                                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     Response Handler                                 ││
│  │                                                                      ││
│  │  Agent response → Check for @mentions → Post via webhook            ││
│  │                                                                      ││
│  │  If response contains "@ReleaseEngineer", the bot automatically     ││
│  │  detects this and the Release session will pick it up on next poll. ││
│  │                                                                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Message Flow Example

```
User: "@SoftwareEngineer fix the login bug"
       │
       ▼
Bot receives message
  → Detects @SoftwareEngineer role mention
  → Routes to SWE session (e.g., CrewAI SoftwareEngineer)
       │
       ▼
SWE Session processes task
  → Uses shell, file, git, GitHub tools
  → Generates response: "Fixed in PR #457. @ReleaseEngineer ready for staging."
       │
       ▼
Bot posts response via webhook (as "SoftwareEngineer")
       │
       ▼
On next poll, bot sees @ReleaseEngineer in the message
  → Routes to Release session
  → Release agent deploys and responds
```

### Key Design Principles

1. **NO transfer tools** - Agents don't call special tools to hand off
2. **Natural @mentions** - Agent writes `@ReleaseEngineer ready for deployment` in its response
3. **One process, multiple sessions** - Single bot routes to different agent sessions
4. **Framework-agnostic** - Each agent can use AutoGen, CrewAI, or OpenHands
5. **Human visibility** - All communication happens in public channels

## Framework Support

The system supports three agent frameworks:

| Framework | Path | Strengths |
|-----------|------|-----------|
| AutoGen | `agents/autogen/` | Multi-agent orchestration, tool use |
| CrewAI | `agents/crewai/` | Role-based agents, native function calling |
| OpenHands | `agents/openhands/` | Coding-focused, sandbox execution |

Framework selection can be done via:
- CLI argument: `--framework crewai`
- Environment variable: `AGENT_FRAMEWORK=crewai`
- Config file: `agents/config.py`

## Tasks

### Phase 1: Remove Transfer Tools

- [x] Delete `vibeteam/tools/transfer.py`
- [x] Delete `vibeteam/swarm.py`
- [x] Delete `scripts/benchmark_handoffs.py`
- [x] Update `vibeteam/tools/__init__.py` - remove transfer exports
- [x] Update `vibeteam/agents/base.py` - remove HANDOFF_PREFIX
- [x] Update `vibeteam/agents/supervisor.py` - remove transfer tools
- [x] Update `vibeteam/agents/software_engineer.py` - remove transfer tools
- [x] Update `vibeteam/agents/release_engineer.py` - remove transfer tools
- [x] Update `vibeteam/agents/support_engineer.py` - remove transfer tools

### Phase 2: Refactor Shared Tools

- [x] Refactor `agents/shared/slack_tools.py`:
  - Keep: `post_slack_message`, `read_slack_channel`, `mention_agent`
  - Remove: `transfer_to_*` functions, `get_slack_handoff_instructions`
  - Add: `get_natural_handoff_instructions()` for agent prompts
- [x] Update `agents/shared/__init__.py` - remove transfer exports
- [x] Refactor `agents/crewai/slack_tools.py` - remove TransferTo* tool classes

### Phase 3: Update Agent Prompts

Add natural @mention handoff instructions to all agent system prompts:

```python
HANDOFF_INSTRUCTIONS = """
## Team Collaboration

When you need another team member's help, @mention them in your response:
- @SoftwareEngineer - for code implementation, bug fixes, PRs
- @ReleaseEngineer - for deployments and releases
- @SupportEngineer - for customer communication
- @ProductManager - for requirements and prioritization
- @MarketingManager - for announcements and content

Example: "I've fixed the login bug in PR #457. @ReleaseEngineer this is ready for staging."

The mentioned agent will automatically pick up the conversation.
"""
```

Update these files:
- [x] `agents/crewai/software_engineer.py` - update backstory
- [x] `agents/crewai/release_engineer.py` - update backstory
- [x] `agents/crewai/support_engineer.py` - update backstory
- [x] `agents/crewai/product_manager.py` - update backstory
- [x] `agents/autogen/*` - similar updates
- [x] `agents/openhands/*` - updated all 5 agents with @RoleName mentions

### Phase 4: Multi-Session Bot Architecture

- [x] Created `vibeteam/router/` package:
  - `models.py` - UnifiedMessage, ThreadSubscription dataclasses
  - `db.py` - PostgreSQL subscription storage (SQLAlchemy)
  - `router.py` - Router class with /RoleName parsing
- [x] Created `scripts/run_discord_bot.py`:
  - Multi-session routing with Router
  - AgentSessionManager for lazy agent creation
  - Supports all frameworks (crewai, autogen, openhands, vibeteam)
  - Eyes emoji reaction on message receipt
  - Handoff detection from bot messages
- [x] Created `scripts/run_slack_bot.py`:
  - Same pattern as Discord bot
  - Thread-based responses
  - Multi-framework support

### Phase 5: Tests

- [x] Update `tests/test_swarm.py` - remove transfer tool tests
- [x] Add tests for natural @mention detection
- [x] Run full test suite: `pytest tests/`
- [x] Create Discord handoff evaluation test: `tests/e2e/test_discord_handoff_eval.py`
- [x] Update `docs/requirements.v2.md` with evaluation test documentation

## Implementation Notes

### Why Remove Transfer Tools?

The old design had agents call `transfer_to_swe(task, context)` which:
1. Required special tools in each agent
2. Had complex Slack/Discord context management
3. Was not visible in the agent's natural response
4. Required SwarmOrchestrator for in-memory handoffs

The new design:
1. Agent naturally writes "@SoftwareEngineer please fix the bug"
2. Bot detects @mention and routes to SWE
3. No special tools needed
4. Human-readable handoffs in channel history

### Framework Selection

Currently using CrewAI as default. To switch:

```bash
# Via environment
export AGENT_FRAMEWORK=autogen
python scripts/run_discord_agent.py

# Via CLI (after refactor)
python scripts/run_discord_agent.py --framework openhands
```

### Webhook Responses

Each agent posts via its own webhook for distinct identity:
- SoftwareEngineer webhook → posts as "SoftwareEngineer" with avatar
- ReleaseEngineer webhook → posts as "ReleaseEngineer" with avatar

This makes it clear in the channel who is responding.

## Completed

### Initial Setup (2026-01-31)

- [x] Created Discord connector `vibeteam/connectors/discord.py`
- [x] Created Discord bot runner `scripts/run_discord_agent.py`
- [x] Added Discord environment variables to `.env.example`
- [x] Created requirements v2 documentation

### Architecture Refactor (2026-01-31)

- [x] Created comprehensive plan.md with architecture details
- [x] Phase 1: Remove transfer tools (completed)
- [x] Phase 2: Refactor shared tools (completed)
- [x] Phase 3: Update agent prompts (CrewAI, AutoGen completed; OpenHands pending)
- [x] Phase 5: Tests updated and new Discord handoff eval test created

### Discord Handoff Evaluation Test (2026-01-31)

- [x] Created `tests/e2e/test_discord_handoff_eval.py`
  - Simulates multi-agent handoff scenario (SupportEngineer -> ReleaseEngineer -> SupportEngineer)
  - Uses G-Eval (LLM-as-judge) with Azure GPT-5.2 for evaluation
  - Evaluates handoff detection, task completion, communication, tool usage
  - Compares all 3 frameworks: AutoGen, CrewAI, OpenHands
  - Mocks Discord and Gmail connectors
- [x] Updated `docs/requirements.v2.md` with evaluation test documentation (Section 8.3)

## Environment Variables

```bash
# Discord (primary)
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_CHANNEL_ID=
DISCORD_ROLE_SWE=
DISCORD_ROLE_RELEASE=
DISCORD_ROLE_SUPPORT=
DISCORD_ROLE_PM=
DISCORD_ROLE_MARKETING=
DISCORD_WEBHOOK_SWE=
DISCORD_WEBHOOK_RELEASE=
DISCORD_WEBHOOK_SUPPORT=
DISCORD_WEBHOOK_PM=
DISCORD_WEBHOOK_MARKETING=

# Slack (secondary)
SLACK_BOT_TOKEN=
SLACK_CHANNEL=

# Framework selection
AGENT_FRAMEWORK=crewai  # or autogen, openhands

# LLM
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=
```

## Phase 6: Production Deployment & Validation (IN PROGRESS)

### Final Goal
**Run the Slack bot and demonstrate real agent-to-agent handoff in a Slack thread.**

Test scenario:
1. User reports via Gmail: "The Vibe GenAI Gateway isn't working"
2. SupportEngineer receives the complaint, checks user subscription status
3. SupportEngineer delegates to @ReleaseEngineer in the Slack thread
4. ReleaseEngineer picks up and investigates the gateway issue
5. Both agents communicate in the same Slack thread - visible to humans

**Success criteria**: See the @ReleaseEngineer handoff message in Slack thread.

### Remaining Tasks

- [ ] Create database migration for `thread_subscriptions` table
- [ ] Create `vibeteam/tools/send_message.py` for agents to post to Slack/Discord
- [ ] Restore `agents/benchmark.py` module for e2e evaluation
- [ ] Run Slack bot with real credentials
- [ ] Execute test scenario: Gmail complaint → Support → Release handoff
- [ ] Verify handoff appears in Slack thread
