from __future__ import annotations

"""
SupportEngineer agent using OpenHands.

Capabilities:
- Gmail access via shared tools for email management
- Google Calendar via shared tools for scheduling
- Langfuse integration via shared tools for LLM observability
- Sentry integration for error tracking

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import re
import tempfile
from typing import Any

from agents.config import SUPPORT_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store
from agents.shared.calendar_tools import get_calendar_context
from agents.shared.docs_tools import get_docs_context

# Import shared tools for context injection
from agents.shared.gmail_tools import get_email_context
from agents.shared.langfuse_tools import get_langfuse_context
from agents.shared.sentry_tools import get_sentry_context


def fetch_sentry_context(hours: int = 24, limit: int = 10) -> str:
    """Fetch Sentry issues and format as context for the agent."""
    return get_sentry_context(hours=hours, limit=limit)


def fetch_gmail_context(max_results: int = 5) -> str:
    """Fetch Gmail context using shared tools."""
    return get_email_context(max_results=max_results)


def fetch_langfuse_context_wrapper(hours: int = 6) -> str:
    """Fetch Langfuse context using shared tools."""
    return get_langfuse_context(hours=hours)


def fetch_calendar_context_wrapper(days: int = 3) -> str:
    """Fetch Calendar context using shared tools."""
    return get_calendar_context(days=days)


def fetch_docs_context_wrapper(query: str) -> str:
    """Fetch documentation context using shared tools."""
    return get_docs_context(query=query, max_results=3)


def convert_numbered_lists_to_bullets(text: str) -> str:
    """Convert numbered lists to bullet points in task text.

    OpenHands interprets numbered lists (1. 2. 3.) as action steps to execute,
    causing empty LLM responses when tools are disabled. Converting to bullet
    points (-) allows OpenHands to treat them as items to discuss/answer instead.

    Args:
        text: The task text that may contain numbered lists

    Returns:
        Text with numbered lists converted to bullet points
    """
    # Pattern matches lines starting with optional whitespace, then number, period, space
    # Examples: "1. First item", "  2. Second item", "10. Tenth item"
    pattern = r"^(\s*)(\d+)\.\s+"
    return re.sub(pattern, r"\1- ", text, flags=re.MULTILINE)


try:
    from openhands.sdk import LLM, Agent, LocalConversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool

    OPENHANDS_AVAILABLE = True

    class AzureLLM(LLM):
        """LLM subclass that forces completion API for Azure OpenAI."""

        def uses_responses_api(self) -> bool:
            """Azure OpenAI doesn't support the Responses API."""
            return False

except ImportError:
    OPENHANDS_AVAILABLE = False
    LLM = None
    AzureLLM = None
    Agent = None
    LocalConversation = None
    Tool = None
    TerminalTool = None
    FileEditorTool = None


