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

## Phase 6: Production Deployment & Validation (COMPLETED ✓)

### Final Goal
**Run the Slack bot and demonstrate real agent-to-agent handoff in a Slack thread.**

Test scenario:
1. User mentions @SupportEngineer about a customer complaint
2. SupportEngineer checks Gmail for customer emails
3. SupportEngineer delegates to @ReleaseEngineer in the Slack thread
4. ReleaseEngineer picks up and investigates
5. Both agents communicate in the same Slack thread - visible to humans

**Success criteria**: See the @ReleaseEngineer handoff message in Slack thread. ✓

### Step-by-Step Deployment Guide

#### Prerequisites

1. **Environment variables** - Copy `.env.example` to `.env` and configure:
   ```bash
   # Required for Slack bot
   SLACK_BOT_TOKEN=xoxb-...          # Slack Bot OAuth Token
   SLACK_CHANNEL=#your-channel       # Channel to monitor
   
   # Required for LLM
   AZURE_API_KEY=...                 # Azure OpenAI API key
   AZURE_API_BASE=https://...        # Azure OpenAI endpoint
   AZURE_API_VERSION=2024-12-01-preview
   
   # Optional - enables Gmail tools
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REFRESH_TOKEN=...
   
   # Optional - enables GitHub tools
   GITHUB_TOKEN=ghp_...
   
   # Optional - for persistent subscriptions (in-memory used if not set)
   DATABASE_URL=postgres://...
   ```

2. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

#### Database Migration (Optional)

If using PostgreSQL for persistent thread subscriptions:

```bash
# Check if migrations are needed
python scripts/migrate_db.py --check

# Run migrations
python scripts/migrate_db.py
```

This creates the `thread_subscriptions` table for tracking which agents are subscribed to which threads. If `DATABASE_URL` is not set, the bot uses `InMemorySubscriptionDB` instead (subscriptions lost on restart).

#### Running the Slack Bot

```bash
# Basic usage - monitors #ai-team with CrewAI agents
python scripts/run_slack_bot.py

# Specify channel and framework
python scripts/run_slack_bot.py --channel "#all-vibetechnologies" --framework crewai

# Debug mode with verbose logging
python scripts/run_slack_bot.py --channel "#test-channel" --debug

# Single poll (useful for testing)
python scripts/run_slack_bot.py --once
```

**CLI Options**:
| Option | Default | Description |
|--------|---------|-------------|
| `--channel` | `#ai-team` | Slack channel to monitor |
| `--poll-interval` | `5` | Seconds between polls |
| `--framework` | `crewai` | Agent framework: `crewai`, `autogen`, `openhands`, `vibeteam` |
| `--once` | false | Run single poll and exit |
| `--debug` | false | Enable debug logging |

#### Running the Discord Bot

```bash
# Basic usage
python scripts/run_discord_bot.py

# With options
python scripts/run_discord_bot.py --framework openhands --debug
```

