"""
BaseVibeAgent - Foundation for all VibeTeam agents using OpenHands SDK.

Replaces the MetaGPT-based VibeRole with a lightweight, tool-oriented design.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from vibeteam.config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Message:
    """A message in the conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None  # Tool name if role is "tool"
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None  # Required for tool role messages


class BaseTool(ABC):
    """Base class for all VibeTeam tools."""

    name: str = "base_tool"
    description: str = "Base tool"

    @abstractmethod
    def get_schema(self) -> dict:
        """Return the OpenAI function schema for this tool."""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
        pass


class BaseVibeAgent:
    """
    Base class for all VibeTeam agents.

    This replaces the MetaGPT Role pattern with a simpler, tool-oriented design
    using LiteLLM for LLM interactions and custom tools for external services.

    Architecture:
    - Agent: Orchestrates LLM + tools to accomplish tasks
    - Tools: Discrete capabilities the agent can invoke
    - Conversation: Message history for context
    """

    # Agent configuration
    name: str = "VibeAgent"
    profile: str = "Team Member"
    goal: str = "Contribute to team success"

    # Model configuration - uses centralized defaults from vibeteam.config
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __init__(
        self,
        name: str | None = None,
        profile: str | None = None,
        goal: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        tools: list[BaseTool] | None = None,
    ):
        """
        Initialize the agent.

        Args:
            name: Agent name
            profile: Agent profile/role description
            goal: Agent's primary goal
            model: LiteLLM model string (e.g., "azure/gpt-4.1")
            temperature: LLM temperature
            tools: List of tools available to this agent
        """
        if name:
            self.name = name
        if profile:
            self.profile = profile
        if goal:
            self.goal = goal
        if model:
            self.model = model
        if temperature is not None:
            self.temperature = temperature

        self.tools: list[BaseTool] = tools or []
        self.conversation: list[Message] = []

        # Initialize conversation with system prompt
        self._init_system_prompt()

    def _init_system_prompt(self) -> None:
        """Initialize the system prompt for this agent."""
        system_content = self._get_system_prompt()
        self.conversation = [Message(role="system", content=system_content)]

    def _get_system_prompt(self) -> str:
        """
        Get the system prompt for this agent.

        Override in subclasses to customize the prompt.
        """
        tool_descriptions = ""
        if self.tools:
            tool_list = "\n".join(f"- {t.name}: {t.description}" for t in self.tools)
            tool_descriptions = f"\n\nAvailable Tools:\n{tool_list}"

        return f"""You are {self.name}, a {self.profile}.

Goal: {self.goal}

You are part of the VibeTeam, an autonomous AI team for SaaS development.
Execute tasks efficiently using the available tools. Always provide clear,
actionable outputs.{tool_descriptions}"""

    def _get_tool_schemas(self) -> list[dict]:
        """Get OpenAI function schemas for all tools."""
        return [tool.get_schema() for tool in self.tools]

    def add_tool(self, tool: BaseTool) -> None:
        """Add a tool to this agent."""
        self.tools.append(tool)
        # Reinitialize system prompt with updated tool list
        self._init_system_prompt()

    def _prepare_messages(self) -> list[dict]:
        """Convert internal messages to LiteLLM format."""
        messages = []
        for msg in self.conversation:
            m: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            messages.append(m)
        return messages

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_llm(self, messages: list[dict]) -> Any:
        """Call the LLM with retry logic."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        # Use max_completion_tokens for GPT-5+ models, max_tokens for older models
        if "gpt-5" in self.model:
            kwargs["max_completion_tokens"] = self.max_tokens
        else:
            kwargs["max_tokens"] = self.max_tokens

        # Add Azure-specific configuration
        if self.model.startswith("azure/"):
            # LiteLLM Azure config - check both possible env var names
            api_base = os.environ.get("AZURE_API_BASE") or os.environ.get("AZURE_OPENAI_ENDPOINT")
            api_key = os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")
            api_version = os.environ.get("AZURE_API_VERSION", "2024-08-01-preview")

            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key
            if api_version:
                kwargs["api_version"] = api_version

        # Add tools if available
        tools = self._get_tool_schemas()
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # Drop unsupported params (e.g., tool_choice for Azure GPT-5)
        litellm.drop_params = True
        response = await litellm.acompletion(**kwargs)
        return response

    async def _execute_tool(self, name: str, arguments: dict) -> ToolResult:
        """Execute a tool by name with the given arguments."""
        tool = next((t for t in self.tools if t.name == name), None)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' not found",
            )

        try:
            return await tool.execute(**arguments)
        except Exception as e:
            logger.exception(f"Tool execution error: {name}")
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {str(e)}",
            )

    async def _process_tool_calls(self, tool_calls: list[dict]) -> list[Message]:
        """Process tool calls from the LLM response."""
        results = []
        for call in tool_calls:
            tool_call_id = call.get("id", "")
            func = call.get("function", {})
            name = func.get("name", "")
            try:
                arguments = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            logger.info(f"Executing tool: {name}")
            result = await self._execute_tool(name, arguments)

            # Format result for conversation
            content = result.output if result.success else f"Error: {result.error}"
            results.append(
                Message(
                    role="tool",
                    content=content,
                    name=name,
                    tool_call_id=tool_call_id,
                )
            )

        return results

    async def run(self, task: str, max_iterations: int = 10) -> str:
        """
        Run the agent on a task.

        Args:
            task: The task to perform
            max_iterations: Maximum number of LLM calls (prevents infinite loops)

        Returns:
            The agent's final response
        """
        # Add user message
        self.conversation.append(Message(role="user", content=task))

        for iteration in range(max_iterations):
            logger.debug(f"Agent iteration {iteration + 1}/{max_iterations}")

            # Call LLM
            messages = self._prepare_messages()
            response = await self._call_llm(messages)

            # Extract response
            choice = response.choices[0]
            assistant_message = choice.message

            # Check for tool calls
            if hasattr(assistant_message, "tool_calls") and assistant_message.tool_calls:
                # Add assistant message with tool calls
                self.conversation.append(
                    Message(
                        role="assistant",
                        content=assistant_message.content or "",
                        tool_calls=[
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in assistant_message.tool_calls
                        ],
                    )
                )

                # Execute tools
                tool_results = await self._process_tool_calls(
                    [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ]
                )

                # Add tool results to conversation
                self.conversation.extend(tool_results)
            else:
                # No tool calls - final response
                final_content = assistant_message.content or ""
                self.conversation.append(Message(role="assistant", content=final_content))
                return final_content

        # Max iterations reached
        logger.warning(f"Agent reached max iterations ({max_iterations})")
        return "Task incomplete: maximum iterations reached."

    def reset(self) -> None:
        """Reset the conversation history."""
        self._init_system_prompt()

    def get_conversation_history(self) -> list[dict]:
        """Get the full conversation history."""
        return [{"role": m.role, "content": m.content, "name": m.name} for m in self.conversation]
