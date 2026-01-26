# Design Doc: Supervisor Agent with AutoGen Swarm Pattern

**Author:** VibeTeam  
**Date:** 2026-01-25  
**Status:** Proposed  
**Issue:** #21

---

## 1. Executive Summary

Implement a Supervisor Agent (Product Manager) that can orchestrate the VibeTeam using the AutoGen Swarm pattern. This enables:
- **Full message visibility**: Supervisor sees all sub-agent conversations
- **Tool-based handoffs**: Deterministic agent switching via `transfer_to_X` tools
- **Chat UI integration**: LibreChat as the user interface
- **Collaborative workflow**: Agents can request help from each other

### Key Design Decisions
1. **Pattern**: AutoGen Swarm (tool-based handoffs) over SelectorGroupChat (more control)
2. **Supervisor**: ProductManagerAgent becomes the orchestrator
3. **Shared State**: All messages stored in shared context accessible to supervisor
4. **LLM Provider**: Continue using LiteLLM (already multi-provider)

---

## 2. Current Architecture

### 2.1 Current Flow
```
User -> CLI -> VibeTeam.run(task) -> route_task(keywords) -> Agent.run()
```

**Limitations:**
- No shared message state between agents
- Keyword-based routing (not LLM-powered)
- No agent-to-agent communication
- Single-agent execution per task

### 2.2 Current Components

| Component | File | Purpose |
|-----------|------|---------|
| `BaseVibeAgent` | `vibeteam/agents/base.py` | Agent base class with LiteLLM |
| `VibeTeam` | `vibeteam/orchestrator.py` | Keyword-based task routing |
| Individual Agents | `vibeteam/agents/*.py` | Specialized agent implementations |

---

## 3. Target Architecture

### 3.1 Overview

```
User -> LibreChat -> Supervisor API -> SupervisorAgent -> Swarm Execution
                                            |
                                            v
                                    SharedMessageState
                                            |
                    +-------+-------+-------+-------+-------+
                    |       |       |       |       |       |
                   SWE    SRE   Release  Support  Marketer  PM
```

### 3.2 Core Components

#### 3.2.1 SharedMessageState
Shared context that all agents can read/write to:

```python
@dataclass
class SharedMessageState:
    """Shared message state for supervisor visibility."""
    
    messages: list[Message] = field(default_factory=list)
    current_agent: str = "supervisor"
    task_context: dict[str, Any] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: str(uuid4()))
    
    def add_message(self, role: str, content: str, agent_name: str | None = None):
        """Add a message to shared state."""
        self.messages.append(Message(
            role=role,
            content=content,
            name=agent_name,
            timestamp=datetime.utcnow(),
        ))
    
    def get_context_for_agent(self, agent_name: str) -> list[dict]:
        """Get relevant context for an agent."""
        return [
            {"role": m.role, "content": m.content, "name": m.name}
            for m in self.messages
        ]
```

#### 3.2.2 Transfer Tools (Swarm Pattern)

Each agent has tools to transfer to other agents:

```python
class TransferToSWETool(BaseTool):
    """Transfer task to Software Engineer."""
    
    name = "transfer_to_swe"
    description = "Transfer to Software Engineer for implementation, code review, or bug fixes"
    
    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task or request for the Software Engineer"
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context from the conversation"
                        }
                    },
                    "required": ["task"]
                }
            }
        }
    
    async def execute(self, task: str, context: str = "") -> ToolResult:
        # This doesn't execute directly - it signals a handoff
        return ToolResult(
            success=True,
            output=f"TRANSFER:swe:{task}",
            metadata={"target_agent": "swe", "context": context}
        )
```

Similar tools: `transfer_to_pm`, `transfer_to_sre`, `transfer_to_release`, `transfer_to_support`, `transfer_to_marketer`, `transfer_to_supervisor`

#### 3.2.3 SupervisorAgent

The Product Manager enhanced with orchestration capabilities:

