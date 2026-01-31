# VibeTeam Agent Evaluation Framework

## Overview

This document describes the VibeTeam evaluation framework using **DeepEval** for comprehensive agent testing. It covers:

1. **System Architecture** - Webhook router, Agent REST API, message broadcast
2. **Team Dynamics** - Proactive responsibility detection, pizza team behavior
3. **Channel Simulation** - Mock Discord/Slack for testing
4. **DeepEval Integration** - Metrics, test cases, and evaluation pipeline
5. **Evaluation Results** - Per-framework scoring tables

---

## 1. System Architecture

### 1.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              External Platforms                              │
│                                                                              │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│   │   Discord   │    │    Slack    │    │    Gmail    │    │   GitHub    │  │
│   │   Server    │    │  Workspace  │    │    Inbox    │    │   Webhooks  │  │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│          │                  │                  │                  │          │
└──────────┼──────────────────┼──────────────────┼──────────────────┼──────────┘
           │                  │                  │                  │
           ▼                  ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WEBHOOK ROUTER (Lambda/K8s)                        │
│                                                                              │
│   POST /webhook/discord    - Discord Gateway events                         │
│   POST /webhook/slack      - Slack Events API                               │
│   POST /webhook/gmail      - Gmail Push notifications                       │
│   POST /webhook/github     - GitHub webhook events                          │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                        Message Normalizer                              │ │
│   │                                                                        │ │
│   │   Discord event  ──┐                                                   │ │
│   │   Slack event    ──┼──►  UnifiedMessage { source, content, author,    │ │
│   │   Gmail message  ──┤       channel, timestamp, mentions, metadata }   │ │
│   │   GitHub event   ──┘                                                   │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      ▼                                       │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Route to Agent API                             │ │
│   │                                                                        │ │
│   │   POST /api/v1/team/broadcast                                          │ │
│   │   Body: { message: UnifiedMessage, context: ConversationContext }      │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT REST API (K8s Service)                        │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                        Team Broadcast Endpoint                         │ │
│   │                                                                        │ │
│   │   POST /api/v1/team/broadcast                                          │ │
│   │                                                                        │ │
│   │   1. Receives UnifiedMessage                                           │ │
│   │   2. Broadcasts to ALL agents simultaneously                           │ │
│   │   3. Each agent evaluates: "Is this my responsibility?"                │ │
│   │   4. Agents that claim responsibility begin working                    │ │
│   │   5. Agents notify team via shared channel                             │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Agent Pool (Always Running)                    │ │
│   │                                                                        │ │
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│   │   │  Software   │  │  Release    │  │  Support    │  │  Product    │  │ │
│   │   │  Engineer   │  │  Engineer   │  │  Engineer   │  │  Manager    │  │ │
│   │   │             │  │             │  │             │  │             │  │ │
│   │   │ Listening   │  │ Listening   │  │ Listening   │  │ Listening   │  │ │
│   │   │ for tasks   │  │ for tasks   │  │ for tasks   │  │ for tasks   │  │ │
│   │   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │ │
│   │                                                                        │ │
│   │   ┌─────────────┐                                                      │ │
│   │   │  Marketing  │     Framework: AutoGen | CrewAI | OpenHands          │ │
│   │   │  Manager    │     (configurable per agent or globally)             │ │
│   │   │             │                                                      │ │
│   │   │ Listening   │                                                      │ │
│   │   │ for tasks   │                                                      │ │
│   │   └─────────────┘                                                      │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                         Shared Team Channel                            │ │
│   │                                                                        │ │
│   │   In-memory message bus that mirrors Discord/Slack channel             │ │
│   │   - All agent responses posted here                                    │ │
│   │   - Enables agent-to-agent communication                               │ │
│   │   - Syncs back to source platform (Discord/Slack)                      │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Response Handler                                  │
│                                                                              │
│   Agent responses are:                                                       │
│   1. Posted to Shared Team Channel (internal)                               │
│   2. Synced to source platform (Discord webhook / Slack API)               │
│   3. Logged to Langfuse for observability                                   │
│   4. Evaluated by DeepEval metrics (in test mode)                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 API Endpoints