Requires additional env vars: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID`.

#### Message Format

Users trigger agents by mentioning roles in messages:

```
@VibeTeam /SoftwareEngineer fix the login bug in auth.py
```

The bot:
1. Detects `/SoftwareEngineer` mention
2. Routes message to SoftwareEngineer agent
3. Agent processes task and responds in thread
4. If agent mentions another role (e.g., `/ReleaseEngineer`), that agent picks up

### Validation Procedure

1. **Start the bot**:
   ```bash
   python scripts/run_slack_bot.py --channel "#all-vibetechnologies" --debug
   ```

2. **Send test message** in Slack:
   ```
   @VibeTeam /SupportEngineer A customer just emailed saying the GenAI Gateway is down.
   After checking their subscription, please ask /ReleaseEngineer to investigate.
   ```

3. **Verify bot response**:
   - Bot adds 👀 reaction to message
   - SupportEngineer agent responds in thread
   - SupportEngineer mentions `/ReleaseEngineer` in response
   - ReleaseEngineer automatically picks up and responds

4. **Check logs** for routing:
   ```
   2026-01-31 14:23:01 [INFO] slack_bot: Running SupportEngineer agent for: A customer just...
   2026-01-31 14:23:15 [INFO] slack_bot: Posted SupportEngineer response in thread 1769910256.222199
   2026-01-31 14:23:16 [INFO] slack_bot: Detected handoff to: ['release_engineer']
   2026-01-31 14:23:30 [INFO] slack_bot: Posted ReleaseEngineer response in thread 1769910256.222199
   ```

### Completed Tasks (2026-01-31)

- [x] Create database migration for `thread_subscriptions` table
  - Commit: 78de195
  - Created `scripts/migrate_db.py`
- [x] Create `vibeteam/tools/send_message.py` for agents to post to Slack/Discord
  - Commit: c5ba4a4
  - Added SendMessageTool with platform-agnostic interface
- [x] Add InMemorySubscriptionDB for testing without PostgreSQL
  - Commit: b25f89f
  - Added to `vibeteam/router/db.py`
- [x] Fix GPT-5.2 API compatibility (max_tokens → max_completion_tokens)
  - Commit: 45ff245
  - Updated `vibeteam/agents/base.py` and `vibeteam/team/responsibility.py`
- [x] Run Slack bot with real credentials
  - Bot successfully connected to #all-vibetechnologies channel
- [x] Execute test scenario: @SupportEngineer → @ReleaseEngineer handoff
  - Thread: 1769910256.222199
  - SupportEngineer processed message and mentioned @ReleaseEngineer
  - ReleaseEngineer automatically picked up and responded
- [x] Verify handoff appears in Slack thread
  - 3 messages in thread: user request, SupportEngineer response, ReleaseEngineer response
  - Both agents used their tools (Gmail, GitHub, Health)
  - Natural @mention handoff working as designed

### Test Results

```
Thread: #all-vibetechnologies / 1769910256.222199

Message 1 (User):
@SupportEngineer A customer just emailed saying the GenAI Gateway is down.
After checking their subscription, please ask @ReleaseEngineer to investigate.

Message 2 (SupportEngineer):
I can't verify the customer's subscription or confirm an outage from what I have
right now—there isn't a customer email about the GenAI Gateway in the unread
inbox I just checked.
@ReleaseEngineer: Please investigate current GenAI Gateway status...

Message 3 (ReleaseEngineer):
@SupportEngineer I've logged this as a **P0** customer report: "GenAI Gateway is down"
I investigated gateway status signals:
- Health checks: overall degraded — api.vibebrowser.app/health returns 401...
```

### Architecture Validated

The multi-session bot architecture works as designed:
1. Single bot process handles multiple agent sessions
2. Router detects @RoleName mentions and routes messages
3. InMemorySubscriptionDB tracks thread subscriptions (no PostgreSQL needed)
4. Agents communicate via natural @mentions in responses
5. Handoffs are visible to humans in the Slack thread
6. Each agent uses its own tools (Gmail, GitHub, Health, etc.)

---

## Phase 7: Gateway Service (FastAPI)

**Goal**: Replace polling-based bots with webhook-driven FastAPI gateway.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GATEWAY (FastAPI)                                 │
│                                                                              │
│   POST /webhook/discord   POST /webhook/slack   POST /webhook/github        │
│   POST /webhook/gmail     POST /webhook/sentry  GET /health                 │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Message Router                                 │ │
│   │  1. Normalize event → UnifiedMessage                                   │ │
│   │  2. Check for @VibeTeam mention → track thread                        │ │
│   │  3. Parse /RoleName mentions → subscribe agents                       │ │
│   │  4. React with :eyes: emoji                                           │ │
│   │  5. Forward to Agent Service                                          │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Tasks

- [ ] Create `vibeteam/gateway/__init__.py`
- [ ] Create `vibeteam/gateway/app.py` - FastAPI app with webhook routes
- [ ] Create `vibeteam/gateway/handlers/slack.py` - Slack event handler
- [ ] Create `vibeteam/gateway/handlers/discord.py` - Discord webhook handler
- [ ] Create `vibeteam/gateway/handlers/github.py` - GitHub webhook handler
- [ ] Create `vibeteam/gateway/handlers/sentry.py` - Sentry webhook handler
- [ ] Create `scripts/run_gateway.py` - Gateway runner with uvicorn
- [ ] Add health check endpoint with dependency status
- [ ] Add request logging and error handling middleware

### Webhook Endpoints

| Endpoint | Source | Event Types |
|----------|--------|-------------|
| `POST /webhook/slack` | Slack Events API | `app_mention`, `message` |
| `POST /webhook/discord` | Discord Interactions | Message create |
| `POST /webhook/github` | GitHub Webhooks | `issue_comment`, `pull_request_review_comment` |
| `POST /webhook/sentry` | Sentry Webhooks | `issue.created`, `issue.resolved` |
| `GET /health` | Internal | Liveness/readiness probe |

---

## Phase 8: Agent Service (FastAPI)

**Goal**: Separate agent execution into its own service with session management.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT SERVICE (FastAPI)                             │
│                                                                              │
│   POST /run              - Run agent with message context                    │
│   GET  /sessions/{id}    - Get session details                              │
│   DELETE /sessions/{id}  - End session                                      │
│   GET  /health           - Health check                                      │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Session Manager                                   │ │
│   │  - Get/create session by (source, thread_id, role)                    │ │
│   │  - Manage persistent workspaces (7-day TTL)                           │ │
│   │  - Inject pre-configured send_message tool                            │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Agent Pool                                        │ │
│   │  SoftwareEngineer | ReleaseEngineer | SupportEngineer                 │ │
│   │  ProductManager   | MarketingManager                                   │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tasks

- [ ] Create `vibeteam/agent_service/__init__.py`
- [ ] Create `vibeteam/agent_service/app.py` - FastAPI app
- [ ] Create `vibeteam/agent_service/session_manager.py` - Session lifecycle
- [ ] Create `vibeteam/agent_service/workspace_manager.py` - Workspace with TTL
- [ ] Create `vibeteam/agent_service/routes.py` - API routes
- [ ] Create `scripts/run_agent_service.py` - Service runner
- [ ] Implement session key format: `{framework}:{role}:{source}:{thread_id}`
- [ ] Add session persistence to PostgreSQL
- [ ] Add workspace cleanup cron job (7-day TTL)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/run` | POST | Run agent with message, returns response |
| `/sessions/{id}` | GET | Get session details and history |
| `/sessions/{id}` | DELETE | End session and cleanup workspace |
| `/health` | GET | Service health check |

