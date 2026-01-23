"""
VibeTeam - MetaGPT-based autonomous AI team for SaaS development.

This package provides a multi-agent system with specialized roles:
- ProductManager: Defines requirements, roadmap, user stories
- SoftwareEngineer: Implements features, fixes bugs, writes tests
- Marketer: Creates content, social media posts, announcements
- SupportEngineer: Handles user issues, documentation, FAQ
- ReliabilityEngineer: Monitors production, handles incidents
- ReleaseEngineer: Manages deployments, versioning, releases
"""

__version__ = "2.0.0"

from vibeteam.team import VibeTeam

__all__ = ["VibeTeam", "__version__"]
