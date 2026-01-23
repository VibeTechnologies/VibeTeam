"""
Tests for VibeTeam orchestrator.
"""

from vibeteam import VibeTeam


class TestVibeTeamInitialization:
    """Test VibeTeam initialization."""

    def test_default_initialization(self) -> None:
        """Test default team with all roles."""
        team = VibeTeam()
        status = team.get_team_status()
        assert len(status) == 6  # All 6 roles

    def test_selective_roles(self) -> None:
        """Test team with selected roles only."""
        team = VibeTeam(include_roles=["pm", "swe"])
        status = team.get_team_status()
        assert len(status) == 2
        assert "Product Manager" in status
        assert "Software Engineer" in status

    def test_single_role(self) -> None:
        """Test team with single role."""
        team = VibeTeam(include_roles=["marketer"])
        status = team.get_team_status()
        assert len(status) == 1
        assert "Marketer" in status

    def test_investment_setting(self) -> None:
        """Test investment budget setting."""
        team = VibeTeam(investment=100.0)
        assert team.investment == 100.0


class TestTeamStatus:
    """Test team status reporting."""

    def test_status_contains_required_fields(self) -> None:
        """Verify status contains all required fields."""
        team = VibeTeam(include_roles=["pm"])
        status = team.get_team_status()

        pm_status = status.get("Product Manager")
        assert pm_status is not None
        assert "name" in pm_status
        assert "goal" in pm_status
        assert "actions" in pm_status

    def test_actions_list_format(self) -> None:
        """Verify actions are returned as list of strings."""
        team = VibeTeam(include_roles=["swe"])
        status = team.get_team_status()

        swe_status = status["Software Engineer"]
        actions = swe_status["actions"]
        assert isinstance(actions, list)
        assert all(isinstance(a, str) for a in actions)
