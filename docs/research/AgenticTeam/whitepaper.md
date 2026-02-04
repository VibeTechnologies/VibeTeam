# Natural Coordination in Multi-Agent Teams: A Thread-Based Subscription Model for Autonomous Collaboration

**A Technical Whitepaper on Agentic Team Architecture**

*VibeTeam Research*  
*Version 1.0 - February 2025*

---

## Abstract

This whitepaper presents a novel approach to multi-agent AI coordination that mirrors natural human team communication patterns. We introduce the **Thread-Based Subscription Model** (TBSM), a paradigm where AI agents collaborate through existing team messaging platforms (Slack, Discord) using natural language mentions and context-aware handoffs. Unlike traditional multi-agent orchestration systems that rely on centralized schedulers or rigid workflows, our approach enables emergent coordination through simple `/RoleName` mention patterns, persistent thread subscriptions, and transparent human-in-the-loop visibility.

We present the VibeTeam system architecture, which implements five specialized agents (SoftwareEngineer, ReleaseEngineer, SupportEngineer, ProductManager, MarketingManager) that autonomously delegate tasks, preserve context across handoffs, and complete complex multi-step operations. We evaluate agent performance using the DeepEval framework with G-Eval methodology, achieving measurable thresholds for task completion, handoff quality, and contextual preservation.

Our results demonstrate that natural language-based coordination in familiar communication channels reduces adoption friction, improves team visibility, and enables flexible agent collaboration without predetermined workflows.

---

## 1. Introduction

### 1.1 The Multi-Agent Coordination Challenge

The deployment of multiple AI agents in production environments presents a fundamental coordination challenge: how do independent agents with specialized capabilities work together on complex tasks that span multiple domains? Traditional approaches fall into two categories:

1. **Centralized Orchestration**: A master agent or scheduler directs all activities, creating bottlenecks and single points of failure.
2. **Predefined Workflows**: Static DAG-based workflows where agent interactions are predetermined, limiting adaptability.

Both approaches suffer from rigidity, opacity (agents communicate through internal channels invisible to human operators), and difficulty scaling to real-world complexity where tasks require dynamic collaboration.

### 1.2 Our Hypothesis: Natural Team Communication as Coordination Primitive

We hypothesize that **multi-agent AI teams can achieve effective coordination by adopting human team communication patterns** rather than implementing novel agent-specific protocols. Specifically:

> **Hypothesis**: AI agents communicating through thread-based messaging platforms using natural language mentions can autonomously coordinate complex tasks while maintaining full human visibility, achieving coordination quality comparable to centralized orchestration systems.

This hypothesis leads to three design principles:

1. **Communication Transparency**: All agent-to-agent communication occurs in visible channels (Slack threads, Discord channels) where humans can observe, intervene, or participate.

2. **Mention-Based Routing**: Agents invoke each other using the same `/RoleName` or `@RoleName` patterns humans use, creating intuitive handoff semantics.

3. **Thread Persistence**: Conversations maintain context through thread subscriptions, allowing agents to receive all subsequent messages after being mentioned, preserving conversational continuity.

### 1.3 Contributions

This whitepaper makes the following contributions:

- A formal model for **Thread-Based Subscription** in multi-agent systems
- The **VibeTeam architecture** implementing five specialized agents
- A **DeepEval-based evaluation framework** using G-Eval methodology for measuring agent team performance
- Empirical results demonstrating handoff quality and task completion across multi-agent scenarios

---

## 2. Related Work

### 2.1 Multi-Agent Orchestration Frameworks

Existing multi-agent frameworks such as AutoGen (Microsoft), CrewAI, and LangGraph provide orchestration primitives for agent collaboration. These systems typically implement:

- **Agent-to-Agent Messaging**: Structured message passing through code-level APIs
- **Workflow Definition**: YAML or code-based workflow specifications
- **Centralized State**: Shared memory or state stores for coordination

