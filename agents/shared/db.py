"""
PostgreSQL database module for agent sessions and task results.

Provides async session storage using SQLAlchemy with asyncpg.
"""

import json
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class Session(Base):
    """Agent session model for PostgreSQL."""

    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), unique=True, nullable=False, index=True)
    framework = Column(String(50), nullable=False)
    role = Column(String(50), nullable=False)
    context_type = Column(String(50), nullable=False)
    context_id = Column(String(255), nullable=False)
    messages = Column(JSONB, default=list)
    metadata_ = Column("metadata", JSONB, default=dict)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    framework = Column(String(50), nullable=False)
    role = Column(String(50), nullable=False)
    task = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    error = Column(Text, nullable=True)
    tokens_used = Column(String(20), nullable=True)
    latency_ms = Column(String(20), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)
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
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if url:
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
        _engine = create_async_engine(
            get_database_url(),
            echo=os.getenv("SQL_DEBUG", "").lower() == "true",
            pool_size=5,
            max_overflow=10,
        )
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


class PostgresSessionStore:
    """PostgreSQL session store for agents."""

    async def save(self, session_data: dict[str, Any]) -> None:
        """Save or update a session."""
        async with get_db_session() as db:
            # Check if session exists
            result = await db.execute(
                text("SELECT id FROM sessions WHERE key = :key"),
                {"key": session_data["key"]},
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update
                await db.execute(
                    text("""
                        UPDATE sessions
                        SET messages = :messages,
                            metadata = :metadata,
                            updated_at = :updated_at
                        WHERE key = :key
                    """),
                    {
                        "key": session_data["key"],
                        "messages": json.dumps(session_data.get("messages", [])),
                        "metadata": json.dumps(session_data.get("metadata", {})),
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
            else:
                # Insert
                await db.execute(
                    text("""
                        INSERT INTO sessions (id, key, framework, role, context_type, context_id, messages, metadata, created_at, updated_at)
                        VALUES (:id, :key, :framework, :role, :context_type, :context_id, :messages, :metadata, :created_at, :updated_at)
                    """),
                    {
                        "id": uuid.uuid4(),
                        "key": session_data["key"],
                        "framework": session_data["framework"],
                        "role": session_data["role"],
                        "context_type": session_data["context_type"],
                        "context_id": session_data["context_id"],
                        "messages": json.dumps(session_data.get("messages", [])),
                        "metadata": json.dumps(session_data.get("metadata", {})),
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    },
                )

    async def load(self, key: str) -> dict[str, Any] | None:
        """Load a session by key."""
        async with get_db_session() as db:
            result = await db.execute(
                text("SELECT * FROM sessions WHERE key = :key"),
                {"key": key},
            )
            row = result.mappings().one_or_none()
            if row:
                return {
                    "session_id": str(row["id"]),
                    "key": row["key"],
                    "framework": row["framework"],
                    "role": row["role"],
                    "context_type": row["context_type"],
                    "context_id": row["context_id"],
                    "messages": row["messages"] or [],
                    "metadata": row["metadata"] or {},
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
            return None

    async def load_by_id(self, session_id: str) -> dict[str, Any] | None:
        """Load a session by ID."""
        async with get_db_session() as db:
            result = await db.execute(
                text("SELECT * FROM sessions WHERE id = :id"),
                {"id": session_id},
            )
            row = result.mappings().one_or_none()
            if row:
                return {
                    "session_id": str(row["id"]),
                    "key": row["key"],
                    "framework": row["framework"],
                    "role": row["role"],
                    "context_type": row["context_type"],
                    "context_id": row["context_id"],
                    "messages": row["messages"] or [],
                    "metadata": row["metadata"] or {},
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
            return None

    async def delete(self, key: str) -> None:
        """Delete a session by key."""
        async with get_db_session() as db:
            await db.execute(
                text("DELETE FROM sessions WHERE key = :key"),
                {"key": key},
            )

    async def list_sessions(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """List sessions matching prefix."""
        async with get_db_session() as db:
            result = await db.execute(
                text(
                    "SELECT * FROM sessions WHERE key LIKE :prefix ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"prefix": f"{prefix}%", "limit": limit},
            )
            rows = result.mappings().all()
            return [
                {
                    "session_id": str(row["id"]),
                    "key": row["key"],
                    "framework": row["framework"],
                    "role": row["role"],
                    "context_type": row["context_type"],
                    "context_id": row["context_id"],
                    "message_count": len(row["messages"] or []),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
                for row in rows
            ]


# Global store instance
_postgres_store: PostgresSessionStore | None = None


def get_postgres_store() -> PostgresSessionStore:
    """Get or create PostgreSQL session store."""
    global _postgres_store
    if _postgres_store is None:
        _postgres_store = PostgresSessionStore()
    return _postgres_store
