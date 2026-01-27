# Agent-to-Agent Communication: Problem & Solutions

*Exploring multi-agent orchestration frameworks for VibeTeam*

---

## The Problem

We're building an AI team (VibeTeam) where multiple specialized agents work together:

| Agent | Tools | Knowledge |
|-------|-------|-----------|
| **SoftwareEngineer** | GitHub, Bash, Code | Codebase, architecture docs |
| **ReleaseEngineer** | GitHub, Bash, Sentry | Release process, changelog |
| **ProductManager** | GitHub Issues, Langfuse | Roadmap, customer requests |
| **SupportEngineer** | Gmail, Docs | Customer tickets, FAQ |
| **MarketingManager** | Twitter, LinkedIn | Brand guidelines, announcements |

### Key Requirements

1. **Different tools per agent** - SoftwareEngineer needs Bash, ProductManager doesn't
2. **Different knowledge bases** - Each agent knows different parts of the system
3. **Agent-to-agent handoffs** - SWE says "done, @ReleaseEngineer deploy please"
4. **Single process** - Not 6 running containers consuming resources
5. **On-demand instantiation** - Build agent only when needed, not pre-running
6. **Human-visible communication** - All agent-to-agent communication must happen in public channels (Slack, Discord, GitHub Issues) where human team members can observe and participate

### The Transparency Requirement

This is critical: **Agent communication must not be hidden in internal function calls or message queues.**

Why?
- **Observability** - Humans need to see what agents are discussing
- **Intervention** - Humans can jump in and correct course ("Actually, don't deploy yet")
- **Auditability** - Full history of agent decisions visible in Slack/GitHub
- **Collaboration** - Agents and humans work together in the same channels

```
#ai-team channel:

🤖 Turing (SoftwareEngineer): Fixed the login bug in auth.py. Created PR #45. 
                              @ReleaseEngineer please deploy to staging.

👤 CEO: Wait, let's also add the password reset fix before deploying.

🤖 Turing (SoftwareEngineer): Good point. Adding password reset fix to PR #45...

🤖 Turing (SoftwareEngineer): Done. PR #45 now includes both fixes.
                              @ReleaseEngineer ready for staging now.

🤖 Einstein (ReleaseEngineer): Deploying PR #45 to staging...
```

Most multi-agent frameworks fail this requirement - they route messages internally without exposing them to humans.

### The Core Question

> When SoftwareEngineer finishes and says "@ReleaseEngineer deploy this", how do we:
> 1. Detect the handoff request
> 2. Build ReleaseEngineer with different tools/knowledge
> 3. Pass conversation context
> 4. Continue the workflow

---

## Solutions Explored

### 1. OpenAI Swarm / Agents SDK

**Approach:** Agent returns another `Agent` object from a function to handoff.

```python
def transfer_to_release():
    return release_agent  # Handoff by returning agent

swe_agent = Agent(functions=[transfer_to_release, github_tool, bash_tool])
release_agent = Agent(functions=[sentry_tool, deploy_tool])
```

**Pros:**
- Extremely lightweight (~100 lines core)
- Easy to understand
- Each agent has distinct tool sets
- Stateless, on-demand

**Limitations:**
- No built-in supervisor/router
- No built-in state management
- Educational/experimental (Swarm deprecated, replaced by Agents SDK)
- Have to build orchestration yourself

---

### 2. LangGraph with langgraph-supervisor

**Approach:** Graph-based workflow with supervisor node routing to specialized agents.

```python
math_agent = create_react_agent(model, tools=[add, multiply], name="math")
research_agent = create_react_agent(model, tools=[search], name="research")

workflow = create_supervisor(
    [math_agent, research_agent],
    model=model,
    prompt="Route tasks to appropriate specialist"
)
```

**Pros:**
- Native supervisor pattern via `create_supervisor()`
- Each agent gets own tool set
- Flexible handoffs with state control
- Production-ready with persistence, streaming
- Single process, agents as graph nodes

**Limitations:**
- Higher complexity (full graph framework)
- Learning curve
- Heavier dependency

---

### 3. AutoGen

**Approach:** Pub/sub topics with factory-based agent instantiation.

```python
await AIAgent.register(
    runtime,
    type="software_engineer",
    factory=lambda: AIAgent(
        tools=[github_tool, bash_tool],
        delegate_tools=[transfer_to_release]
    )
)
```

**Pros:**
- Factory pattern = on-demand instantiation
- Different tools per agent
- Pub/sub decouples agents

**Limitations:**
- Complex runtime system
- Topic-based routing adds indirection
- Steeper learning curve
- Overkill for our use case

---

### 4. CrewAI

**Approach:** Role-based agents with sequential or hierarchical process.

```python
swe = Agent(role="Software Engineer", tools=[github, bash], allow_delegation=True)
release = Agent(role="Release Engineer", tools=[sentry, deploy])

crew = Crew(
    agents=[swe, release],
    process=Process.hierarchical,
    manager_llm="gpt-4"
)
```

**Pros:**
- Most "human-like" abstraction (roles, goals, backstories)
- Built-in delegation
- Easy to understand