SUPPORT_ENGINEER_CONTEXT = """You are Grace, the Support Engineer for VibeTeam.

## YOUR INVESTIGATION WORKFLOW

You are responsible for INVESTIGATING issues. You have TWO sources of information:

### 1. Pre-Injected Data (Sentry/Gmail/Langfuse)
Look for sections below starting with "## Current Sentry Issues" - this is pre-fetched monitoring data.
- Report what you find: error messages, counts, timestamps
- If nothing matches the user's complaint, say so clearly

### 2. Kubernetes Cluster Access (USE THIS!)
You have kubectl access for READ-ONLY investigation. **Actually run these commands:**

```bash
# Check pod status
kubectl get pods -n vibeteam

# Check recent events for errors
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -20

# Check deployment logs for errors
kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100 --timestamps

# Check if there were recent deployments
kubectl rollout history deployment/vibeteam-gateway -n vibeteam
```

**IMPORTANT: You MUST run kubectl commands to investigate infrastructure issues.**
Do NOT just recommend checking logs - actually check them yourself!

## INVESTIGATION STEPS (DO ALL OF THESE)

1. **Check Sentry data** (pre-injected below) - report specific issues found
2. **Run kubectl get pods** - report pod status (Running, CrashLoopBackOff, etc.)
3. **Run kubectl get events** - look for recent errors, OOMKilled, restarts
4. **Run kubectl logs** - look for error patterns around the reported time
5. **Correlate findings** - match timestamps between Sentry, events, and logs

## OWNERSHIP: READ-ONLY Investigation

**YOU CAN:**
- Run kubectl get, describe, logs commands
- Query and report on cluster state
- Identify root causes from logs/events

**YOU CANNOT (hand off to ReleaseEngineer):**
- Rollback deployments
- Restart pods
- Scale deployments
- Apply any changes to the cluster

## HANDOFF TO RELEASEENGINEER FOR ACTIONS

After investigation, if action is needed, hand off with YOUR FINDINGS:

**Good handoff example:**
"Investigated the 400 errors:
- Sentry: No 400s captured (likely not instrumented)
- kubectl get pods: All pods Running
- kubectl get events: Found 'OOMKilled' on vibeteam-gateway at 08:05
- kubectl logs: Memory spike correlates with deployment at 08:00

Root cause: OOM after 08:00 deployment causing request failures.

@ReleaseEngineer Please rollback vibeteam-gateway to the previous version."

## CRITICAL: Communication is Handled By the System

DO NOT try to use Slack/email tools. Your text response is automatically posted.

## HANDOFF DECISION LOGIC (EVIDENCE-BASED)

**ONLY recommend ROLLBACK if you find EVIDENCE of problems:**
- Errors in logs (5xx, OOM, crashes) that correlate with deployment timing
- Failing pods, restarts, or OOMKilled events
- Sentry alerts showing errors started after deployment

**If NO evidence of problems found:**
- Report "Infrastructure appears healthy" with your findings
- Ask customer for more details: request IDs, timestamps, specific error messages
- Do NOT recommend rollback based solely on customer report timing

**Use SoftwareEngineer ONLY when:**
- Issue is clearly a long-standing code bug (NOT deployment-related)
- Customer confirms issue existed BEFORE recent deployments

## HANDOFF ROLES
- `@ReleaseEngineer` - for deployments, rollbacks, infrastructure ACTIONS (only if evidence supports)
- `@SoftwareEngineer` - for code bugs, logic errors
- `@ProductManager` - for product decisions

## CRITICAL: Evidence-Based Decisions
- If kubectl shows healthy pods, clean logs, no errors → report this clearly
- If Sentry shows no related issues → report this clearly  
- DO NOT recommend drastic actions (rollback) when no issues are found
- Unnecessary rollbacks waste engineering time and may cause downtime
"""


