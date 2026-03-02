#!/usr/bin/env python3
"""
Database migration script for VibeTeam.

Creates required tables for the router-based architecture.

Usage:
    python scripts/migrate_db.py
    python scripts/migrate_db.py --check  # Check if migrations needed
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# SQL for creating thread_subscriptions table
CREATE_THREAD_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    agent_role VARCHAR(50) NOT NULL,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
"""

CREATE_SUBSCRIPTIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_subscriptions_thread 
ON thread_subscriptions(source, thread_id);
"""

# SQL for checking if table exists
CHECK_TABLE_EXISTS = """
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name = 'thread_subscriptions'
);
"""


async def get_db_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable not set")

    # Convert postgres:// to postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return url


async def check_migrations_needed() -> bool:
    """Check if migrations are needed."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = await get_db_url()
    engine = create_async_engine(url)

    async with engine.begin() as conn:
        result = await conn.execute(text(CHECK_TABLE_EXISTS))
        exists = result.scalar()

    await engine.dispose()
    return not exists


async def run_migrations():
    """Run all database migrations."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    # Import ORM models so Base.metadata includes them
    from agent_service.shared.db import Base  # noqa: F811

    url = await get_db_url()
    logger.info(f"Connecting to database...")

    engine = create_async_engine(url)

    try:
        async with engine.begin() as conn:
            # Create all ORM-managed tables (sessions, task_results)
            # Uses dialect-agnostic Uuid type — works on both PostgreSQL and SQLite
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Created/verified ORM-managed tables (sessions, task_results)")

            # Create thread_subscriptions table (not ORM-managed yet)
            logger.info("Creating thread_subscriptions table...")
            await conn.execute(text(CREATE_THREAD_SUBSCRIPTIONS))
            logger.info("Created thread_subscriptions table")

            # Create index
            logger.info("Creating index...")
            await conn.execute(text(CREATE_SUBSCRIPTIONS_INDEX))
            logger.info("Created idx_subscriptions_thread index")

            logger.info("All migrations completed successfully!")

    finally:
        await engine.dispose()


async def main():
    """Main entry point."""
    check_only = "--check" in sys.argv

    try:
        if check_only:
            needed = await check_migrations_needed()
            if needed:
                logger.info("Migrations needed: thread_subscriptions table does not exist")
                sys.exit(1)
            else:
                logger.info("No migrations needed")
                sys.exit(0)
        else:
            await run_migrations()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