While effective for predetermined workflows, these approaches create opacity between agent activities and human operators, limiting practical deployment in team settings.

### 2.2 Tool-Augmented LLM Agents

OpenHands (formerly OpenDevin), OpenCode, and similar coding agents demonstrate the effectiveness of LLM-based agents with tool access for complex tasks. These systems provide:

- **Shell and Code Execution**: Agents can write and execute code
- **File System Access**: Reading, writing, and modifying files
- **External API Integration**: Connecting to services like GitHub, Sentry, etc.

Our work extends these capabilities by embedding tool-augmented agents within team communication platforms.

### 2.3 Human-AI Collaboration

Research on human-AI collaboration emphasizes the importance of transparency, controllability, and appropriate trust calibration. Studies show that AI systems operating through familiar interfaces (email, chat) achieve higher adoption rates than specialized interfaces.

---

## 3. Thread-Based Subscription Model

### 3.1 Formal Model

We define a **Thread-Based Subscription Model** (TBSM) with the following components:

**Definition 1 (Thread)**: A thread T is an ordered sequence of messages M = {m₁, m₂, ..., mₙ} with a unique identifier and associated metadata (channel, timestamp, parent message).

**Definition 2 (Subscription)**: A subscription S is a tuple (source, thread_id, agent_role, session_id) indicating that an agent of role R is subscribed to receive messages in thread T.

**Definition 3 (Mention)**: A mention is a pattern `/RoleName` or `@RoleName` within a message that triggers subscription of the mentioned agent to the thread.

**Definition 4 (Handoff)**: A handoff H occurs when agent A₁ posts a message containing a mention of agent A₂, causing A₂ to be subscribed to the thread and receive all subsequent messages.

The formal routing rules are:

```
R1: Thread Activation
    IF message M contains "@VibeTeam" THEN mark thread(M) as active

R2: Agent Subscription  
    IF message M in active thread contains "/RoleName" THEN
        subscribe(agent=RoleName, thread=thread(M))

R3: Persistent Subscription
    IF agent A is subscribed to thread T THEN
        A receives all subsequent messages in T

R4: Handoff Processing
    IF agent A₁ posts message M containing "/A₂" THEN
        execute R2 (subscribe A₂ to thread)
        forward M to A₂
```

### 3.2 Data Model

Thread subscriptions are persisted in a relational database:

```sql
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,        -- slack, discord, github_issue, github_pr
    thread_id VARCHAR(255) NOT NULL,    -- platform-specific thread identifier
    agent_role VARCHAR(50) NOT NULL,    -- software_engineer, release_engineer, etc.
    session_id UUID NOT NULL,           -- link to agent session
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
```

Session state is maintained per (thread, agent) tuple:

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,   -- openhands:{role}:{source}:{thread_id}
    framework VARCHAR(50) NOT NULL,     -- openhands, crewai, autogen
    role VARCHAR(50) NOT NULL,
    source VARCHAR(50) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    workspace VARCHAR(500),             -- persistent directory path
    messages JSONB DEFAULT '[]',        -- conversation history
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.3 Thread ID Formats

Different sources use different thread identification schemes:

| Source | Thread ID Format | Example |
|--------|------------------|---------|
| Slack | `{thread_ts}` | `1234567890.123456` |
| Discord | `{channel_id}:{message_id}` | `123456789:987654321` |
| GitHub Issue | `{repo}:{issue_number}` | `VibeTech/Repo:345` |
| GitHub PR | `{repo}:pr:{pr_number}` | `VibeTech/Repo:pr:123` |

---

## 4. VibeTeam System Architecture

### 4.1 Overview

VibeTeam implements TBSM through a microservices architecture deployed on Kubernetes:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              External Platforms                              │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│   │   Discord   │    │    Slack    │    │   GitHub    │    │   Sentry    │  │
│   │   Server    │    │  Workspace  │    │   Webhooks  │    │   Alerts    │  │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
└──────────┼──────────────────┼──────────────────┼──────────────────┼──────────┘
           │                  │                  │                  │
           ▼                  ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GATEWAY SERVICE                                   │