#### Webhook Router (Edge/Lambda)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/discord` | POST | Receives Discord Gateway events |
| `/webhook/slack` | POST | Receives Slack Events API callbacks |
| `/webhook/gmail` | POST | Receives Gmail push notifications |
| `/webhook/github` | POST | Receives GitHub webhook events |
| `/health` | GET | Health check |

#### Agent REST API (Internal Service)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/team/broadcast` | POST | Broadcast message to all agents |
| `/api/v1/team/channel` | GET | Get shared channel history |
| `/api/v1/team/channel` | POST | Post message to shared channel |
| `/api/v1/agent/{role}/run` | POST | Direct message to specific agent |
| `/api/v1/agent/{role}/status` | GET | Get agent status |
| `/health` | GET | Health check with agent pool status |

### 1.3 Message Flow Example

```
1. Customer emails: "API Gateway returning 404 errors"
   └─► Gmail push → /webhook/gmail

2. Webhook Router normalizes to UnifiedMessage
   └─► POST /api/v1/team/broadcast

3. All 5 agents receive the message simultaneously

4. Each agent evaluates responsibility:
   - SoftwareEngineer: "Not my area, it's infrastructure" → PASS
   - ReleaseEngineer: "Infrastructure issue, I should investigate" → CLAIM
   - SupportEngineer: "Customer communication, I should respond" → CLAIM
   - ProductManager: "Not a feature request" → PASS
   - MarketingManager: "Not marketing related" → PASS

5. ReleaseEngineer posts: "I'm investigating the API Gateway 404 issue"
   └─► Shared Channel → Discord webhook

6. SupportEngineer posts: "I'll prepare customer communication"
   └─► Shared Channel → Discord webhook

7. ReleaseEngineer fixes and posts: "Fixed! Routing table was misconfigured"
   └─► Shared Channel → Discord webhook

8. SupportEngineer sends email to customer with resolution
   └─► Gmail API → Shared Channel confirmation
```

---

## 2. Pizza Team Dynamics

### 2.1 What is a Pizza Team?

A "pizza team" is a small, autonomous team (5-8 people) that can be fed with two pizzas. Each member has a distinct role but the team is cross-functional and self-organizing.

**VibeTeam Agents as a Pizza Team:**

| Agent | Role | Responsibility Keywords |
|-------|------|------------------------|
| **SoftwareEngineer** | Builder | code, bug, fix, implement, PR, test, refactor |
| **ReleaseEngineer** | Deployer | deploy, release, kubernetes, infrastructure, CI/CD |
| **SupportEngineer** | Communicator | customer, email, error, sentry, support, ticket |
| **ProductManager** | Prioritizer | feature, requirement, backlog, prioritize, roadmap |
| **MarketingManager** | Announcer | announce, social, post, content, launch |

### 2.2 Proactive Responsibility Detection

Each agent has a **Responsibility Detector** that evaluates incoming messages:

```python
class ResponsibilityDetector:
    """Determines if an agent should claim responsibility for a task."""
    
    def __init__(self, agent_role: str, keywords: list[str], llm_model: str):
        self.agent_role = agent_role
        self.keywords = keywords
        self.llm = llm_model
    
    async def should_claim(self, message: UnifiedMessage) -> ResponsibilityClaim:
        """
        Evaluate if this agent should work on this message.
        
        Returns:
            ResponsibilityClaim with:
            - should_claim: bool
            - confidence: float (0-1)
            - reasoning: str
            - estimated_effort: str (small/medium/large)
        """
        # Step 1: Keyword matching (fast path)
        keyword_match = self._keyword_score(message.content)
        
        # Step 2: Direct mention check
        if self.agent_role in message.mentions:
            return ResponsibilityClaim(
                should_claim=True,
                confidence=1.0,
                reasoning=f"Directly mentioned as @{self.agent_role}",
                estimated_effort="unknown"
            )
        
        # Step 3: LLM-based responsibility inference
        if keyword_match > 0.3:  # Only call LLM if keywords suggest relevance
            return await self._llm_evaluate(message)
        
        return ResponsibilityClaim(should_claim=False, confidence=0.0)
```

### 2.3 Team Coordination Protocol

