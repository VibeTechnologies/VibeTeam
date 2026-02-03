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
│                            GATEWAY (FastAPI)                                 │
│                                                                              │
│   POST /webhook/discord   POST /webhook/slack   POST /webhook/github        │
│   POST /webhook/gmail     GET /health                                        │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Message Router                                 │ │
│   │                                                                        │ │
│   │  1. Normalize event → UnifiedMessage                                   │ │
│   │  2. Check for @VibeTeam mention → track thread                        │ │
│   │  3. Parse /RoleName mentions → subscribe agents                       │ │
│   │  4. React with :eyes: emoji                                           │ │
│   │  5. Forward to subscribed agents                                      │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT SERVICE (FastAPI)                             │
│                                                                              │
│   POST /run              - Run agent with message context                    │
│   GET  /sessions/{id}    - Get session details                              │
│   GET  /health           - Health check                                      │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Session Manager                                   │ │
│   │                                                                        │ │
│   │  - Get/create session by (source, thread_id, role)                    │ │
│   │  - Manage persistent workspaces (7-day TTL)                           │ │
│   │  - Inject pre-configured send_message tool                            │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                      Agent Pool (OpenHands)                            │ │
│   │                                                                        │ │
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │ │
│   │   │  Software   │  │  Release    │  │  Support    │                   │ │
│   │   │  Engineer   │  │  Engineer   │  │  Engineer   │                   │ │
│   │   └─────────────┘  └─────────────┘  └─────────────┘                   │ │
│   │                                                                        │ │
│   │   ┌─────────────┐  ┌─────────────┐                                    │ │
│   │   │  Product    │  │  Marketing  │                                    │ │
│   │   │  Manager    │  │  Manager    │                                    │ │
│   │   └─────────────┘  └─────────────┘                                    │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Message Router

### Thread Subscription Model

The router maintains a table of which agents are subscribed to which threads:

```python
@dataclass
class ThreadSubscription:
    source: str          # slack, discord, github_issue, github_pr
    thread_id: str       # unique identifier for the thread
    agent_role: str      # software_engineer, release_engineer, etc.
    session_id: str      # UUID linking to agent session
    subscribed_at: datetime
```

### Routing Logic

```python
class Router:
    ROLE_PATTERN = re.compile(
        r'/(SoftwareEngineer|ReleaseEngineer|SupportEngineer|ProductManager|MarketingManager)',
        re.IGNORECASE
    )
    
    async def route_message(self, message: UnifiedMessage) -> list[str]:
        """Route message to appropriate agents."""
        
        # 1. Parse /RoleName mentions
        role_mentions = self.ROLE_PATTERN.findall(message.content)
        roles = [self._normalize_role(r) for r in role_mentions]
        
        # 2. Subscribe new agents to thread
        for role in roles:
            await self.subscribe_agent(
                source=message.source,
                thread_id=message.thread_id,
                agent_role=role
            )
        
        # 3. Get all subscribed agents
        subscribed = await self.get_subscribed_agents(
            source=message.source,
            thread_id=message.thread_id
        )
        
        # 4. Forward to each subscribed agent
        for agent_role in subscribed:
            await self.forward_to_agent(message, agent_role)
        
        return subscribed
```

### Bot Message Handling

The router processes the bot's own messages to detect handoffs:

```python
async def handle_slack_event(event: dict):
    # Don't ignore bot messages - we need to detect handoffs
    if event.get("bot_id") == OUR_BOT_ID:
        text = event.get("text", "")
        
        # Check for /RoleName mentions (handoff)
        role_mentions = ROLE_PATTERN.findall(text)
        if role_mentions:
            # This is a handoff - subscribe mentioned agents
            for role in role_mentions:
                await router.subscribe_agent(source, thread_id, role)
                await forward_to_agent(message, role)
        
        return  # Don't process further
    
    # Process user messages normally
    await router.route_message(message)
```

## Agent Service

### Session Management

Each agent maintains a session per thread:

