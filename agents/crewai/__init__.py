"""
CrewAI agent implementations for VibeTeam.

CrewAI provides:
- Multi-agent orchestration via Crew
- 40+ built-in tools
- Enterprise apps integration (Gmail, Calendar, etc.)
- Task delegation and hierarchical processes
"""

from agents.crewai.release_engineer import (
    CrewAIReleaseEngineer,
    create_release_engineer,
)
from agents.crewai.marketing_manager import (
    CrewAIMarketingManager,
    create_marketing_manager,
)
from agents.crewai.support_engineer import (
    CrewAISupportEngineer,
    create_support_engineer,
)
from agents.crewai.crew import CrewAITeam, create_team

__all__ = [
    "CrewAIReleaseEngineer",
    "CrewAIMarketingManager",
    "CrewAISupportEngineer",
    "CrewAITeam",
    "create_release_engineer",
    "create_marketing_manager",
    "create_support_engineer",
    "create_team",
]
