"""VibeTeam test library.

This module provides:
- SimulatedChannel: In-memory Discord/Slack channel simulation for testing
- ResponsibilityDetector: Keyword-based task ownership detection (legacy)
- TeamTestHarness: Test harness for multi-agent scenarios
"""

from vibeteam.lib.channel import ChannelMessage, SimulatedChannel
from vibeteam.lib.harness import (
    MockAgent,
    ScenarioResult,
    TeamTestHarness,
    create_handoff_test_case,
)
from vibeteam.lib.responsibility import ResponsibilityClaim, ResponsibilityDetector

__all__ = [
    # Channel simulation
    "ChannelMessage",
    "SimulatedChannel",
    # Responsibility detection (legacy - use /RoleName routing instead)
    "ResponsibilityClaim",
    "ResponsibilityDetector",
    # Test harness
    "MockAgent",
    "ScenarioResult",
    "TeamTestHarness",
    "create_handoff_test_case",
]