When multiple agents might claim the same task:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Coordination Protocol                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. BROADCAST: Message sent to all agents                        │
│                                                                  │
│  2. EVALUATE: Each agent runs ResponsibilityDetector             │
│     - Returns within 2 seconds                                   │
│     - Includes confidence score                                  │
│                                                                  │
│  3. CLAIM: Agents with should_claim=True announce intent         │
│     "I'm taking responsibility for [task summary]"               │
│                                                                  │
│  4. COORDINATE: If multiple claims:                              │
│     - Highest confidence wins primary                            │
│     - Others become supporting roles                             │
│     - Or agents negotiate: "I'll handle X, you handle Y"         │
│                                                                  │
│  5. EXECUTE: Primary agent works on task                         │
│     - Posts updates to shared channel                            │
│     - Can @mention others for help                               │
│                                                                  │
│  6. HANDOFF: When task requires different expertise              │
│     "@ReleaseEngineer this is ready for deployment"              │
│                                                                  │
│  7. COMPLETE: Agent announces completion                         │
│     "Task complete: [summary of what was done]"                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.4 Agent System Prompts (Excerpt)

Each agent has a system prompt that includes team awareness:

```python
TEAM_AWARENESS_PROMPT = """
## Team Collaboration

You are part of a 5-person AI team. When you receive a message:

1. **Evaluate Responsibility**: Is this task within your expertise?
   - If YES and no one else is working on it → Claim it
   - If YES but someone else claimed it → Offer to help or stand by
   - If NO → Let the appropriate team member handle it

2. **Announce Your Work**: When you start a task, tell the team:
   "I'm taking this - [brief description of what you'll do]"

3. **Ask for Help**: If you need another team member:
   "@SoftwareEngineer can you review this fix?"
   "@SupportEngineer please notify the customer"

4. **Handoff Cleanly**: When your part is done:
   "Done with [X]. @ReleaseEngineer ready for deployment."

5. **Stay Informed**: Read team messages even if not for you.
   You might spot issues or have helpful context.

## Your Team Members

- @SoftwareEngineer - Code, bugs, tests, PRs
- @ReleaseEngineer - Deployments, infrastructure, CI/CD
- @SupportEngineer - Customer communication, error analysis
- @ProductManager - Requirements, prioritization, roadmap
- @MarketingManager - Announcements, social media, content
"""
```

---

## 3. Channel Simulation for Testing

### 3.1 SimulatedChannel Class

For testing, we simulate Discord/Slack with an in-memory channel:

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable
import asyncio

@dataclass
class ChannelMessage:
    """A message in the simulated channel."""
    id: str
    author: str  # Agent role or "user" or "system"
    content: str
    timestamp: datetime
    mentions: list[str] = field(default_factory=list)
    reply_to: str | None = None
    metadata: dict = field(default_factory=dict)

@dataclass
class SimulatedChannel:
    """
    In-memory simulation of a Discord/Slack channel.
    
    Used for testing multi-agent conversations without real API calls.
    """
    name: str
    messages: list[ChannelMessage] = field(default_factory=list)
    listeners: list[Callable[[ChannelMessage], Awaitable[None]]] = field(default_factory=list)
    _message_counter: int = 0
    
    def post(
        self,
        author: str,
        content: str,
        mentions: list[str] | None = None,
        reply_to: str | None = None,
    ) -> ChannelMessage:
        """Post a message to the channel."""
        self._message_counter += 1
        msg = ChannelMessage(
            id=f"msg_{self._message_counter:04d}",
            author=author,
            content=content,
            timestamp=datetime.now(timezone.utc),
            mentions=mentions or self._extract_mentions(content),
            reply_to=reply_to,
        )
        self.messages.append(msg)
        
        # Notify listeners (agents watching the channel)
        for listener in self.listeners:
            asyncio.create_task(listener(msg))
        
        return msg
    
    def _extract_mentions(self, content: str) -> list[str]:
        """Extract @mentions from message content."""
        import re
        return re.findall(r"@(\w+)", content)
    
    def get_history(self, limit: int = 50) -> list[ChannelMessage]:
        """Get recent messages."""
        return self.messages[-limit:]
    
    def get_messages_by_author(self, author: str) -> list[ChannelMessage]:
        """Get all messages from a specific author."""
        return [m for m in self.messages if m.author == author]
    
    def subscribe(self, callback: Callable[[ChannelMessage], Awaitable[None]]) -> None:
        """Subscribe to new messages."""
        self.listeners.append(callback)
    
    def to_transcript(self) -> str:
        """Generate human-readable transcript."""
        lines = []
        for msg in self.messages:
            reply = f" (replying to {msg.reply_to})" if msg.reply_to else ""
            lines.append(f"[{msg.timestamp.strftime('%H:%M:%S')}] {msg.author}{reply}: {msg.content}")
        return "\n".join(lines)
    
    def to_deepeval_turns(self) -> list["Turn"]:
        """Convert to DeepEval Turn objects for evaluation."""
        from deepeval.test_case import Turn
        
        turns = []
        for msg in self.messages:
            role = "user" if msg.author == "user" else "assistant"
            turns.append(Turn(
                role=role,
                content=f"[{msg.author}]: {msg.content}",
            ))
        return turns