```python
class SupervisorAgent(ProductManagerAgent):
    """
    Supervisor Agent - Orchestrates the VibeTeam.
    
    Based on ProductManager with added:
    - Transfer tools for delegation
    - Shared state management
    - Multi-turn conversation handling
    """
    
    name: str = "Curie (Supervisor)"
    profile: str = "Product Manager & Team Supervisor"
    goal: str = "Orchestrate the VibeTeam to accomplish user goals"
    
    def __init__(self, shared_state: SharedMessageState, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state
        
        # Add transfer tools
        self.add_tool(TransferToSWETool())
        self.add_tool(TransferToSRETool())
        self.add_tool(TransferToReleaseTool())
        self.add_tool(TransferToSupportTool())
        self.add_tool(TransferToMarketerTool())
    
    def _get_system_prompt(self) -> str:
        return """You are Curie, the Product Manager and Supervisor of VibeTeam.

Your role is to:
1. Understand user requests and break them into tasks
2. Delegate to appropriate team members using transfer tools
3. Synthesize results from team members
4. Provide final answers to the user

Team Members:
- SWE (Ada): Implementation, code review, bug fixes
- SRE (Heisenberg): Monitoring, incidents, Sentry errors
- Release (Jenkins): Deployments, versioning, changelogs
- Support (Watson): Customer issues, documentation
- Marketer (Bernays): Social media, announcements, content

Guidelines:
- Always explain your delegation decisions
- Summarize team member outputs for the user
- You can transfer back to yourself to synthesize
- If a task is simple, you can handle it directly
"""
```

#### 3.2.4 SwarmOrchestrator

Manages the swarm execution loop:

```python
class SwarmOrchestrator:
    """
    Orchestrates multi-agent execution using Swarm pattern.
    
    Features:
    - Tool-based agent handoffs
    - Shared message state
    - Maximum iteration limits
    - Langfuse tracing
    """
    
    def __init__(
        self,
        supervisor: SupervisorAgent,
        agents: dict[str, BaseVibeAgent],
        shared_state: SharedMessageState,
        max_iterations: int = 20,
    ):
        self.supervisor = supervisor
        self.agents = agents
        self.shared_state = shared_state
        self.max_iterations = max_iterations
        self.current_agent = supervisor
    
    async def run(self, user_message: str) -> str:
        """Run the swarm until completion or max iterations."""
        
        # Add user message to shared state
        self.shared_state.add_message("user", user_message)
        
        for iteration in range(self.max_iterations):
            # Run current agent
            response = await self.current_agent.run_with_state(
                self.shared_state
            )
            
            # Check for transfer signal
            if response.startswith("TRANSFER:"):
                _, target, task = response.split(":", 2)
                self.current_agent = self._get_agent(target)
                self.shared_state.current_agent = target
                self.shared_state.add_message(
                    "system",
                    f"Transferred to {target}: {task}",
                    agent_name=self.shared_state.current_agent
                )
                continue
            
            # Check if we're back at supervisor with a final answer
            if self.current_agent == self.supervisor and not self._is_transfer(response):
                self.shared_state.add_message("assistant", response, "supervisor")
                return response
        
        return "Maximum iterations reached. Please try a simpler request."
    
    def _get_agent(self, key: str) -> BaseVibeAgent:
        if key == "supervisor":
            return self.supervisor
        return self.agents.get(key, self.supervisor)
```

---

## 4. Message Flow Example

### User Request: "Analyze Sentry errors and fix any critical bugs"

```
1. User -> Supervisor: "Analyze Sentry errors and fix any critical bugs"

2. Supervisor thinks: "This needs SRE to check Sentry, then SWE to fix"
   Supervisor -> transfer_to_sre(task="Check Sentry for critical errors in last 24h")

3. SRE -> Sentry API -> Gets 3 critical errors
   SRE -> transfer_to_supervisor(result="Found 3 critical errors: #123, #124, #125")

4. Supervisor thinks: "Need SWE to fix these"
   Supervisor -> transfer_to_swe(task="Fix critical error #123: NullPointerException in auth")

5. SWE -> GitHub API -> Creates fix PR
   SWE -> transfer_to_supervisor(result="Created PR #456 fixing error #123")

6. Supervisor -> User: "Found 3 critical Sentry errors. Created PR #456 to fix the auth issue. 
   Shall I continue with errors #124 and #125?"
```

