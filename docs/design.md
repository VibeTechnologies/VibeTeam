# VibeTeam System Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              External Platforms                              │
│                                                                              │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│   │   Discord   │    │    Slack    │    │   GitHub    │    │    Gmail    │  │
│   │   Server    │    │  Workspace  │    │   Webhooks  │    │    Push     │  │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
└──────────┼──────────────────┼──────────────────┼──────────────────┼──────────┘
           │                  │                  │                  │
           ▼                  ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        WEBHOOK ROUTER (Gateway)                              │
│                                                                              │
│   POST /webhook/discord   POST /webhook/slack   POST /webhook/github        │
│   POST /webhook/gmail     GET /health                                        │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Message Normalizer                                │ │
│   │   Platform event → UnifiedMessage { source, content, author, channel } │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      ▼                                       │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                       Routing Decision                                 │ │
│   │                                                                        │ │
│   │   IF @AgentName mentioned:                                             │ │
│   │       → Route DIRECTLY to that agent (skip broadcast)                  │ │
│   │                                                                        │ │
│   │   ELSE (no agent mentioned):                                           │ │
│   │       → BROADCAST to ALL agents                                        │ │
│   │       → Each agent decides: "Should I take this?"                      │ │
│   │                                                                        │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT REST API                                      │
│                                                                              │
│   POST /api/v1/team/broadcast    - Send to ALL agents (they self-select)    │
│   POST /api/v1/agent/{role}/run  - Direct message to SPECIFIC agent         │
│   GET  /api/v1/team/channel      - Get shared channel history               │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Agent Pool (5 Agents)                             │ │
│   │                                                                        │ │
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │ │
│   │   │  Software   │  │  Release    │  │  Support    │                   │ │
│   │   │  Engineer   │  │  Engineer   │  │  Engineer   │                   │ │
│   │   └─────────────┘  └─────────────┘  └─────────────┘                   │ │
│   │                                                                        │ │
│   │   ┌─────────────┐  ┌─────────────┐                                    │ │
│   │   │  Product    │  │  Marketing  │    Framework: AutoGen | CrewAI |   │ │
│   │   │  Manager    │  │  Manager    │    OpenHands | OpenCode            │ │
│   │   └─────────────┘  └─────────────┘                                    │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Message Routing Logic

### Case 1: Direct Mention (Route to Specific Agent)

```
User: "@SoftwareEngineer fix the login bug"
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ Router detects: @SoftwareEngineer mentioned                   │
│                                                               │
│ Action: POST /api/v1/agent/software_engineer/run              │
│         (Direct route, no broadcast)                          │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
SoftwareEngineer receives and processes immediately
```

### Case 2: No Mention (Broadcast to All)

```
User: "The API is returning 404 errors, 500 users affected"
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ Router detects: No agent mentioned                            │
│                                                               │
│ Action: POST /api/v1/team/broadcast                           │
│         (All agents receive simultaneously)                   │
└──────────────────────────────────────────────────────────────┘
       │
       ├───────────────────┬───────────────────┬─────────────────┐
       ▼                   ▼                   ▼                 ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐   ┌─────────────┐
│ SWE decides │     │ Release     │     │ Support     │   │ PM decides  │
│ "Not code"  │     │ decides     │     │ decides     │   │ "Not feat"  │
│ → PASS      │     │ "Infra!"    │     │ "Customer!" │   │ → PASS      │
│             │     │ → CLAIM     │     │ → CLAIM     │   │             │
└─────────────┘     └─────────────┘     └─────────────┘   └─────────────┘
                           │                   │
                           ▼                   ▼
                    Both work on their aspects of the problem
```

### Case 3: Agent-to-Agent Handoff

```
SoftwareEngineer: "Fixed in PR #457. @ReleaseEngineer ready for staging"
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ Router detects: @ReleaseEngineer in agent response            │
│                                                               │
│ Action: POST /api/v1/agent/release_engineer/run               │
│         Context: { previous_agent: "software_engineer",       │
│                    pr_number: 457, action: "deploy" }         │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
ReleaseEngineer receives with full context
```

## Agent Frameworks

VibeTeam supports 4 agent frameworks, selectable per-agent or globally:

