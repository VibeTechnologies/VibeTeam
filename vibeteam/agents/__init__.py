"""
VibeTeam Agents - OpenHands-based agents replacing MetaGPT roles.

Each agent is a specialized worker with specific tools and capabilities.
"""

from vibeteam.agents.base import BaseVibeAgent
from vibeteam.agents.marketer import MarketerAgent
from vibeteam.agents.product_manager import ProductManagerAgent
from vibeteam.agents.release_engineer import ReleaseEngineerAgent
from vibeteam.agents.software_engineer import SoftwareEngineerAgent
from vibeteam.agents.supervisor import SupervisorAgent
from vibeteam.agents.support_engineer import SupportEngineerAgent

__all__ = [
    "BaseVibeAgent",
    "ProductManagerAgent",
    "SoftwareEngineerAgent",
    "MarketerAgent",
    "SupportEngineerAgent",
    "ReleaseEngineerAgent",
    "SupervisorAgent",
]
