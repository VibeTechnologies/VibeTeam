"""
Tests for SwarmOrchestrator and Supervisor Agent.

These tests verify:
1. SharedMessageState functionality
2. Transfer tools work correctly
3. SupervisorAgent initialization and handoff handling
4. SwarmOrchestrator routing and iteration
"""

from datetime import datetime

import pytest

from vibeteam.config import DEFAULT_MODEL
from vibeteam.state import SharedMessageState, SwarmMessage
from vibeteam.tools.transfer import (
    HANDOFF_PREFIX,
    TransferToSRETool,
    TransferToSupervisorTool,
    TransferToSWETool,
    get_transfer_tools_for_agent,
    is_handoff_result,
    parse_handoff,
)


class TestSharedMessageState:
    """Tests for SharedMessageState."""

    def test_create_empty_state(self):
        """Test creating an empty shared state."""
        state = SharedMessageState()

        assert state.messages == []
        assert state.current_agent == "supervisor"
        assert len(state.session_id) > 0
        assert state.agents_used == []
        assert state.iteration_count == 0

    def test_add_message(self):
        """Test adding messages to state."""
        state = SharedMessageState()

        msg = state.add_message("user", "Hello, help me fix a bug")

        assert len(state.messages) == 1
        assert msg.role == "user"
        assert msg.content == "Hello, help me fix a bug"

    def test_add_message_with_agent(self):
        """Test adding messages with agent names."""
        state = SharedMessageState()

        state.add_message("assistant", "I'll help you", agent_name="supervisor")
        state.add_message("assistant", "Looking at the code", agent_name="swe")

        assert len(state.messages) == 2
        assert state.agents_used == ["supervisor", "swe"]

    def test_add_handoff(self):
        """Test recording handoffs."""
        state = SharedMessageState()

        msg = state.add_handoff("supervisor", "swe", "Fix the login bug")

        assert state.current_agent == "swe"
        assert "[Handoff]" in msg.content
        assert msg.metadata["type"] == "handoff"
        assert msg.metadata["from"] == "supervisor"
        assert msg.metadata["to"] == "swe"

    def test_get_context_for_agent(self):
        """Test getting context for an agent."""
        state = SharedMessageState()

        state.add_message("user", "Fix the bug")
        state.add_message("assistant", "On it", agent_name="supervisor")
        state.add_message("system", "Transferring...")

        context = state.get_context_for_agent("swe")

        assert len(context) == 3
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"
        assert context[2]["role"] == "system"

    def test_get_context_without_system(self):
        """Test getting context without system messages."""
        state = SharedMessageState()

        state.add_message("user", "Fix the bug")
        state.add_message("system", "Internal note")
        state.add_message("assistant", "Done", agent_name="swe")

        context = state.get_context_for_agent("swe", include_system=False)

        assert len(context) == 2
        assert all(m["role"] != "system" for m in context)

    def test_get_last_user_message(self):
        """Test getting the last user message."""
        state = SharedMessageState()

        state.add_message("user", "First question")
        state.add_message("assistant", "Answer 1")
        state.add_message("user", "Follow up")
        state.add_message("assistant", "Answer 2")

        last = state.get_last_user_message()

        assert last is not None
        assert last.content == "Follow up"

    def test_serialization(self):
        """Test state serialization and deserialization."""
        state = SharedMessageState()
        state.add_message("user", "Test message")
        state.add_message("assistant", "Response", agent_name="supervisor")
        state.add_handoff("supervisor", "swe", "Code task")

        # Serialize
        data = state.to_dict()

        # Deserialize
        restored = SharedMessageState.from_dict(data)

        assert restored.session_id == state.session_id
        assert len(restored.messages) == 3
        assert restored.current_agent == "swe"
        assert restored.agents_used == ["supervisor"]

    def test_clear(self):
        """Test clearing state."""
        state = SharedMessageState()
        state.add_message("user", "Test")
        state.agents_used = ["swe", "sre"]
        state.iteration_count = 5

        state.clear()

        assert state.messages == []
        assert state.agents_used == []
        assert state.iteration_count == 0
        assert state.current_agent == "supervisor"


