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

## Structured Agent Decisions

Based on research from multi-agent systems (OpenAI Swarm, AutoGen, CrewAI, and academic
papers like TS-Debate and CodeDelegator), VibeTeam uses a **hybrid approach**:

- **Structured Output (JSON Schema)**: For claim detection and routing decisions
- **Tool Calls**: For discrete actions (handoffs, external API calls)

### Phase 1: Claim Detection

Each agent evaluates incoming messages using structured output:

```python
from pydantic import BaseModel
from typing import Literal, Optional, List

class ClaimDecision(BaseModel):
    """Produced by each agent when evaluating a broadcast message."""
    
    # Core decision
    should_claim: bool                    # Take ownership of this task?
    confidence: float                     # 0.0 to 1.0
    
    # Reasoning (for observability)
    relevance_signals: List[str]          # ["mentions error", "customer issue"]
    reasoning: str                        # Brief explanation
    
    # Collaboration support
    can_assist: bool                      # Can help even if not claiming?
    assistance_type: Optional[str]        # "research", "review", "execute"
    
    # Effort estimation
    estimated_effort: Literal["trivial", "moderate", "complex"]
```

### Phase 2: Response Decision

After claiming, agents decide how to respond:

```python
class AgentResponse(BaseModel):
    """Structured response from an agent."""
    
    response_type: Literal["respond", "handoff", "ignore", "escalate"]
    
    # Content (for respond/handoff)
    content: Optional[str]                # The message to send
    
    # Handoff details
    handoff_to: Optional[str]             # Agent role to hand off to
    handoff_context: Optional[str]        # Context for receiving agent
    
    # Actions taken
    actions_taken: List[str]              # ["created_issue", "sent_email"]
    
    # For escalation
    escalation_reason: Optional[str]      # Why human needed
```

### Phase 3: Arbitration

When multiple agents claim a message, the arbitrator resolves:

```python
def resolve_claims(claims: List[ClaimDecision]) -> ArbitrationResult:
    """Determine which agents should act."""
    
    claimers = [c for c in claims if c.should_claim]
    
    # Case 1: Single high-confidence claim
    high_conf = [c for c in claimers if c.confidence > 0.8]
    if len(high_conf) == 1:
        return ArbitrationResult(
            primary=high_conf[0].agent_id,
            assistants=[],
            mode="single"
        )
    
    # Case 2: Multiple claims - collaborative mode
    if len(claimers) > 1:
        primary = max(claimers, key=lambda c: c.confidence)
        assistants = [c for c in claims if c.can_assist and c != primary]
        return ArbitrationResult(
            primary=primary.agent_id,
            assistants=[a.agent_id for a in assistants],
            mode="collaborative"
        )
    
    # Case 3: No claims - escalate
    return ArbitrationResult(
        primary=None,
        assistants=[],
        mode="escalate_to_human"
    )
```

### Why Structured Output vs Tool Calls?

| Use Case | Mechanism | Rationale |
|----------|-----------|-----------|
| Claim detection | Structured Output | Need reasoning + confidence alongside decision |
| Handoffs | Tool Calls | Clear action semantics, explicit control transfer |
| External APIs | Tool Calls | Native support, automatic validation |
| Response formatting | Structured Output | Flexible schema, includes metadata |

**Academic Support:**
- OpenAI Swarm uses function returns for handoffs (explicit, traceable)
- TS-Debate paper: "verification-conflict-calibration mechanism" for multi-agent claims
- CodeDelegator: Clean context isolation between Delegator and Coder roles

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
