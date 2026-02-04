# Natural Language Coordination in Multi-Agent AI Systems: A Thread-Based Subscription Architecture for Human-Visible Agent Collaboration

**VibeTeam Research Whitepaper**

**Authors:** VibeTeam Research Group  
**Date:** February 2025  
**Version:** 1.0

---

## Abstract

We present VibeTeam, a novel multi-agent AI system architecture that enables natural coordination between specialized AI agents through existing human communication platforms (Slack, Discord). Our key hypothesis is that AI agents can collaborate effectively using the same communication patterns humans use in team settings---specifically, @mentions for delegation, thread-based conversations for context isolation, and role-based responsibility claims. Unlike traditional multi-agent orchestration frameworks that rely on programmatic inter-agent communication, our approach leverages familiar collaboration tools as the coordination substrate, ensuring full human visibility into agent activities. We introduce a *thread-based subscription model* where agents dynamically subscribe to conversation threads based on `/RoleName` mentions, enabling emergent handoff chains without centralized orchestration. We evaluate agent performance using DeepEval with G-Eval methodology, employing an LLM-as-judge approach with custom evaluation criteria for task completion, handoff quality, and professional communication. Our experiments demonstrate that this architecture achieves 75%+ task completion rates while maintaining context preservation during multi-agent handoffs.

---

## 1. Introduction

### 1.1 The Multi-Agent Coordination Problem

As Large Language Model (LLM) capabilities expand, there is growing interest in deploying multiple specialized AI agents to handle complex organizational tasks. Traditional approaches to multi-agent systems fall into two categories:

1. **Centralized Orchestration**: A master agent or conductor coordinates all sub-agents, routing tasks and collecting results (e.g., AutoGen's GroupChat, CrewAI's process flows).

2. **Direct Agent-to-Agent Communication**: Agents communicate through programmatic APIs or internal message buses, invisible to human observers.

Both approaches suffer from a fundamental limitation: **opacity**. Human stakeholders cannot easily observe, understand, or intervene in agent-to-agent communications. This creates trust issues and makes debugging difficult.

### 1.2 Our Hypothesis: Human Communication Platforms as Coordination Substrate

We hypothesize that existing human communication platforms---particularly Slack and Discord---provide an ideal coordination substrate for multi-agent AI systems. Our core claims are:

**H1: Natural Interaction Patterns.** Agents can adopt human team communication conventions (mentions, threads, emoji reactions) without specialized orchestration logic.

**H2: Human Visibility by Design.** Using existing chat platforms ensures all agent activities are visible to human team members, enabling oversight and intervention.

**H3: Emergent Coordination.** Thread-based subscriptions enable agents to dynamically form task-specific collaborations without centralized planning.

**H4: Graceful Handoffs.** Role-based mentions (`/RoleName`) provide a natural mechanism for task delegation that preserves context.

### 1.3 Contributions

This paper makes the following contributions:

1. A **thread-based subscription architecture** for multi-agent coordination that leverages existing communication platforms.

2. A **/RoleName mention protocol** for natural agent invocation and handoffs.

3. A **DeepEval-based evaluation framework** using G-Eval methodology with custom metrics for agentic team assessment.

4. Empirical results demonstrating the viability of our approach across multiple agent roles and task types.

---

## 2. Related Work

### 2.1 Multi-Agent Orchestration Frameworks

**AutoGen** (Microsoft, 2023) introduces conversational agents that can engage in multi-turn dialogues. While powerful, AutoGen's GroupChat model uses programmatic routing logic that requires explicit configuration of allowed speaker sequences.

**CrewAI** (2024) provides hierarchical and sequential process models where agents are assigned roles and tasks flow through defined pipelines. This requires upfront specification of agent relationships.

**LangGraph** (LangChain, 2024) offers graph-based agent orchestration with explicit state machines. While flexible, it requires developers to define all possible state transitions.

Our approach differs by eliminating explicit orchestration graphs in favor of emergent coordination through natural language mentions.

### 2.2 Human-AI Collaboration Platforms

**ChatOps** (GitHub, 2013) pioneered the concept of performing DevOps operations through chat interfaces. Our work extends this paradigm to AI agents as first-class team members.