```

### 3.2 Test Harness

```python
class TeamTestHarness:
    """
    Test harness for running multi-agent scenarios.
    
    Simulates the full message flow:
    1. User posts to channel
    2. All agents receive and evaluate
    3. Agents claim responsibility and work
    4. Agents coordinate via channel
    5. Task completes
    """
    
    def __init__(self, framework: str = "crewai"):
        self.framework = framework
        self.channel = SimulatedChannel(name="test-team-channel")
        self.agents: dict[str, BaseAgent] = {}
        self._setup_agents()
    
    def _setup_agents(self) -> None:
        """Initialize all team agents."""
        agent_roles = [
            "software_engineer",
            "release_engineer", 
            "support_engineer",
            "product_manager",
            "marketing_manager",
        ]
        
        for role in agent_roles:
            agent = self._create_agent(role)
            self.agents[role] = agent
            
            # Subscribe agent to channel messages
            self.channel.subscribe(
                lambda msg, a=agent: self._on_message(a, msg)
            )
    
    async def _on_message(self, agent: BaseAgent, message: ChannelMessage) -> None:
        """Handle incoming message for an agent."""
        # Skip messages from this agent (no self-reply)
        if message.author == agent.role:
            return
        
        # Check if agent should respond
        claim = await agent.responsibility_detector.should_claim(message)
        
        if claim.should_claim:
            # Agent claims and works on task
            response = await agent.run(message.content)
            self.channel.post(
                author=agent.role,
                content=response,
                reply_to=message.id,
            )
    
    async def run_scenario(
        self,
        initial_message: str,
        timeout: float = 60.0,
        expected_agents: list[str] | None = None,
    ) -> ScenarioResult:
        """
        Run a test scenario.
        
        Args:
            initial_message: The user's initial message
            timeout: Maximum time to wait for agents
            expected_agents: Which agents we expect to respond
        
        Returns:
            ScenarioResult with conversation and metadata
        """
        start_time = time.perf_counter()
        
        # Post initial message
        self.channel.post(author="user", content=initial_message)
        
        # Wait for agents to respond (with timeout)
        await asyncio.sleep(timeout)
        
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        
        # Collect results
        agent_responses = {
            role: self.channel.get_messages_by_author(role)
            for role in self.agents.keys()
        }
        
        return ScenarioResult(
            framework=self.framework,
            channel=self.channel,
            initial_message=initial_message,
            agent_responses=agent_responses,
            elapsed_ms=elapsed_ms,
            expected_agents=expected_agents or [],
        )
```

---

## 4. DeepEval Integration

### 4.1 Why DeepEval?

| Capability | DeepEval | Native LLM-as-Judge |
|------------|----------|---------------------|
| Pre-built metrics | 20+ metrics | Custom only |
| Conversation support | ConversationalTestCase | Manual |
| Tool use evaluation | ToolCorrectnessMetric | Manual |
| Hallucination detection | HallucinationMetric | Manual |
| Task completion | TaskCompletionMetric | Manual |
| G-Eval (custom) | GEval class | Manual prompt |
| Tracing | Built-in @observe | Manual |
| CI/CD integration | pytest plugin | Manual |
| Dashboard | Confident AI platform | None |

### 4.2 Metrics Used

#### Core Metrics

| Metric | Purpose | Input |
|--------|---------|-------|
| `ConversationalGEval` | Custom criteria on conversations | ConversationalTestCase |
| `TaskCompletionMetric` | Did agents complete the task? | Agent traces |
| `ToolCorrectnessMetric` | Did agents use correct tools? | Tool calls |
| `ToolUseMetric` | Were tools used effectively? | ConversationalTestCase |
| `HallucinationMetric` | Factual accuracy | Output + context |
| `AnswerRelevancyMetric` | Response relevance | Input + output |

#### Custom G-Eval Metrics for VibeTeam

```python
from deepeval.metrics import ConversationalGEval, GEval
from deepeval.test_case import TurnParams, LLMTestCaseParams

