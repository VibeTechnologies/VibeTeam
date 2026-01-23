"""
VibeTeam Roles - Specialized agents based on MetaGPT Role pattern.
"""

from vibeteam.roles.base import VibeRole
from vibeteam.roles.marketer import Marketer
from vibeteam.roles.product_manager import ProductManager
from vibeteam.roles.reliability_engineer import ReliabilityEngineer
from vibeteam.roles.release_engineer import ReleaseEngineer
from vibeteam.roles.software_engineer import SoftwareEngineer
from vibeteam.roles.support_engineer import SupportEngineer

__all__ = [
    "VibeRole",
    "ProductManager",
    "SoftwareEngineer",
    "Marketer",
    "SupportEngineer",
    "ReliabilityEngineer",
    "ReleaseEngineer",
]
