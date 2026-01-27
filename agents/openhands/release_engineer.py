"""
ReleaseEngineer agent using OpenHands.

Capabilities:
- Shell command execution
- File editing and creation
- Git operations
- k3s cluster deployment
- GitHub PR and release management
"""

import os
from typing import Any

from agents.config import (
    AgentConfig,
    LLMConfig,
    RELEASE_ENGINEER_CONFIG,
    get_mcp_config_dict,
)
from agents.sessions import SessionState, get_or_create_session, get_session_store

# OpenHands imports - will fail gracefully if not installed
try:
    from openhands.sdk import Agent, Conversation, LLM, Tool
    from openhands.tools.terminal import TerminalTool
    from openhands.tools.file_editor import FileEditorTool

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    Agent = None
    Conversation = None


RELEASE_ENGINEER_SYSTEM_PROMPT = """You are Einstein, the Release Engineer for VibeTeam.

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
    """Release Engineer agent using OpenHands SDK."""

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or RELEASE_ENGINEER_CONFIG
        self.llm = self._create_llm()
        self.agent = self._create_agent()

    def _create_llm(self) -> "LLM":
        """Create OpenHands LLM instance."""
        return LLM(
            model=self.config.llm.model,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            temperature=self.config.llm.temperature,
        )

    def _create_agent(self) -> "Agent":
        """Create OpenHands Agent with tools and MCP config."""
        mcp_config = get_mcp_config_dict(self.config.mcp_servers)

        return Agent(
            llm=self.llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ],
            mcp_config=mcp_config if mcp_config["mcpServers"] else None,
            system_prompt=RELEASE_ENGINEER_SYSTEM_PROMPT,
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
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

        # Get or create session
        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="release_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        # Create conversation with persistence
        workspace = workspace or os.getcwd()
        conversation = Conversation(
            agent=self.agent,
            workspace=workspace,
            persistence_dir=self.config.session.storage_path,
            conversation_id=session.session_id,
        )

        # Send message and run
        conversation.send_message(task)
        conversation.run()

        # Get response
        response = conversation.get_last_assistant_message()

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
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Async version of run (OpenHands is sync, so this wraps it)."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, workspace)


def create_release_engineer(config: AgentConfig | None = None) -> OpenHandsReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return OpenHandsReleaseEngineer(config)
