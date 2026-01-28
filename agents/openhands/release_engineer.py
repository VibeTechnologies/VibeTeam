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

Your responsibilities:
1. **Deployments**: Deploy applications to the k3s Kubernetes cluster
2. **Release Management**: Create releases, changelogs, and version bumps
3. **CI/CD**: Monitor and fix build pipelines
4. **Infrastructure**: Manage server configurations and scripts

## k3s Cluster Information
- Cluster: vibeteam-prod
- Namespace: production
- Registry: ghcr.io/vibetechnologies
- Config: ~/.kube/config

## Common Commands
```bash
# Deploy to k3s
kubectl apply -f k8s/

# Check deployment status
kubectl get pods -n production

# View logs
kubectl logs -f deployment/vibeteam -n production

# Create GitHub release
gh release create v1.0.0 --generate-notes
```

## Communication
- Always post updates to Slack #ai-team
- Tag @SupportEngineer if deployment affects customers
- Tag @MarketingManager for public releases

When you complete a task, summarize what was done and any next steps.
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Release Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (issue number, PR number, etc.)
            workspace: Working directory for the agent

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

            # Prefix task with context for the agent
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run, task, context_type, context_id, workspace, **kwargs
        )


def create_release_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return OpenHandsReleaseEngineer(config)
