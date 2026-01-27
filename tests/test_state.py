"""Tests for SharedMessageState and SwarmMessage."""

from datetime import datetime, timezone

import pytest

from vibeteam.state import SharedMessageState, SwarmMessage


class TestSwarmMessage:
    """Tests for SwarmMessage dataclass."""

    def test_create_message(self):
        """Test basic message creation."""
        msg = SwarmMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.tool_calls is None
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_all_fields(self):
        """Test message with all optional fields."""
        msg = SwarmMessage(
            role="assistant",
            content="Response",
            name="TestAgent",
            tool_call_id="call_123",
            tool_calls=[{"id": "1", "function": {"name": "test"}}],
            metadata={"key": "value"},
        )
        assert msg.name == "TestAgent"
        assert msg.tool_call_id == "call_123"
        assert len(msg.tool_calls) == 1
        assert msg.metadata["key"] == "value"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        msg = SwarmMessage(
            role="assistant",
            content="Test",
            name="Agent",
            metadata={"type": "test"},
        )
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "Test"
        assert d["name"] == "Agent"
        assert "timestamp" in d
        assert d["metadata"]["type"] == "test"

    def test_to_llm_message(self):
        """Test conversion to LLM-compatible format."""
        msg = SwarmMessage(
            role="tool",
            content="Tool result",
            name="my_tool",
            tool_call_id="call_456",
        )
        llm_msg = msg.to_llm_message()
        assert llm_msg["role"] == "tool"
        assert llm_msg["content"] == "Tool result"
        assert llm_msg["name"] == "my_tool"
        assert llm_msg["tool_call_id"] == "call_456"

    def test_to_llm_message_without_optional_fields(self):
        """Test LLM message without optional fields."""
        msg = SwarmMessage(role="user", content="Hello")
        llm_msg = msg.to_llm_message()
        assert llm_msg == {"role": "user", "content": "Hello"}


