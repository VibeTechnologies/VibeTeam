"""Tests for SupervisorAgent."""


from vibeteam.agents.supervisor import (
    SupervisorAgent,
    get_handoff_target,
    is_supervisor_response_final,
)
from vibeteam.state import SharedMessageState
from vibeteam.tools.transfer import HANDOFF_PREFIX


class TestSupervisorAgent:
    """Tests for SupervisorAgent initialization and configuration."""

    def test_initialization(self):
        """Test supervisor initializes correctly."""
        supervisor = SupervisorAgent()
        assert supervisor.name == "Curie (Supervisor)"
        assert supervisor.profile == "Product Manager & Team Supervisor"
        assert "gpt-4" in supervisor.model

    def test_initialization_with_shared_state(self):
        """Test supervisor with explicit shared state."""
        state = SharedMessageState()
        supervisor = SupervisorAgent(shared_state=state)
        assert supervisor.shared_state is state

    def test_initialization_with_custom_model(self):
        """Test supervisor with custom model."""
        supervisor = SupervisorAgent(model="azure/gpt-5-2")
        assert supervisor.model == "azure/gpt-5-2"

    def test_has_transfer_tools(self):
        """Test supervisor has transfer tools."""
        supervisor = SupervisorAgent()
        tool_names = [t.name for t in supervisor.tools]

        assert "transfer_to_swe" in tool_names
        assert "transfer_to_sre" in tool_names
        assert "transfer_to_release" in tool_names
        assert "transfer_to_support" in tool_names
        assert "transfer_to_marketer" in tool_names

    def test_system_prompt_includes_team(self):
        """Test system prompt includes team member descriptions."""
        supervisor = SupervisorAgent()
        prompt = supervisor._get_system_prompt()

        assert "Ada" in prompt or "SWE" in prompt
        assert "supervisor" in prompt.lower() or "orchestrat" in prompt.lower()

    def test_delegate_to(self):
        """Test programmatic delegation."""
        supervisor = SupervisorAgent()
        handoff = supervisor.delegate_to("swe", "Fix bug #123")

        assert handoff.startswith(HANDOFF_PREFIX)
        assert "swe" in handoff
        assert "Fix bug #123" in handoff


class TestSupervisorResponseHelpers:
    """Tests for supervisor response helper functions."""

    def test_is_final_response_true(self):
        """Test detecting final responses."""
        assert is_supervisor_response_final("Here is your answer.")
        assert is_supervisor_response_final("The task is complete.")
        assert is_supervisor_response_final("")

    def test_is_final_response_false_for_handoff(self):
        """Test handoff is not a final response."""
        handoff = f"{HANDOFF_PREFIX}swe:Fix the bug"
        assert not is_supervisor_response_final(handoff)

    def test_get_handoff_target_valid(self):
        """Test parsing valid handoff."""
        handoff = f"{HANDOFF_PREFIX}swe:Fix the bug"
        result = get_handoff_target(handoff)

        assert result is not None
        agent, task = result
        assert agent == "swe"
        assert task == "Fix the bug"

    def test_get_handoff_target_no_task(self):
        """Test parsing handoff without task."""
        handoff = f"{HANDOFF_PREFIX}sre"
        result = get_handoff_target(handoff)

        assert result is not None
        agent, task = result
        assert agent == "sre"
        assert task == ""

    def test_get_handoff_target_not_handoff(self):
        """Test non-handoff returns None."""
        result = get_handoff_target("Just a regular response")
        assert result is None


class TestSupervisorWithSharedState:
    """Tests for supervisor integration with SharedMessageState."""

    def test_run_with_state_adds_context(self):
        """Test run_with_state uses shared state context."""
        state = SharedMessageState()
        state.add_message("user", "Previous context")

        supervisor = SupervisorAgent(shared_state=state)
        # Just verify the method exists and accepts the state
        # Actual LLM call would require mocking
        assert hasattr(supervisor, "run_with_state")

    def test_supervisor_preserves_state_reference(self):
        """Test supervisor maintains reference to shared state."""
        state = SharedMessageState()
        supervisor = SupervisorAgent(shared_state=state)

        # Modify state externally
        state.add_message("user", "Hello")

        # Supervisor should see the change
        assert supervisor.shared_state is state
        assert len(supervisor.shared_state.messages) == 1
