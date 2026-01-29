"""
Tests for VibeTeam OpenHands agents and tools.

These tests verify the new OpenHands-based agent architecture.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibeteam.agents.base import BaseTool, BaseVibeAgent, Message, ToolResult


class MockTool(BaseTool):
    """Mock tool for testing."""

    name = "mock_tool"
    description = "A mock tool for testing"

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Action to perform",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "default")
        return ToolResult(
            success=True,
            output=f"Executed action: {action}",
        )


class TestBaseVibeAgent:
    """Test BaseVibeAgent initialization and basic functionality."""

    def test_default_initialization(self) -> None:
        """Test agent initializes with defaults."""
        agent = BaseVibeAgent()
        assert agent.name == "VibeAgent"
        assert agent.profile == "Team Member"
        assert agent.goal == "Contribute to team success"
        assert agent.model == "azure/gpt-5-2"
        assert agent.temperature == 0.3
        assert agent.tools == []

    def test_custom_initialization(self) -> None:
        """Test agent with custom parameters."""
        agent = BaseVibeAgent(
            name="CustomAgent",
            profile="Custom Role",
            goal="Custom goal",
            model="gpt-5-mini",
            temperature=0.5,
        )
        assert agent.name == "CustomAgent"
        assert agent.profile == "Custom Role"
        assert agent.goal == "Custom goal"
        assert agent.model == "gpt-5-mini"
        assert agent.temperature == 0.5

    def test_add_tool(self) -> None:
        """Test adding tools to agent."""
        agent = BaseVibeAgent()
        tool = MockTool()
        agent.add_tool(tool)
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "mock_tool"

    def test_system_prompt_generation(self) -> None:
        """Test system prompt contains agent info."""
        agent = BaseVibeAgent(
            name="TestAgent",
            profile="Tester",
            goal="Test things",
        )
        prompt = agent._get_system_prompt()
        assert "TestAgent" in prompt
        assert "Tester" in prompt
        assert "Test things" in prompt

    def test_system_prompt_includes_tools(self) -> None:
        """Test system prompt includes tool descriptions."""
        agent = BaseVibeAgent(tools=[MockTool()])
        prompt = agent._get_system_prompt()
        assert "mock_tool" in prompt
        assert "mock tool for testing" in prompt

    def test_tool_schemas(self) -> None:
        """Test tool schema generation."""
        agent = BaseVibeAgent(tools=[MockTool()])
        schemas = agent._get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "mock_tool"

    def test_conversation_initialization(self) -> None:
        """Test conversation starts with system message."""
        agent = BaseVibeAgent()
        assert len(agent.conversation) == 1
        assert agent.conversation[0].role == "system"

    def test_reset(self) -> None:
        """Test conversation reset."""
        agent = BaseVibeAgent()
        agent.conversation.append(Message(role="user", content="test"))
        assert len(agent.conversation) == 2
        agent.reset()
        assert len(agent.conversation) == 1
        assert agent.conversation[0].role == "system"


class TestBaseTool:
    """Test BaseTool and tool execution."""

    @pytest.mark.asyncio
    async def test_mock_tool_execution(self) -> None:
        """Test mock tool executes correctly."""
        tool = MockTool()
        result = await tool.execute(action="test_action")
        assert result.success is True
        assert "test_action" in result.output

    @pytest.mark.asyncio
    async def test_tool_execution_via_agent(self) -> None:
        """Test tool execution through agent."""
        agent = BaseVibeAgent(tools=[MockTool()])
        result = await agent._execute_tool("mock_tool", {"action": "agent_test"})
        assert result.success is True
        assert "agent_test" in result.output

    @pytest.mark.asyncio
    async def test_unknown_tool_execution(self) -> None:
        """Test handling of unknown tool."""
        agent = BaseVibeAgent()
        result = await agent._execute_tool("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error


class TestToolResult:
    """Test ToolResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful result creation."""
        result = ToolResult(success=True, output="done")
        assert result.success is True
        assert result.output == "done"
        assert result.error is None
        assert result.metadata == {}

    def test_error_result(self) -> None:
        """Test error result creation."""
        result = ToolResult(
            success=False,
            output="",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_result_with_metadata(self) -> None:
        """Test result with metadata."""
        result = ToolResult(
            success=True,
            output="data",
            metadata={"count": 5},
        )
        assert result.metadata["count"] == 5


class TestMessage:
    """Test Message dataclass."""

    def test_basic_message(self) -> None:
        """Test basic message creation."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
        assert msg.tool_calls is None

    def test_tool_message(self) -> None:
        """Test tool result message."""
        msg = Message(role="tool", content="result", name="test_tool")
        assert msg.role == "tool"
        assert msg.name == "test_tool"

    def test_assistant_with_tool_calls(self) -> None:
        """Test assistant message with tool calls."""
        tool_calls = [{"function": {"name": "test", "arguments": "{}"}}]
        msg = Message(role="assistant", content="", tool_calls=tool_calls)
        assert len(msg.tool_calls) == 1


class TestAgentRun:
    """Test agent run functionality with mocked LLM."""

    @pytest.mark.asyncio
    async def test_run_simple_response(self) -> None:
        """Test agent run with simple (no tool) response."""
        agent = BaseVibeAgent()

        # Mock LLM response without tool calls
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello, I can help you."
        mock_response.choices[0].message.tool_calls = None

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run("Say hello")

        assert "Hello" in result
        assert len(agent.conversation) == 3  # system, user, assistant

    @pytest.mark.asyncio
    async def test_run_with_tool_call(self) -> None:
        """Test agent run with tool call."""
        agent = BaseVibeAgent(tools=[MockTool()])

        # First response: tool call
        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = ""
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "mock_tool"
        tool_call.function.arguments = '{"action": "test"}'
        tool_response.choices[0].message.tool_calls = [tool_call]

        # Second response: final answer
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Done using the tool."
        final_response.choices[0].message.tool_calls = None

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [tool_response, final_response]
            result = await agent.run("Use the tool")

        assert "Done" in result
        # system, user, assistant (tool call), tool result, assistant (final)
        assert len(agent.conversation) == 5