**Slack Apps** and **Discord Bots** have traditionally operated as single-purpose automation tools. We demonstrate that multiple specialized agents can share a single bot identity while maintaining distinct responsibilities.

### 2.3 Agent Evaluation Methodologies

**G-Eval** (Liu et al., 2023) introduced the concept of using LLMs as judges with chain-of-thought evaluation criteria. We adapt this methodology for multi-agent task assessment.

**DeepEval** provides an open-source framework for LLM application testing with built-in metrics for relevance, coherence, and faithfulness.

---

## 3. System Architecture

### 3.1 Architectural Overview

VibeTeam employs a two-tier architecture consisting of a **Gateway** (message routing) and an **Agent Service** (agent execution):

```
+------------------------+     +------------------+     +------------------+
|  External Platforms    |     |     Gateway      |     |  Agent Service   |
|  (Slack/Discord/       | --> |  (Message Router)| --> |  (OpenHands)     |
|   GitHub/Gmail)        |     |                  |     |                  |
+------------------------+     +------------------+     +------------------+
                                       |
                                       v
                               +------------------+
                               |   PostgreSQL     |
                               | (Subscriptions)  |
                               +------------------+
```

### 3.2 Agent Roster

We deploy five specialized agents, each with distinct responsibilities and toolsets:

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `/SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `/ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `/SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `/ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | `/MarketingManager` | Social media, announcements, content | Chrome DevTools MCP |

### 3.3 Thread-Based Subscription Model

Our core innovation is the **thread-based subscription model**, which tracks agent involvement at the thread level:

```sql
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,        -- slack, discord, github_issue
    thread_id VARCHAR(255) NOT NULL,    -- unique thread identifier
    agent_role VARCHAR(50) NOT NULL,    -- software_engineer, etc.
    session_id UUID NOT NULL,           -- link to agent session
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
```

**Subscription Rules:**

1. **Thread Activation**: A thread becomes "active" when `@VibeTeam` is mentioned.
2. **Agent Subscription**: `/RoleName` mentions subscribe that agent to the thread.
3. **Persistent Subscription**: Once subscribed, an agent receives ALL subsequent messages.
4. **Handoff Detection**: The router parses agent responses for `/OtherAgent` mentions.

### 3.4 Message Flow Example

Consider a customer support escalation scenario:

```
User: @VibeTeam /SupportEngineer customer reports GenAI Gateway 400 errors
       |
       v
Router: 1. Detect @VibeTeam -> track thread
        2. Parse /SupportEngineer -> subscribe agent
        3. React with :eyes: emoji
        4. Forward to SupportEngineer
       |
       v
SupportEngineer: [checks Sentry] Found 127 errors from auth-service.
                 Stack trace shows JWT validation failure.
                 /ReleaseEngineer this looks like a deployment issue.
       |
       v
Router: Detects /ReleaseEngineer in agent message -> subscribes ReleaseEngineer
       |
       v
ReleaseEngineer: [checks kubectl] The auth-service was updated at 8am.
                 Rolling back to previous version... Done.
                 @SupportEngineer service restored, please verify with customer.
```

This flow demonstrates:
- **Natural invocation**: User mentions agent like a human team member
- **Autonomous investigation**: SupportEngineer uses Sentry without prompting
- **Context-preserving handoff**: Technical findings passed to ReleaseEngineer
- **Collaborative resolution**: ReleaseEngineer loops back after taking action

---

## 4. Natural Interaction Patterns

### 4.1 The /RoleName Protocol

We adopt a slash-command syntax (`/RoleName`) for agent invocation, chosen for several reasons:

1. **Familiarity**: Resembles Slack slash commands, familiar to users
2. **Parsability**: Easy regex pattern matching for routing
3. **Distinctiveness**: Clearly different from @user mentions
4. **Role-based**: Invokes by function, not individual identity

**Pattern Recognition:**

```python
ROLE_PATTERN = re.compile(
    r'/(SoftwareEngineer|ReleaseEngineer|SupportEngineer|ProductManager|MarketingManager)',
    re.IGNORECASE
)
```

### 4.2 Emoji Reactions as Status Signals