### Shared State After:
```json
{
  "messages": [
    {"role": "user", "content": "Analyze Sentry errors...", "name": null},
    {"role": "system", "content": "Transferred to sre: Check Sentry...", "name": "supervisor"},
    {"role": "assistant", "content": "Checking Sentry...", "name": "sre"},
    {"role": "tool", "content": "[{id: 123, title: 'NullPointer...'}]", "name": "sentry"},
    {"role": "assistant", "content": "Found 3 critical errors", "name": "sre"},
    {"role": "system", "content": "Transferred to supervisor", "name": "sre"},
    {"role": "system", "content": "Transferred to swe: Fix error #123", "name": "supervisor"},
    {"role": "assistant", "content": "Creating fix...", "name": "swe"},
    {"role": "tool", "content": "PR #456 created", "name": "github"},
    {"role": "system", "content": "Transferred to supervisor", "name": "swe"},
    {"role": "assistant", "content": "Found 3 critical Sentry errors...", "name": "supervisor"}
  ],
  "current_agent": "supervisor",
  "session_id": "abc-123"
}
```

---

## 5. API Design

### 5.1 Supervisor API Endpoint

For LibreChat integration:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    context: dict[str, Any] | None = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    agents_used: list[str]
    iteration_count: int

# Session storage (use Redis in production)
sessions: dict[str, SwarmOrchestrator] = {}