# Metric 1: Team Coordination
team_coordination = ConversationalGEval(
    name="TeamCoordination",
    criteria="""Evaluate how well the AI agents coordinated as a team:
    1. Did agents correctly identify their responsibilities?
    2. Did agents communicate their intentions clearly?
    3. Did agents hand off tasks appropriately?
    4. Did agents avoid duplicating work?
    5. Did the team complete the overall objective?
    """,
    evaluation_params=[TurnParams.CONTENT],
    threshold=0.7,
)

# Metric 2: Responsibility Detection
responsibility_detection = ConversationalGEval(
    name="ResponsibilityDetection",
    criteria="""Evaluate if agents correctly identified task ownership:
    - SoftwareEngineer should claim: code bugs, implementations, PRs
    - ReleaseEngineer should claim: deployments, infrastructure
    - SupportEngineer should claim: customer issues, error analysis
    - ProductManager should claim: feature requests, prioritization
    - MarketingManager should claim: announcements, content
    
    Score based on:
    1. Correct agent claimed the task (or multiple if appropriate)
    2. Wrong agents did NOT claim tasks outside their area
    3. Clear communication about who is handling what
    """,
    evaluation_params=[TurnParams.CONTENT],
    threshold=0.7,
)

# Metric 3: Handoff Quality
handoff_quality = ConversationalGEval(
    name="HandoffQuality",
    criteria="""Evaluate the quality of task handoffs between agents:
    1. Was context preserved when handing off?
    2. Was the receiving agent properly @mentioned?
    3. Was there a clear explanation of what was done and what's needed?
    4. Did the receiving agent acknowledge the handoff?
    """,
    evaluation_params=[TurnParams.CONTENT],
    threshold=0.7,
)

# Metric 4: Task Completion
task_completion = ConversationalGEval(
    name="TaskCompletion",
    criteria="""Evaluate if the team successfully completed the requested task:
    1. Was the original request fully addressed?
    2. Were all necessary actions taken?
    3. Was the user/customer informed of the resolution?
    4. Were there any loose ends or missing steps?
    """,
    evaluation_params=[TurnParams.CONTENT],
    threshold=0.7,
)

# Metric 5: Professional Communication
professionalism = ConversationalGEval(
    name="Professionalism",
    criteria="""Evaluate the professionalism of agent communication:
    1. Clear and concise messaging
    2. Appropriate tone for the situation
    3. No unnecessary verbosity
    4. Proper formatting and structure
    """,
    evaluation_params=[TurnParams.CONTENT],
    threshold=0.7,
)
```

### 4.3 Test Case Creation

```python
from deepeval import evaluate
from deepeval.test_case import ConversationalTestCase, Turn, ToolCall
from deepeval.metrics import (
    ConversationalGEval,
    ToolCorrectnessMetric,
    HallucinationMetric,
)

def create_handoff_test_case(
    scenario: ScenarioResult,
) -> ConversationalTestCase:
    """
    Convert a scenario result to a DeepEval ConversationalTestCase.
    """
    turns = []
    
    # Add user's initial message
    turns.append(Turn(
        role="user",
        content=scenario.initial_message,
    ))
    
    # Add all channel messages as turns
    for msg in scenario.channel.messages[1:]:  # Skip first (user message)
        # Determine role
        role = "user" if msg.author == "user" else "assistant"
        
        # Include author in content for multi-agent clarity
        content = f"[{msg.author}]: {msg.content}"
        
        # Extract tool calls if present
        tools_called = []
        if hasattr(msg, "tool_calls"):
            tools_called = [
                ToolCall(name=tc.name, input=tc.input, output=tc.output)
                for tc in msg.tool_calls
            ]
        
        turns.append(Turn(
            role=role,
            content=content,
            tools_called=tools_called if tools_called else None,
        ))
    
    return ConversationalTestCase(
        turns=turns,
        # Additional context for evaluation
        additional_metadata={
            "framework": scenario.framework,
            "expected_agents": scenario.expected_agents,
            "elapsed_ms": scenario.elapsed_ms,
        }
    )
