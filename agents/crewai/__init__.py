"""
CrewAI agent implementations for VibeTeam.

CrewAI provides:
- Multi-agent orchestration via Crew
- 40+ built-in tools
- Enterprise apps integration (Gmail, Calendar, etc.)
- Task delegation and hierarchical processes
"""

from agents.crewai.crew import CrewAITeam, create_team
from agents.crewai.llm import AzureFunctionCallingLLM
from agents.crewai.marketing_manager import (
    CrewAIMarketingManager,
    create_marketing_manager,
)
from agents.crewai.product_manager import (
    CrewAIProductManager,
    create_product_manager,
)
from agents.crewai.release_engineer import (
    CrewAIReleaseEngineer,
    create_release_engineer,
)
from agents.crewai.software_engineer import (
    CrewAISoftwareEngineer,
    create_software_engineer,
)
from agents.crewai.support_engineer import (
    CrewAISupportEngineer,
    create_support_engineer,
)

__all__ = [
    "AzureFunctionCallingLLM",
    "CrewAIProductManager",
    "CrewAIReleaseEngineer",
    "CrewAIMarketingManager",
    "CrewAISoftwareEngineer",
    "CrewAISupportEngineer",
    "CrewAITeam",
    "create_product_manager",
    "create_release_engineer",
    "create_marketing_manager",
    "create_software_engineer",
    "create_support_engineer",
    "create_team",
]
