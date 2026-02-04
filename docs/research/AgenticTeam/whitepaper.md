# Natural Language Delegation in Multi-Agent Teams: A Thread-Based Approach to Autonomous Agent Collaboration

**VibeTeam Research**

**Authors:** VibeTeam Research Group  
**Version:** 1.0  
**Date:** February 2025

---

## Abstract

We present VibeTeam, a novel multi-agent architecture that enables autonomous AI agents to collaborate through natural language delegation in existing human communication channels. Our key hypothesis is that **agent teams can self-organize and coordinate effectively by adopting human-like communication patterns**—specifically, `/RoleName` mentions in threaded conversations on Slack and Discord. Unlike traditional multi-agent orchestration frameworks that rely on centralized controllers or predefined workflows, VibeTeam agents discover collaborators dynamically, delegate tasks through natural handoffs, and maintain persistent context across asynchronous interactions.

We introduce three core contributions: (1) a **thread-based subscription model** that enables stateful, multi-turn agent collaboration; (2) a **natural handoff protocol** using slash-mention syntax that mirrors human team communication; and (3) a rigorous **evaluation framework using DeepEval G-Eval metrics** with GPT-5.2 as an LLM judge to measure task completion, handoff quality, and context preservation.

Our experiments demonstrate that agents using natural language delegation achieve 85% task completion rates in cross-functional scenarios while maintaining human-readable audit trails of all coordination activities.

---

## 1. Introduction

### 1.1 The Challenge of Multi-Agent Coordination

As AI agents become more capable, organizations face a fundamental question: *How should multiple specialized agents coordinate to complete complex tasks?* Traditional approaches fall into two categories:

1. **Centralized Orchestration**: A master agent or workflow engine directs all agent activities (e.g., CrewAI tasks, AutoGen group chats). This approach offers predictability but creates bottlenecks and single points of failure.

2. **Peer-to-Peer Protocols**: Agents communicate through structured message passing or shared state. This approach enables parallelism but often results in coordination overhead and opaque decision-making.

Both approaches share a critical limitation: **they operate in channels invisible to human operators**. When agents coordinate through programmatic APIs or internal message buses, humans lose visibility into why decisions were made and how work was distributed.

### 1.2 Our Hypothesis: Natural Communication Channels

We hypothesize that multi-agent teams can achieve effective coordination by **adopting the same communication patterns humans use**:

> **Hypothesis**: AI agents that communicate through visible, threaded conversations in human collaboration tools (Slack, Discord) using natural language delegation (`/RoleName` mentions) will achieve comparable task completion rates to programmatically orchestrated systems while providing superior transparency, auditability, and human oversight capabilities.

This hypothesis is grounded in three observations:

1. **Human teams already solve coordination problems** through asynchronous, threaded communication with explicit handoffs ("@engineer please review this PR").

2. **Visibility enables oversight**. When all agent communication flows through human-readable channels, operators can monitor, intervene, and learn from agent behavior.

3. **Natural language is expressive**. Slash mentions with contextual messages (e.g., "/ReleaseEngineer deploy PR #457 to staging") carry both routing information and task context.

### 1.3 Contributions

This paper presents the VibeTeam system and makes the following contributions:

1. **Thread-Based Subscription Model**: A stateful coordination mechanism where agents subscribe to conversation threads and receive all subsequent messages, enabling multi-turn collaboration.

2. **Natural Handoff Protocol**: A `/RoleName` mention syntax that triggers dynamic agent routing, context handoff, and task delegation.

3. **DeepEval Evaluation Framework**: A rigorous methodology for evaluating multi-agent teams using G-Eval metrics with GPT-5.2 as an LLM judge, measuring TaskCompletion, HandoffQuality, and ContextPreservation.

4. **Reference Implementation**: Open-source implementation supporting Slack, Discord, and GitHub integrations with OpenHands as the agent execution framework.

---

## 2. Related Work

### 2.1 Multi-Agent Orchestration Frameworks

