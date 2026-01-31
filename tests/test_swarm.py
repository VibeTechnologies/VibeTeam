"""
Tests for SharedMessageState and SwarmMessage.

These tests verify:
1. SharedMessageState functionality
2. SwarmMessage creation and serialization
3. Context retrieval for agents
"""

from datetime import datetime

import pytest

from vibeteam.state import SharedMessageState, SwarmMessage


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

    def test_get_recent_messages(self):
        """Test getting recent messages."""
        state = SharedMessageState()
        for i in range(15):
            state.add_message("user", f"Message {i}")

        recent = state.get_recent_messages(5)

        assert len(recent) == 5
        assert recent[0].content == "Message 10"
        assert recent[-1].content == "Message 14"

    def test_get_messages_by_agent(self):
        """Test getting messages by agent."""
        state = SharedMessageState()
        state.add_message("assistant", "Supervisor says", agent_name="supervisor")
        state.add_message("assistant", "SWE says", agent_name="swe")
        state.add_message("assistant", "More from supervisor", agent_name="supervisor")

        supervisor_msgs = state.get_messages_by_agent("supervisor")

        assert len(supervisor_msgs) == 2
        assert all(m.name == "supervisor" for m in supervisor_msgs)

    def test_get_summary(self):
        """Test getting state summary."""
        state = SharedMessageState()
        state.add_message("user", "Test")
        state.add_message("assistant", "Response", agent_name="swe")
        state.iteration_count = 3

        summary = state.get_summary()

        assert summary["session_id"] == state.session_id
        assert summary["current_agent"] == "supervisor"
        assert summary["message_count"] == 2
        assert summary["agents_used"] == ["swe"]
        assert summary["iteration_count"] == 3


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

    def test_to_llm_message_with_tool_role(self):
        """Test tool role includes name."""
        msg = SwarmMessage(
            role="tool",
            content="Result",
            name="github",
            tool_call_id="call_123",
        )

        llm_msg = msg.to_llm_message()

        assert llm_msg["role"] == "tool"
        assert llm_msg["name"] == "github"
        assert llm_msg["tool_call_id"] == "call_123"

    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        tool_calls = [
            {"id": "call_1", "function": {"name": "search", "arguments": "{}"}}
        ]
        msg = SwarmMessage(
            role="assistant",
            content="Let me search",
            tool_calls=tool_calls,
        )

        assert msg.tool_calls == tool_calls
        llm_msg = msg.to_llm_message()
        assert llm_msg["tool_calls"] == tool_calls


class TestSupervisorAgent:
    """Tests for SupervisorAgent (without LLM calls)."""

    def test_create_supervisor(self):
        """Test creating a supervisor agent."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()

        assert supervisor.name == "ProductManager"
        assert "Supervisor" in supervisor.profile

    def test_supervisor_system_prompt(self):
        """Test supervisor system prompt includes team info."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()
        prompt = supervisor._get_system_prompt()

        # Should mention team members by role name
        assert "SoftwareEngineer" in prompt
        assert "ReleaseEngineer" in prompt
        assert "SupportEngineer" in prompt

        # Should mention orchestration and @mentions
        assert "orchestrat" in prompt.lower()
        assert "@" in prompt  # Should have @mention examples

    def test_supervisor_with_shared_state(self):
        """Test supervisor with shared state."""
        from vibeteam.agents.supervisor import SupervisorAgent

        state = SharedMessageState()
        state.add_message("user", "Hello")

        supervisor = SupervisorAgent(shared_state=state)

        assert supervisor.shared_state is state
        assert len(supervisor.shared_state.messages) == 1

    def test_supervisor_run_with_state_method_exists(self):
        """Test run_with_state method exists."""
        from vibeteam.agents.supervisor import SupervisorAgent

        supervisor = SupervisorAgent()
        assert hasattr(supervisor, "run_with_state")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
