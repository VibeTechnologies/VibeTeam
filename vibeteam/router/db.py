"""
Database operations for thread subscriptions.

Uses SQLAlchemy with async PostgreSQL for persistent storage.
Lazy imports to allow the router package to be used without database deps.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from vibeteam.router.models import AgentRole, MessageSource, ThreadSubscription

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Lazy imports for database operations
def _get_db_session():
    """Lazy import of database session context manager."""
    try:
        from agents.shared.db import get_db_session
        return get_db_session
    except ImportError:
        raise ImportError(
            "Database support requires agents.shared.db. "
            "Make sure SQLAlchemy and asyncpg are installed."
        )


def _get_text():
    """Lazy import of SQLAlchemy text function."""
    from sqlalchemy import text
    return text


class SubscriptionDB:
    """
    SQLAlchemy-backed storage for thread subscriptions.

    Table schema:
        CREATE TABLE thread_subscriptions (
            id SERIAL PRIMARY KEY,
            source VARCHAR(50) NOT NULL,
            thread_id VARCHAR(255) NOT NULL,
            agent_role VARCHAR(50) NOT NULL,
            session_id UUID REFERENCES sessions(id),
            subscribed_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source, thread_id, agent_role)
        );

        CREATE INDEX idx_subscriptions_thread ON thread_subscriptions(source, thread_id);
    """

    async def subscribe(
        self,
        source: MessageSource,
        thread_id: str,
        agent_role: AgentRole,
        session_id: str,
    ) -> ThreadSubscription:
        """
        Subscribe an agent to a thread.

        Uses INSERT ... ON CONFLICT to handle existing subscriptions.
        """
        get_db_session = _get_db_session()
        text = _get_text()

        async with get_db_session() as db:
            # Try to get existing subscription
            result = await db.execute(
                text("""
                    SELECT id, source, thread_id, agent_role, session_id, subscribed_at
                    FROM thread_subscriptions
                    WHERE source = :source AND thread_id = :thread_id AND agent_role = :agent_role
                """),
                {"source": source, "thread_id": thread_id, "agent_role": agent_role},
            )
            existing = result.mappings().one_or_none()

            if existing:
                # Update existing subscription
                await db.execute(
                    text("""
                        UPDATE thread_subscriptions
                        SET session_id = :session_id
                        WHERE id = :id
                    """),
                    {"id": existing["id"], "session_id": session_id},
                )
                return ThreadSubscription(
                    source=existing["source"],
                    thread_id=existing["thread_id"],
                    agent_role=existing["agent_role"],
                    session_id=session_id,
                    subscribed_at=existing["subscribed_at"],
                )
            else:
                # Insert new subscription
                now = datetime.now(timezone.utc)
                await db.execute(
                    text("""
                        INSERT INTO thread_subscriptions (source, thread_id, agent_role, session_id, subscribed_at)
                        VALUES (:source, :thread_id, :agent_role, :session_id, :subscribed_at)
                    """),
                    {
                        "source": source,
                        "thread_id": thread_id,
                        "agent_role": agent_role,
                        "session_id": session_id,
                        "subscribed_at": now,
                    },
                )
                return ThreadSubscription(
                    source=source,
                    thread_id=thread_id,
                    agent_role=agent_role,
                    session_id=session_id,
                    subscribed_at=now,
                )

    async def get_subscribed_agents(
        self,
        source: MessageSource,
        thread_id: str,
    ) -> list[ThreadSubscription]:
        """Get all agents subscribed to a thread."""
        get_db_session = _get_db_session()
        text = _get_text()

        async with get_db_session() as db:
            result = await db.execute(
                text("""
                    SELECT source, thread_id, agent_role, session_id, subscribed_at
                    FROM thread_subscriptions
                    WHERE source = :source AND thread_id = :thread_id
                    ORDER BY subscribed_at
                """),
                {"source": source, "thread_id": thread_id},
            )
            rows = result.mappings().all()

        return [
            ThreadSubscription(
                source=row["source"],
                thread_id=row["thread_id"],
                agent_role=row["agent_role"],
                session_id=str(row["session_id"]) if row["session_id"] else "",
                subscribed_at=row["subscribed_at"],
            )
            for row in rows
        ]

    async def unsubscribe(
        self,
        source: MessageSource,
        thread_id: str,
        agent_role: AgentRole,
    ) -> bool:
        """
        Unsubscribe an agent from a thread.

        Returns True if a subscription was removed.
        """
        get_db_session = _get_db_session()
        text = _get_text()

        async with get_db_session() as db:
            result = await db.execute(
                text("""
                    DELETE FROM thread_subscriptions
                    WHERE source = :source AND thread_id = :thread_id AND agent_role = :agent_role
                """),
                {"source": source, "thread_id": thread_id, "agent_role": agent_role},
            )
            # Check rowcount to see if anything was deleted
            return result.rowcount > 0

    async def cleanup_expired(self, days: int = 7) -> int:
        """
        Remove subscriptions older than the specified days.

        Returns the number of subscriptions removed.
        """
        get_db_session = _get_db_session()
        text = _get_text()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async with get_db_session() as db:
            result = await db.execute(
                text("""
                    DELETE FROM thread_subscriptions
                    WHERE subscribed_at < :cutoff
                """),
                {"cutoff": cutoff},
            )
            count = result.rowcount
            logger.info(f"Cleaned up {count} expired subscriptions")
            return count


class InMemorySubscriptionDB:
    """
    In-memory implementation of SubscriptionDB.

    Used when DATABASE_URL is not set or for testing.
    Thread subscriptions are stored in memory and lost on restart.
    """

    def __init__(self):
        # Key: (source, thread_id) -> list of ThreadSubscription
        self._subscriptions: dict[tuple[str, str], list[ThreadSubscription]] = {}
        logger.info("Using in-memory subscription database (subscriptions will not persist)")

    async def subscribe(
        self,
        source: MessageSource,
        thread_id: str,
        agent_role: AgentRole,
        session_id: str,
    ) -> ThreadSubscription:
        """Subscribe an agent to a thread."""
        key = (source, thread_id)
        now = datetime.now(timezone.utc)

        if key not in self._subscriptions:
            self._subscriptions[key] = []

        # Check for existing subscription
        for sub in self._subscriptions[key]:
            if sub.agent_role == agent_role:
                # Update existing
                sub.session_id = session_id
                return sub

        # Create new subscription
        sub = ThreadSubscription(
            source=source,
            thread_id=thread_id,
            agent_role=agent_role,
            session_id=session_id,
            subscribed_at=now,
        )
        self._subscriptions[key].append(sub)
        return sub

    async def get_subscribed_agents(
        self,
        source: MessageSource,
        thread_id: str,
    ) -> list[ThreadSubscription]:
        """Get all agents subscribed to a thread."""
        key = (source, thread_id)
        return self._subscriptions.get(key, [])

    async def unsubscribe(
        self,
        source: MessageSource,
        thread_id: str,
        agent_role: AgentRole,
    ) -> bool:
        """Unsubscribe an agent from a thread."""
        key = (source, thread_id)
        if key not in self._subscriptions:
            return False

        original_len = len(self._subscriptions[key])
        self._subscriptions[key] = [
            s for s in self._subscriptions[key] if s.agent_role != agent_role
        ]
        return len(self._subscriptions[key]) < original_len

    async def cleanup_expired(self, days: int = 7) -> int:
        """Remove subscriptions older than the specified days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0

        for key in list(self._subscriptions.keys()):
            original_len = len(self._subscriptions[key])
            self._subscriptions[key] = [
                s for s in self._subscriptions[key]
                if s.subscribed_at and s.subscribed_at >= cutoff
            ]
            count += original_len - len(self._subscriptions[key])

            if not self._subscriptions[key]:
                del self._subscriptions[key]

        logger.info(f"Cleaned up {count} expired subscriptions")
        return count


# Singleton instance
_db: SubscriptionDB | InMemorySubscriptionDB | None = None


def get_subscription_db() -> SubscriptionDB | InMemorySubscriptionDB:
    """
    Get the singleton subscription database instance.

    Uses PostgreSQL if DATABASE_URL is set, otherwise uses in-memory storage.
    """
    import os

    global _db
    if _db is None:
        if os.environ.get("DATABASE_URL"):
            _db = SubscriptionDB()
        else:
            _db = InMemorySubscriptionDB()
    return _db


def reset_subscription_db() -> None:
    """Reset the singleton for testing."""
    global _db
    _db = None