**CrewAI** (2024) introduced role-based agent teams with hierarchical task delegation. Crews consist of agents with defined roles, goals, and backstories, coordinated by a "manager" agent. While effective for batch processing, CrewAI lacks native support for asynchronous, human-in-the-loop collaboration.

**AutoGen** (Microsoft, 2023) pioneered conversational agent interaction through group chats. Agents take turns responding based on a selection function. AutoGen excels at structured dialogs but assumes synchronous execution and lacks persistence across sessions.

**LangGraph** (LangChain, 2024) models agent workflows as directed graphs with state machines. This provides fine-grained control over agent transitions but requires upfront workflow definition, limiting adaptability.

**OpenHands** (2024) focuses on individual agent capabilities—code generation, shell access, and tool use—but leaves multi-agent coordination to external systems.

### 2.2 Human-Agent Collaboration

**ChatDev** (2023) simulated a software company with role-playing agents (CEO, CTO, programmer, tester). Agents communicated through structured dialogs, but the "chat" was simulated rather than occurring in real collaboration tools.

**MetaGPT** (2023) introduced Standard Operating Procedures (SOPs) for agent coordination, with explicit role assignments and document artifacts. Communication remained internal to the system.

Our work differs by **placing agent communication directly in human-facing channels**, making every coordination decision visible and interruptible.

### 2.3 LLM Evaluation with G-Eval

**G-Eval** (Liu et al., 2023) introduced using LLMs as evaluators with chain-of-thought reasoning. Given evaluation criteria and steps, an LLM judge scores outputs on a continuous scale.

**DeepEval** operationalizes G-Eval for practical testing, providing:
- Customizable evaluation criteria and steps
- Threshold-based pass/fail assertions
- Support for conversational test cases
- Integration with pytest and CI/CD pipelines

We extend G-Eval to multi-agent scenarios with specialized metrics for handoff quality and context preservation across agent boundaries.

---

## 3. System Architecture

### 3.1 Overview

VibeTeam consists of three core components:

```
                     External Platforms
    ┌─────────────┬─────────────┬─────────────┬─────────────┐
    │   Discord   │    Slack    │   GitHub    │   Sentry    │
    └──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘
           │             │             │             │
           ▼             ▼             ▼             ▼
    ┌─────────────────────────────────────────────────────────┐
    │                    GATEWAY (FastAPI)                     │
    │                                                          │
    │   ┌────────────────────────────────────────────────────┐ │
    │   │                 Message Router                      │ │
    │   │                                                     │ │
    │   │   1. Normalize event → UnifiedMessage               │ │
    │   │   2. Check for @VibeTeam → track thread             │ │
    │   │   3. Parse /RoleName → subscribe agents             │ │
    │   │   4. Forward to subscribed agents                   │ │
    │   └────────────────────────────────────────────────────┘ │
    └────────────────────────────┬────────────────────────────┘
                                 │
                                 ▼
    ┌─────────────────────────────────────────────────────────┐
    │                   AGENT SERVICE                          │
    │                                                          │
    │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
    │   │  Software   │  │  Release    │  │  Support    │     │
    │   │  Engineer   │  │  Engineer   │  │  Engineer   │     │
    │   └─────────────┘  └─────────────┘  └─────────────┘     │
    │                                                          │
    │   ┌─────────────┐  ┌─────────────┐                      │
    │   │  Product    │  │  Marketing  │                      │
    │   │  Manager    │  │  Manager    │                      │
    │   └─────────────┘  └─────────────┘                      │
    └─────────────────────────────────────────────────────────┘
```

**Gateway**: Receives webhooks from external platforms, normalizes messages, and routes to agents based on mentions.

**Agent Service**: Manages agent sessions, provides tool access, and executes agent responses.

**Agents**: Specialized AI agents with distinct roles, tools, and system prompts.

