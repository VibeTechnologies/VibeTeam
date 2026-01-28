"""
Scheduler Service.

FastAPI server with APScheduler for task scheduling and execution.
Persists jobs to PostgreSQL for durability across restarts.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from apscheduler import AsyncScheduler
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Request/Response Models
class ScheduleRequest(BaseModel):
    """Request to schedule a task."""

    task: str = Field(..., description="The task description to execute")
    run_at: datetime | None = Field(None, description="Specific time to run (ISO 8601)")
    delay_hours: int = Field(0, description="Hours from now to run")
    delay_minutes: int = Field(0, description="Minutes from now to run")
    cron: str | None = Field(None, description="Cron expression for recurring tasks")
    interval_minutes: int | None = Field(None, description="Interval in minutes for recurring")
    agent_service: str = Field(
        "autogen-svc", description="Target agent service (autogen-svc or crewai-svc)"
    )
    role: str | None = Field(None, description="Specific agent role")
    context_type: str = Field("scheduled", description="Context type")
    context_id: str | None = Field(None, description="Context ID")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleResponse(BaseModel):
    """Response from scheduling a task."""

    job_id: str
    task: str
    run_at: datetime | None
    schedule_type: str  # once, cron, interval
    agent_service: str
    status: str = "scheduled"


class JobInfo(BaseModel):
    """Information about a scheduled job."""

    job_id: str
    task: str
    next_run: datetime | None
    schedule_type: str
    agent_service: str
    role: str | None
    context_type: str
    context_id: str | None
    status: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    scheduler_running: bool
    job_count: int
    timestamp: str


def get_database_url() -> str:
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    return "postgresql+asyncpg://vibeteam:vibeteam-pg-2026@postgres:5432/vibeteam"


# Global scheduler instance
_scheduler: AsyncScheduler | None = None
_job_metadata: dict[str, dict[str, Any]] = {}  # Store job metadata (task, service, etc.)


def get_agent_service_url(service: str) -> str:
    """Get URL for agent service."""
    urls = {
        "autogen-svc": os.getenv("AUTOGEN_SERVICE_URL", "http://autogen-svc:8080"),
        "crewai-svc": os.getenv("CREWAI_SERVICE_URL", "http://crewai-svc:8080"),
    }
    return urls.get(service, urls["autogen-svc"])


async def execute_scheduled_task(job_id: str) -> None:
    """Execute a scheduled task by calling the agent service."""
    metadata = _job_metadata.get(job_id, {})
    if not metadata:
        logger.error(f"No metadata found for job {job_id}")
        return

    task = metadata.get("task", "")
    service = metadata.get("agent_service", "autogen-svc")
    role = metadata.get("role")
    context_type = metadata.get("context_type", "scheduled")
    context_id = metadata.get("context_id") or job_id

    service_url = get_agent_service_url(service)

    logger.info(f"Executing scheduled task {job_id}: {task[:50]}...")

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{service_url}/run",
                json={
                    "task": task,
                    "role": role,
                    "context_type": context_type,
                    "context_id": context_id,
                },
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Task {job_id} completed: {result.get('response', '')[:100]}...")

    except Exception as e:
        logger.error(f"Failed to execute task {job_id}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _scheduler

    logger.info("Starting Scheduler service...")

    # Create SQLAlchemy engine for APScheduler
    engine = create_async_engine(get_database_url())

    # Create data store
    data_store = SQLAlchemyDataStore(engine)

    # Create and start scheduler
    _scheduler = AsyncScheduler(data_store=data_store)
    await _scheduler.start_in_background()
    logger.info("Scheduler started")

    # Register initial recurring tasks (CronJob replacements)
    await register_default_tasks()

    yield

    # Cleanup
    logger.info("Shutting down Scheduler service...")
    if _scheduler:
        await _scheduler.stop()


async def register_default_tasks() -> None:
    """Register default recurring tasks (replacing CronJobs)."""
    if not _scheduler:
        return

    default_tasks = [
        {
            "job_id": "support-emails",
            "task": "Process support emails from Gmail inbox and respond to customer inquiries",
            "cron": "*/15 * * * *",  # Every 15 minutes
            "agent_service": "autogen-svc",
            "role": "support_engineer",
            "context_type": "scheduled",
        },
        {
            "job_id": "product-analysis",
            "task": "Analyze customer feedback, feature requests, and prioritize backlog items",
            "cron": "0 */2 * * *",  # Every 2 hours
            "agent_service": "autogen-svc",
            "role": "support_engineer",  # PM role uses support tools
            "context_type": "scheduled",
        },
        {
            "job_id": "release-check",
            "task": "Check for pending releases, review changelogs, and prepare release notes",
            "cron": "0 9 * * *",  # Daily at 9am UTC
            "agent_service": "autogen-svc",
            "role": "release_engineer",
            "context_type": "scheduled",
        },
        {
            "job_id": "health-check",
            "task": "Check system health, Sentry errors, and Langfuse traces for anomalies",
            "cron": "*/5 * * * *",  # Every 5 minutes
            "agent_service": "autogen-svc",
            "role": "support_engineer",
            "context_type": "scheduled",
        },
        {
            "job_id": "issue-triage",
            "task": "Review and triage new GitHub issues, assign priorities and labels",
            "cron": "0 */4 * * *",  # Every 4 hours
            "agent_service": "autogen-svc",
            "role": "support_engineer",
            "context_type": "scheduled",
        },
    ]

    for task_config in default_tasks:
        job_id = task_config["job_id"]

        # Check if job already exists
        try:
            existing = await _scheduler.get_job(job_id)
            if existing:
                logger.info(f"Job {job_id} already exists, skipping registration")
                continue
        except Exception:
            pass  # Job doesn't exist

        # Store metadata
        _job_metadata[job_id] = {
            "task": task_config["task"],
            "agent_service": task_config["agent_service"],
            "role": task_config["role"],
            "context_type": task_config["context_type"],
            "context_id": job_id,
        }

        # Schedule with cron trigger
        trigger = CronTrigger.from_crontab(task_config["cron"])
        await _scheduler.add_schedule(
            execute_scheduled_task,
            trigger,
            id=job_id,
            args=[job_id],
        )
        logger.info(f"Registered recurring task: {job_id}")


# Create FastAPI app
app = FastAPI(
    title="VibeTeam Scheduler Service",
    description="Task scheduling service with APScheduler and PostgreSQL persistence",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    job_count = len(_job_metadata)
    return HealthResponse(
        status="healthy",
        scheduler_running=_scheduler is not None,
        job_count=job_count,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/tasks", response_model=ScheduleResponse)
async def schedule_task(request: ScheduleRequest):
    """Schedule a new task."""
    if not _scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")

    job_id = str(uuid.uuid4())[:8]

    # Determine trigger type and run time
    schedule_type = "once"
    run_at = None

    if request.cron:
        trigger = CronTrigger.from_crontab(request.cron)
        schedule_type = "cron"
    elif request.interval_minutes:
        trigger = IntervalTrigger(minutes=request.interval_minutes)
        schedule_type = "interval"
    elif request.run_at:
        trigger = DateTrigger(run_time=request.run_at)
        run_at = request.run_at
    else:
        # Calculate run time from delay
        run_at = datetime.now(timezone.utc) + timedelta(
            hours=request.delay_hours,
            minutes=request.delay_minutes,
        )
        trigger = DateTrigger(run_time=run_at)

    # Store metadata
    _job_metadata[job_id] = {
        "task": request.task,
        "agent_service": request.agent_service,
        "role": request.role,
        "context_type": request.context_type,
        "context_id": request.context_id or job_id,
        "metadata": request.metadata,
    }

    # Add schedule
    await _scheduler.add_schedule(
        execute_scheduled_task,
        trigger,
        id=job_id,
        args=[job_id],
    )

    logger.info(f"Scheduled task {job_id}: {request.task[:50]}... ({schedule_type})")

    return ScheduleResponse(
        job_id=job_id,
        task=request.task,
        run_at=run_at,
        schedule_type=schedule_type,
        agent_service=request.agent_service,
        status="scheduled",
    )


@app.get("/tasks")
async def list_tasks():
    """List all scheduled tasks."""
    tasks = []
    for job_id, metadata in _job_metadata.items():
        tasks.append(
            JobInfo(
                job_id=job_id,
                task=metadata.get("task", ""),
                next_run=None,  # Would need to query scheduler for this
                schedule_type="unknown",
                agent_service=metadata.get("agent_service", "autogen-svc"),
                role=metadata.get("role"),
                context_type=metadata.get("context_type", "scheduled"),
                context_id=metadata.get("context_id"),
                status="scheduled",
            )
        )
    return {"tasks": tasks, "count": len(tasks)}


@app.get("/tasks/{job_id}", response_model=JobInfo)
async def get_task(job_id: str):
    """Get details of a scheduled task."""
    metadata = _job_metadata.get(job_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Task not found")

    return JobInfo(
        job_id=job_id,
        task=metadata.get("task", ""),
        next_run=None,
        schedule_type="unknown",
        agent_service=metadata.get("agent_service", "autogen-svc"),
        role=metadata.get("role"),
        context_type=metadata.get("context_type", "scheduled"),
        context_id=metadata.get("context_id"),
        status="scheduled",
    )


@app.delete("/tasks/{job_id}")
async def cancel_task(job_id: str):
    """Cancel a scheduled task."""
    if not _scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")

    if job_id not in _job_metadata:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        await _scheduler.remove_schedule(job_id)
        del _job_metadata[job_id]
        logger.info(f"Cancelled task {job_id}")
        return {"status": "cancelled", "job_id": job_id}
    except Exception as e:
        logger.error(f"Failed to cancel task {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/{job_id}/run")
async def run_task_now(job_id: str):
    """Execute a task immediately (regardless of schedule)."""
    if job_id not in _job_metadata:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        await execute_scheduled_task(job_id)
        return {"status": "executed", "job_id": job_id}
    except Exception as e:
        logger.error(f"Failed to execute task {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run(
        "agents.scheduler.server:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