│                                                                              │
│   POST /webhook/discord   POST /webhook/slack   POST /webhook/github        │
│   POST /webhook/sentry    GET /health                                        │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Message Router                                 │ │
│   │  1. Normalize event → UnifiedMessage                                   │ │
│   │  2. Check for @VibeTeam mention → track thread                        │ │
│   │  3. Parse /RoleName mentions → subscribe agents                       │ │
│   │  4. React with :eyes: emoji (acknowledged)                            │ │
│   │  5. Forward to subscribed agents                                      │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT SERVICE                                       │
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
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │ │
│   │   │  Software   │  │  Release    │  │  Support    │                   │ │
│   │   │  Engineer   │  │  Engineer   │  │  Engineer   │                   │ │
│   │   └─────────────┘  └─────────────┘  └─────────────┘                   │ │
│   │   ┌─────────────┐  ┌─────────────┐                                    │ │
│   │   │  Product    │  │  Marketing  │                                    │ │
│   │   │  Manager    │  │  Manager    │                                    │ │
│   │   └─────────────┘  └─────────────┘                                    │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Agent Roles and Capabilities

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `/SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `/ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `/SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `/ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | `/MarketingManager` | Social media, announcements, content | Chrome DevTools MCP |

### 4.3 The send_message Tool

Every agent receives a pre-configured `send_message` tool that:

1. **Prefixes messages** with `[RoleName]` for identification
2. **Posts to the correct thread** using stored tokens
3. **Triggers routing** for any `/RoleName` mentions in the response

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

### 4.4 Message Flow Example

A complete handoff scenario:

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

---

## 5. Natural Agent Interaction Patterns

### 5.1 Mention-Based Addressing

Agents use the same addressing patterns humans use in team chat:

```
# Direct addressing
/SoftwareEngineer can you fix the bug in auth.py?

# Multiple addressing
/SoftwareEngineer /ReleaseEngineer we need a hotfix deployed

# Contextual handoff
I've identified the root cause. /ReleaseEngineer please rollback to v1.2.3
```

### 5.2 Context Preservation Across Handoffs

When Agent A hands off to Agent B, the entire thread context is available:

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

### 5.3 Bot Message Processing for Handoffs

The router processes its own messages to detect agent-initiated handoffs:

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

---

## 6. Evaluation Methodology

### 6.1 DeepEval with G-Eval

We evaluate agent performance using **DeepEval**, an open-source framework for LLM evaluation, with **G-Eval** methodology. G-Eval uses an LLM judge (Azure GPT-5.2 in our configuration) to assess output quality against specified criteria.

```python
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

evaluator_config = {
    "model": "azure/gpt-5.2",
    "api_key": os.environ["AZURE_API_KEY"],
    "api_base": os.environ["AZURE_API_BASE"],
    "api_version": "2024-12-01-preview",
}
```

### 6.2 Evaluation Metrics

| Metric | Threshold | Evaluation Criteria |
|--------|-----------|---------------------|
| **TaskCompletion** | 0.7 | Did the agent complete the requested task? Consider tool usage, output quality, and whether the user's intent was satisfied. |
| **HandoffQuality** | 0.7 | Was context preserved during handoff? Did the receiving agent understand the task without re-explanation? |
| **ResponseTime** | < 60s | Time from message receipt to first response. Measured via timestamps. |
| **Professionalism** | 0.7 | Clear, concise, professional communication. Appropriate tone for the audience. |
| **ToolUsage** | 0.7 | Did the agent use appropriate tools? Were tools called with correct parameters? |
| **ContextPreservation** | 0.7 | Does agent maintain conversation context across messages in a thread? |

### 6.3 Strict Metric Implementation

