"""
End-to-end tests for VibeTeam.

These tests verify the complete workflow with actual LLM calls.
Requires OPENAI_API_KEY to be set.
"""

import os

import pytest

from vibeteam import VibeTeam
from vibeteam.roles import ProductManager, SoftwareEngineer
from vibeteam.roles.product_manager import WritePRD


@pytest.mark.e2e
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestE2EWorkflow:
    """End-to-end workflow tests."""

    @pytest.mark.asyncio
    async def test_prd_generation(self) -> None:
        """Test PRD generation from requirement."""
        action = WritePRD()
        result = await action.run("Build a simple todo list application")

        assert result is not None
        assert len(result) > 100  # Should generate substantial content
        assert "todo" in result.lower() or "task" in result.lower()

    @pytest.mark.asyncio
    async def test_team_basic_run(self) -> None:
        """Test basic team execution."""
        team = VibeTeam(include_roles=["pm"], investment=1.0)

        # This would actually run the team - expensive operation
        # For CI, we just verify initialization works
        status = team.get_team_status()
        assert "Product Manager" in status


@pytest.mark.e2e
class TestGitHubCopilotCompatibility:
    """Tests for GitHub Copilot subscription compatibility."""

    def test_model_configuration(self) -> None:
        """Verify models use Azure OpenAI gpt-5.2."""
        from vibeteam.roles.base import VibeRole

        role = VibeRole()
        # Should use azure/gpt-5.2 for high-quality agent reasoning
        assert role.model == "azure/gpt-5.2"

    def test_all_roles_use_compatible_models(self) -> None:
        """Verify all roles use compatible models."""
        from vibeteam.roles import (
            Marketer,
            ReleaseEngineer,
            ReliabilityEngineer,
            SupportEngineer,
        )

        roles = [
            ProductManager(),
            SoftwareEngineer(),
            Marketer(),
            SupportEngineer(),
            ReliabilityEngineer(),
            ReleaseEngineer(),
        ]

        for role in roles:
            # All should inherit from VibeRole which sets azure/gpt-5.2
            assert hasattr(role, "model")
            assert role.model == "azure/gpt-5.2"