class TestTransferTools:
    """Tests for transfer tools."""

    @pytest.mark.asyncio
    async def test_transfer_to_swe(self):
        """Test TransferToSWETool."""
        tool = TransferToSWETool()

        result = await tool.execute(task="Fix the login bug", priority="high")

        assert result.success
        assert result.output.startswith(HANDOFF_PREFIX)
        assert "swe" in result.output
        assert result.target_agent == "swe"
        assert result.task == "Fix the login bug"

    @pytest.mark.asyncio
    async def test_transfer_to_sre(self):
        """Test TransferToSRETool."""
        tool = TransferToSRETool()

        result = await tool.execute(task="Check Sentry errors", context="High priority")

        assert result.success
        assert result.target_agent == "sre"
        assert "Check Sentry" in result.task

    @pytest.mark.asyncio
    async def test_transfer_to_supervisor(self):
        """Test TransferToSupervisorTool."""
        tool = TransferToSupervisorTool()

        result = await tool.execute(result="Completed the code fix", needs_followup=True)

        assert result.success
        assert result.target_agent == "supervisor"
        assert "Completed the code fix" in result.task

    def test_is_handoff_result(self):
        """Test handoff detection."""
        assert is_handoff_result(f"{HANDOFF_PREFIX}swe:task")
        assert is_handoff_result(f"{HANDOFF_PREFIX}supervisor:done")
        assert not is_handoff_result("Regular response")
        assert not is_handoff_result("")

    def test_parse_handoff(self):
        """Test handoff parsing."""
        # Valid handoff
        result = parse_handoff(f"{HANDOFF_PREFIX}swe:Fix the bug")
        assert result == ("swe", "Fix the bug")

        # Handoff without task
        result = parse_handoff(f"{HANDOFF_PREFIX}sre")
        assert result == ("sre", "")

        # Not a handoff
        result = parse_handoff("Regular message")
        assert result is None

    def test_get_transfer_tools_for_supervisor(self):
        """Test getting transfer tools for supervisor."""
        tools = get_transfer_tools_for_agent("supervisor")

        tool_names = [t.name for t in tools]
        assert "transfer_to_swe" in tool_names
        assert "transfer_to_sre" in tool_names
        assert "transfer_to_release" in tool_names
        assert "transfer_to_support" in tool_names
        assert "transfer_to_marketer" in tool_names
        # Supervisor shouldn't have transfer to supervisor or PM
        assert "transfer_to_supervisor" not in tool_names

    def test_get_transfer_tools_for_swe(self):
        """Test getting transfer tools for SWE."""
        tools = get_transfer_tools_for_agent("swe")

        tool_names = [t.name for t in tools]
        # SWE should have transfer to supervisor
        assert "transfer_to_supervisor" in tool_names
        # But not other agent transfers (those go through supervisor)
        assert "transfer_to_sre" not in tool_names


class TestSwarmMessage:
    """Tests for SwarmMessage."""

    def test_create_message(self):
        """Test creating a swarm message."""
        msg = SwarmMessage(
            role="user",
            content="Hello",
        )

        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_metadata(self):
        """Test message with metadata."""
        msg = SwarmMessage(
            role="assistant",
            content="Response",
            name="supervisor",
            metadata={"handoff": True},
        )

        assert msg.name == "supervisor"
        assert msg.metadata["handoff"] is True

    def test_to_dict(self):
        """Test message serialization."""
        msg = SwarmMessage(
            role="tool",
            content="Result",
            name="github",
            tool_call_id="call_123",
        )

        d = msg.to_dict()

        assert d["role"] == "tool"
        assert d["content"] == "Result"
        assert d["name"] == "github"
        assert d["tool_call_id"] == "call_123"
        assert "timestamp" in d

    def test_to_llm_message(self):
        """Test converting to LLM format."""
        msg = SwarmMessage(
            role="assistant",
            content="Hello",
            name="supervisor",
        )

        llm_msg = msg.to_llm_message()

        assert llm_msg["role"] == "assistant"
        assert llm_msg["content"] == "Hello"
        # Name is only included for tool role
        assert "name" not in llm_msg


class TestToolSchema:
    """Tests for tool schemas."""

    def test_transfer_to_swe_schema(self):
        """Test SWE transfer tool schema."""
        tool = TransferToSWETool()
        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "transfer_to_swe"

        params = schema["function"]["parameters"]["properties"]
        assert "task" in params
        assert "priority" in params
        assert "context" in params

    def test_transfer_to_supervisor_schema(self):
        """Test supervisor transfer tool schema."""
        tool = TransferToSupervisorTool()
        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "transfer_to_supervisor"

        params = schema["function"]["parameters"]["properties"]
        assert "result" in params
        assert "needs_followup" in params