For rigorous evaluation, we implement strict criteria that penalize superficial responses:

```python
def create_investigation_quality_metric(model):
    """
    Strict metric: Did the agent ACTUALLY investigate the issue?
    
    This should FAIL if the agent just gives generic advice without:
    - Using tools to check Sentry/logs/metrics
    - Providing specific findings from investigation
    - Taking concrete action or making specific handoff
    """
    return GEval(
        name="InvestigationQuality",
        criteria=(
            "Did the SupportEngineer ACTUALLY investigate the reported issue using Sentry? "
            "A proper investigation MUST include: "
            "(1) Using Sentry tool to check error patterns, counts, and stack traces - "
            "not just saying they would check; "
            "(2) Reporting SPECIFIC findings from the investigation "
            "(error messages, affected endpoints, timestamps); "
            "(3) Either resolving the issue OR handing off to ReleaseEngineer/SoftwareEngineer "
            "with specific technical details. "
            "A generic 'triage checklist' or 'here's what I would do' response is a FAILURE - "
            "the agent must actually DO the investigation with Sentry, not describe how to do it."
        ),
        evaluation_steps=[
            "Check if the agent used Sentry tool to check errors",
            "Verify the agent reported SPECIFIC findings",
            "Check if the response contains actual investigation results vs generic advice",
            "If no specific findings from Sentry, score should be LOW (< 0.5)",
            "A checklist or process description without actual execution should score < 0.3",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.70,
        model=model,
    )
```

### 6.4 Test Scenarios

| Test File | Scenario | Agents Tested | Key Metrics |
|-----------|----------|---------------|-------------|
| `test_slack_routing.py` | Slack message → agent response | All agents | TaskCompletion, ResponseTime |
| `test_discord_routing.py` | Discord message → agent response | All agents | TaskCompletion, ResponseTime |
| `test_github_routing.py` | GitHub issue comment → agent response | SWE, PM | TaskCompletion, Professionalism |
| `test_handoff_chain.py` | Multi-agent handoff chain | Support → Release → Support | HandoffQuality, ContextPreservation |
| `test_sentry_alert.py` | Sentry error → investigation | Support, Release | TaskCompletion, ToolUsage |

### 6.5 Example E2E Test

```python
class TestHandoffChain:
    """Test multi-agent handoff scenarios with DeepEval."""
    
    @pytest.fixture
    def gpt52_evaluator(self):
        """GPT-5.2 evaluator configuration."""
        return {
            "model": "azure/gpt-5.2",
            "api_key": os.environ["AZURE_API_KEY"],
            "api_base": os.environ["AZURE_API_BASE"],
        }
    
    @pytest.mark.asyncio
    async def test_support_to_release_handoff(self, mock_slack, gpt52_evaluator):
        """
        Scenario: Customer reports outage, Support hands off to Release.
        
        Flow:
        1. User: @SupportEngineer customer reports GenAI Gateway down
        2. SupportEngineer: checks Gmail, responds, mentions @ReleaseEngineer
        3. ReleaseEngineer: investigates, reports status
        """
        # Arrange
        user_message = "Customer emailed that GenAI Gateway is returning 500 errors"
        
        # Act
        support_response = await run_agent("support_engineer", user_message)
        release_response = await run_agent("release_engineer", support_response)
        
        # Evaluate with DeepEval
        test_case = LLMTestCase(
            input=user_message,
            actual_output=f"{support_response}\n\n{release_response}",
            expected_output="Support checks email, identifies issue, hands off to Release",
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
        
        # Assert
        results = evaluate([test_case], [handoff_metric, task_metric])
        assert results.passed, f"Evaluation failed: {results.summary}"
```

### 6.6 Agent-Specific Thresholds

Different agents have different threshold requirements based on role:

