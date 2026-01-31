"""
VibeTeam Message Router.

Thread-based subscription model with /RoleName mentions for agent routing.
"""

from vibeteam.router.models import ThreadSubscription, UnifiedMessage
from vibeteam.router.router import Router

__all__ = [
    "Router",
    "UnifiedMessage",
    "ThreadSubscription",
]