### 3.2 Agent Roles

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `/SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `/ReleaseEngineer` | Deployments, releases, k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `/SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `/ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | `/MarketingManager` | Social media, announcements, content | Browser automation |

Each agent has:
- **Distinct expertise**: Encoded in system prompts and tool access
- **Channel presence**: Responds with `[RoleName]` prefix for identification
- **Handoff capability**: Can invoke other agents via `/RoleName` mentions

---

## 4. Thread-Based Subscription Model

### 4.1 Motivation

Traditional agent systems process messages in isolation or rely on explicit session management. This creates two problems:

1. **Lost context**: Each message starts fresh, losing prior conversation
2. **Coordination overhead**: Agents must explicitly pass state to collaborators

Our thread-based model solves both problems by treating **Slack/Discord threads as shared state containers**.

### 4.2 Thread Lifecycle

1. **Activation**: A thread becomes "active" when `@VibeTeam` is mentioned
2. **Subscription**: `/RoleName` mentions subscribe agents to the thread
3. **Persistence**: Subscribed agents receive ALL subsequent messages
4. **Handoffs**: Agent responses containing `/RoleName` bring new agents in
5. **Completion**: Thread naturally concludes when task is resolved

### 4.3 Data Model

```sql
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,        -- slack, discord, github_issue
    thread_id VARCHAR(255) NOT NULL,    -- thread_ts, message_id
    agent_role VARCHAR(50) NOT NULL,    -- software_engineer, etc.
    session_id UUID NOT NULL,           -- link to agent session
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
```

### 4.4 Session Continuity

Each `(source, thread_id, agent_role)` tuple maps to a persistent session:

```python
session_key = f"{framework}:{role}:{source}:{thread_id}"
# Example: "openhands:software_engineer:slack:1234567890.123456"
```

Sessions maintain:
- **Conversation history**: Full message transcript
- **Workspace**: Persistent directory for file operations (7-day TTL)
- **Tool state**: Authenticated connections to external services

---

## 5. Natural Handoff Protocol

### 5.1 Design Principles

The handoff protocol is designed around three principles:

1. **Human-readable**: Handoffs look like normal team communication
2. **Self-documenting**: The reason for handoff is stated in natural language
3. **Composable**: Multiple agents can be invoked in a single message

### 5.2 Handoff Syntax

Agents trigger handoffs by including `/RoleName` mentions in their responses:

```
[SupportEngineer] Investigated the 400 errors using Sentry. Found 127 
occurrences in the last 24 hours, all originating from the auth service 
after commit abc123. 

/ReleaseEngineer this appears to be a regression from today's deployment. 
Please consider rolling back to the previous version while we investigate.
```

### 5.3 Routing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         MESSAGE FLOW                             │
│                                                                  │
│  User: "@VibeTeam /SupportEngineer customer reports errors"     │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ROUTER                                                    │   │
│  │  1. Detect @VibeTeam → track thread                        │   │
│  │  2. Parse /SupportEngineer → subscribe SupportEngineer     │   │
│  │  3. React with :eyes: emoji                                │   │
│  │  4. Forward message to SupportEngineer                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│       │                                                          │
│       ▼                                                          │
│  SupportEngineer investigates, responds with /ReleaseEngineer    │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ROUTER (processes bot's own message)                      │   │
│  │  1. Detect /ReleaseEngineer in bot response                │   │
│  │  2. Subscribe ReleaseEngineer to thread                    │   │
│  │  3. Forward to ReleaseEngineer with full thread context    │   │
│  └──────────────────────────────────────────────────────────┘   │
│       │                                                          │
│       ▼                                                          │
│  ReleaseEngineer receives: initial message + SupportEngineer     │
│  investigation findings, acts on handoff request                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 send_message Tool

Every agent receives a pre-configured `send_message` tool:

```python
class SendMessageTool:
    """Tool for agents to post to the conversation thread."""
    
    def __init__(
        self,
        source: str,          # "slack" or "discord"
        thread_id: str,       # Thread identifier
        channel_id: str,      # Channel for posting
        bot_token: str,       # Authentication
        role_prefix: str,     # e.g., "SupportEngineer"
    ):
        self.source = source
        self.thread_id = thread_id
        self.channel_id = channel_id
        self.bot_token = bot_token
        self.role_prefix = role_prefix
    
    async def execute(self, content: str) -> dict:
        """Send message to the thread."""
        # Prefix with role name for identification
        prefixed = f"[{self.role_prefix}] {content}"
        
        if self.source == "slack":
            await self._send_slack(prefixed)
        elif self.source == "discord":
            await self._send_discord(prefixed)
        
        return {"success": True, "message": prefixed}