**Limitations:**
- Agents are pre-instantiated (not on-demand)
- Less flexible handoff control
- Better for fixed team compositions

---

### 5. PydanticAI

**Approach:** Call another agent inside a tool function.

```python
@outer_agent.tool
async def delegate_to_release(ctx: RunContext[Deps]) -> str:
    result = await release_agent.run("deploy", deps=ctx.deps)
    return result.output
```

**Pros:**
- Full Pydantic type safety
- Clean, explicit delegation
- Lightweight

**Limitations:**
- Multi-agent patterns are manual
- No built-in supervisor
- Better for single agents

---

## Comparison Matrix

| Feature | Swarm | LangGraph | AutoGen | CrewAI | PydanticAI |
|---------|-------|-----------|---------|--------|------------|
| Different tools per agent | ✅ | ✅ | ✅ | ✅ | ✅ |
| Built-in supervisor | ❌ | ✅ | ❌ | ✅ | ❌ |
| On-demand agents | ✅ | ✅ | ✅ | ❌ | ✅ |
| Single process | ✅ | ✅ | ✅ | ✅ | ✅ |
| Handoff mechanism | Function return | Command(goto) | Topic pub/sub | Delegation flag | Tool call |
| **Human-visible comms** | ❌ | ❌ | ❌ | ❌ | ❌ |
| Complexity | Very Low | Medium | High | Low | Low |
| Production-ready | ❌ | ✅ | ✅ | ✅ | ✅ |

### The Gap: Human-Visible Communication

**None of these frameworks natively support human-visible agent-to-agent communication.**

All frameworks route messages internally:
- **Swarm/Agents SDK**: Function returns agent object (internal)
- **LangGraph**: `Command(goto=agent)` updates graph state (internal)
- **AutoGen**: Topic pub/sub messages (internal)
- **CrewAI**: Delegation happens in memory (internal)
- **PydanticAI**: Agent called inside tool function (internal)

**Our requirement**: Messages must appear in Slack/Discord/GitHub where humans can see and intervene.

---

## The Real Solution: Slack/GitHub IS the Communication Layer

Instead of using a framework's internal communication, we use external channels:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Slack #ai-team channel                       │
│                                                                 │
│  All agent messages posted here                                 │
│  All agent @mentions trigger other agents                       │
│  Humans see everything, can participate                         │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VibeTeam Supervisor                          │
│                                                                 │
│  1. Watches Slack for /commands and @mentions                   │
│  2. Builds agent on-demand (tools + knowledge)                  │
│  3. Agent executes and posts response to Slack                  │
│  4. If response contains @Agent, triggers next agent            │
│  5. Loop continues in public channel                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight**: The multi-agent framework handles agent configuration (tools, knowledge, prompts). But communication happens through Slack/GitHub, not internal message passing.

---

## Revised Recommendation

### Use LangGraph for Agent Configuration, Slack for Communication

**LangGraph provides:**
- Different tools per agent via `create_react_agent()`
- On-demand agent instantiation
- State management within a single agent's execution

**Slack provides:**
- Human-visible agent-to-agent communication
- Human intervention points
- Audit trail
- @mention-based routing

**We build:**
- Supervisor that watches Slack
- Routes to LangGraph agents based on @mentions
- Posts agent responses back to Slack
- Detects @mentions in responses to trigger next agent

---

## Architecture

```
Slack: /SoftwareEngineer fix the login bug

     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│ VibeTeam Supervisor                                             │
│                                                                 │
│ 1. Parse command → SoftwareEngineer                             │
│ 2. Build agent with LangGraph (tools: github, bash, code)       │
│ 3. Execute agent                                                │
│ 4. Post response to Slack:                                      │
│    "Fixed! PR #45 created. @ReleaseEngineer deploy please"      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Slack shows:
🤖 Turing (SoftwareEngineer): Fixed! PR #45 created. 
                              @ReleaseEngineer deploy please

CEO can intervene here: "Wait, add the other fix too"

     │ If no human intervention, supervisor sees @ReleaseEngineer
     ▼
┌─────────────────────────────────────────────────────────────────┐
│ VibeTeam Supervisor                                             │
│                                                                 │
│ 1. Detect @ReleaseEngineer in previous message                  │
│ 2. Build agent with LangGraph (tools: github, sentry, bash)     │
│ 3. Pass context: original request + SWE response                │
│ 4. Execute agent                                                │
│ 5. Post response to Slack                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Slack shows:
🤖 Einstein (ReleaseEngineer): Deployed PR #45 to staging. 
                               Tests passing. Ready for production.
```

---

## Next Steps

1. Keep LangGraph for agent configuration (tools, prompts, execution)
2. Build Supervisor that integrates with Slack
3. All agent responses go to Slack (human-visible)
4. @mentions in Slack trigger agent handoffs
5. Humans can intervene at any point

---

## Research: Academic Foundations for Multi-Agent Communication

### Key Papers