```python
class SessionManager:
    async def get_or_create_session(
        self,
        source: str,
        thread_id: str,
        role: str,
    ) -> AgentSession:
        """Get existing session or create new one."""
        
        session_key = f"openhands:{role}:{source}:{thread_id}"
        
        # Check for existing session
        existing = await self.db.get_session(session_key)
        if existing:
            return existing
        
        # Create new session with persistent workspace
        workspace = self._create_workspace(session_key)
        session_id = str(uuid.uuid4())
        
        session = AgentSession(
            session_id=session_id,
            key=session_key,
            framework="openhands",
            role=role,
            source=source,
            thread_id=thread_id,
            workspace=workspace,
            messages=[],
            created_at=datetime.now(timezone.utc),
        )
        
        await self.db.save_session(session)
        return session
```

### Workspace Management

Agent workspaces are persistent directories with automatic cleanup:

```python
class WorkspaceManager:
    BASE_PATH = "/var/lib/vibeteam/workspaces"
    TTL_DAYS = 7
    
    def create_workspace(self, session_key: str) -> str:
        """Create persistent workspace directory."""
        # Hash session key for safe directory name
        dir_name = hashlib.sha256(session_key.encode()).hexdigest()[:16]
        path = os.path.join(self.BASE_PATH, dir_name)
        os.makedirs(path, exist_ok=True)
        return path
    
    async def cleanup_expired(self):
        """Remove workspaces older than TTL."""
        cutoff = datetime.now() - timedelta(days=self.TTL_DAYS)
        # Query sessions older than cutoff and remove their workspaces
        ...
```

### send_message Tool

The `send_message` tool is pre-configured with thread context:

```python
class SendMessageTool:
    """Tool for agents to send messages to the thread."""
    
    def __init__(
        self,
        source: str,
        thread_id: str,
        channel_id: str,
        bot_token: str,
        role_prefix: str,
    ):
        self.source = source
        self.thread_id = thread_id
        self.channel_id = channel_id
        self.bot_token = bot_token
        self.role_prefix = role_prefix
    
    async def execute(self, content: str) -> dict:
        """Send message to the thread."""
        # Prefix with role name
        prefixed = f"[{self.role_prefix}] {content}"
        
        if self.source == "slack":
            await self._send_slack(prefixed)
        elif self.source == "discord":
            await self._send_discord(prefixed)
        
        return {"success": True, "message": prefixed}
```

## Discord Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                    Discord Server: VibeTeam                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Bot: @VibeTeam                                                 │
│    - Single bot handles all agent roles                         │
│    - Responds with [RoleName] prefix                            │
│    - Reacts with :eyes: when message received                   │
│                                                                  │
│  Message Format:                                                 │
│    User: "@VibeTeam /SoftwareEngineer fix the login bug"        │
│    Bot:  "[SoftwareEngineer] I'll look into the login bug..."   │
│    Bot:  "[SoftwareEngineer] Fixed in PR #457.                  │
│           /ReleaseEngineer ready for staging."                  │
│    Bot:  "[ReleaseEngineer] Deploying to staging now..."        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Slack Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                    Slack Workspace: VibeTeam                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  App: @VibeTeam                                                 │
│    - Single app handles all agent roles                         │
│    - Responds in threads with [RoleName] prefix                 │
│    - Reacts with :eyes: when message received                   │
│                                                                  │
│  Events subscribed:                                              │
│    - app_mention (when @VibeTeam is mentioned)                  │
│    - message.channels (for thread replies)                      │
│                                                                  │
│  Thread Example:                                                 │
│    User: "@VibeTeam /SoftwareEngineer fix bug #345"             │
│    :eyes: (reaction)                                            │
│    Bot:  "[SoftwareEngineer] Looking at issue #345..."          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## GitHub Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                      GitHub → Agents                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Issue Comment: "@VibeTeam /SoftwareEngineer please investigate" │
│       │                                                          │
│       ▼                                                          │
│  Router:                                                         │
│    source = "github_issue"                                       │
│    thread_id = "VibeTechnologies/VibeWebAgent:345"              │
│    role = "software_engineer"                                    │
│       │                                                          │
│       ▼                                                          │
│  Agent responds via GitHub API comment                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Sentry Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                      Sentry → Agents                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Sentry detects error spike                                  │
│     └─► Webhook to /webhook/sentry                              │
│                                                                  │
│  2. Router creates synthetic thread:                            │
│     source = "sentry"                                            │
│     thread_id = "sentry:{issue_id}"                             │
│     Auto-routes to /SupportEngineer                             │
│                                                                  │
│  3. SupportEngineer investigates, may handoff:                  │
│     "/SoftwareEngineer this is a bug in auth.py:45"             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Database Schema