```

### 4.4 Evaluation Pipeline

```python
from deepeval import evaluate
from deepeval.dataset import EvaluationDataset

async def run_evaluation(
    scenarios: list[tuple[str, str]],  # (scenario_name, initial_message)
    frameworks: list[str] = ["autogen", "crewai", "openhands"],
) -> EvaluationReport:
    """
    Run full evaluation across scenarios and frameworks.
    
    Returns:
        EvaluationReport with per-framework scores
    """
    results = {}
    
    for framework in frameworks:
        print(f"\n{'=' * 60}")
        print(f"Evaluating: {framework.upper()}")
        print(f"{'=' * 60}")
        
        test_cases = []
        
        for scenario_name, initial_message in scenarios:
            print(f"\n>>> Scenario: {scenario_name}")
            
            # Run scenario with this framework
            harness = TeamTestHarness(framework=framework)
            scenario_result = await harness.run_scenario(
                initial_message=initial_message,
                timeout=120.0,
            )
            
            # Convert to DeepEval test case
            test_case = create_handoff_test_case(scenario_result)
            test_cases.append(test_case)
        
        # Define metrics
        metrics = [
            team_coordination,
            responsibility_detection,
            handoff_quality,
            task_completion,
            professionalism,
        ]
        
        # Run DeepEval evaluation
        eval_result = evaluate(
            test_cases=test_cases,
            metrics=metrics,
            run_async=True,
            print_results=True,
        )
        
        results[framework] = eval_result
    
    return EvaluationReport(results=results)
```

### 4.5 pytest Integration

```python
# tests/e2e/test_team_eval.py

import pytest
from deepeval import assert_test
from deepeval.test_case import ConversationalTestCase, Turn
from deepeval.metrics import ConversationalGEval

# Define test scenarios
SCENARIOS = [
    {
        "name": "customer_api_error",
        "message": "Customer reports API Gateway returning 404 errors. 500 users affected.",
        "expected_agents": ["support_engineer", "release_engineer"],
    },
    {
        "name": "feature_request",
        "message": "Can we add dark mode to the dashboard? Multiple customers asking.",
        "expected_agents": ["product_manager", "software_engineer"],
    },
    {
        "name": "deployment_request",
        "message": "PR #457 is approved and ready. Please deploy to staging.",
        "expected_agents": ["release_engineer"],
    },
    {
        "name": "error_spike",
        "message": "Sentry alert: 50 new GraphRecursionError events in the last hour.",
        "expected_agents": ["support_engineer", "software_engineer"],
    },
]


class TestTeamHandoffs:
    """DeepEval tests for multi-agent team handoffs."""
    
    @pytest.fixture(autouse=True)
    def setup_metrics(self):
        """Setup evaluation metrics."""
        self.team_coordination = ConversationalGEval(
            name="TeamCoordination",
            criteria="Evaluate how well agents coordinated as a team.",
            threshold=0.7,
        )
        self.task_completion = ConversationalGEval(
            name="TaskCompletion", 
            criteria="Evaluate if the team completed the requested task.",
            threshold=0.7,
        )
    
    @pytest.mark.parametrize("framework", ["autogen", "crewai", "openhands"])
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
    async def test_team_scenario(self, framework: str, scenario: dict):
        """Test a team scenario with a specific framework."""
        # Run scenario
        harness = TeamTestHarness(framework=framework)
        result = await harness.run_scenario(
            initial_message=scenario["message"],
            expected_agents=scenario["expected_agents"],
            timeout=120.0,
        )
        
        # Create test case
        test_case = create_handoff_test_case(result)
        
        # Assert with DeepEval
        assert_test(
            test_case=test_case,
            metrics=[self.team_coordination, self.task_completion],
        )