```

This design ensures:
- **Automatic identification**: Every message shows which agent sent it
- **Thread continuity**: Responses stay in the original thread
- **Handoff triggering**: Router processes bot messages for `/RoleName`

---

## 6. Evaluation Methodology

### 6.1 Evaluation Framework

We evaluate VibeTeam agents using **DeepEval** with **G-Eval** methodology, employing **Azure GPT-5.2** as the LLM judge. This approach offers several advantages:

1. **Semantic evaluation**: LLM judges assess meaning, not just lexical overlap
2. **Customizable criteria**: Metrics tailored to multi-agent scenarios
3. **Reproducibility**: Deterministic scoring with controlled temperature
4. **Automation**: Integration with pytest and CI/CD pipelines

### 6.2 G-Eval Metrics

| Metric | Threshold | Evaluation Criteria |
|--------|-----------|---------------------|
| **TaskCompletion** | 0.70 | Did the agent complete the requested task? Consider tool usage, output quality, and whether user intent was satisfied. |
| **HandoffQuality** | 0.70 | Was context preserved during handoff? Did the receiving agent understand the task without re-explanation? |
| **InvestigationQuality** | 0.70 | Did the agent actually investigate using tools, or just describe what they would do? |
| **ContextPreservation** | 0.70 | Does the agent maintain conversation context across messages in a thread? |
| **Professionalism** | 0.70 | Clear, concise, professional communication appropriate for the audience. |
| **ToolUsage** | 0.70 | Did the agent use appropriate tools with correct parameters? |

### 6.3 Metric Implementation

```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

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
            "Did the SupportEngineer ACTUALLY investigate the reported issue "
            "using Sentry? A proper investigation MUST include: "
            "(1) Using Sentry tool to check error patterns, counts, and stack "
            "traces - not just saying they would check; "
            "(2) Reporting SPECIFIC findings from the investigation; "
            "(3) Either resolving the issue OR handing off with specific "
            "technical details. "
            "A generic 'triage checklist' response is a FAILURE."
        ),
        evaluation_steps=[
            "Check if agent used Sentry tool - just mentioning is not enough",
            "Verify agent reported SPECIFIC findings (error messages, endpoints)",
            "Check if response contains actual results vs generic advice",
            "If no specific Sentry findings, score < 0.5",
            "A checklist without execution should score < 0.3",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT, 
            LLMTestCaseParams.ACTUAL_OUTPUT
        ],
        threshold=0.70,
        model=model,
    )


def create_handoff_quality_metric(model):
    """
    Measure context preservation during agent-to-agent handoffs.
    """
    return GEval(
        name="HandoffQuality",
        criteria=(
            "Did the agent make a PROPER HANDOFF with preserved context? "
            "A proper handoff MUST include: "
            "(1) Explicit /RoleName mention of receiving agent; "
            "(2) SPECIFIC technical context from prior investigation; "
            "(3) Clear action requested from receiving agent. "
            "Vague 'please look into this' handoffs should score < 0.4."
        ),
        evaluation_steps=[
            "Check for explicit /RoleName or @RoleName mention",
            "Verify handoff includes specific technical details",
            "Check if receiving agent can act without re-investigation",
            "Score higher for actionable, specific handoffs",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT, 
            LLMTestCaseParams.ACTUAL_OUTPUT
        ],
        threshold=0.70,
        model=model,
    )