| Agent | TaskCompletion | HandoffQuality | Professionalism |
|-------|----------------|----------------|-----------------|
| SoftwareEngineer | >= 0.75 | >= 0.70 | >= 0.70 |
| ReleaseEngineer | >= 0.75 | >= 0.70 | >= 0.70 |
| SupportEngineer | >= 0.80 | >= 0.75 | >= 0.80 |
| ProductManager | >= 0.70 | >= 0.70 | >= 0.80 |
| MarketingManager | >= 0.70 | >= 0.65 | >= 0.85 |

SupportEngineer has higher thresholds due to the customer-facing nature of the role.

---

## 7. End-to-End Evaluation Flow

### 7.1 Test Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           E2E TEST FLOW                                      │
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
                     │ Gateway Service │  (K8s microservice)
                     │                 │
                     └────────┬────────┘
                              │ routes /SupportEngineer
                              ▼
Step 3: Agent service processes
                     ┌─────────────────┐
                     │ Agent Service   │  (K8s service)
                     │                 │  - Creates session for thread_ts X
                     │ /SupportEngineer│  - Runs agent with tools
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
                     │ Gateway Service │  routes /ReleaseEngineer
                     └────────┬────────┘
                              │
Step 6: Release Engineer processes
                              ▼
                     ┌─────────────────┐
                     │ Agent Service   │
                     │ /ReleaseEngineer│  - Same thread, new session
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
```

### 7.2 Running Evaluations

```bash
# Install DeepEval
pip install deepeval>=0.21.0

# Set required environment variables
export AZURE_API_KEY="your-key"
export AZURE_API_BASE="https://your-endpoint.openai.azure.com"
export AZURE_API_VERSION="2024-12-01-preview"

# Run all E2E evaluation tests
pytest tests/e2e/ -v -s

# Run specific scenario
python scripts/eval_slack_e2e.py --scenario support_400_errors

# Generate evaluation report
python scripts/run_evaluation.py --output results/eval_report.json
```

### 7.3 CI/CD Integration

```yaml
name: Agent Evaluation

on:
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 6 * * *'  # Daily at 6 AM UTC

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run E2E Evaluation
        env:
          AZURE_API_KEY: ${{ secrets.AZURE_API_KEY }}
          AZURE_API_BASE: ${{ secrets.AZURE_API_BASE }}
        run: pytest tests/e2e/ -v --tb=short
      
      - name: Upload Results
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-results
          path: results/