@app.post("/v1/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat with the VibeTeam Supervisor."""
    
    # Get or create session
    if request.session_id and request.session_id in sessions:
        orchestrator = sessions[request.session_id]
    else:
        shared_state = SharedMessageState()
        orchestrator = create_swarm_orchestrator(shared_state)
        sessions[shared_state.session_id] = orchestrator
    
    # Run the swarm
    response = await orchestrator.run(request.message)
    
    return ChatResponse(
        response=response,
        session_id=orchestrator.shared_state.session_id,
        agents_used=orchestrator.get_agents_used(),
        iteration_count=orchestrator.iteration_count,
    )

@app.get("/v1/sessions/{session_id}/history")
async def get_history(session_id: str):
    """Get conversation history for a session."""
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    return sessions[session_id].shared_state.messages
```

### 5.2 LibreChat Configuration

```yaml
# librechat.yaml
endpoints:
  custom:
    - name: "VibeTeam"
      apiKey: "${VIBETEAM_API_KEY}"
      baseURL: "http://localhost:8000/v1"
      models:
        default: ["vibeteam-supervisor"]
      titleConvo: true
      titleModel: "vibeteam-supervisor"
      dropParams: ["stop", "user"]
```

---

## 6. Langfuse Integration

All LLM calls are already traced via LiteLLM. Add session tracking:

```python
# In SwarmOrchestrator.run()
from langfuse import Langfuse

langfuse = Langfuse()

async def run(self, user_message: str) -> str:
    # Create trace for the entire swarm session
    trace = langfuse.trace(
        name="swarm_session",
        session_id=self.shared_state.session_id,
        metadata={
            "user_message": user_message,
            "agents": list(self.agents.keys()),
        }
    )
    
    for iteration in range(self.max_iterations):
        span = trace.span(
            name=f"iteration_{iteration}",
            metadata={"agent": self.current_agent.name}
        )
        
        response = await self.current_agent.run_with_state(...)
        
        span.end(output={"response": response})
    
    trace.update(
        output={"final_response": response},
        metadata={"iterations": iteration + 1}
    )
```

---

## 7. Implementation Plan

### Phase 1: Core Infrastructure (3 days)

| Task | Description | Effort |
|------|-------------|--------|
| 1.1 | Implement `SharedMessageState` class | 0.5d |
| 1.2 | Create transfer tools (`transfer_to_*`) | 1d |
| 1.3 | Implement `SwarmOrchestrator` | 1d |
| 1.4 | Unit tests for core components | 0.5d |

### Phase 2: Supervisor Agent (2 days)

| Task | Description | Effort |
|------|-------------|--------|
| 2.1 | Create `SupervisorAgent` extending PM | 0.5d |
| 2.2 | Update all agents with `run_with_state()` | 1d |
| 2.3 | Integration tests for swarm execution | 0.5d |

### Phase 3: API & Integration (3 days)

| Task | Description | Effort |
|------|-------------|--------|
| 3.1 | Create FastAPI supervisor endpoint | 1d |
| 3.2 | Session management (Redis) | 0.5d |
| 3.3 | LibreChat configuration | 0.5d |
| 3.4 | Langfuse trace enhancement | 0.5d |
| 3.5 | End-to-end testing | 0.5d |

### Phase 4: Polish & Deploy (2 days)

| Task | Description | Effort |
|------|-------------|--------|
| 4.1 | Error handling & edge cases | 0.5d |
| 4.2 | Documentation | 0.5d |
| 4.3 | K8s deployment manifests | 0.5d |
| 4.4 | Production deployment | 0.5d |

**Total: ~10 days**

---

## 8. File Structure

```
vibeteam/
  agents/
    base.py                    # Add run_with_state() method
    supervisor.py              # NEW: SupervisorAgent
    product_manager.py
    software_engineer.py
    ...
  tools/
    __init__.py
    transfer.py                # NEW: Transfer tools
  orchestrator.py              # Keep for backward compatibility
  swarm.py                     # NEW: SwarmOrchestrator
  state.py                     # NEW: SharedMessageState
  api/
    __init__.py
    main.py                    # NEW: FastAPI app
    models.py                  # NEW: Request/Response models
    session.py                 # NEW: Session management
```

---

## 9. Testing Strategy

### Unit Tests
```python
# tests/test_swarm.py

async def test_transfer_tool_execution():
    tool = TransferToSWETool()
    result = await tool.execute(task="Fix bug #123")
    assert result.output.startswith("TRANSFER:swe:")

async def test_shared_state_message_tracking():
    state = SharedMessageState()
    state.add_message("user", "Hello")
    state.add_message("assistant", "Hi!", agent_name="supervisor")
    assert len(state.messages) == 2

async def test_swarm_orchestrator_simple_flow():
    state = SharedMessageState()
    orchestrator = create_test_orchestrator(state)
    response = await orchestrator.run("What is 2+2?")
    assert "4" in response
```

### Integration Tests
```python
# tests/test_swarm_integration.py

async def test_supervisor_delegates_to_sre():
    """Test that Sentry-related tasks get delegated to SRE."""
    response = await swarm.run("Check Sentry for errors")
    assert "sre" in state.get_agents_used()

async def test_multi_agent_workflow():
    """Test a workflow involving multiple agents."""
    response = await swarm.run("Check Sentry errors and fix critical ones")
    agents_used = state.get_agents_used()
    assert "sre" in agents_used
    assert "swe" in agents_used
```

---

## 10. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Infinite transfer loops | High | Medium | Max iteration limit, loop detection |
| Context window overflow | High | Medium | Summarization, context pruning |
| Agent confusion on handoffs | Medium | Medium | Clear system prompts, examples |
| LLM hallucinating transfers | Medium | Low | Validate transfer targets |
| Session state loss | Medium | Low | Redis persistence, backup |

---

## 11. Future Enhancements

1. **Parallel Agent Execution**: Run multiple agents simultaneously for independent tasks
2. **Agent-to-Agent Direct Communication**: `@mention` syntax for direct requests
3. **Skills System**: OpenHands-style skills for progressive disclosure
4. **Memory**: Long-term memory across sessions
5. **Human-in-the-Loop**: Approval gates for sensitive operations

---

## 12. References

- [AutoGen Swarm Documentation](https://microsoft.github.io/autogen/docs/topics/swarm)
- [GitHub Issue #21](https://github.com/VibeTechnologies/VibeTeam/issues/21)
- [LibreChat Custom Endpoints](https://www.librechat.ai/docs/configuration/librechat_yaml/ai_endpoints)
- [Langfuse LiteLLM Integration](https://langfuse.com/docs/integrations/litellm)
