"""VibeTeam team orchestration and simulation.

This module provides:
- SimulatedChannel: In-memory Discord/Slack channel simulation for testing
- ResponsibilityDetector: Proactive task ownership detection for agents
- TeamTestHarness: Test harness for multi-agent scenarios
- Schemas: Structured output for multi-agent coordination (ClaimDecision, AgentResponse)
- Arbitrator: Resolve claims when multiple agents want to handle a message
"""

from vibeteam.team.channel import ChannelMessage, SimulatedChannel
from vibeteam.team.responsibility import ResponsibilityClaim, ResponsibilityDetector
from vibeteam.team.schemas import AgentResponse, ArbitrationResult, ClaimDecision
from vibeteam.team.arbitrator import get_active_agents, resolve_claims, should_escalate
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
    # Responsibility detection (legacy)
    "ResponsibilityClaim",
    "ResponsibilityDetector",
    # Structured schemas (new)
    "ClaimDecision",
    "AgentResponse",
    "ArbitrationResult",
    # Arbitration
    "resolve_claims",
    "should_escalate",
    "get_active_agents",
    # Test harness
    "MockAgent",
    "ScenarioResult",
    "TeamTestHarness",
    "create_handoff_test_case",
]