class TestSharedMessageState:
    """Tests for SharedMessageState."""

    def test_initial_state(self):
        """Test initial state is empty."""
        state = SharedMessageState()
        assert len(state.messages) == 0
        assert state.current_agent == "supervisor"
        assert len(state.session_id) > 0
        assert state.iteration_count == 0
        assert len(state.agents_used) == 0

    def test_add_message(self):
        """Test adding a message."""
        state = SharedMessageState()
        msg = state.add_message("user", "Hello")
        assert len(state.messages) == 1
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_add_message_tracks_agents(self):
        """Test that adding messages tracks agent usage."""
        state = SharedMessageState()
        state.add_message("assistant", "Response 1", agent_name="Agent1")
        state.add_message("assistant", "Response 2", agent_name="Agent2")
        state.add_message("assistant", "Response 3", agent_name="Agent1")

        assert len(state.agents_used) == 2
        assert "Agent1" in state.agents_used
        assert "Agent2" in state.agents_used

    def test_add_handoff(self):
        """Test recording a handoff."""
        state = SharedMessageState()
        msg = state.add_handoff("supervisor", "swe", "Fix bug #123")

        assert state.current_agent == "swe"
        assert msg.role == "system"
        assert "supervisor" in msg.content
        assert "swe" in msg.content
        assert msg.metadata["type"] == "handoff"
        assert msg.metadata["from"] == "supervisor"
        assert msg.metadata["to"] == "swe"
        assert msg.metadata["task"] == "Fix bug #123"

    def test_get_context_for_agent(self):
        """Test getting context for an agent."""
        state = SharedMessageState()
        state.add_message("system", "System prompt")
        state.add_message("user", "Hello")
        state.add_message("assistant", "Hi there", agent_name="Agent1")

        # With system messages
        context = state.get_context_for_agent("Agent1", include_system=True)
        assert len(context) == 3

        # Without system messages
        context = state.get_context_for_agent("Agent1", include_system=False)
        assert len(context) == 2

    def test_get_recent_messages(self):
        """Test getting recent messages."""
        state = SharedMessageState()
        for i in range(15):
            state.add_message("user", f"Message {i}")

        recent = state.get_recent_messages(5)
        assert len(recent) == 5
        assert recent[-1].content == "Message 14"
        assert recent[0].content == "Message 10"

    def test_get_messages_by_agent(self):
        """Test filtering messages by agent."""
        state = SharedMessageState()
        state.add_message("assistant", "Response 1", agent_name="Agent1")
        state.add_message("assistant", "Response 2", agent_name="Agent2")
        state.add_message("assistant", "Response 3", agent_name="Agent1")

        agent1_msgs = state.get_messages_by_agent("Agent1")
        assert len(agent1_msgs) == 2
        assert all(m.name == "Agent1" for m in agent1_msgs)

    def test_get_last_user_message(self):
        """Test getting the last user message."""
        state = SharedMessageState()
        state.add_message("user", "First question")
        state.add_message("assistant", "Answer")
        state.add_message("user", "Second question")

        last_user = state.get_last_user_message()
        assert last_user is not None
        assert last_user.content == "Second question"

    def test_get_last_user_message_empty(self):
        """Test getting last user message when none exists."""
        state = SharedMessageState()
        state.add_message("assistant", "Hello")

        last_user = state.get_last_user_message()
        assert last_user is None

    def test_get_summary(self):
        """Test getting state summary."""
        state = SharedMessageState()
        state.add_message("user", "Hello")
        state.add_message("assistant", "Hi", agent_name="Agent1")
        state.iteration_count = 3

        summary = state.get_summary()
        assert summary["message_count"] == 2
        assert summary["agents_used"] == ["Agent1"]
        assert summary["iteration_count"] == 3
        assert "session_id" in summary
        assert "created_at" in summary

    def test_to_dict(self):
        """Test serialization to dictionary."""
        state = SharedMessageState()
        state.add_message("user", "Hello")
        state.add_message("assistant", "Hi", agent_name="Agent1")
        state.task_context = {"key": "value"}

        d = state.to_dict()
        assert d["session_id"] == state.session_id
        assert d["current_agent"] == "supervisor"
        assert len(d["messages"]) == 2
        assert d["task_context"]["key"] == "value"
        assert d["agents_used"] == ["Agent1"]

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        original = SharedMessageState()
        original.add_message("user", "Hello")
        original.add_message("assistant", "Hi", agent_name="Agent1")
        original.iteration_count = 5

        d = original.to_dict()
        restored = SharedMessageState.from_dict(d)

        assert restored.session_id == original.session_id
        assert len(restored.messages) == 2
        assert restored.messages[0].content == "Hello"
        assert restored.messages[1].name == "Agent1"
        assert restored.iteration_count == 5

    def test_clear(self):
        """Test clearing state."""
        state = SharedMessageState()
        state.add_message("user", "Hello")
        state.add_message("assistant", "Hi", agent_name="Agent1")
        state.iteration_count = 5
        state.current_agent = "swe"

        state.clear()

        assert len(state.messages) == 0
        assert len(state.agents_used) == 0
        assert state.iteration_count == 0
        assert state.current_agent == "supervisor"
        # Session ID should be preserved
        assert len(state.session_id) > 0


class TestSharedMessageStateIntegration:
    """Integration tests for SharedMessageState."""

    def test_full_conversation_flow(self):
        """Test a full conversation flow with handoffs."""
        state = SharedMessageState()

        # User request
        state.add_message("user", "Fix the login bug from Sentry")

        # Supervisor analyzes and hands off to SRE
        state.add_message(
            "assistant",
            "I'll delegate this to our Reliability Engineer to investigate.",
            agent_name="supervisor",
        )
        state.add_handoff("supervisor", "sre", "Investigate Sentry error")

        # SRE investigates and hands off to SWE
        state.add_message(
            "assistant",
            "Found the bug in login.py line 42. Handing off to SWE for fix.",
            agent_name="sre",
        )
        state.add_handoff("sre", "swe", "Fix login.py line 42")

        # SWE fixes and returns to supervisor
        state.add_message(
            "assistant",
            "Fixed the bug and created PR #123.",
            agent_name="swe",
        )
        state.add_handoff("swe", "supervisor", "PR #123 created")

        # Supervisor synthesizes
        state.add_message(
            "assistant",
            "The login bug has been fixed. PR #123 is ready for review.",
            agent_name="supervisor",
        )

        # Verify state
        assert len(state.agents_used) == 3
        assert "supervisor" in state.agents_used
        assert "sre" in state.agents_used
        assert "swe" in state.agents_used
        assert state.current_agent == "supervisor"

        # Verify we can get context for any agent
        swe_context = state.get_context_for_agent("swe")
        assert len(swe_context) > 0
