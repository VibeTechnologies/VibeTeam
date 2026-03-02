"""
Base agent class for OpenCode agents.

Provides common functionality for all OpenCode-based agents including:
- Session management
- Prompt construction
- Response handling
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_service.config import AgentConfig
from agent_service.sessions import get_or_create_session, get_session_store

from .client import OpenCodeClient, OpenCodeClientConfig, create_client


@dataclass
class OpenCodeAgentConfig:
    """Configuration for an OpenCode agent."""

    agent_config: AgentConfig | None = None
    client_config: OpenCodeClientConfig | None = None
    timeout: int = 120


class OpenCodeBaseAgent(ABC):
    """
    Base class for OpenCode-based agents.

    Subclasses must implement:
    - role: The agent role identifier (e.g., "software_engineer")
    - name: The agent's persona name (e.g., "Alan")
    - system_prompt: The system prompt for the agent
    """

    def __init__(self, config: OpenCodeAgentConfig | None = None):
        self.config = config or OpenCodeAgentConfig()
        self._client: OpenCodeClient | None = None

    @property
    @abstractmethod
    def role(self) -> str:
        """Return the agent role identifier."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the agent's persona name."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass

    @property
    def client(self) -> OpenCodeClient:
        """Get or create the OpenCode client."""
        if self._client is None:
            self._client = create_client(self.config.client_config)
        return self._client

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with this agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (enables session persistence)
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        # Get or create session for persistence
        session = get_or_create_session(
            framework="opencode",
            role=self.role,
            context_type=context_type,
            context_id=context_id,
        )

        # Build session ID for opencode (uses session key for persistence)
        opencode_session_id = f"vibeteam-{self.role}-{context_type}-{context_id}"

        # Run the task
        response = self.client.run(
            prompt=task,
            session_id=opencode_session_id,
            system_prompt=self.system_prompt,
            timeout=self.config.timeout,
        )

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", response.text)
        get_session_store().save(session)

        return {
            "response": response.text,
            "session_key": session.key,
            "session_id": session.session_id,
            "opencode_session_id": response.session_id,
            "framework": "opencode",
            "agent": self.role,
            "tokens_input": response.tokens_input,
            "tokens_output": response.tokens_output,
            "cost": response.cost,
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="opencode",
            role=self.role,
            context_type=context_type,
            context_id=context_id,
        )

        opencode_session_id = f"vibeteam-{self.role}-{context_type}-{context_id}"

        response = await self.client.run_async(
            prompt=task,
            session_id=opencode_session_id,
            system_prompt=self.system_prompt,
            timeout=self.config.timeout,
        )

        session.add_message("user", task)
        session.add_message("assistant", response.text)
        get_session_store().save(session)

        return {
            "response": response.text,
            "session_key": session.key,
            "session_id": session.session_id,
            "opencode_session_id": response.session_id,
            "framework": "opencode",
            "agent": self.role,
            "tokens_input": response.tokens_input,
            "tokens_output": response.tokens_output,
            "cost": response.cost,
        }
