"""
VibeTeam Message Router.

Thread-based subscription model with /RoleName mentions for agent routing.
"""

from vibeteam.router.db import InMemorySubscriptionDB, SubscriptionDB, get_subscription_db
from vibeteam.router.models import ThreadSubscription, UnifiedMessage
from vibeteam.router.router import Router

__all__ = [
    "InMemorySubscriptionDB",
    "Router",
    "SubscriptionDB",
    "ThreadSubscription",
    "UnifiedMessage",
    "get_subscription_db",
]