We use emoji reactions to communicate agent status without cluttering the conversation:

| Emoji | Meaning |
|-------|---------|
| :eyes: | Message acknowledged, agent is reading |
| :hourglass: | Agent is working on the task |
| :white_check_mark: | Task completed |
| :question: | Agent needs clarification |

### 4.3 Role Prefix Convention

All agent messages are prefixed with `[RoleName]` to clearly identify the responding agent:

```
[SupportEngineer] I've investigated the issue using Sentry...
[ReleaseEngineer] Deployment rolled back successfully...
```

This convention:
- Enables humans to quickly identify which agent is speaking
- Allows agents to reference each other's statements
- Provides audit trail for accountability

---

## 5. Handoff and Delegation Mechanisms

### 5.1 Explicit Handoffs

An **explicit handoff** occurs when an agent directly mentions another agent:

```
[SupportEngineer] This requires code changes. /SoftwareEngineer can you fix the
validation logic in auth-service/jwt.py line 45?
```

The router:
1. Parses the `/SoftwareEngineer` mention
2. Subscribes SoftwareEngineer to the thread
3. Forwards the full thread context to the new agent

### 5.2 Context Preservation During Handoffs

A critical challenge in multi-agent systems is context loss during handoffs. Our architecture addresses this through:

1. **Full Thread Replay**: When an agent joins a thread, it receives all previous messages.
2. **Session Persistence**: Each agent maintains a session per thread with conversation history.
3. **Workspace Continuity**: Agents share a persistent workspace directory for file operations.

**Session Key Format:**
```
{framework}:{role}:{source}:{thread_id}
```

Example: `openhands:software_engineer:slack:1234567890.123456`

### 5.3 The send_message Tool

Every agent receives a pre-configured `send_message` tool that:

1. Prefixes messages with `[RoleName]` for identification
2. Posts to the correct thread using stored credentials
3. Triggers router processing of any `/RoleName` mentions

```python
class SendMessageTool:
    def __init__(self, source, thread_id, channel_id, bot_token, role_prefix):
        self.source = source
        self.thread_id = thread_id
        self.channel_id = channel_id
        self.bot_token = bot_token
        self.role_prefix = role_prefix
    
    async def execute(self, content: str) -> dict:
        prefixed = f"[{self.role_prefix}] {content}"
        if self.source == "slack":
            await self._send_slack(prefixed)
        elif self.source == "discord":
            await self._send_discord(prefixed)
        return {"success": True, "message": prefixed}
```

### 5.4 Handoff Chains

Complex tasks may involve multiple handoffs forming a **handoff chain**:

```
User -> SupportEngineer -> ReleaseEngineer -> SoftwareEngineer -> ReleaseEngineer
```

Each agent in the chain:
1. Receives full thread context
2. Performs its specialized function
3. Hands off with specific findings

Our architecture caps handoff chains at a configurable depth (default: 3) to prevent infinite loops.

---

## 6. Evaluation Framework

### 6.1 DeepEval with G-Eval Methodology

We evaluate agent performance using **DeepEval** with **G-Eval** (LLM-as-judge) methodology. G-Eval uses chain-of-thought prompting to have an LLM evaluate agent outputs against defined criteria.

**Why G-Eval?**

1. **Nuanced Assessment**: LLMs can evaluate semantic quality, not just keyword matching
2. **Custom Criteria**: We define domain-specific evaluation rubrics
3. **Scalable**: Automated evaluation enables continuous testing
4. **Explainable**: LLM provides reasoning for scores

### 6.2 Evaluation Metrics

We define six core metrics, each with specific evaluation criteria:

| Metric | Threshold | Description |
|--------|-----------|-------------|
| **TaskCompletion** | 0.7 | Did the agent complete the requested task? |
| **HandoffQuality** | 0.7 | Was context preserved during handoff? |
| **ResponseTime** | < 60s | Time from message receipt to first response |
| **Professionalism** | 0.7 | Clear, concise, professional communication |
| **ToolUsage** | 0.7 | Were appropriate tools used correctly? |
| **ContextPreservation** | 0.7 | Did agent maintain thread context? |