```

---

## 8. Discussion

### 8.1 Advantages of TBSM

**Transparency**: All agent coordination is visible in team channels. Humans can:
- Observe agent reasoning and decisions
- Intervene when agents make mistakes
- Learn from agent behaviors
- Maintain audit trails

**Simplicity**: The mention-based routing requires no agent-specific protocol learning. Agents use the same patterns humans use.

**Flexibility**: Unlike rigid workflows, agents can dynamically involve other agents based on task requirements.

**Persistence**: Thread subscriptions ensure context is maintained across handoffs without explicit context passing.

### 8.2 Limitations

**Latency**: Message-based coordination adds latency compared to direct function calls between agents.

**Platform Dependency**: The system depends on external platforms (Slack, Discord) which may have rate limits or outages.

**Context Length**: Very long threads may exceed agent context windows, requiring summarization strategies.

### 8.3 Future Work

1. **Multi-Thread Coordination**: Agents coordinating across multiple threads simultaneously
2. **Proactive Agents**: Agents initiating threads based on monitoring (e.g., Sentry alerts)
3. **Learning from Feedback**: Incorporating human corrections into agent behavior
4. **Cross-Platform Threads**: Unifying conversations across Slack, Discord, and GitHub

---

## 9. Conclusion

We have presented the Thread-Based Subscription Model for multi-agent AI coordination, demonstrating that natural team communication patterns can serve as effective coordination primitives. The VibeTeam implementation shows that:

1. Agents can coordinate complex tasks through `/RoleName` mentions
2. Thread subscriptions preserve context across handoffs
3. Human visibility is maintained throughout agent interactions
4. G-Eval methodology provides rigorous evaluation of agent team performance

Our approach reduces the complexity of multi-agent orchestration while improving transparency and human controllability. The familiar Slack/Discord interface lowers adoption barriers and enables natural human-AI team collaboration.

---

## References

1. AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation (Microsoft Research, 2023)
2. CrewAI: Framework for orchestrating role-playing AI agents (https://www.crewai.com/)
3. OpenHands: An Open Platform for AI Software Developers (2024)
4. DeepEval: The Open-Source LLM Evaluation Framework (https://docs.confident-ai.com/)
5. G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment (Liu et al., 2023)
6. LangGraph: Building language agents as graphs (LangChain, 2024)

---

## Appendix A: Evaluation Scenario Definitions

```python
SCENARIOS = {
    "support_400_errors": {
        "name": "Support Engineer - API 400 Errors Investigation",
        "message": (
            "/SupportEngineer there is a request from a user who sees the issue with "
            "Vibe API Gateway returning 400 errors. Customer ACME Corp reports this "
            "started after the deployment at 8am. Multiple customers affected, about "
            "500 users. This seems infrastructure-related. Please investigate."
        ),
        "expected_agent": "support_engineer",
        "evaluation_criteria": {
            "InvestigationQuality": (
                "Did the SupportEngineer ACTUALLY investigate the issue using their tools? "
                "Score 0.0 if no investigation occurred. "
                "Score 1.0 if Sentry was used and specific findings were reported."
            ),
            "ActionableResolution": (
                "Did the SupportEngineer provide actionable next steps based on investigation? "
                "Score 1.0 if concrete findings and clear next steps provided."
            ),
        },
        "threshold": 0.70,
    },
    "github_issue": {
        "name": "Software Engineer - GitHub Issue Triage",
        "message": (
            "/SoftwareEngineer we have a new GitHub issue #42 reporting that the "
            "browser extension crashes when clicking the record button."
        ),
        "expected_agent": "software_engineer",
        "evaluation_criteria": {
            "IssueAnalysis": "Did the SoftwareEngineer analyze the GitHub issue properly?",
            "ActionablePlan": "Did the agent provide an actionable plan?",
        },
        "threshold": 0.70,
    },
}
```

---

## Appendix B: Test Harness Implementation

```python
class TeamTestHarness:
    """Test harness for running multi-agent scenarios."""

    AGENT_ROLES = [
        "software_engineer",
        "release_engineer",
        "support_engineer",
        "product_manager",
        "marketing_manager",
    ]

    def __init__(self, framework: str = "openhands"):
        self.framework = framework
        self.channel = SimulatedChannel(name="test-team-channel")
        self.agents = {}
        self._setup_agents()

    async def run_scenario(
        self,
        initial_message: str,
        timeout: float = 120.0,
        expected_agents: list[str] | None = None,
    ) -> ScenarioResult:
        """Run a test scenario and return results for evaluation."""
        start_time = time.perf_counter()
        self.channel.clear()

        # Create the initial user message
        initial_msg = ChannelMessage(
            id="msg_0001",
            author="user",
            content=initial_message,
            timestamp=datetime.now(timezone.utc),
            mentions=[],
            reply_to=None,
        )
        self.channel.messages.append(initial_msg)

        # Process message with each agent
        for role, agent in self.agents.items():
            should_respond = await agent.evaluate_message(initial_msg)
            if should_respond:
                response = await agent.generate_response(initial_msg)
                self.channel.post(author=role, content=response, reply_to=initial_msg.id)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        return ScenarioResult(
            framework=self.framework,
            channel=self.channel,
            initial_message=initial_message,
            agent_responses={role: self.channel.get_messages_by_author(role) 
                           for role in self.agents.keys()},
            elapsed_ms=elapsed_ms,
            expected_agents=expected_agents or [],
        )
```

---

*End of Whitepaper*