### Request/Response Models

```python
class RunRequest(BaseModel):
    source: str              # slack, discord, github_issue
    thread_id: str           # Thread identifier
    channel_id: str          # Channel for responses
    role: str                # software_engineer, release_engineer, etc.
    content: str             # Message content
    author: str              # Message author
    framework: str = "crewai"  # Agent framework

class RunResponse(BaseModel):
    session_id: str
    response: str
    mentioned_roles: list[str]  # Detected handoffs
    tool_calls: list[dict]      # Tools used
```

---

## Phase 9: GitHub & Sentry Integration

**Goal**: Enable agents to respond to GitHub issues/PRs and Sentry alerts.

### GitHub Integration

```
GitHub Issue Comment: "@VibeTeam /SoftwareEngineer please investigate"
       │
       ▼
POST /webhook/github
       │
       ▼
Router:
  source = "github_issue"
  thread_id = "VibeTechnologies/VibeWebAgent:345"
  role = "software_engineer"
       │
       ▼
Agent responds via GitHub API comment
```

### Tasks

- [ ] Create `vibeteam/gateway/handlers/github.py`:
  - Handle `issue_comment` events
  - Handle `pull_request_review_comment` events
  - Parse @VibeTeam /RoleName mentions
  - Create UnifiedMessage with GitHub context
- [ ] Create `vibeteam/tools/github_comment.py`:
  - Tool for agents to post GitHub comments
  - Pre-configured with repo/issue context
- [ ] Add GitHub webhook signature verification
- [ ] Create thread ID format: `{repo}:{issue_number}` or `{repo}:pr:{pr_number}`

### Sentry Integration

```
Sentry Error Spike
       │
       ▼
POST /webhook/sentry
       │
       ▼
Router creates synthetic thread:
  source = "sentry"
  thread_id = "sentry:{issue_id}"
  Auto-routes to /SupportEngineer
       │
       ▼
SupportEngineer investigates, may handoff:
  "/SoftwareEngineer this is a bug in auth.py:45"
```

### Tasks

- [ ] Create `vibeteam/gateway/handlers/sentry.py`:
  - Handle `issue.created` events
  - Auto-route based on severity (P0 → ReleaseEngineer, else SupportEngineer)
  - Create synthetic thread for Sentry issues
