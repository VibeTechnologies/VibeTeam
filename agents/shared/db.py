from __future__ import annotations

"""
Database module for agent sessions and task results.

Provides async session storage using SQLAlchemy ORM.
Supports PostgreSQL (production) and SQLite (local / test).

All queries use the ORM so they are dialect-agnostic — switching
between PostgreSQL and SQLite requires only changing DATABASE_URL.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class Session(Base):
    """Agent session model (works on PostgreSQL and SQLite)."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(255), unique=True, nullable=False, index=True)
    framework = Column(String(50), nullable=False)
    role = Column(String(50), nullable=False)
    context_type = Column(String(50), nullable=False)
    context_id = Column(String(255), nullable=False)
    messages = Column(JSON, default=list)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": str(self.id),
            "key": self.key,
            "framework": self.framework,
            "role": self.role,
            "context_type": self.context_type,
            "context_id": self.context_id,
            "messages": self.messages or [],
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskResult(Base):
    """Task execution result model."""

    __tablename__ = "task_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), nullable=True, index=True)
    framework = Column(String(50), nullable=False)
    role = Column(String(50), nullable=False)
    task = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    error = Column(Text, nullable=True)
    tokens_used = Column(String(20), nullable=True)
    latency_ms = Column(String(20), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "framework": self.framework,
            "role": self.role,
            "task": self.task,
            "response": self.response,
            "status": self.status,
            "error": self.error,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def get_database_url() -> str:
    """Get database URL from environment.

    Supports:
      - ``sqlite+aiosqlite:///path/to/db`` (local / test)
      - ``postgres://`` or ``postgresql://`` (converted to asyncpg)
    """
    url = os.getenv("DATABASE_URL")
    if url:
        # SQLite – pass through as-is
        if url.startswith("sqlite"):
            return url
        # Convert postgres:// to postgresql+asyncpg://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    # Default for in-cluster
    return "postgresql+asyncpg://vibeteam:vibeteam-pg-2026@postgres:5432/vibeteam"


# Global engine and session factory
_engine = None
_async_session_factory = None


def get_engine():
    """Get or create async engine."""
    global _engine
    if _engine is None:
        url = get_database_url()
        kwargs: dict[str, Any] = {
            "echo": os.getenv("SQL_DEBUG", "").lower() == "true",
        }
        # SQLite doesn't support connection pooling options
        if not url.startswith("sqlite"):
            kwargs.update(pool_size=5, max_overflow=10)
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session as async context manager."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    global _engine, _async_session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None


class SessionStore:
    """Database-agnostic session store using SQLAlchemy ORM.

    Works identically on PostgreSQL and SQLite — all queries go
    through the ORM so there is zero dialect-specific SQL.
    """

    async def save(self, session_data: dict[str, Any]) -> None:
        """Save or update a session."""
        async with get_db_session() as db:
            result = await db.execute(
                select(Session).where(Session.key == session_data["key"])
            )
            existing = result.scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if existing:
                existing.messages = session_data.get("messages", [])
                existing.metadata_ = session_data.get("metadata", {})
                existing.updated_at = now
            else:
                db.add(
                    Session(
                        id=str(uuid.uuid4()),
                        key=session_data["key"],
                        framework=session_data["framework"],
                        role=session_data["role"],
                        context_type=session_data["context_type"],
                        context_id=session_data["context_id"],
                        messages=session_data.get("messages", []),
                        metadata_=session_data.get("metadata", {}),
                        created_at=now,
                        updated_at=now,
                    )
                )

    async def load(self, key: str) -> dict[str, Any] | None:
        """Load a session by key."""
        async with get_db_session() as db:
            result = await db.execute(
                select(Session).where(Session.key == key)
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def load_by_id(self, session_id: str) -> dict[str, Any] | None:
        """Load a session by ID."""
        async with get_db_session() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def delete(self, key: str) -> None:
        """Delete a session by key."""
        async with get_db_session() as db:
            result = await db.execute(
                select(Session).where(Session.key == key)
            )
            row = result.scalar_one_or_none()
            if row:
                await db.delete(row)

    async def list_sessions(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """List sessions matching prefix."""
        async with get_db_session() as db:
            stmt = (
                select(Session)
                .where(Session.key.like(f"{prefix}%"))
                .order_by(Session.updated_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    **row.to_dict(),
                    "message_count": len(row.messages or []),
                }
                for row in rows
            ]


# Backward-compatible alias
PostgresSessionStore = SessionStore

# Global store instance
_session_store: SessionStore | None = None


def get_session_store_db() -> SessionStore:
    """Get or create the session store singleton."""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


# Backward-compatible alias
get_postgres_store = get_session_store_db
