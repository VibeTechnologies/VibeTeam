"""VibeTeam team orchestration and simulation.

This module provides:
- SimulatedChannel: In-memory Discord/Slack channel simulation for testing
- ResponsibilityDetector: Proactive task ownership detection for agents
- TeamTestHarness: Test harness for multi-agent scenarios
"""

from vibeteam.team.channel import ChannelMessage, SimulatedChannel
from vibeteam.team.responsibility import ResponsibilityClaim, ResponsibilityDetector
from vibeteam.team.harness import (
    MockAgent,
    ScenarioResult,
    TeamTestHarness,
    create_handoff_test_case,
)

__all__ = [
    # Channel simulation
    "ChannelMessage",
    "SimulatedChannel",
    # Responsibility detection
    "ResponsibilityClaim",
    "ResponsibilityDetector",
    # Test harness
    "MockAgent",
    "ScenarioResult",
    "TeamTestHarness",
    "create_handoff_test_case",
]