```

---

## 5. Evaluation Results

### 5.1 Results Table Format

After running evaluation, results are presented in this format:

#### Per-Scenario Results

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SCENARIO: customer_api_error                             │
│   Message: "Customer reports API Gateway returning 404 errors..."           │
│   Expected Agents: support_engineer, release_engineer                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Framework    Coordination  Responsibility  Handoff  Completion  Prof.     │
│   ──────────── ────────────  ──────────────  ───────  ──────────  ─────     │
│   AutoGen      0.85          0.90            0.75     0.80        0.90      │
│   CrewAI       0.80          0.85            0.80     0.85        0.85      │
│   OpenHands    0.90          0.95            0.85     0.90        0.88      │
│                                                                              │
│   Winner: OpenHands (avg: 0.896)                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Aggregate Results

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AGGREGATE EVALUATION RESULTS                            │
│                                                                              │
│   Scenarios: 4 | Metrics: 5 | Date: 2026-01-31                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                           SCORE BY METRIC                                    │
│                                                                              │
│   Metric               AutoGen    CrewAI    OpenHands    Best               │
│   ──────────────────── ────────── ───────── ──────────── ──────────         │
│   TeamCoordination     0.82       0.79      0.88         OpenHands          │
│   Responsibility       0.88       0.84      0.92         OpenHands          │
│   HandoffQuality       0.75       0.82      0.84         OpenHands          │
│   TaskCompletion       0.80       0.83      0.87         OpenHands          │
│   Professionalism      0.88       0.85      0.86         AutoGen            │
│   ──────────────────── ────────── ───────── ──────────── ──────────         │
│   AVERAGE              0.826      0.826     0.874        OpenHands          │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                          SCORE BY SCENARIO                                   │
│                                                                              │
│   Scenario             AutoGen    CrewAI    OpenHands    Best               │
│   ──────────────────── ────────── ───────── ──────────── ──────────         │
│   customer_api_error   0.84       0.83      0.90         OpenHands          │
│   feature_request      0.80       0.82      0.85         OpenHands          │
│   deployment_request   0.85       0.84      0.88         OpenHands          │
│   error_spike          0.82       0.80      0.87         OpenHands          │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                              WINNER                                          │
│                                                                              │
│   ╔═══════════════════════════════════════════════════════════════════════╗ │
│   ║                                                                       ║ │
│   ║   OPENHANDS wins with average score 0.874                            ║ │
│   ║                                                                       ║ │
│   ║   Strengths:                                                          ║ │
│   ║   - Best at responsibility detection (0.92)                           ║ │
│   ║   - Best at team coordination (0.88)                                  ║ │
│   ║   - Best at task completion (0.87)                                    ║ │
│   ║                                                                       ║ │
│   ║   Areas for improvement:                                              ║ │
│   ║   - Professionalism slightly behind AutoGen (0.86 vs 0.88)           ║ │
│   ║                                                                       ║ │
│   ╚═══════════════════════════════════════════════════════════════════════╝ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Detailed Feedback Format

For each framework, detailed feedback is provided:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DETAILED FEEDBACK: OpenHands                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│ SCENARIO: customer_api_error                                                 │
│                                                                              │
│ TeamCoordination (0.90/1.0):                                                │
│   "Excellent coordination between SupportEngineer and ReleaseEngineer.      │
│    SupportEngineer immediately recognized customer impact and notified      │
│    the team. ReleaseEngineer responded promptly and kept everyone           │
│    informed during investigation. Clear handoff back to SupportEngineer     │
│    for customer communication."                                             │
│                                                                              │
│ ResponsibilityDetection (0.95/1.0):                                         │
│   "Both SupportEngineer and ReleaseEngineer correctly identified their      │
│    roles. SupportEngineer handled customer communication, ReleaseEngineer   │
│    handled infrastructure investigation. Other agents appropriately         │
│    stayed out of the task."                                                 │
│                                                                              │
│ HandoffQuality (0.85/1.0):                                                  │
│   "Good context preservation in handoffs. ReleaseEngineer's handoff to      │
│    SupportEngineer included: what was fixed, when, and suggested            │
│    customer messaging. Minor deduction: could have included more            │
│    technical details for the customer FAQ."                                 │
│                                                                              │
│ TaskCompletion (0.90/1.0):                                                  │
│   "Task fully completed. Customer received resolution email with            │
│    appropriate details. Issue was fixed. Team coordination was smooth."     │
│                                                                              │
│ Professionalism (0.88/1.0):                                                 │
│   "Professional communication throughout. Messages were clear and           │
│    concise. Customer email was well-formatted and apologetic."              │
│                                                                              │
│ TRANSCRIPT:                                                                  │
│   [09:15:00] user: Customer reports API Gateway returning 404 errors...     │
│   [09:15:02] support_engineer: I'm taking this - will assess customer       │
│              impact and coordinate with team.                                │
│   [09:15:03] release_engineer: I see infrastructure issue - investigating   │
│              API Gateway now.                                                │
│   [09:15:45] release_engineer: Found it - routing table misconfigured       │
│              after last deployment. Fixing now.                              │
│   [09:16:10] release_engineer: Fixed and verified. @support_engineer        │
│              Gateway is back online, all endpoints responding.               │
│   [09:16:15] support_engineer: Thanks! Sending resolution email to          │
│              customer now.                                                   │
│   [09:16:30] support_engineer: Done - customer notified with full           │
│              resolution details.                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Running Evaluations

### 6.1 Prerequisites

```bash
# Install DeepEval
pip install deepeval

