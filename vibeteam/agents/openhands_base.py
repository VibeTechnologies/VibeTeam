"""
OpenHands Base Agent - Wrapper around OpenHands SDK for autonomous task execution.

This provides a reusable base class for creating specialized agents
that can execute code, run commands, edit files, and create PRs.

Usage:
    agent = OpenHandsAgent(
        system_prompt="You are a Release Engineer...",
        workspace_path="/path/to/repo"
    )
    result = await agent.execute("Fix the bug in src/index.ts")
"""

import os
import platform
from collections.abc import Callable
from typing import Any

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    Event,
    LLMConvertibleEvent,
    Tool,
    get_logger,
)
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool
from pydantic import SecretStr

logger = get_logger(__name__)


class OpenHandsAgent:
    """
    Base class for OpenHands-powered autonomous agents.

    Features:
    - Executes tasks in a real workspace (local or Docker)
    - Has access to Terminal, FileEditor, and TaskTracker tools
    - Tracks costs and token usage
    - Supports callbacks for real-time event streaming

    Environment Variables:
        LLM_API_KEY: API key for the LLM provider
        LLM_MODEL: Model to use (default: azure/gpt-5-2)
        LLM_BASE_URL: Base URL for the LLM API (for Azure)
    """

    def __init__(
        self,
        system_prompt: str,
        workspace_path: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        mcp_config: dict | None = None,
    ):
        """
        Initialize the OpenHands agent.

        Args:
            system_prompt: System prompt defining the agent's role and behavior
            workspace_path: Path to the workspace directory (default: current dir)
            model: LLM model to use (default: from env or azure/gpt-5-2)
            temperature: LLM temperature (default: 0.3 for precise analysis)
            mcp_config: Optional MCP server configuration
        """
        self.system_prompt = system_prompt
        self.workspace_path = workspace_path or os.getcwd()
        self.model = model or os.getenv("LLM_MODEL", "azure/gpt-5-2")
        self.temperature = temperature
        self.mcp_config = mcp_config

        # Initialize LLM
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("LLM_API_KEY environment variable is not set")

        self.llm = LLM(
            usage_id="agent",
            model=self.model,
            base_url=os.getenv("LLM_BASE_URL"),
            api_key=SecretStr(api_key),
            temperature=temperature,
        )

        # Track events and costs
        self.events: list[Event] = []
        self.llm_messages: list[Any] = []

    def _get_tools(self) -> list[Tool]:
        """Get the default tools for the agent."""
        return [
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ]

    def _create_agent(self) -> Agent:
        """Create the OpenHands agent with tools and system prompt."""
        return Agent(
            llm=self.llm,
            tools=self._get_tools(),
            system_prompt=self.system_prompt,
            mcp_config=self.mcp_config,
        )

    def _event_callback(self, event: Event) -> None:
        """Callback for tracking events during execution."""
        self.events.append(event)
        if isinstance(event, LLMConvertibleEvent):
            self.llm_messages.append(event.to_llm_message())

    async def execute(
        self,
        task: str,
        callbacks: list[Callable[[Event], None]] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a task using the OpenHands agent.

        Args:
            task: Natural language description of the task to perform
            callbacks: Optional list of callbacks for event streaming

        Returns:
            Dictionary with:
                - success: Whether the task completed
                - events: List of events that occurred
                - cost: Total cost of the execution
                - tokens: Token usage statistics
        """
        # Reset tracking
        self.events = []
        self.llm_messages = []

        # Build callbacks list
        all_callbacks = [self._event_callback]
        if callbacks:
            all_callbacks.extend(callbacks)

        # Create agent and conversation
        agent = self._create_agent()
        conversation = Conversation(
            agent=agent,
            workspace=self.workspace_path,
            callbacks=all_callbacks,
        )

        try:
            # Send message and run
            logger.info(f"Executing task: {task[:100]}...")
            conversation.send_message(task)
            conversation.run()

            # Collect metrics
            metrics = conversation.conversation_stats.get_combined_metrics()

            return {
                "success": True,
                "events": self.events,
                "event_count": len(self.events),
                "cost": metrics.accumulated_cost,
                "tokens": {
                    "prompt": metrics.accumulated_token_usage.prompt_tokens
                    if metrics.accumulated_token_usage
                    else 0,
                    "completion": metrics.accumulated_token_usage.completion_tokens
                    if metrics.accumulated_token_usage
                    else 0,
                },
            }
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "events": self.events,
                "event_count": len(self.events),
            }

    async def send_followup(
        self,
        conversation: Conversation,
        message: str,
    ) -> dict[str, Any]:
        """
        Send a follow-up message to an existing conversation.

        Args:
            conversation: Existing conversation instance
            message: Follow-up message

        Returns:
            Execution result
        """
        try:
            conversation.send_message(message)
            conversation.run()

            metrics = conversation.conversation_stats.get_combined_metrics()
            return {
                "success": True,
                "cost": metrics.accumulated_cost,
            }
        except Exception as e:
            logger.error(f"Follow-up failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_total_cost(self) -> float:
        """Get total accumulated cost across all executions."""
        return self.llm.metrics.accumulated_cost


class DockerOpenHandsAgent(OpenHandsAgent):
    """
    OpenHands agent that runs in a Docker container.

    Use this when you need isolated execution environment,
    especially for untrusted code or when modifying system files.

    Note: Requires Docker to be running.
    """

    def __init__(
        self,
        system_prompt: str,
        host_port: int = 8010,
        docker_image: str = "ghcr.io/openhands/agent-server:latest",
        **kwargs,
    ):
        """
        Initialize Docker-based agent.

        Args:
            system_prompt: System prompt for the agent
            host_port: Port to expose the agent server on
            docker_image: Docker image to use for the agent server
            **kwargs: Additional arguments passed to OpenHandsAgent
        """
        super().__init__(system_prompt, **kwargs)
        self.host_port = host_port
        self.docker_image = docker_image

    @staticmethod
    def _detect_platform() -> str:
        """Detect the correct Docker platform string."""
        machine = platform.machine().lower()
        if "arm" in machine or "aarch64" in machine:
            return "linux/arm64"
        return "linux/amd64"

    async def execute_in_docker(
        self,
        task: str,
        callbacks: list[Callable[[Event], None]] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a task in a Docker container.

        This provides full isolation and allows running commands
        that might modify the system.

        Args:
            task: Task to execute
            callbacks: Optional callbacks

        Returns:
            Execution result
        """
        from openhands.workspace import DockerWorkspace

        # Reset tracking
        self.events = []
        self.llm_messages = []

        # Build callbacks list
        all_callbacks = [self._event_callback]
        if callbacks:
            all_callbacks.extend(callbacks)

        try:
            with DockerWorkspace(
                server_image=self.docker_image,
                host_port=self.host_port,
                platform=self._detect_platform(),
            ) as workspace:
                agent = self._create_agent()
                conversation = Conversation(
                    agent=agent,
                    workspace=workspace,
                    callbacks=all_callbacks,
                )

                logger.info(f"Executing in Docker: {task[:100]}...")
                conversation.send_message(task)
                conversation.run()

                metrics = conversation.conversation_stats.get_combined_metrics()

                return {
                    "success": True,
                    "events": self.events,
                    "event_count": len(self.events),
                    "cost": metrics.accumulated_cost,
                    "tokens": {
                        "prompt": metrics.accumulated_token_usage.prompt_tokens
                        if metrics.accumulated_token_usage
                        else 0,
                        "completion": metrics.accumulated_token_usage.completion_tokens
                        if metrics.accumulated_token_usage
                        else 0,
                    },
                }
        except Exception as e:
            logger.error(f"Docker execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "events": self.events,
            }
