# Multi-Framework Agent Comparison: OpenHands vs CrewAI vs AutoGen

This document compares three leading agent frameworks for building multi-agent AI systems. We implemented the same three agents across all frameworks to provide a practical, apples-to-apples comparison.

## Executive Summary

| Criteria | OpenHands | CrewAI | AutoGen |
|----------|-----------|--------|---------|
| **Best For** | Code-heavy tasks, SWE | Business workflows | Conversational AI |
| **Learning Curve** | Medium | Low | Medium-High |
| **Tool Integration** | Native MCP | Custom BaseTool | Async functions |
| **Multi-Agent** | Manual routing | Crew + Process | SelectorGroupChat |
| **Session Persistence** | Built-in | Manual | Manual |
| **Async Support** | Sync (wrap) | Sync (wrap) | Native async |

**Recommendation**: Use **OpenHands** for software engineering tasks, **CrewAI** for business process automation, and **AutoGen** for complex conversational multi-agent systems.

## Agents Implemented

We implemented three agents across all frameworks:

1. **ReleaseEngineer (Einstein)**: Shell commands, file operations, k3s deployment, GitHub
2. **MarketingManager (Ada)**: Web research, social media, content creation, sentiment analysis
3. **SupportEngineer (Grace)**: Email, calendar, Sentry errors, Langfuse traces

## Framework Deep Dive

### OpenHands

**Strengths:**
- Native MCP (Model Context Protocol) support for tool integration
- Built-in session persistence via `Conversation` with `persistence_dir`
- Strong SWE-Bench performance (77.6% on verified subset)
- Excellent for code generation and repository manipulation

**Weaknesses:**
- Synchronous by default (requires wrapping for async)
- SDK documentation still maturing
- Less flexible for non-coding tasks

**Code Pattern:**
```python
from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.tools.terminal import TerminalTool

agent = Agent(
    llm=LLM(model="azure/gpt-5-2", api_key=key, base_url=base),
    tools=[Tool(name=TerminalTool.name)],
    mcp_config=mcp_config,
    system_prompt=SYSTEM_PROMPT,
)

conversation = Conversation(
    agent=agent,
    workspace="/path/to/workspace",
    persistence_dir="./.sessions",
    conversation_id=session_id,
)
conversation.send_message(task)
conversation.run()
```

**Tool Integration:** Native MCP servers configured via JSON:
```python
mcp_config = {
    "mcpServers": {
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"]},
    }
}
```

---

### CrewAI

**Strengths:**
- Intuitive role/goal/backstory agent definition
- Built-in `Crew` orchestration with process types (sequential, hierarchical)
- 40+ built-in tools available
- Enterprise integrations (Gmail, Calendar, etc.)
- Lowest learning curve

**Weaknesses:**
- Custom tools require `BaseTool` subclass boilerplate
- Session persistence must be implemented manually
- Less control over agent-to-agent communication

**Code Pattern:**
```python
from crewai import Agent, Task, Crew, Process

agent = Agent(
    role="Release Engineer",
    goal="Deploy applications safely",
    backstory="You are Einstein, expert in k8s and CI/CD...",
    tools=[ShellTool(), FileReadTool()],
    verbose=True,
    llm="azure/gpt-5-2",
)

crew = Crew(
    agents=[agent1, agent2, agent3],
    tasks=[task1, task2, task3],
    process=Process.sequential,  # or Process.hierarchical
)
result = crew.kickoff()
```

**Tool Integration:** Custom `BaseTool` subclasses:
```python
class ShellTool(BaseTool):
    name: str = "shell"
    description: str = "Execute shell commands"

    def _run(self, command: str) -> str:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout
```

---

### AutoGen

**Strengths:**
- Native async support throughout
- Sophisticated multi-agent patterns (SelectorGroupChat, RoundRobinGroupChat, Swarm)
- Model-based speaker selection for dynamic routing
- Rich termination conditions (TextMention, MaxMessage, External)
- Best for complex conversational flows

**Weaknesses:**
- No native MCP support (tools are plain async functions)
- Steeper learning curve for multi-agent patterns
- API changed significantly from 0.2 to 0.4+

**Code Pattern:**
```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

model_client = AzureOpenAIChatCompletionClient(
    azure_deployment="gpt-5-2",
    model="gpt-5-2",
    api_version="2024-08-01-preview",
    azure_endpoint=endpoint,
    api_key=key,
)

agent = AssistantAgent(
    name="ReleaseEngineer",
    model_client=model_client,
    tools=[execute_shell, read_file, write_file],
    system_message=SYSTEM_PROMPT,
    description="Handles deployments and CI/CD",
)

team = SelectorGroupChat(
    participants=[agent1, agent2, agent3],
    model_client=model_client,
    termination_condition=TextMentionTermination("TASK_COMPLETE"),
)
result = await team.run(task="Deploy to production")
```

**Tool Integration:** Plain async functions with docstrings:
```python
async def execute_shell(command: str) -> str:
    """Execute a shell command and return the output.
    
    Args:
        command: The shell command to execute
        
    Returns:
        The command output (stdout + stderr)
    """
    result = await asyncio.to_thread(subprocess.run, command, shell=True, ...)
    return result.stdout
```

---

## Feature Comparison Matrix

### Agent Definition

| Feature | OpenHands | CrewAI | AutoGen |
|---------|-----------|--------|---------|
| System prompt | `system_prompt` | `backstory` + `goal` | `system_message` |
| Role definition | Implicit in prompt | Explicit `role` field | `name` + `description` |
| Tool attachment | `tools=[Tool(name=...)]` | `tools=[ToolInstance()]` | `tools=[async_func]` |
| Model config | `LLM(model=...)` | `llm="model_name"` | `model_client=Client()` |

