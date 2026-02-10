# VibeTeam Agent Architecture Exploration

## Goal
Explore and document the VibeTeam agent architecture to understand:
1. Agent structure (`agents/` directory)
2. Handoff mechanisms
3. Context passing
4. Available tools

## Tasks
- [x] Explore `agents/openhands/` structure
- [x] Explore `agents/autogen/` and `agents/crewai/` (if populated)
- [x] Identify handoff patterns (grep for mentions, roles)
- [x] Identify tool access patterns
- [x] Document findings

## Findings

### 1. Agent Structure
The repository supports multiple agent frameworks with a unified interface:
- **OpenHands** (`agents/openhands/`): The primary implementation. Uses `server.py` (FastAPI) and `team.py` (orchestrator). Individual agents (`software_engineer.py`, etc.) wrap `openhands.sdk` components.
- **AutoGen** (`agents/autogen/`): Uses `autogen_agentchat` with `SelectorGroupChat` for orchestration.
- **CrewAI** (`agents/crewai/`): Uses `crewai` `Crew` and `Process` for orchestration.

### 2. Handoff Mechanisms
- **OpenHands**: Text-based `@mention` system.
    - Initial routing: `team.py` parses `@Role` from the user task.
    - Mid-task handoff: Agents are instructed to "@mention" other roles in their text response. The system (likely the gateway or a loop not fully seen in `team.py`) interprets this.
    - Explicit instruction in `software_engineer.py`: "If you need to hand off, tag the *other* specific role".
- **AutoGen**: Uses `SelectorGroupChat` which dynamically selects the next speaker based on conversation history and a selector prompt. Terminates with "TASK_COMPLETE".
- **CrewAI**: Supports both single-agent routing (via keywords/@mentions) and a fixed multi-agent workflow (Analyze -> Execute -> Review) defined in `crew.py`.

### 3. Context Passing
- **OpenHands**:
    - **Explicit Injection**: The `run()` method in `software_engineer.py` actively fetches context (e.g., `kubectl` logs, GitHub issue details) and injects it into the system prompt *before* the agent starts.
    - **Session Storage**: Sessions are stored in PostgreSQL/Redis (implied by `agents.sessions` usage).
- **AutoGen/CrewAI**: Rely more on the framework's native conversation history management.

### 4. Available Tools
- **OpenHands**: Heavy reliance on `TerminalTool` (shell access) and `FileEditorTool`.
    - **SoftwareEngineer**: Has full shell access, uses `gh` CLI (with mandatory output redirection), `grep`, and `git`.
- **AutoGen**: Uses specific Python functions exposed as tools (e.g., `execute_shell`, `web_search`, `get_sentry_issues`).
- **CrewAI**: Wraps similar functionality in CrewAI Tool classes.

### 5. Key Implementation Details
- **Gateway**: `vibeteam/gateway/routes/slack.py` (referenced in old plan) seems to be the entry point that formats the task and potentially handles the response parsing for handoffs.
- **Unified Interface**: All frameworks expose a `create_team(config)` factory and a `run(task)` method, allowing the system to swap backends easily.