- [ ] Create `vibeteam/tools/sentry_tools.py`:
  - `get_sentry_issue(issue_id)` - Get issue details
  - `get_sentry_events(issue_id)` - Get recent events
  - `resolve_sentry_issue(issue_id)` - Mark resolved
- [ ] Add Sentry webhook signature verification

---

## Phase 10: E2E Testing with DeepEval

**Goal**: Comprehensive agent evaluation using DeepEval with GPT-5.2 as judge.

### Testing Framework

```python
# tests/e2e/conftest.py
import pytest
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

@pytest.fixture
def gpt52_evaluator():
    """GPT-5.2 evaluator for G-Eval metrics."""
    return {
        "model": "azure/gpt-5.2",
        "api_key": os.environ["AZURE_API_KEY"],
        "api_base": os.environ["AZURE_API_BASE"],
    }
```

### Test Scenarios

| Test | Scenario | Metrics |
|------|----------|---------|
| `test_slack_routing.py` | Slack message → agent response | TaskCompletion, ResponseTime |
| `test_discord_routing.py` | Discord message → agent response | TaskCompletion, ResponseTime |
| `test_github_routing.py` | GitHub comment → agent response | TaskCompletion, Professionalism |
| `test_handoff_chain.py` | Support → Release → Support | HandoffQuality, ContextPreservation |
| `test_sentry_alert.py` | Sentry alert → investigation | TaskCompletion, ToolUsage |

### Evaluation Metrics (DeepEval G-Eval)

| Metric | Threshold | Evaluation Criteria |
|--------|-----------|---------------------|
| **TaskCompletion** | 0.7 | Did the agent complete the requested task? |
| **HandoffQuality** | 0.7 | Was context preserved during handoff? |
| **ResponseTime** | < 60s | Time from message to first response |
| **Professionalism** | 0.7 | Clear, concise, professional communication |
| **ToolUsage** | 0.7 | Did agent use appropriate tools? |
| **ContextPreservation** | 0.7 | Does agent maintain conversation context? |

### Tasks

- [ ] Create `tests/e2e/conftest.py` - DeepEval fixtures with GPT-5.2
- [ ] Create `tests/e2e/test_slack_routing.py` - Slack routing tests
- [ ] Create `tests/e2e/test_discord_routing.py` - Discord routing tests
- [ ] Create `tests/e2e/test_github_routing.py` - GitHub routing tests
- [ ] Create `tests/e2e/test_handoff_chain.py` - Multi-agent handoff tests
- [ ] Create `tests/e2e/test_sentry_alert.py` - Sentry alert handling tests
- [ ] Add DeepEval to requirements: `deepeval>=0.21.0`
- [ ] Create `scripts/run_evaluation.py` - Run all E2E tests with reporting
- [ ] Add CI job for E2E evaluation tests

### Running Tests

```bash
# Run all E2E tests
pytest tests/e2e/ -v -s

# Run specific test with DeepEval metrics
pytest tests/e2e/test_handoff_chain.py -v -s --tb=short

# Run evaluation suite with report
python scripts/run_evaluation.py --output results/eval_report.json
```

### Example Test

```python
# tests/e2e/test_handoff_chain.py
import pytest
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

class TestHandoffChain:
    """Test multi-agent handoff scenarios."""
    
    @pytest.mark.asyncio
    async def test_support_to_release_handoff(self, mock_slack, gpt52_evaluator):
        """
        Scenario: Customer reports outage, Support investigates and hands off to Release.
        
        Expected flow:
        1. User: @SupportEngineer customer reports GenAI Gateway down
        2. SupportEngineer: checks Gmail, responds, mentions @ReleaseEngineer
        3. ReleaseEngineer: investigates, reports status
        """
        # Setup
        user_message = "Customer emailed that GenAI Gateway is returning 500 errors"
        
        # Run agents
        support_response = await run_agent("support_engineer", user_message)
        
        # Verify handoff detected
        assert "/ReleaseEngineer" in support_response or "@ReleaseEngineer" in support_response
        
        # Run Release agent with handoff context
        release_response = await run_agent("release_engineer", support_response)
        
        # Evaluate with DeepEval
        test_case = LLMTestCase(
            input=user_message,
            actual_output=f"{support_response}\n\n{release_response}",
            expected_output="Support checks customer email, identifies issue, hands off to Release who investigates infrastructure",
        )
        
        handoff_metric = GEval(
            name="HandoffQuality",
            criteria="Was the handoff context-preserving and actionable?",
            threshold=0.7,
            **gpt52_evaluator,
        )
        
        task_metric = GEval(
            name="TaskCompletion",
            criteria="Did both agents contribute to resolving the customer issue?",
            threshold=0.7,
            **gpt52_evaluator,
        )
        
        results = evaluate([test_case], [handoff_metric, task_metric])
        
        assert results.passed, f"Evaluation failed: {results.summary}"
```

