"""
SoftwareEngineer agent using OpenHands.

Capabilities:
- Shell command execution for builds and tests
- File editing and creation
- Git operations (branch, commit, merge)
- Full development workflow automation

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import tempfile
from typing import Any

from agents.config import SOFTWARE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store

try:
    from openhands.sdk import LLM, Agent, LocalConversation

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    LLM = None
    Agent = None
    LocalConversation = None


SOFTWARE_ENGINEER_CONTEXT = """You are Alan, the Software Engineer for VibeTeam.

Your responsibilities:
1. **Feature Implementation**: Implement features from user stories and PRDs
2. **Bug Fixing**: Fix bugs reported by SupportEngineer or from Sentry
3. **Testing**: Write and maintain unit tests and integration tests
4. **Code Review**: Review code changes and suggest improvements
5. **Pull Requests**: Create and manage pull requests

## Development Workflow
1. Understand the requirement from the issue or user story
2. Create a feature branch: `git checkout -b feat/feature-name`
3. Implement the changes with tests
4. Run tests to verify: `pytest tests/`
5. Commit with descriptive message: `git commit -m "feat: description"`
6. Create a pull request with summary

## Code Standards
- Follow existing code patterns in the repository
- Write docstrings for functions and classes
- Add type hints where appropriate
- Keep functions focused and small
- Write tests for new functionality

## Communication
- Post updates to Slack #ai-team
- Tag @ReleaseEngineer when ready for deployment
- Tag @SupportEngineer if changes affect customer-facing features

When you complete a task, summarize what was done, files changed, and any next steps.
"""


class OpenHandsSoftwareEngineer:
    """
    Software Engineer agent using OpenHands SDK.

    Uses OpenHands' agentic loop with built-in tools for:
    - Shell command execution
    - File editing and creation
    - Web browsing (optional)
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError(
                "OpenHands SDK not installed. Run: pip install openhands-ai"
            )

        self.config = config or SOFTWARE_ENGINEER_CONFIG

    def _create_llm(self) -> "LLM":
        """Create LLM with Azure configuration."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return LLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,
        )

    def _create_agent(self, llm: "LLM") -> "Agent":
        """Create Agent with LLM."""
        return Agent(
            llm=llm,
            system_prompt_kwargs={
                "agent_context": SOFTWARE_ENGINEER_CONTEXT,
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
        Run a task with the Software Engineer agent.

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
            role="software_engineer",
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
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            full_task = f"{SOFTWARE_ENGINEER_CONTEXT}\n\nTask: {task}"
            response = conversation.ask_agent(full_task)

            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            return {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "software_engineer",
                "workspace": workspace_path,
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run, task, context_type, context_id, workspace, **kwargs
        )


def create_software_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsSoftwareEngineer:
    """Factory function to create Software Engineer agent."""
    return OpenHandsSoftwareEngineer(config)