### 6.3 Custom G-Eval Metric Implementation

Example of a custom G-Eval metric for investigation quality:

```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

def create_investigation_quality_metric(model):
    return GEval(
        name="InvestigationQuality",
        criteria=(
            "Did the SupportEngineer ACTUALLY investigate the issue using Sentry? "
            "A proper investigation MUST include: "
            "(1) Using Sentry tool to check error patterns, counts, and stack traces; "
            "(2) Reporting SPECIFIC findings from the investigation; "
            "(3) Either resolving OR handing off with specific technical details. "
            "A generic 'triage checklist' is a FAILURE."
        ),
        evaluation_steps=[
            "Check if the agent used Sentry tool",
            "Verify SPECIFIC findings were reported",
            "Check if response contains actual results vs generic advice",
            "If no specific findings from Sentry, score < 0.5",
            "A checklist without execution should score < 0.3",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT, 
            LLMTestCaseParams.ACTUAL_OUTPUT
        ],
        threshold=0.70,
        model=model,
    )
```

### 6.4 End-to-End Test Flow

Our E2E evaluation follows this flow:

```
+------------+     +----------------+     +----------------+
|   pytest   | --> |  Slack API     | --> | Slack Webhook  |
| (test)     |     |  POST message  |     | (microservice) |
+------------+     +----------------+     +----------------+
                                                  |
                          routes /SupportEngineer |
                                                  v
                                          +----------------+
                                          | OpenHands      |
                                          | Agent Service  |
                                          +----------------+
                                                  |
                          responds via send_message tool   |
                                                  v
                                          +----------------+
                                          |  Slack API     |
                                          |  thread_ts: X  |
                                          +----------------+
                                                  |
                          handoff to /ReleaseEngineer      |
                                                  v
                                          +----------------+
                                          | ReleaseEngineer|
                                          | processes...   |
                                          +----------------+
                                                  |
                                                  v
+------------+     +----------------+
|   pytest   | <-- |  GET thread    |
| DeepEval   |     |  messages      |
| evaluate() |     +----------------+
+------------+
      |
      v
  ASSERT: HandoffQuality >= 0.7
  ASSERT: TaskCompletion >= 0.7
```

### 6.5 Test Scenario Example

```python
class TestHandoffChain:
    """Test multi-agent handoff scenarios with DeepEval."""
    
    @pytest.mark.asyncio
    async def test_support_to_release_handoff(self, mock_slack, gpt52_evaluator):
        """
        Scenario: Customer reports outage, Support hands off to Release.
        """
        # Arrange
        user_message = "Customer reports GenAI Gateway returning 500 errors"
        
        # Act
        support_response = await run_agent("support_engineer", user_message)
        release_response = await run_agent("release_engineer", support_response)
        
        # Evaluate with DeepEval
        test_case = LLMTestCase(
            input=user_message,
            actual_output=f"{support_response}\n\n{release_response}",
            expected_output="Support investigates, hands off to Release who fixes",
        )
        
        handoff_metric = GEval(
            name="HandoffQuality",
            criteria="Was the handoff context-preserving and actionable?",
            threshold=0.7,
            **gpt52_evaluator,
        )
        
        # Assert
        results = evaluate([test_case], [handoff_metric])
        assert results.passed, f"Evaluation failed: {results.summary}"
```

### 6.6 Agent-Specific Thresholds

Different agents have different threshold requirements based on their role:

| Agent | TaskCompletion | HandoffQuality | Professionalism |
|-------|----------------|----------------|-----------------|
| SoftwareEngineer | >= 0.75 | >= 0.70 | >= 0.70 |
| ReleaseEngineer | >= 0.75 | >= 0.70 | >= 0.70 |
| SupportEngineer | >= 0.80 | >= 0.75 | >= 0.80 |
| ProductManager | >= 0.70 | >= 0.70 | >= 0.80 |
| MarketingManager | >= 0.70 | >= 0.65 | >= 0.85 |

**Rationale**: SupportEngineer has higher thresholds due to customer-facing nature. MarketingManager has highest Professionalism threshold due to public communication responsibility.

---

## 7. Implementation Details

### 7.1 Agent Framework: OpenHands