class TestSupervisorAgent:
    """Tests for SupervisorAgent (without LLM calls)."""

    def test_create_supervisor(self):
        """Test creating a supervisor agent."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()

        assert "Supervisor" in supervisor.name
        assert "Curie" in supervisor.name

    def test_supervisor_has_transfer_tools(self):
        """Test that supervisor has transfer tools."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()

        tool_names = [t.name for t in supervisor.tools]
        assert "transfer_to_swe" in tool_names
        assert "transfer_to_sre" in tool_names
        assert "transfer_to_release" in tool_names

    def test_supervisor_system_prompt(self):
        """Test supervisor system prompt includes team info."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()
        prompt = supervisor._get_system_prompt()

        # Should mention team members
        assert "Ada" in prompt or "SWE" in prompt
        assert "Heisenberg" in prompt or "SRE" in prompt
        assert "Jenkins" in prompt or "Release" in prompt

        # Should mention orchestration
        assert "orchestrat" in prompt.lower()

    def test_delegate_to_method(self):
        """Test delegate_to convenience method."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()
        result = supervisor.delegate_to("swe", "Fix the bug")

        assert is_handoff_result(result)
        parsed = parse_handoff(result)
        assert parsed == ("swe", "Fix the bug")


class TestSwarmOrchestratorUnit:
    """Unit tests for SwarmOrchestrator (without LLM calls)."""

    def test_create_orchestrator(self):
        """Test creating an orchestrator."""
        from vibeteam.swarm import SwarmOrchestrator

        orch = SwarmOrchestrator()

        assert orch.supervisor is not None
        assert "swe" in orch.agents
        assert "sre" in orch.agents
        assert orch.max_iterations == 20

    def test_orchestrator_with_custom_state(self):
        """Test orchestrator with custom shared state."""
        from vibeteam.swarm import SwarmOrchestrator

        state = SharedMessageState()
        state.session_id = "custom-session"

        orch = SwarmOrchestrator(shared_state=state)

        assert orch.shared_state.session_id == "custom-session"

    def test_get_agent(self):
        """Test getting agents by key."""
        from vibeteam.swarm import SwarmOrchestrator

        orch = SwarmOrchestrator()

        swe = orch.get_agent("swe")
        assert swe is not None
        assert "Ada" in swe.name or "Software" in swe.profile

        supervisor = orch.get_agent("supervisor")
        assert supervisor == orch.supervisor

        # PM should return supervisor
        pm = orch.get_agent("pm")
        assert pm == orch.supervisor

    def test_get_unknown_agent_returns_supervisor(self):
        """Test that unknown agent keys return supervisor."""
        from vibeteam.swarm import SwarmOrchestrator

        orch = SwarmOrchestrator()

        unknown = orch.get_agent("unknown_agent")
        assert unknown == orch.supervisor

    def test_get_summary(self):
        """Test getting orchestrator summary."""
        from vibeteam.swarm import SwarmOrchestrator

        orch = SwarmOrchestrator()
        summary = orch.get_summary()

        assert "session_id" in summary
        assert "current_agent" in summary
        assert "iteration_count" in summary
        assert "max_iterations" in summary
        assert summary["current_agent"] == "supervisor"

    def test_reset(self):
        """Test resetting the orchestrator."""
        from vibeteam.swarm import SwarmOrchestrator

        orch = SwarmOrchestrator()
        orch.iteration_count = 5
        orch.shared_state.add_message("user", "Test")

        orch.reset()

        assert orch.iteration_count == 0
        assert len(orch.shared_state.messages) == 0


class TestCreateSwarmOrchestrator:
    """Tests for the factory function."""

    def test_create_default(self):
        """Test creating with defaults."""
        from vibeteam.swarm import create_swarm_orchestrator

        orch = create_swarm_orchestrator()

        assert orch.model == DEFAULT_MODEL
        assert orch.max_iterations == 20

    def test_create_with_custom_model(self):
        """Test creating with custom model."""
        from vibeteam.swarm import create_swarm_orchestrator

        orch = create_swarm_orchestrator(model="openai/gpt-4o")

        assert orch.model == "openai/gpt-4o"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