```sql
-- Agent sessions
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(255) UNIQUE NOT NULL,
    framework VARCHAR(50) NOT NULL,
    role VARCHAR(50) NOT NULL,
    source VARCHAR(50) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    workspace VARCHAR(500),
    messages JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Thread subscriptions
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    agent_role VARCHAR(50) NOT NULL,
    session_id UUID REFERENCES sessions(id),
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);

-- Index for fast lookups
CREATE INDEX idx_subscriptions_thread ON thread_subscriptions(source, thread_id);
CREATE INDEX idx_sessions_key ON sessions(key);
```

## Testing

### E2E Evaluation Tests

```bash
# All scenarios
pytest tests/e2e/test_team_eval.py -v -s

# Slack routing tests
pytest tests/e2e/test_slack_routing.py -v -s

# Discord routing tests
pytest tests/e2e/test_discord_routing.py -v -s
```

### Evaluation Metrics (DeepEval)

| Metric | Threshold | Description |
|--------|-----------|-------------|
| TaskCompletion | 0.7 | Request fully addressed |
| HandoffQuality | 0.7 | Context preservation |
| ResponseTime | < 60s | Time to first response |


# DeepEval test design

┌─────────────────────────────────────────────────────────────────────────────┐
│                           E2E TEST FLOW                                     │
└─────────────────────────────────────────────────────────────────────────────┘
Step 1: Test posts initial message to Slack
┌──────────┐         ┌─────────────────┐
│  pytest  │ ──────► │  Slack API      │  POST /SupportEngineer, issue...
└──────────┘         │  #channel       │
                     │  thread_ts: X   │
                     └────────┬────────┘
                              │
Step 2: Webhook picks up message
                              ▼
                     ┌─────────────────┐
                     │ Slack Webhook   │  (K8s microservice)
                     │ Microservice    │
                     └────────┬────────┘
                              │ routes /SupportEngineer
                              ▼
Step 3: Agent service processes
                     ┌─────────────────┐
                     │ OpenHands Agent │  (K8s service)
                     │ Service         │
                     │                 │  - Checks PostgreSQL for session
                     │ /SupportEngineer│  - No session for thread_ts X
                     │                 │  - Creates new session
                     └────────┬────────┘
                              │
Step 4: Agent responds via send_message tool
                              │ Tool pre-initialized with:
                              │   - thread_ts: X
                              │   - slack_token
                              ▼
                     ┌─────────────────┐
                     │  Slack API      │  "Handing off to /ReleaseEngineer..."
                     │  thread_ts: X   │
                     └────────┬────────┘
                              │
Step 5: Webhook picks up handoff
                              ▼
                     ┌─────────────────┐
                     │ Slack Webhook   │  routes /ReleaseEngineer
                     │ Microservice    │
                     └────────┬────────┘
                              │
Step 6: Release Engineer processes
                              ▼
                     ┌─────────────────┐
                     │ OpenHands Agent │
                     │ /ReleaseEngineer│  - Same thread, new/existing session
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  Slack API      │  "Investigated, found X..."
                     │  thread_ts: X   │
                     └────────┬────────┘
                              │
Step 7: Test reads thread, evaluates
                              ▼
┌──────────┐         ┌─────────────────┐
│  pytest  │ ◄────── │  Slack API      │  GET thread messages
│          │         │  thread_ts: X   │
│ DeepEval │         └─────────────────┘
│ evaluate │
│          │
│ ASSERT   │  - Thread has N messages
│          │  - HandoffQuality score
│          │  - TaskCompletion score
└──────────┘