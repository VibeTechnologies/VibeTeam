"""Tests for VibeTeam orchestrator."""

from vibeteam import AgentType, TaskResult, VibeTeam
from vibeteam.orchestrator import AGENT_REGISTRY, ROUTING_KEYWORDS


class TestVibeTeamInit:
    """Tests for VibeTeam initialization."""

    def test_default_initialization(self):
        """Test team initializes with all agents by default."""
        team = VibeTeam()
        assert len(team._agents) == 6
        assert AgentType.PM in team._agents
        assert AgentType.SWE in team._agents
        assert AgentType.MARKETER in team._agents
        assert AgentType.SUPPORT in team._agents
        assert AgentType.SRE in team._agents
        assert AgentType.RELEASE in team._agents

    def test_custom_agents(self):
        """Test team with subset of agents."""
        team = VibeTeam(include_agents=[AgentType.SWE, AgentType.PM])
        assert len(team._agents) == 2
        assert AgentType.SWE in team._agents
        assert AgentType.PM in team._agents
        assert AgentType.MARKETER not in team._agents

    def test_custom_model(self):
        """Test team with custom model."""
        team = VibeTeam(model="anthropic/claude-3-opus-20240229")
        for agent in team._agents.values():
            assert agent.model == "anthropic/claude-3-opus-20240229"


class TestTaskRouting:
    """Tests for automatic task routing."""

    def test_routes_to_swe_for_code(self):
        """Test code-related tasks route to SWE."""
        team = VibeTeam()
        task = "Implement the login feature from GitHub issue #123"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.SWE

    def test_routes_to_pm_for_requirements(self):
        """Test requirement tasks route to PM."""
        team = VibeTeam()
        task = "Analyze Langfuse conversations and prioritize features"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.PM

    def test_routes_to_marketer_for_social(self):
        """Test social media tasks route to Marketer."""
        team = VibeTeam()
        task = "Create a LinkedIn post about the new release"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.MARKETER

    def test_routes_to_support_for_customer(self):
        """Test customer issues route to Support."""
        team = VibeTeam()
        task = "Help a customer with their support ticket"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.SUPPORT

    def test_routes_to_sre_for_monitoring(self):
        """Test monitoring tasks route to SRE."""
        team = VibeTeam()
        task = "Check Sentry for production errors and alerts"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.SRE

    def test_routes_to_release_for_deployment(self):
        """Test deployment tasks route to Release."""
        team = VibeTeam()
        task = "Create a changelog and tag the release"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.RELEASE

    def test_defaults_to_swe(self):
        """Test ambiguous tasks default to SWE."""
        team = VibeTeam()
        task = "Do something with the thing"
        agent_type = team.route_task(task)
        assert agent_type == AgentType.SWE


class TestTeamOperations:
    """Tests for team operations."""

    def test_get_agent(self):
        """Test getting a specific agent."""
        team = VibeTeam()
        agent = team.get_agent(AgentType.SWE)
        assert agent is not None
        assert agent.profile == "Software Engineer"

    def test_get_agent_not_included(self):
        """Test getting an agent not in the team."""
        team = VibeTeam(include_agents=[AgentType.PM])
        agent = team.get_agent(AgentType.SWE)
        assert agent is None

    def test_list_agents(self):
        """Test listing all agents."""
        team = VibeTeam()
        agents = team.list_agents()
        assert len(agents) == 6
        agent_types = [t for t, _ in agents]
        assert AgentType.SWE in agent_types

    def test_get_team_status(self):
        """Test getting team status."""
        team = VibeTeam()
        status = team.get_team_status()
        assert "swe" in status
        assert "name" in status["swe"]
        assert "tools" in status["swe"]
        assert "model" in status["swe"]


class TestAgentRegistry:
    """Tests for agent registry and routing keywords."""

    def test_all_agent_types_registered(self):
        """Test all agent types have registry entries."""
        for agent_type in AgentType:
            assert agent_type in AGENT_REGISTRY

    def test_all_agent_types_have_keywords(self):
        """Test all agent types have routing keywords."""
        for agent_type in AgentType:
            assert agent_type in ROUTING_KEYWORDS
            assert len(ROUTING_KEYWORDS[agent_type]) > 0


class TestTaskResult:
    """Tests for TaskResult dataclass."""

    def test_success_result(self):
        """Test successful task result."""
        result = TaskResult(
            agent_type=AgentType.SWE,
            task="test task",
            success=True,
            response="done",
        )
        assert result.success
        assert result.error is None

    def test_error_result(self):
        """Test error task result."""
        result = TaskResult(
            agent_type=AgentType.SWE,
            task="test task",
            success=False,
            response="",
            error="something went wrong",
        )
        assert not result.success
        assert result.error == "something went wrong"
