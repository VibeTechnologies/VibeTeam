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


# Singleton instance
_db: SubscriptionDB | None = None


def get_subscription_db() -> SubscriptionDB:
    """Get the singleton subscription database instance."""
    global _db
    if _db is None:
        _db = SubscriptionDB()
    return _db