### Multi-Agent Coordination

| Pattern | OpenHands | CrewAI | AutoGen |
|---------|-----------|--------|---------|
| Sequential | Manual | `Process.sequential` | `RoundRobinGroupChat` |
| Hierarchical | Manual | `Process.hierarchical` | `SelectorGroupChat` |
| Dynamic routing | `parse_mention()` | Task dependencies | Model-based selection |
| Handoffs | Manual | Task context | `HandoffMessage` (Swarm) |

### Session Management

| Feature | OpenHands | CrewAI | AutoGen |
|---------|-----------|--------|---------|
| Built-in persistence | Yes (`persistence_dir`) | No | No |
| Message history | Automatic | Manual | Manual |
| Session resume | `conversation_id` | Custom implementation | Custom implementation |

### Tool Ecosystem

| Category | OpenHands | CrewAI | AutoGen |
|----------|-----------|--------|---------|
| MCP servers | Native | Not supported | Not supported |
| Built-in tools | Terminal, FileEditor, Browser | 40+ tools | None (use functions) |
| Custom tools | Via MCP or SDK | `BaseTool` subclass | Async functions |
| Tool schemas | Automatic from MCP | Manual in class | From function signature |

---

## Implementation Insights

### 1. Routing Strategy

All frameworks required implementing @mention parsing for agent routing:

```python
def parse_mention(text: str) -> str | None:
    text_lower = text.lower()
    if "@releaseengineer" in text_lower or "@einstein" in text_lower:
        return "release_engineer"
    if "@marketingmanager" in text_lower or "@ada" in text_lower:
        return "marketing_manager"
    if "@supportengineer" in text_lower or "@grace" in text_lower:
        return "support_engineer"
    return None
```

AutoGen's `SelectorGroupChat` can replace this with model-based selection, but explicit mentions provide more predictable routing.

### 2. Session Key Design

We standardized session keys across frameworks:
```
{framework}:{role}:{context_type}:{context_id}
```

Examples:
- `autogen:release_engineer:issue:123`
- `crewai:marketing_manager:slack:C123456`
- `openhands:support_engineer:email:msg-789`

### 3. Azure OpenAI Configuration

Each framework handles Azure OpenAI differently:

**OpenHands:**
```python
LLM(model="azure/gpt-5-2", api_key=key, base_url=base)
```

**CrewAI:**
```python
llm="azure/gpt-5-2"  # Uses environment variables
```

**AutoGen:**
```python
AzureOpenAIChatCompletionClient(
    azure_deployment="gpt-5-2",
    model="gpt-5-2",
    api_version="2024-08-01-preview",
    azure_endpoint=endpoint,
    api_key=key,
)
```

### 4. Error Handling Patterns

- **OpenHands**: Exceptions bubble up from conversation
- **CrewAI**: Task results include success/failure status
- **AutoGen**: `TaskResult.messages` contains full conversation including errors

---

## Recommendations by Use Case

### Software Engineering Tasks
**Use OpenHands**
- Best SWE-Bench performance
- Native terminal and file editing
- MCP integration for GitHub, filesystem

### Business Process Automation
**Use CrewAI**
- Intuitive role/goal/backstory model
- Built-in process orchestration
- Extensive tool library

### Complex Conversational Systems
**Use AutoGen**
- Sophisticated multi-agent patterns
- Model-based speaker selection
- Native async support

### Hybrid Approach
For VibeTeam, we recommend:
1. **OpenHands** for ReleaseEngineer (code-heavy tasks)
2. **AutoGen** for team coordination (SelectorGroupChat)
3. **Shared session layer** (`agents/sessions.py`) for cross-framework state

---

## Performance Considerations

| Metric | OpenHands | CrewAI | AutoGen |
|--------|-----------|--------|---------|
| Cold start | ~2s | ~1s | ~1.5s |
| Tool call overhead | Low (MCP) | Medium (class) | Low (function) |
| Memory usage | Medium | Low | Medium |
| Token efficiency | High | Medium | High |

---

## Migration Path

If migrating between frameworks:

### OpenHands → AutoGen
1. Convert `Tool` definitions to async functions
2. Replace `Conversation` with `AssistantAgent.run()`
3. Implement custom session persistence

### CrewAI → AutoGen
1. Convert `BaseTool` classes to async functions
2. Replace `Crew` with `SelectorGroupChat` or `RoundRobinGroupChat`
3. Map `Process.hierarchical` to custom selector prompt

### AutoGen → OpenHands
1. Wrap async functions in MCP server or SDK Tool
2. Replace `SelectorGroupChat` with manual routing
3. Use built-in `Conversation` persistence

---

## Conclusion

All three frameworks are production-ready for multi-agent systems. The choice depends on:

1. **Task type**: OpenHands for coding, CrewAI for business, AutoGen for conversation
2. **Team expertise**: CrewAI has lowest learning curve
3. **Integration needs**: OpenHands for MCP, AutoGen for async
4. **Orchestration complexity**: AutoGen offers most sophisticated patterns

For VibeTeam's mix of engineering, marketing, and support tasks, a hybrid approach using the shared session layer provides flexibility to use the best framework for each agent role.

---

## References

- [OpenHands Documentation](https://docs.all-hands.dev/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/stable/)
- [GitHub Issue #29](https://github.com/VibeTechnologies/VibeTeam/issues/29)