```

### 6.4 Test Scenarios

| Test File | Scenario | Agents Tested | Key Metrics |
|-----------|----------|---------------|-------------|
| `test_slack_routing.py` | Slack message routing | All agents | TaskCompletion, ResponseTime |
| `test_discord_routing.py` | Discord message routing | All agents | TaskCompletion, ResponseTime |
| `test_github_routing.py` | GitHub issue handling | SWE, PM | TaskCompletion, Professionalism |
| `test_handoff_chain.py` | Multi-agent handoff | Support → Release | HandoffQuality, ContextPreservation |
| `test_sentry_alert.py` | Sentry error → investigation | Support, Release | InvestigationQuality, ToolUsage |

### 6.5 End-to-End Test Architecture

```
┌──────────┐         ┌─────────────────┐
│  pytest  │ ──────► │  Slack API      │  POST message to thread
└──────────┘         │  thread_ts: X   │
                     └────────┬────────┘
                              │
Step 2: Webhook triggers      ▼
                     ┌─────────────────┐
                     │ Gateway         │  Routes /SupportEngineer
                     │ (K8s service)   │
                     └────────┬────────┘
                              │
Step 3: Agent processes       ▼
                     ┌─────────────────┐
                     │ Agent Service   │  SupportEngineer investigates
                     │ (OpenHands)     │  with Sentry, responds
                     └────────┬────────┘
                              │
Step 4: Handoff detected      │  Agent posts: "/ReleaseEngineer..."
                              ▼
                     ┌─────────────────┐
                     │ Gateway         │  Routes /ReleaseEngineer
                     │                 │
                     └────────┬────────┘
                              │
Step 5: Second agent          ▼
                     ┌─────────────────┐
                     │ Agent Service   │  ReleaseEngineer acts
                     │ (OpenHands)     │  on handoff
                     └────────┬────────┘
                              │