class OpenHandsSupportEngineer:
    """
    Support Engineer agent using OpenHands SDK.

    Uses OpenHands' agentic loop for customer support tasks.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or SUPPORT_ENGINEER_CONFIG

    def _create_llm(self) -> "LLM":
        """Create LLM with Azure configuration."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return AzureLLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,
            # Reduce reasoning overhead for faster responses in benchmark scenarios
            reasoning_effort="medium",
            extended_thinking_budget=10000,
        )

    def _create_agent(self, llm: "LLM", use_tools: bool = True) -> "Agent":
        """Create Agent with LLM and optionally tools.

        Args:
            llm: The LLM instance to use
            use_tools: If True, include TerminalTool and FileEditorTool.
                      If False, create agent without tools for direct responses.
        """
        tools = []
        if use_tools:
            tools = [
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ]

        return Agent(
            llm=llm,
            tools=tools,
            system_prompt_kwargs={
                "agent_context": SUPPORT_ENGINEER_CONTEXT,
            },
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        use_tools: bool = True,
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Support Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context
            workspace: Working directory for the agent
            use_tools: If True, enable TerminalTool and FileEditorTool for agentic exploration.
                      If False, disable tools for direct LLM responses (faster for analysis tasks).
            skip_context_injection: If True, don't automatically inject Sentry/Gmail/etc context.
                      Useful for benchmarks where you want the agent to only use provided task content.

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="support_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        llm = self._create_llm()
        agent = self._create_agent(llm, use_tools=use_tools)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            # Inject relevant context based on task keywords (unless skipped)
            injected_context = []

            if not skip_context_injection:
                task_lower = task.lower()

                # Sentry context for error-related tasks
                # Expanded to include infrastructure/incident keywords
                sentry_keywords = [
                    "sentry",
                    "error",
                    "issue",
                    "bug",
                    "crash",  # original
                    "400",
                    "500",
                    "4xx",
                    "5xx",
                    "http",  # HTTP errors
                    "incident",
                    "outage",
                    "down",
                    "failing",
                    "failure",  # incidents
                    "gateway",
                    "api",
                    "endpoint",
                    "service",  # infrastructure
                    "deployment",
                    "deploy",
                    "release",
                    "rollback",  # deployments
                    "customer",
                    "user",
                    "report",
                    "complaint",  # customer reports often relate to errors
                ]
                if any(kw in task_lower for kw in sentry_keywords):
                    sentry_ctx = fetch_sentry_context()
                    injected_context.append(sentry_ctx)

                # Gmail context for email-related tasks
                if any(kw in task_lower for kw in ["email", "gmail", "inbox", "message", "mail"]):
                    injected_context.append(fetch_gmail_context())

                # Calendar context for scheduling-related tasks
                if any(kw in task_lower for kw in ["calendar", "meeting", "schedule", "event"]):
                    injected_context.append(fetch_calendar_context_wrapper())

                # Langfuse context for LLM observability tasks
                if any(
                    kw in task_lower
                    for kw in [
                        "langfuse",
                        "trace",
                        "llm",
                        "observability",
                        "latency",
                        "token",
                    ]
                ):
                    injected_context.append(fetch_langfuse_context_wrapper())

                # Documentation context for product/feature/setup questions
                if any(
                    kw in task_lower
                    for kw in [
                        "doc",
                        "documentation",
                        "how to",
                        "setup",
                        "configure",
                        "install",
                        "api",
                        "feature",
                    ]
                ):
                    # Use the task itself as the search query
                    injected_context.append(fetch_docs_context_wrapper(task))

            # Build full task with context
            context_str = "\n\n".join(injected_context) if injected_context else ""
            if context_str:
                # Add very clear visual separators so agents know this is the injected data
                context_block = f"""
================================================================================
INJECTED DATA FROM MONITORING SYSTEMS - THIS IS YOUR DATA, USE IT!
================================================================================

{context_str}

================================================================================
END OF INJECTED DATA - The above data has ALREADY been fetched for you
================================================================================
"""
                full_task = f"{SUPPORT_ENGINEER_CONTEXT}\n{context_block}\nTask: {task}"
            else:
                full_task = f"{SUPPORT_ENGINEER_CONTEXT}\n\nTask: {task}"

            # When tools are disabled, convert numbered lists to bullet points.
            # OpenHands interprets numbered lists as action steps to execute,
            # causing empty LLM responses. Bullet points work correctly.
            if not use_tools:
                full_task = convert_numbered_lists_to_bullets(full_task)

            # Use send_message + run for the full agentic loop with tools
            conversation.send_message(full_task)
            conversation.run()

            # Get the response from conversation events
            # Check event type by class name since different events have different structures
            response = ""

            for event in reversed(conversation.state.events):
                event_type = type(event).__name__

                # Check for ActionEvent containing FinishAction or AgentFinishAction
                if event_type == "ActionEvent":
                    action = getattr(event, "action", None)
                    action_name = type(action).__name__ if action else ""
                    if action and action_name in ("FinishAction", "AgentFinishAction"):
                        # Get message from the action
                        message = getattr(action, "message", "")
                        if message:
                            response = message
                            break
                        # Fallback to thought
                        thought = getattr(action, "thought", "")
                        if thought:
                            response = thought
                            break

                # Check for MessageEvent (direct response without finish tool)
                elif event_type == "MessageEvent" and getattr(event, "source", None) == "agent":
                    if hasattr(event, "llm_message") and event.llm_message:
                        llm_msg = event.llm_message
                        if hasattr(llm_msg, "content") and llm_msg.content:
                            for block in llm_msg.content:
                                if hasattr(block, "text") and block.text:
                                    response = block.text
                                    break
                    if response:
                        break

            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            return {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "support_engineer",
            }

        finally:
            if temp_dir:
                try:
                    conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        use_tools: bool = True,
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context
            workspace: Working directory for the agent
            use_tools: If True, enable tools for agentic exploration.
                      If False, disable tools for direct LLM responses.
            skip_context_injection: If True, don't automatically inject context.
        """
        import asyncio

        return await asyncio.to_thread(
            self.run,
            task,
            context_type,
            context_id,
            workspace,
            use_tools,
            skip_context_injection,
            **kwargs,
        )


def create_support_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsSupportEngineer:
    """Factory function to create Support Engineer agent."""
    return OpenHandsSupportEngineer(config)