| Framework | Package | Strengths |
|-----------|---------|-----------|
| **AutoGen** | `agents/autogen/` | Multi-agent orchestration, async tools |
| **CrewAI** | `agents/crewai/` | Role-based agents, native function calling |
| **OpenHands** | `agents/openhands/` | Coding sandbox, file editing |
| **OpenCode** | `agents/opencode/` | Long-running sessions, IDE-like |

### Framework Selection

```bash
# Environment variable
export AGENT_FRAMEWORK=crewai  # or autogen, openhands, opencode

# CLI argument
python scripts/run_discord_agent.py --framework openhands
```

## Responsibility Detection

When a message is broadcast (no direct @mention), each agent uses `ResponsibilityDetector`:

```python
class ResponsibilityDetector:
    ROLE_KEYWORDS = {
        "software_engineer": ["bug", "fix", "implement", "code", "PR", "test"],
        "release_engineer": ["deploy", "release", "k8s", "staging", "production"],
        "support_engineer": ["customer", "error", "sentry", "email", "support"],
        "product_manager": ["feature", "requirement", "backlog", "prioritize"],
        "marketing_manager": ["announce", "social", "post", "content", "launch"],
    }
    
    def should_claim(self, message: str, role: str) -> ResponsibilityClaim:
        # Keyword matching with threshold
        score = self._keyword_score(message, role)
        
        if score >= 0.5:  # At least 1 keyword match
            return ResponsibilityClaim(
                should_claim=True,
                confidence=score,
                reasoning=f"Matched keywords for {role}"
            )
        
        return ResponsibilityClaim(should_claim=False, confidence=score)
```

**Key Points:**
- Multiple agents CAN claim the same broadcast message
- Each agent works on their aspect (Support handles customer, Release handles infra)
- Agents coordinate via shared channel with @mentions

## Discord Integration

### Role-Based Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Discord Server: VibeTeam                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Roles (mentionable, assigned to bot):                          │
│    @SoftwareEngineer  ─┐                                        │
│    @ReleaseEngineer   ─┼─► Single bot listens for all roles     │
│    @SupportEngineer   ─┤                                        │
│    @ProductManager    ─┤                                        │
│    @MarketingManager  ─┘                                        │
│                                                                  │
│  Webhooks (distinct agent identity):                            │
│    webhook_swe      → Posts as "SoftwareEngineer"               │
│    webhook_release  → Posts as "ReleaseEngineer"                │
│    webhook_support  → Posts as "SupportEngineer"                │
│    webhook_pm       → Posts as "ProductManager"                 │
│    webhook_marketing→ Posts as "MarketingManager"               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Sentry Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                      Sentry → SupportEngineer                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Sentry detects error spike                                  │
│     └─► Webhook to /webhook/sentry                              │
│                                                                  │
│  2. Router: No agent mentioned → BROADCAST                      │
│                                                                  │
│  3. Agents evaluate:                                            │
│     - SupportEngineer: "error" keyword → CLAIM                  │
│     - SoftwareEngineer: might claim if code-related error       │
│                                                                  │
│  4. SupportEngineer investigates, may handoff:                  │
│     "@SoftwareEngineer this is a bug in auth.py:45"             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Session Persistence

Sessions are stored in PostgreSQL for conversation continuity:

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    key VARCHAR(255) UNIQUE,      -- "crewai:swe:slack:C123"
    framework VARCHAR(50),
    role VARCHAR(50),
    context_type VARCHAR(50),     -- slack, discord, issue, pr
    context_id VARCHAR(255),
    messages JSONB,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

## Testing

### E2E Evaluation Tests

```bash
# All frameworks, all scenarios
pytest tests/e2e/test_team_eval.py -v -s

# Specific framework
pytest tests/e2e/test_team_eval.py -v -s -k "crewai"
```

### Evaluation Metrics (DeepEval)

| Metric | Threshold | Description |
|--------|-----------|-------------|
| TeamCoordination | 0.7 | Agent collaboration quality |
| ResponsibilityDetection | 0.7 | Correct task ownership |
| HandoffQuality | 0.7 | Context preservation |
| TaskCompletion | 0.7 | Request fully addressed |