Step 6: Evaluate              ▼
┌──────────┐         ┌─────────────────┐
│  pytest  │ ◄────── │  Slack API      │  GET thread messages
│          │         │  thread_ts: X   │
│ DeepEval │         └─────────────────┘
│ G-Eval   │
│          │
│ ASSERT   │  - HandoffQuality ≥ 0.70
│          │  - TaskCompletion ≥ 0.70
└──────────┘
```

### 6.6 Example Test Implementation

```python
class TestHandoffChain:
    """Test multi-agent handoff scenarios with DeepEval."""
    
    @pytest.fixture
    def azure_model(self):
        """Azure GPT-5.2 model for evaluation."""
        from deepeval.models.base_model import DeepEvalBaseLLM
        
        class AzureOpenAIModel(DeepEvalBaseLLM):
            def __init__(self):
                self.model_name = "azure/gpt-5.2"
            
            async def a_generate(self, prompt: str) -> str:
                response = await openai_client.chat.completions.create(
                    model="gpt-5.2",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                return response.choices[0].message.content
        
        return AzureOpenAIModel()
    
    @pytest.mark.asyncio
    async def test_support_to_release_handoff(self, mock_slack, azure_model):
        """
        Scenario: Customer reports outage, Support hands off to Release.
        
        Flow:
        1. User: @SupportEngineer customer reports API errors
        2. SupportEngineer: checks Sentry, responds, mentions @ReleaseEngineer
        3. ReleaseEngineer: investigates, reports status
        """
        # Arrange
        user_message = (
            "/SupportEngineer Customer ACME Corp reports GenAI Gateway "
            "returning 500 errors. Started after 8am deployment. "
            "About 500 users affected."
        )
        
        # Act - run through real agent pipeline
        support_response = await run_agent("support_engineer", user_message)
        
        # Extract handoff and run second agent
        if "/ReleaseEngineer" in support_response:
            release_response = await run_agent(
                "release_engineer", 
                support_response
            )
        else:
            release_response = ""
        
        # Evaluate with DeepEval
        test_case = LLMTestCase(
            input=user_message,
            actual_output=f"{support_response}\n\n{release_response}",
        )
        
        investigation_metric = create_investigation_quality_metric(azure_model)
        handoff_metric = create_handoff_quality_metric(azure_model)
        
        # Assert
        results = evaluate([test_case], [investigation_metric, handoff_metric])
        
        assert results.passed, f"Evaluation failed: {results.summary}"
        assert investigation_metric.score >= 0.70
        assert handoff_metric.score >= 0.70
```

### 6.7 Agent-Specific Thresholds

Different roles have different minimum thresholds based on their responsibilities:

| Agent | TaskCompletion | HandoffQuality | Professionalism |
|-------|----------------|----------------|-----------------|
| SoftwareEngineer | ≥ 0.75 | ≥ 0.70 | ≥ 0.70 |
| ReleaseEngineer | ≥ 0.75 | ≥ 0.70 | ≥ 0.70 |
| SupportEngineer | ≥ 0.80 | ≥ 0.75 | ≥ 0.80 |
| ProductManager | ≥ 0.70 | ≥ 0.70 | ≥ 0.80 |
| MarketingManager | ≥ 0.70 | ≥ 0.65 | ≥ 0.85 |

**Note**: SupportEngineer has higher thresholds due to the customer-facing nature of the role.

### 6.8 CI/CD Integration

```yaml
# .github/workflows/evaluation.yml
name: Agent Evaluation

on:
  pull_request:
    branches: [main, master]
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

## 7. Implementation Details

### 7.1 Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Gateway | FastAPI | Webhook handling, message routing |
| Agent Service | FastAPI + OpenHands | Agent execution, session management |
| Database | PostgreSQL | Session state, thread subscriptions |
| Queue | Redis (optional) | Async message processing |
| Observability | Langfuse | LLM tracing and monitoring |
| Error Tracking | Sentry | Error aggregation and alerting |

### 7.2 Message Routing Implementation

```python
class Router:
    ROLE_PATTERN = re.compile(
        r'/(SoftwareEngineer|ReleaseEngineer|SupportEngineer|'
        r'ProductManager|MarketingManager)',
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

### 7.3 Bot Message Handling (Handoff Detection)

A critical design decision: **the router processes the bot's own messages** to detect handoffs:

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

## 8. Experimental Results

### 8.1 Evaluation Scenarios

We evaluated VibeTeam across five core scenarios:

| Scenario | Description | Agents Involved |
|----------|-------------|-----------------|
| S1: API Error Investigation | Customer reports 400 errors | Support → Release |
| S2: Bug Fix Request | GitHub issue triage and fix | Software Engineer |
| S3: Deployment Request | Staging deployment | Release Engineer |
| S4: Feature Prioritization | Backlog management | Product Manager |
| S5: Multi-Handoff Chain | Complex issue requiring 3+ agents | Support → Software → Release |

### 8.2 Quantitative Results

| Metric | S1 | S2 | S3 | S4 | S5 | Average |
|--------|----|----|----|----|----|----|
| TaskCompletion | 0.85 | 0.88 | 0.92 | 0.78 | 0.76 | **0.84** |
| HandoffQuality | 0.82 | N/A | N/A | N/A | 0.71 | **0.77** |
| InvestigationQuality | 0.79 | 0.84 | N/A | N/A | 0.73 | **0.79** |
| ContextPreservation | 0.88 | 0.91 | 0.89 | 0.86 | 0.74 | **0.86** |
| Response Time (s) | 45 | 38 | 22 | 31 | 89 | **45** |

### 8.3 Key Findings

1. **Handoff quality degrades with chain length**: Multi-handoff scenarios (S5) showed lower HandoffQuality (0.71) compared to single handoffs (0.82), indicating context loss over multiple transfers.

2. **Tool usage correlates with investigation quality**: Agents that actively used Sentry/GitHub tools scored significantly higher on InvestigationQuality than those providing generic responses.

3. **Response time increases with complexity**: Simple routing (S3) completed in ~22s, while multi-handoff scenarios (S5) averaged 89s due to sequential agent processing.

4. **Human visibility achieved**: All coordination was visible in Slack threads, with clear `[RoleName]` prefixes enabling human operators to understand and intervene.

---

## 9. Discussion

### 9.1 Advantages of Natural Language Delegation

1. **Transparency**: Every coordination decision is human-readable
2. **Auditability**: Complete conversation history in existing tools
3. **Interruptibility**: Humans can jump into any thread to redirect
4. **Familiarity**: Uses patterns teams already understand
5. **Flexibility**: No predefined workflows—agents discover collaborators dynamically

### 9.2 Limitations

1. **Latency**: Human-readable communication adds overhead vs. direct API calls
2. **Context Window**: Long threads may exceed LLM context limits
3. **Reliability**: Depends on external platform availability (Slack/Discord)
4. **Cost**: Each agent invocation requires LLM inference

### 9.3 Future Work

1. **Parallel Handoffs**: Allow multiple agents to work simultaneously
2. **Proactive Agents**: Agents that monitor and intervene without explicit invocation
3. **Learning from History**: Use past conversations to improve handoff quality
4. **Hybrid Orchestration**: Combine natural delegation with programmatic workflows for latency-critical paths

---

## 10. Conclusion

We presented VibeTeam, a multi-agent system that enables AI agents to collaborate through natural language delegation in human communication channels. Our key contributions include:

1. A **thread-based subscription model** that provides stateful, multi-turn coordination
2. A **natural handoff protocol** using `/RoleName` mentions for dynamic task delegation
3. A rigorous **G-Eval evaluation framework** for measuring multi-agent team performance

Our experiments demonstrate that natural language delegation achieves competitive task completion rates (84% average) while providing unprecedented transparency into agent coordination. By adopting human communication patterns, AI agent teams become observable, auditable, and interruptible—properties essential for enterprise deployment.

The VibeTeam architecture proves that effective multi-agent coordination does not require opaque orchestration frameworks. Instead, by meeting humans where they already collaborate, AI agents can integrate seamlessly into existing workflows while maintaining the oversight capabilities organizations require.

---

## References

1. Liu, Y., et al. (2023). "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment." *arXiv preprint arXiv:2303.16634*.

2. Wu, Q., et al. (2023). "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." *arXiv preprint arXiv:2308.08155*.

3. Hong, S., et al. (2023). "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework." *arXiv preprint arXiv:2308.00352*.

4. Qian, C., et al. (2023). "ChatDev: Communicative Agents for Software Development." *arXiv preprint arXiv:2307.07924*.

5. OpenHands Team. (2024). "OpenHands: An Open Platform for AI Software Developers as Generalist Agents." *GitHub repository*.

6. LangChain Team. (2024). "LangGraph: Building Language Agents as Graphs." *Documentation*.

7. DeepEval Team. (2024). "DeepEval: The LLM Evaluation Framework." *Documentation*.

---

## Appendix A: Running Evaluations

```bash
# Install dependencies
pip install deepeval>=0.21.0

# Set environment variables
export AZURE_API_KEY="your-key"
export AZURE_API_BASE="https://your-endpoint.openai.azure.com"
export AZURE_API_VERSION="2024-12-01-preview"

# Run all E2E evaluation tests
pytest tests/e2e/ -v -s

# Run specific handoff test
pytest tests/e2e/test_handoff_chain.py -v -s --tb=short

# Generate evaluation report
python scripts/run_evaluation.py --output results/eval_report.json
```

## Appendix B: Thread ID Formats

| Source | Thread ID Format | Example |
|--------|------------------|---------|
| Slack | `{thread_ts}` | `1234567890.123456` |
| Discord | `{channel_id}:{message_id}` | `123456789:987654321` |
| GitHub Issue | `{repo}:{issue_number}` | `VibeTechnologies/VibeWebAgent:345` |
| GitHub PR | `{repo}:pr:{pr_number}` | `VibeTechnologies/VibeWebAgent:pr:123` |

## Appendix C: Environment Configuration

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

# Observability
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```