| Paper | Authors | Key Contribution |
|-------|---------|------------------|
| **AutoGen** (arXiv:2308.08155) | Wu et al. (Microsoft) | Multi-agent conversation framework; agents are customizable, conversable |
| **CAMEL** (arXiv:2303.17760, NeurIPS 2023) | Li et al. | Role-playing inception prompting for autonomous agent cooperation |
| **CoELA** (arXiv:2307.02485, ICLR 2024) | Zhang et al. | Cognitive-inspired agents that plan, communicate, and cooperate in natural language |
| **Generative Agents** (arXiv:2304.03442) | Park et al. (Stanford/Google) | Memory architecture: observation, planning, reflection |
| **μACP** (arXiv:2601.00219, AAMAS 2026) | Minimal four-verb basis {PING, TELL, ASK, OBSERVE} for agent communication |
| **Agent Contracts** (arXiv:2601.08815) | Formal framework extending Contract Net Protocol with resource governance |

### Communication Architecture Patterns

#### Pattern 1: Message Passing (Explicit Communication)

Agents exchange discrete messages through defined channels (AutoGen, CAMEL, Slack).

- **Pros:** Transparent, auditable, human-readable, flexible topology
- **Cons:** Higher latency, token overhead

#### Pattern 2: Shared Memory / Blackboard

Agents read/write to a common knowledge store (Generative Agents' memory stream).

- **Pros:** Reduces redundant communication, enables implicit coordination
- **Cons:** Concurrency issues, less transparent

#### Pattern 3: Hybrid Approach (Recommended by Research)

Combine explicit messaging with shared context:

```
┌─────────────────────────────────────────────────────┐
│                 SHARED CONTEXT STORE                │
│  (Task state, artifacts, decisions, assignments)    │
└─────────────────────────────────────────────────────┘
         ▲                    ▲                 ▲
         │ read/write         │ read/write      │ read/write
    ┌────┴────┐          ┌────┴────┐       ┌────┴────┐
    │ Agent A │◄────────►│ Agent B │◄─────►│ Agent C │
    └─────────┘ messages └─────────┘       └─────────┘
```

### Why Natural Language Communication Works

From **CoELA** paper:
> "CoELA communicating in natural language can earn more trust and cooperate more effectively with humans."

From **μACP** paper:
> A minimal four-verb basis {PING, TELL, ASK, OBSERVE} is sufficient for semantic expressiveness.

**Reasons NL works for LLM agents:**
1. LLMs are native NL processors - no encoding/decoding overhead
2. Human interpretability - auditable, debuggable
3. Flexibility - handles ambiguity and context
4. Emergent behavior - agents develop communication conventions

### Human-Agent Teaming Research

**Trust Building Factors** (from CoELA, Generative Agents):
1. **Transparency** - Agents explain their reasoning
2. **Natural Language** - Human-readable communication
3. **Predictability** - Consistent behavior patterns
4. **Controllability** - Human can intervene/override

**Human-in-the-Loop Patterns:**

| Pattern | Description | Use Case |
|---------|-------------|----------|
| **Approval Gates** | Human approves before critical actions | Deployments, external comms |
| **Escalation** | Agent requests human help when uncertain | Complex decisions |
| **Monitoring** | Human observes, intervenes as needed | Continuous oversight |
| **Collaborative** | Human and agents work together | Creative tasks |

### Why Slack Aligns with Research

| Research Finding | Slack Alignment |
|-----------------|-----------------|
| Asynchronous event-driven (AutoGen v0.4) | ✅ Async by design |
| Natural language native (CAMEL, CoELA) | ✅ Text-based |
| Human-readable transparency | ✅ All messages visible |
| Shared memory pattern | ✅ Thread history acts as shared context |
| Human escalation points | ✅ Humans in same channel |

### Recommended Message Protocol

Based on μACP research, use typed intents with natural language content:

| Intent | Description | Example |
|--------|-------------|---------|
| `TELL` | Share information | "PR #45 is ready for review" |
| `ASK` | Request action/info | "@ReleaseEngineer deploy to staging" |
| `OBSERVE` | Monitor status | "Watching Sentry for errors" |
| `PING` | Acknowledge | "Acknowledged, starting deployment" |

---

## Questions for Discussion

1. Should agents be able to run in parallel, or always sequential?
2. How deep should handoff chains go before requiring human intervention?
3. Should we persist conversation state across Slack sessions?
4. Do we need different LLM models for different agents (cost optimization)?

---

## References

### Academic Papers (arXiv)
- 2308.08155 - AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation
- 2303.17760 - CAMEL: Communicative Agents for Mind Exploration
- 2309.07864 - The Rise and Potential of Large Language Model Based Agents: A Survey
- 2304.03442 - Generative Agents: Interactive Simulacra of Human Behavior
- 2307.02485 - CoELA: Building Cooperative Embodied Agents with LLMs
- 2601.00219 - μACP: Formal Calculus for Agent Communication
- 2601.08815 - Agent Contracts: Formal Framework for Resource-Bounded AI

### Industry Resources
- Microsoft AutoGen: https://github.com/microsoft/autogen
- LangGraph: https://blog.langchain.dev/langgraph-multi-agent-workflows/

---

*Last updated: January 2026*
