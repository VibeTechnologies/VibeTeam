from __future__ import annotations

"""
ReleaseEngineer agent using OpenHands.

Capabilities:
- Shell command execution
- File editing and creation
- Git operations
- k3s cluster deployment
- GitHub PR and release management

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import tempfile
from typing import Any

from agents.config import RELEASE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store
from agents.shared.kubectl_tools import get_kubectl_context


def fetch_kubectl_context() -> str:
    """Fetch Kubernetes context using shared tools."""
    return get_kubectl_context()


# OpenHands imports - will fail gracefully if not installed
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


# Note: OpenHands uses Jinja2 templates for system prompts.
# For custom prompts, you can extend Agent and override system_prompt_filename
# or provide system_prompt_kwargs for template variables.

RELEASE_ENGINEER_CONTEXT = """You are Einstein, the Release Engineer for VibeTeam.

## YOU ARE THE ONLY AGENT WHO CAN TAKE PRODUCTION ACTIONS

You have FULL access to the production Kubernetes cluster. When you receive a handoff
from SupportEngineer with investigation findings, YOUR JOB IS TO ACT.

## PRE-FETCHED DATA AVAILABLE
Look for the section starting with "## Pre-Fetched Kubernetes Context" below.
This contains the CURRENT state of pods, events, logs, and rollout history.
**USE THIS DATA FIRST** instead of running manual `kubectl` commands to verify state.

## CRITICAL: TAKE ACTION, DON'T JUST INVESTIGATE

SupportEngineer has already investigated. When you receive a handoff:
1. **Review their findings** and the **Pre-Fetched Kubernetes Context** below
2. **Verify if needed** (only if pre-fetched data is insufficient)
3. **TAKE THE APPROPRIATE ACTION** - don't just recommend, DO IT

## ACTIONS YOU MUST TAKE (not just recommend)

### Rollback a Deployment
```bash
# Check rollout history
kubectl rollout history deployment/vibeteam-gateway -n vibeteam

# Rollback to previous version
kubectl rollout undo deployment/vibeteam-gateway -n vibeteam

# Verify rollback succeeded
kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=120s
```

### Restart Pods (for transient issues)
```bash
# Rolling restart
kubectl rollout restart deployment/vibeteam-gateway -n vibeteam

# Wait for restart to complete
kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=120s
```

### Scale for Load Issues
```bash
# Scale up
kubectl scale deployment/vibeteam-gateway -n vibeteam --replicas=3

# Verify scaling
kubectl get pods -n vibeteam -l app=vibeteam-gateway
```

### Check Current State Before/After Actions
```bash
# Pod status
kubectl get pods -n vibeteam -o wide

# Recent events
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -10

# Deployment status
kubectl get deployments -n vibeteam
```

## k3s Cluster Information
- Cluster: vibeteam-k3s
- Namespace: vibeteam
- Registry: ghcr.io/vibetechnologies
- Config: In-cluster (ServiceAccount: vibeteam-agent)

## OWNERSHIP MATRIX

**YOU ARE RESPONSIBLE FOR:**
- Rollbacks (kubectl rollout undo)
- Restarts (kubectl rollout restart)
- Scaling (kubectl scale)
- Deployments (kubectl apply)
- Any production cluster modifications

**YOU HAND OFF TO:**
- @SoftwareEngineer - if root cause is a code bug that needs fixing
- @MarketingManager - to announce incident resolution to customers
- @SupportEngineer - to notify customer that issue is resolved

## RESPONSE FORMAT AFTER TAKING ACTION

```
Received handoff about [issue].

**Action Taken:**
- Ran: `kubectl rollout undo deployment/vibeteam-gateway -n vibeteam`
- Result: Rolled back to revision 5
- Verified: All pods now Running, no errors in events

**Current Status:**
- Pods: 2/2 Running
- No OOMKilled or CrashLoopBackOff events
- Logs show normal operation

@SupportEngineer Please confirm with customer that 400 errors have stopped.
```

## CRITICAL: Communication is Handled By the System

DO NOT try to use Slack/email tools. Your text response is automatically posted.

**IMPORTANT**: Do NOT hand off back to yourself. If you need more info, state what's needed.
"""


class OpenHandsReleaseEngineer:
    """
    Release Engineer agent using OpenHands SDK.

    Uses OpenHands' agentic loop with built-in tools for:
    - Shell command execution
    - File editing
    - Web browsing (optional)
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or RELEASE_ENGINEER_CONFIG

    def _create_llm(self) -> "LLM":
        """Create LLM with Azure configuration."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        # OpenHands uses litellm format: azure/<deployment>
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return AzureLLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,  # Critical for Azure GPT-4 models
        )

    def _create_agent(self, llm: "LLM") -> "Agent":
        """Create Agent with LLM and tools."""
        return Agent(
            llm=llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ],
            # OpenHands uses template-based system prompts
            # We pass context as kwargs for custom templates
            system_prompt_kwargs={
                "agent_context": RELEASE_ENGINEER_CONTEXT,
            },
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Release Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (issue number, PR number, etc.)
            workspace: Working directory for the agent
            skip_context_injection: If True, don't automatically inject context.

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="release_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        llm = self._create_llm()
        agent = self._create_agent(llm)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            # Create local conversation with required workspace
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            # Inject relevant context (ReleaseEngineer almost always needs kubectl)
            injected_context = []
            if not skip_context_injection:
                # Always inject kubectl context for Release Engineer as they deal with infra
                kubectl_ctx = fetch_kubectl_context()
                injected_context.append(kubectl_ctx)

            # Build full task with context
            context_str = "\n\n".join(injected_context) if injected_context else ""
            if context_str:
                context_block = f"""
================================================================================
INJECTED DATA FROM MONITORING SYSTEMS - THIS IS YOUR DATA, USE IT!
================================================================================

{context_str}

================================================================================
END OF INJECTED DATA - The above data has ALREADY been fetched for you
================================================================================
"""
                full_task = f"{RELEASE_ENGINEER_CONTEXT}\n{context_block}\nTask: {task}"
            else:
                full_task = f"{RELEASE_ENGINEER_CONTEXT}\n\nTask: {task}"

            # Use send_message + run for the full agentic loop with tools
            conversation.send_message(full_task)
            conversation.run()

            # Get the last assistant message from conversation events
            response = ""
            for event in reversed(conversation.state.events):
                if event.kind == "MessageEvent" and getattr(event, "source", None) == "agent":
                    if hasattr(event, "llm_message") and event.llm_message:
                        llm_msg = event.llm_message
                        if hasattr(llm_msg, "content") and llm_msg.content:
                            for block in llm_msg.content:
                                if hasattr(block, "text"):
                                    response = block.text
                                    break
                    break

            # Update session
            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            return {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "release_engineer",
                "workspace": workspace_path,
            }

        finally:
            # Clean up temp directory if we created one
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
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run,
            task,
            context_type,
            context_id,
            workspace,
            skip_context_injection,
            **kwargs,
        )


def create_release_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return OpenHandsReleaseEngineer(config)