---

## Phase 11: True Agent-to-Agent Slack Communication (COMPLETED ✓)

**Goal**: Agents communicate directly over Slack using `send_message` tool, not through test framework.

### What Was Fixed

1. **Message format**: Changed from `*RoleName* responds:` to `[RoleName:session_id]`
2. **Handoff syntax**: Changed from `@RoleName` to `/RoleName` per requirements.md
3. **Agent posting**: Agents now use `send_message()` tool to post directly to Slack
4. **Session tracking**: Added `session_id` to Slack context for message prefixes

### Changes Made

| File | Changes |
|------|---------|
| `agents/shared/handoff.py` | Updated to use `/RoleName` mentions, instruct agents to use `send_message()` |
| `agents/shared/slack_tools.py` | Added `send_message()` with `[RoleName:session_id]` prefix, added `session_id` to context |
| `agents/shared/__init__.py` | Exported `send_message` and `send_message_sync` |
| `agents/autogen/support_engineer.py` | Updated to use `send_message()` for all responses |
| `agents/autogen/release_engineer.py` | Updated to use `send_message()` for all responses |
| `agents/autogen/software_engineer.py` | Updated to use `send_message()` for all responses |
| `agents/autogen/product_manager.py` | Updated to use `send_message()` for all responses |
| `agents/autogen/marketing_manager.py` | Updated to use `send_message()` for all responses |
| `tests/e2e/test_slack_routing.py` | Updated to set `session_id` in context, verify agents post via `send_message` |

### Test Results

```
>>> Step 7: Verifying messages in Slack...
    Found 4 messages in thread
    [1] [E2E Handoff Test] /SupportEngineer customer ACME Corp reports API 404 errors...
    [2] [SupportEngineer:621504cf] /ReleaseEngineer /SiteReliabilityEngineer ACME Corp reports...
    [3] [SupportEngineer:621504cf] For customer response: can you confirm ACME is using...
    [4] [ReleaseEngineer:d763be34] /SupportEngineer /SiteReliabilityEngineer Investigated k3s...

======================================================================
HANDOFF TEST SUMMARY
======================================================================
SupportEngineer Success: True
Handoff Detected: True
ReleaseEngineer Success: True
HandoffQuality Score: 0.80 (threshold: 0.75) ✅
TaskCompletion Score: 0.80 (threshold: 0.80) ✅
======================================================================
1 passed in 52.66s
```

**Key Achievement**: Agents now communicate directly over Slack using the `send_message` tool:
- Messages are prefixed with `[RoleName:session_id]` for identification
- Handoffs use `/RoleName` format which the router can detect
- Multiple messages per agent show they're actively using the tool

---

## Summary: Remaining Work

| Phase | Status | Priority | Effort |
|-------|--------|----------|--------|
| **Phase 11: True Slack Communication** | **Completed ✓** | Critical | Done |
| Phase 7: Gateway Service | Not Started | High | 2-3 days |
| Phase 8: Agent Service | Not Started | High | 2-3 days |
| Phase 9: GitHub/Sentry | Not Started | Medium | 2 days |
| Phase 10: E2E Testing | Partially Done | High | 1 day |

### Quick Start (Minimal Viable)

For fastest path to production:
1. **Fix Phase 11** - Agents must use `send_message` tool to communicate
2. **Skip Gateway/Agent Service split** - current polling bots work
3. **Add GitHub webhook handler** to existing bot
4. **Create E2E tests with DeepEval** - validate agent quality
5. **Run evaluation suite** before releases