# Set up Azure OpenAI for evaluation
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="..."
export AZURE_API_VERSION="2024-08-01-preview"
export AZURE_OPENAI_DEPLOYMENT="gpt-5-2"

# Optional: DeepEval dashboard
export DEEPEVAL_API_KEY="..."  # From confident-ai.com
```

### 6.2 CLI Commands

```bash
# Run all team evaluations
pytest tests/e2e/test_team_eval.py -v -s

# Run specific framework
pytest tests/e2e/test_team_eval.py -v -s -k "openhands"

# Run specific scenario
pytest tests/e2e/test_team_eval.py -v -s -k "customer_api_error"

# Generate evaluation report
python -m scripts.run_team_eval \
    --scenarios customer_api_error,feature_request \
    --frameworks autogen,crewai,openhands \
    --output reports/team-eval-$(date +%Y%m%d).md

# View in DeepEval dashboard
deepeval login
deepeval test run tests/e2e/test_team_eval.py
```

### 6.3 CI/CD Integration

```yaml
# .github/workflows/agent-eval.yml
name: Agent Evaluation

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 6 * * 1'  # Weekly on Monday 6am

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e ".[eval]"
      
      - name: Run evaluation
        env:
          AZURE_OPENAI_API_KEY: ${{ secrets.AZURE_OPENAI_API_KEY }}
          AZURE_OPENAI_ENDPOINT: ${{ secrets.AZURE_OPENAI_ENDPOINT }}
          DEEPEVAL_API_KEY: ${{ secrets.DEEPEVAL_API_KEY }}
        run: |
          pytest tests/e2e/test_team_eval.py -v \
            --tb=short \
            --export-results=results/eval-${{ github.sha }}.json
      
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: eval-results
          path: results/
```

---

## 7. Migration from Native LLM-as-Judge

### 7.1 What Changes

| Aspect | Before (Native) | After (DeepEval) |
|--------|-----------------|------------------|
| Metrics | Custom prompts | Pre-built + custom GEval |
| Test cases | Manual dataclass | ConversationalTestCase |
| Tool eval | Not supported | ToolCorrectnessMetric |
| Hallucination | Manual prompt | HallucinationMetric |
| Dashboard | None | Confident AI |
| pytest | Manual assertions | assert_test() |
| Tracing | Manual | @observe decorator |

### 7.2 Migration Steps

1. **Add DeepEval dependency**
   ```toml
   # pyproject.toml
   [project.optional-dependencies]
   eval = ["deepeval>=0.21.0"]
   ```

2. **Update evaluation tests**
   - Replace `ComparativeEvaluator` with DeepEval metrics
   - Use `ConversationalTestCase` for multi-turn conversations
   - Use `assert_test()` for pytest integration

3. **Update benchmark scripts**
   - Replace custom prompts with `GEval` and `ConversationalGEval`
   - Add tool call tracking with `ToolCall`
   - Enable DeepEval dashboard with `DEEPEVAL_API_KEY`

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-31 | 1.0 | Initial eval.md with DeepEval integration and team architecture |
