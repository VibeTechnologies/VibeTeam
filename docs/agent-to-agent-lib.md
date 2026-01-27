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
| Complexity | Very Low | Medium | High | Low | Low |
| Production-ready | ❌ | ✅ | ✅ | ✅ | ✅ |

---

## Recommendation

### Primary: LangGraph with langgraph-supervisor

Best fit because:
1. **Native supervisor pattern** - `create_supervisor()` is exactly what we need
2. **Different tools per agent** - Each `create_react_agent()` gets its own tool set
3. **On-demand** - Agents are graph nodes, invoked only when routed to
4. **Production-ready** - Memory, persistence, streaming built-in
5. **Flexible** - Can build complex hierarchies

### Alternative: OpenAI Agents SDK

If we want maximum simplicity:
- Build our own lightweight supervisor
- Very easy to understand and modify
- Each agent has distinct tools
- But need to implement orchestration ourselves

---

## Next Steps

1. Prototype with LangGraph supervisor pattern
2. Define agent configurations (tools, knowledge, prompts)
3. Implement Slack slash command integration
4. Test agent-to-agent handoffs

---

## Questions for Discussion

1. Should agents be able to run in parallel, or always sequential?
2. How deep should handoff chains go before requiring human intervention?
3. Should we persist conversation state across Slack sessions?
4. Do we need different LLM models for different agents (cost optimization)?

---

*Last updated: January 2026*
