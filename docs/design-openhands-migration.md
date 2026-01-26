# Design Doc: Migration from MetaGPT to OpenHands SDK

**Author:** VibeTeam  
**Date:** 2026-01-25  
**Status:** Implemented  
**Issue:** #12

---

## Implementation Summary

This migration has been **completed**. OpenHands is now integrated and available via:

| Channel | Access | Status |
|---------|--------|--------|
| **Web UI** | [team.vibebrowser.app](https://team.vibebrowser.app) | Live |
| **Slack** | `@vibeteam` mention | Live |
| **GitHub** | `fix-me` label or `@openhands-agent` | Live |

### Deployed Components

- **K8s Deployment**: `k8s/base/openhands/` - OpenHands server with Local Runtime
- **GitHub Workflow**: `templates/github-workflows/openhands-resolver.yml`
- **Microagent Configs**: `templates/openhands-microagents/`

### Enabled Repositories

- VibeTechnologies/VibeWebAgent
- VibeTechnologies/vibe-mcp
- VibeTechnologies/VibeBrowserAppPage

See [OpenHands Integration Guide](openhands-integration.md) for usage instructions.

---

## 1. Executive Summary

Migrate VibeTeam from MetaGPT framework to OpenHands Software Agent SDK. This migration will provide better maintainability, state-of-the-art performance on coding tasks, and alignment with the broader OpenHands ecosystem used in production.

### Key Benefits
- **Better SWE Performance**: OpenHands achieves 77.6% on SWE-Bench vs MetaGPT's lower scores
- **Active Development**: OpenHands has 467+ contributors vs MetaGPT's slower update cycle
- **Production Ready**: Built-in Docker sandboxing, REST API, Kubernetes support
- **Tool Ecosystem**: Pre-built tools for terminal, file editing, web browsing, MCP
- **Model Agnostic**: Works with any LiteLLM-supported provider (Azure, OpenAI, Anthropic, etc.)

---

## 2. Current Architecture (MetaGPT)

### 2.1 Package Structure
```
vibeteam/
  __init__.py
  cli.py                    # CLI entrypoint
  team.py                   # VibeTeam orchestrator (extends metagpt.Team)
  roles/
    __init__.py
    base.py                 # VibeRole (extends metagpt.Role)
    product_manager.py      # ProductManager role
    software_engineer.py    # SoftwareEngineer role
    marketer.py             # Marketer role
    support_engineer.py     # SupportEngineer role
    reliability_engineer.py # ReliabilityEngineer role
    release_engineer.py     # ReleaseEngineer role
  connectors/
    __init__.py
    github.py               # GitHub API connector
    sentry.py               # Sentry API connector
    langfuse.py             # Langfuse observability connector
    gmail.py                # Gmail API connector
    health.py               # Health check connector
```

### 2.2 MetaGPT Dependencies
```python
from metagpt.roles import Role
from metagpt.actions import Action
from metagpt.schema import Message
from metagpt.context import Context
from metagpt.team import Team
```

### 2.3 Role Pattern (MetaGPT)
```python
class VibeRole(Role):
    name: str = Field(default="VibeRole")
    profile: str = Field(default="Team Member")
    goal: str = Field(default="Contribute to team success")
    model: str = Field(default="azure/gpt-5-2")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    async def _think(self) -> bool: ...
    async def _act(self) -> Message: ...
    async def _observe(self) -> int: ...
    async def _react(self) -> Message: ...

class SomeAction(Action):
    name: str = "SomeAction"
    PROMPT_TEMPLATE: str = "..."
    
    async def run(self, input: str) -> str:
        rsp = await self._aask(prompt)
        return rsp
```

### 2.4 Team Orchestration (MetaGPT)
```python
class VibeTeam(Team):
    def __init__(self, context, investment, include_roles):
        super().__init__(context=context, investment=investment)
        self.hire([ProductManager(), SoftwareEngineer(), ...])
    
    async def run_project(self, requirement: str) -> str:
        return await self.run(n_round=5, idea=requirement)
```

---

## 3. Target Architecture (OpenHands SDK)

### 3.1 Package Structure (Proposed)
```
vibeteam/
  __init__.py
  cli.py                    # CLI entrypoint (updated)
  team.py                   # VibeTeam orchestrator (new implementation)
  agents/                   # Renamed from roles/
    __init__.py
    base.py                 # BaseVibeAgent (extends openhands.sdk.Agent)
    product_manager.py      # ProductManager agent
    software_engineer.py    # SoftwareEngineer agent
    marketer.py             # Marketer agent
    support_engineer.py     # SupportEngineer agent
    reliability_engineer.py # ReliabilityEngineer agent
    release_engineer.py     # ReleaseEngineer agent
  tools/                    # Custom tools (new)
    __init__.py
    github.py               # GitHubTool (wraps connector)
    sentry.py               # SentryTool (wraps connector)
    langfuse.py             # LangfuseTool (wraps connector)
    gmail.py                # GmailTool (wraps connector)
    health.py               # HealthCheckTool (wraps connector)
  connectors/               # Keep connectors as-is (API wrappers)
    __init__.py
    github.py
    sentry.py
    langfuse.py
    gmail.py
    health.py
```

### 3.2 OpenHands Dependencies
```python
from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool
from openhands.tools.task_tracker import TaskTrackerTool
```

### 3.3 Agent Pattern (OpenHands)
```python
from openhands.sdk import Agent, Tool, LLM

class BaseVibeAgent:
    """Base class for VibeTeam agents."""
    
    def __init__(
        self,
        name: str,
        profile: str,
        goal: str,
        model: str = "azure/gpt-5-2",
        temperature: float = 0.3,
    ):
        self.name = name
        self.profile = profile
        self.goal = goal
        
        self.llm = LLM(
            model=model,
            api_key=os.environ.get("AZURE_API_KEY"),
            base_url=os.environ.get("AZURE_API_BASE"),
            temperature=temperature,
        )
        
        self.agent = Agent(
            llm=self.llm,
            tools=self._get_tools(),
            system_prompt=self._get_system_prompt(),
        )
    
    def _get_tools(self) -> list[Tool]:
        """Override in subclasses to define agent-specific tools."""
        return [
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
        ]
    
    def _get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.profile}.
Goal: {self.goal}
"""

    async def run(self, task: str, workspace: str = None) -> str:
        """Execute a task."""
        conversation = Conversation(
            agent=self.agent,
            workspace=workspace or os.getcwd(),
        )
        conversation.send_message(task)
        result = await conversation.run()
        return result
```

### 3.4 Custom Tool Pattern (OpenHands)
```python
from openhands.sdk import Tool
from openhands.sdk.tool import ToolResult

class SentryTool(Tool):
    """Tool for interacting with Sentry error tracking."""
    
    name = "sentry"
    description = "Fetch and manage Sentry issues"
    
    def __init__(self):
        self.connector = SentryConnector()
    
    async def fetch_issues(self, hours: int = 24, project: str = None) -> ToolResult:
        """Fetch unresolved Sentry issues."""
        issues = self.connector.fetch_unresolved_issues(hours=hours, project=project)
        return ToolResult(
            success=True,
            output=json.dumps([asdict(i) for i in issues], indent=2),
        )
    
    async def resolve_issue(self, issue_id: str, reason: str) -> ToolResult:
        """Resolve a Sentry issue."""
        self.connector.add_comment(issue_id, f"Resolved: {reason}")
        self.connector.resolve_issue(issue_id)
        return ToolResult(success=True, output=f"Issue {issue_id} resolved")
```

### 3.5 Team Orchestration (OpenHands)
```python
from openhands.sdk import Agent, Conversation

class VibeTeam:
    """VibeTeam - Autonomous AI team for SaaS development."""
    
    def __init__(self, include_agents: list[str] = None):
        self.agents = {}
        
        agent_map = {
            "pm": ProductManagerAgent,
            "swe": SoftwareEngineerAgent,
            "marketer": MarketerAgent,
            "support": SupportEngineerAgent,
            "sre": ReliabilityEngineerAgent,
            "release": ReleaseEngineerAgent,
        }
        
        include_agents = include_agents or list(agent_map.keys())
        
        for key in include_agents:
            if key in agent_map:
                self.agents[key] = agent_map[key]()
    
    async def run_task(self, task: str, agent_key: str = None) -> str:
        """Run a task with the appropriate agent."""
        if agent_key:
            agent = self.agents.get(agent_key)
            if agent:
                return await agent.run(task)
        
        # Auto-route based on task content
        agent = self._route_task(task)
        return await agent.run(task)
    
    def _route_task(self, task: str) -> BaseVibeAgent:
        """Route task to appropriate agent based on keywords."""
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["feature", "requirement", "prd"]):
            return self.agents.get("pm")
        elif any(kw in task_lower for kw in ["deploy", "release", "monitor"]):
            return self.agents.get("release")
        # ... more routing logic
        return self.agents.get("swe")  # Default to SWE
```

---

## 4. Migration Plan

### Phase 1: Foundation (Week 1)
| Task | Description | Effort |
|------|-------------|--------|
| 1.1 | Add `openhands-sdk` to dependencies | 0.5d |
| 1.2 | Create `vibeteam/tools/` directory structure | 0.5d |
| 1.3 | Implement `BaseVibeAgent` class | 1d |
| 1.4 | Convert connectors to OpenHands Tools | 2d |
| 1.5 | Update tests for new tool structure | 1d |

### Phase 2: Agent Migration (Week 2)
| Task | Description | Effort |
|------|-------------|--------|
| 2.1 | Migrate `ProductManager` role to agent | 1d |
| 2.2 | Migrate `SoftwareEngineer` role to agent | 1d |
| 2.3 | Migrate `Marketer` role to agent | 0.5d |
| 2.4 | Migrate `SupportEngineer` role to agent | 1d |
| 2.5 | Migrate `ReliabilityEngineer` role to agent | 0.5d |
| 2.6 | Migrate `ReleaseEngineer` role to agent | 1d |

### Phase 3: Team & CLI (Week 3)
| Task | Description | Effort |
|------|-------------|--------|
| 3.1 | Implement new `VibeTeam` orchestrator | 1d |
| 3.2 | Update CLI to use new agent system | 1d |
| 3.3 | Update k8s CronJobs to use new agents | 1d |
| 3.4 | Integration testing | 1d |
| 3.5 | Documentation update | 1d |

### Phase 4: Cleanup (Week 4)
| Task | Description | Effort |
|------|-------------|--------|
| 4.1 | Remove MetaGPT dependency | 0.5d |
| 4.2 | Remove old `roles/` directory | 0.5d |
| 4.3 | Final testing and validation | 1d |
| 4.4 | Update README and AGENTS.md | 0.5d |
| 4.5 | Release and deploy | 0.5d |

---

## 5. Mapping Table: MetaGPT to OpenHands

| MetaGPT Concept | OpenHands Equivalent | Notes |
|-----------------|---------------------|-------|
| `Role` | `Agent` | Base class for agents |
| `Action` | `Tool` | Discrete capabilities |
| `Message` | Conversation messages | Built into Conversation |
| `Team` | Custom `VibeTeam` class | Orchestrator pattern |
| `Context` | Workspace + Conversation | Execution context |
| `_aask()` | `llm.generate()` | LLM interaction |
| `_think()` | Built into Agent loop | Automatic |
| `_act()` | Tool execution | Via Conversation.run() |
| `_observe()` | Conversation history | Automatic |
| `hire()` | `__init__` with agents | Manual registration |

---

## 6. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Breaking changes in OpenHands SDK | High | Low | Pin SDK version, follow release notes |
| Different LLM interaction patterns | Medium | Medium | Thorough testing, keep old code for reference |
| K8s CronJobs may need updates | Medium | High | Test CronJobs in staging before prod |
| Lost functionality during migration | High | Medium | Parallel run old/new systems during transition |
| Team learning curve | Low | Low | Documentation and examples |

---

## 7. Success Criteria

1. **Functional Parity**: All existing features work identically
2. **Tests Pass**: All existing tests pass with new implementation
3. **No MetaGPT**: Zero MetaGPT imports in codebase
4. **K8s Working**: All CronJobs run successfully
5. **Performance**: No regression in LLM task performance
6. **Documentation**: README, AGENTS.md updated

---

## 8. Dependencies

### New Dependencies (pyproject.toml)
```toml
[project.dependencies]
openhands-sdk = "^1.2.0"
openhands-tools = "^1.2.0"
# Remove: metagpt
```

### Environment Variables (unchanged)
```bash
AZURE_API_KEY=...
AZURE_API_BASE=...
AZURE_API_VERSION=...
GITHUB_TOKEN=...
SENTRY_AUTH_TOKEN=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

---

## 9. Open Questions

1. **Multi-agent collaboration**: OpenHands doesn't have built-in multi-agent message passing like MetaGPT. Do we need this, or is sequential task routing sufficient?

2. **Workspace isolation**: Should each agent run in its own Docker workspace, or share a common workspace?

3. **Observability**: OpenHands has built-in tracing. Should we replace Langfuse integration or layer on top?

---

## 10. References

- [OpenHands SDK Documentation](https://docs.openhands.dev/sdk)
- [OpenHands GitHub Repository](https://github.com/OpenHands/software-agent-sdk)
- [MetaGPT Documentation](https://docs.deepwisdom.ai/main/en/)
- [VibeTeam Current Implementation](https://github.com/VibeTechnologies/VibeTeam)
