"""
Tests for VibeTeam roles.
"""

from vibeteam.roles import (
    Marketer,
    ProductManager,
    ReleaseEngineer,
    ReliabilityEngineer,
    SoftwareEngineer,
    SupportEngineer,
)


class TestRoleInitialization:
    """Test that all roles initialize correctly."""

    def test_product_manager_init(self) -> None:
        pm = ProductManager()
        assert pm.profile == "Product Manager"
        assert pm.name == "Alice"
        assert len(pm.actions) == 3

    def test_software_engineer_init(self) -> None:
        swe = SoftwareEngineer()
        assert swe.profile == "Software Engineer"
        assert swe.name == "Bob"
        assert len(swe.actions) == 4

    def test_marketer_init(self) -> None:
        marketer = Marketer()
        assert marketer.profile == "Marketer"
        assert marketer.name == "Carol"
        assert len(marketer.actions) == 4

    def test_support_engineer_init(self) -> None:
        support = SupportEngineer()
        assert support.profile == "Support Engineer"
        assert support.name == "Diana"
        assert len(support.actions) == 4

    def test_reliability_engineer_init(self) -> None:
        sre = ReliabilityEngineer()
        assert sre.profile == "Reliability Engineer"
        assert sre.name == "Eve"
        assert len(sre.actions) == 4

    def test_release_engineer_init(self) -> None:
        release = ReleaseEngineer()
        assert release.profile == "Release Engineer"
        assert release.name == "Frank"
        assert len(release.actions) == 4


class TestRoleConfiguration:
    """Test role configuration and properties."""

    def test_temperature_settings(self) -> None:
        """Verify temperature is appropriate for each role."""
        pm = ProductManager()
        swe = SoftwareEngineer()
        marketer = Marketer()
        sre = ReliabilityEngineer()

        # Creative roles should have higher temperature
        assert marketer.temperature > pm.temperature
        # Precise roles should have lower temperature
        assert swe.temperature <= 0.3
        assert sre.temperature <= 0.3

    def test_custom_name(self) -> None:
        """Test custom name assignment."""
        pm = ProductManager(name="CustomPM")
        assert pm.name == "CustomPM"

    def test_actions_are_set(self) -> None:
        """Verify all roles have actions configured."""
        roles = [
            ProductManager(),
            SoftwareEngineer(),
            Marketer(),
            SupportEngineer(),
            ReliabilityEngineer(),
            ReleaseEngineer(),
        ]
        for role in roles:
            assert len(role.actions) > 0, f"{role.profile} has no actions"
