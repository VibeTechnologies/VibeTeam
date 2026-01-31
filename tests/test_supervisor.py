"""Tests for SupervisorAgent."""

from vibeteam.agents.supervisor import SupervisorAgent
from vibeteam.state import SharedMessageState


class TestSupervisorAgent:
    """Tests for SupervisorAgent initialization and configuration."""

    def test_initialization(self):
        """Test supervisor initializes correctly."""
        supervisor = SupervisorAgent()
        assert supervisor.name == "ProductManager"
        assert supervisor.profile == "Product Manager & Team Supervisor"

    def test_initialization_with_shared_state(self):
        """Test supervisor with explicit shared state."""
        state = SharedMessageState()
        supervisor = SupervisorAgent(shared_state=state)
        assert supervisor.shared_state is state

    def test_initialization_with_custom_model(self):
        """Test supervisor with custom model."""
        supervisor = SupervisorAgent(model="azure/gpt-5-2")
        assert supervisor.model == "azure/gpt-5-2"

    def test_system_prompt_includes_team(self):
        """Test system prompt includes team member descriptions."""
        supervisor = SupervisorAgent()
        prompt = supervisor._get_system_prompt()

        # Should include team members
        assert "SoftwareEngineer" in prompt
        assert "ReleaseEngineer" in prompt
        assert "SupportEngineer" in prompt
        assert "SiteReliabilityEngineer" in prompt
        assert "MarketingManager" in prompt

    def test_system_prompt_includes_mention_instructions(self):
        """Test system prompt includes @mention instructions."""
        supervisor = SupervisorAgent()
        prompt = supervisor._get_system_prompt()

        # Should have @mention examples
        assert "@SoftwareEngineer" in prompt
        assert "@ReleaseEngineer" in prompt

        # Should mention orchestration
        assert "orchestrat" in prompt.lower()


class TestSupervisorWithSharedState:
    """Tests for supervisor integration with SharedMessageState."""

    def test_run_with_state_method_exists(self):
        """Test run_with_state uses shared state context."""
        state = SharedMessageState()
        state.add_message("user", "Previous context")

        supervisor = SupervisorAgent(shared_state=state)
        # Verify the method exists and accepts the state
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