We currently use **OpenHands** as our primary agent framework due to:

1. **Full Tool Support**: Shell, Git, GitHub, browser automation
2. **Session Persistence**: Agents maintain state across interactions
3. **Workspace Management**: Persistent directories for file operations
4. **LLM Flexibility**: Supports Azure OpenAI, Anthropic, local models

### 7.2 Message Routing Implementation

```python
class Router:
    ROLE_PATTERN = re.compile(
        r'/(SoftwareEngineer|ReleaseEngineer|SupportEngineer|'
        r'ProductManager|MarketingManager)',
        re.IGNORECASE
    )
    
    async def route_message(self, message: UnifiedMessage) -> list[str]:
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

### 7.3 Bot Message Handling for Handoffs

A critical design decision is processing the bot's own messages to detect handoffs:

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
        return
    
    # Process user messages normally
    await router.route_message(message)
```

---

## 8. Experimental Results

### 8.1 Test Scenarios

We evaluated our system across five primary scenarios:

| Scenario | Agents Tested | Key Metrics |
|----------|---------------|-------------|
| Slack Routing | All agents | TaskCompletion, ResponseTime |
| Discord Routing | All agents | TaskCompletion, ResponseTime |
| GitHub Issue Triage | SWE, PM | TaskCompletion, Professionalism |
| Handoff Chain | Support -> Release -> Support | HandoffQuality, ContextPreservation |
| Sentry Alert | Support, Release | TaskCompletion, ToolUsage |

### 8.2 Evaluation Results

**Aggregate Performance (n=50 test runs):**

| Metric | Mean Score | Std Dev | Pass Rate |
|--------|------------|---------|-----------|
| TaskCompletion | 0.78 | 0.12 | 82% |
| HandoffQuality | 0.74 | 0.15 | 76% |
| Professionalism | 0.81 | 0.09 | 88% |
| ToolUsage | 0.72 | 0.18 | 71% |
| ContextPreservation | 0.76 | 0.11 | 79% |

**Per-Agent Performance:**

| Agent | TaskCompletion | HandoffQuality | Overall |
|-------|----------------|----------------|---------|
| SoftwareEngineer | 0.79 | 0.73 | 0.77 |
| ReleaseEngineer | 0.77 | 0.72 | 0.75 |
| SupportEngineer | 0.81 | 0.78 | 0.80 |
| ProductManager | 0.74 | 0.71 | 0.73 |
| MarketingManager | 0.72 | 0.68 | 0.71 |

### 8.3 Observations

1. **SupportEngineer performs best** on customer-facing metrics, likely due to training emphasis on empathy and clear communication.

2. **HandoffQuality varies by complexity**: Simple handoffs (Support -> Release) score higher than complex chains (Support -> SWE -> Release -> Support).

3. **Tool usage is the weakest metric**: Agents sometimes describe actions without executing them, particularly when Sentry or kubectl access is unclear.

4. **Response latency averages 45 seconds**, well under our 60-second threshold.

---

## 9. Discussion

### 9.1 Advantages of Our Approach

**Human Visibility**: All agent activities occur in existing communication channels, enabling:
- Real-time oversight by human team members
- Easy intervention when agents make mistakes
- Natural audit trail in chat history

**Familiar Patterns**: Using @mentions and threads leverages existing team habits:
- No new interfaces to learn
- Agents feel like team members, not tools
- Gradual trust building through transparency

**Emergent Coordination**: Thread-based subscriptions enable:
- Dynamic team formation per task
- No upfront specification of agent relationships
- Organic handoff chains based on actual needs

### 9.2 Limitations

**Platform Dependency**: Our architecture is tightly coupled to Slack/Discord APIs:
- Rate limits may affect response times
- API changes require system updates
- Offline operation is not possible

**Context Window Limits**: Long threads may exceed LLM context windows:
- We currently truncate to recent messages
- Future work could use summarization or RAG

**Evaluation Subjectivity**: G-Eval scores depend on the judge LLM:
- Different judge models may produce different scores
- Criteria wording significantly affects results

### 9.3 Future Work

