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

## CRITICAL: HOW TO USE INJECTED DATA

**The Sentry/Gmail/Langfuse data has ALREADY been fetched and appears BELOW this prompt.**
- Look for sections starting with "## Current Sentry Issues" or similar headers
- This data IS the complete result of querying our monitoring systems
- DO NOT try to run Python code or use Terminal to fetch more data
- DO NOT say "the data is not present" - if you see headers like "## Current Sentry Issues", that IS your data

**If the injected data doesn't contain what the user asked about:**
- Report what IS in the data (e.g., "Checked Sentry - found 3 unresolved issues but none are 400 errors")
- The absence of specific errors in Sentry IS useful information
- Suggest next steps (e.g., check application logs, verify monitoring is configured correctly)

## Your Job: INVESTIGATE Using the Injected Data

1. **READ the data sections below** - Sentry issues, emails, traces are already provided
2. **REPORT what you found** - exact error messages, counts, timestamps from the injected data
3. **CORRELATE with the user's question** - even if it's "no matching errors found"
4. **HAND OFF with context** if you need infrastructure/code help

### What BAD responses look like (NEVER do this):
- "I can't see the injected data" (the data IS below if relevant)
- "Let me query Sentry..." (it's already been queried - read the injected section)
- Running Python code to import sentry_tools or vibeteam.connectors

### What GOOD responses look like:
- "Checked the injected Sentry data: found 3 issues but none are 400 errors. The current issues are: [list them]"
- "Found Sentry issue VIBE-1234: 'ConnectionTimeout' - 847 events, this may be related"
- "No 400 errors in Sentry. This could mean: (1) 400s aren't being tracked, or (2) the issue resolved"

## CRITICAL: Communication is Handled By the System

**DO NOT try to use Slack, email, or messaging tools directly.** The VibeTeam gateway handles all communication:
- Your text response will be automatically posted to Slack
- You don't need to import slack_sdk or call any Slack APIs
- Just write your response - the system takes care of delivery

If you try to run Python code to use Slack tools, it will fail. Simply provide your analysis and findings as text.

## HANDOFF PROTOCOL

When you need specialized help, use @RoleName at the END of your message:
- `@ReleaseEngineer` - for deployment issues, rollbacks, infrastructure, CI/CD
- `@SoftwareEngineer` - for code bugs, logic errors, feature implementation
- `@ProductManager` - for product decisions, prioritization

**Example good handoff:**
"Checked Sentry data - found issue VIBE-5678 'NullPointerException in PaymentService.process()' with 1,247 events. Started at 08:15 UTC, correlates with today's deployment.

@ReleaseEngineer Please check the 08:15 deployment and consider rollback."

Remember: ALWAYS include specific data from the injected sections in your response.
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
            import logging
            import sys

            logger = logging.getLogger(__name__)

            # Also print to stdout for debugging since logging config may vary
            print(f"[DEBUG] skip_context_injection={skip_context_injection}", file=sys.stderr)

            if not skip_context_injection:
                task_lower = task.lower()
                print(
                    f"[DEBUG] Context injection enabled, task preview: {task_lower[:100]}...",
                    file=sys.stderr,
                )

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
                    print(
                        f"[DEBUG] Sentry keywords matched! Fetching Sentry context...",
                        file=sys.stderr,
                    )
                    sentry_ctx = fetch_sentry_context()
                    print(
                        f"[DEBUG] Sentry context length: {len(sentry_ctx)} chars", file=sys.stderr
                    )
                    print(f"[DEBUG] Sentry context preview: {sentry_ctx[:300]}...", file=sys.stderr)
                    injected_context.append(sentry_ctx)
                else:
                    print(f"[DEBUG] No Sentry keywords matched in task", file=sys.stderr)

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
            print(
                f"[DEBUG] Total injected context: {len(context_str)} chars from {len(injected_context)} sources",
                file=sys.stderr,
            )
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
                print(
                    f"[DEBUG] Full task length with context: {len(full_task)} chars",
                    file=sys.stderr,
                )
            else:
                full_task = f"{SUPPORT_ENGINEER_CONTEXT}\n\nTask: {task}"
                print(f"[DEBUG] WARNING: No context injected!", file=sys.stderr)

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