1. **Cross-Platform Threads**: Enable threads spanning Slack and GitHub issues.
2. **Agent Memory**: Long-term memory for recurring issues and solutions.
3. **Learning from Feedback**: Train agents on human corrections in threads.
4. **Capability Discovery**: Agents dynamically discover each other's capabilities.

---

## 10. Conclusion

We have presented VibeTeam, a multi-agent AI system that enables natural collaboration between specialized agents through existing human communication platforms. Our thread-based subscription architecture demonstrates that effective multi-agent coordination can emerge from simple mention-based invocations without centralized orchestration.

Key findings:
1. **/RoleName mentions provide a natural invocation mechanism** that is both parsable by systems and intuitive for humans.
2. **Thread-based subscriptions preserve context** across handoffs better than message-level routing.
3. **DeepEval with G-Eval enables meaningful evaluation** of agentic behaviors through custom criteria.
4. **Human visibility is achievable without sacrificing automation**, making this approach suitable for production environments.

Our hypothesis that human communication patterns can serve as effective coordination primitives for AI agents is supported by empirical results showing 75%+ task completion rates and context preservation during handoffs.

---

## References

1. Wu, Q., et al. (2023). "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." Microsoft Research.

2. Liu, Y., et al. (2023). "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment." arXiv:2303.16634.

3. Hendler, J., et al. (1995). "An Introduction to Multi-Agent Systems." Addison-Wesley.

4. OpenHands Project. (2024). "OpenHands: Open Hands Framework for AI Agents." https://github.com/all-hands-ai/openhands

5. DeepEval. (2024). "DeepEval: The Open-Source LLM Evaluation Framework." https://github.com/confident-ai/deepeval

6. CrewAI. (2024). "CrewAI: Framework for Orchestrating Role-playing AI Agents." https://github.com/joaomdmoura/crewAI

7. Park, J.S., et al. (2023). "Generative Agents: Interactive Simulacra of Human Behavior." Stanford University.

---

## Appendix A: Configuration Reference

### Environment Variables

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

# Optional
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

### Running Evaluation Tests

```bash
# Install DeepEval
pip install deepeval>=0.21.0

# Set environment variables
export AZURE_API_KEY="your-key"
export AZURE_API_BASE="https://your-endpoint.openai.azure.com"

# Run all E2E evaluation tests
pytest tests/e2e/ -v -s

# Run with DeepEval dashboard reporting
deepeval test run tests/e2e/

# Generate evaluation report
python scripts/run_evaluation.py --output results/eval_report.json
```

---

## Appendix B: Thread ID Formats

| Source | Thread ID Format | Example |
|--------|------------------|---------|
| Slack | `{thread_ts}` | `1234567890.123456` |
| Discord | `{channel_id}:{message_id}` | `123456789:987654321` |
| GitHub Issue | `{repo}:{issue_number}` | `VibeTechnologies/VibeWebAgent:345` |
| GitHub PR | `{repo}:pr:{pr_number}` | `VibeTechnologies/VibeWebAgent:pr:123` |

---

## Appendix C: G-Eval Metric Definitions

### TaskCompletion

```python
GEval(
    name="TaskCompletion",
    criteria=(
        "Did the agent complete the requested task? Consider: "
        "(1) Tool usage - did the agent use appropriate tools? "
        "(2) Output quality - is the result correct and complete? "
        "(3) User intent - was the user's underlying goal satisfied?"
    ),
    threshold=0.7,
)
```

### HandoffQuality

```python
GEval(
    name="HandoffQuality", 
    criteria=(
        "Was context preserved during handoff? Did the receiving agent "
        "understand the task without re-explanation? Consider: "
        "(1) Technical context - were relevant findings passed along? "
        "(2) Action items - were clear next steps specified? "
        "(3) Continuity - did the handoff feel like a natural transition?"
    ),
    threshold=0.7,
)
```

### Professionalism

```python
GEval(
    name="Professionalism",
    criteria=(
        "Was communication clear, concise, and professional? Consider: "
        "(1) Tone - appropriate for the audience (internal team vs customer)? "
        "(2) Clarity - easy to understand without jargon overload? "
        "(3) Completeness - all necessary information included?"
    ),
    threshold=0.7,
)
```
