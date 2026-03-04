"""
REST API Handlers.

Provides REST API endpoints for manual task invocation and management:
- POST /api/run - Execute a task with an agent
- POST /api/schedule - Schedule a task for later execution
- GET /api/sessions - List sessions
- GET /api/tasks - List scheduled tasks
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from vibeteam.agents_config import resolve_framework
from vibeteam.gateway.server import (
    RunRequest,
    RunResponse,
    call_agent_service,
    call_scheduler_service,
    config,
    get_http_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["API"])


# ==============================================================================
# Request/Response Models
# ==============================================================================


class ScheduleRequest(BaseModel):
    """Request to schedule a task."""

    task: str = Field(..., description="The task to execute")
    run_at: str | None = Field(None, description="ISO datetime to run (None for immediate)")
    role: str | None = Field(None, description="Agent role")
    framework: str | None = Field(
        None,
        description="Optional framework override (legacy). "
        "Aliases autogen/crewai map to openhands.",
    )
    context_type: str = Field("api", description="Context type")
    context_id: str | None = Field(None, description="Context ID")


class ScheduleResponse(BaseModel):
    """Response from scheduling a task."""

    task_id: str
    scheduled_at: str
    status: str


class SessionListResponse(BaseModel):
    """Response listing sessions."""

    sessions: list[dict[str, Any]]
    count: int


class TaskListResponse(BaseModel):
    """Response listing scheduled tasks."""

    tasks: list[dict[str, Any]]
    count: int


# ==============================================================================
# Endpoints
# ==============================================================================


@router.post("/run", response_model=RunResponse)
async def run_task(request: RunRequest):
    """
    Execute a task with an agent microservice.

    This endpoint routes the task to the appropriate agent service based on
    role mapping in agents/agents.yaml, with optional legacy framework override.
    """
    try:
        result = await call_agent_service(
            task=request.task,
            role=request.role,
            framework=request.framework,
            context_type=request.context_type,
            context_id=request.context_id,
            stream=request.stream,
        )

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return RunResponse(
            response=result.get("response", ""),
            session_id=result.get("session_id", ""),
            framework=result.get(
                "framework",
                resolve_framework(request.role, request.framework, config.DEFAULT_FRAMEWORK),
            ),
            agents_used=result.get("agents_used", []),
            metadata=result.get("metadata", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to run task: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/schedule", response_model=ScheduleResponse)
async def schedule_task(request: ScheduleRequest):
    """
    Schedule a task for later execution.

    If run_at is not specified, the task is executed immediately.
    """
    try:
        result = await call_scheduler_service(
            task=request.task,
            run_at=request.run_at,
            role=request.role,
            framework=request.framework,
            context_type=request.context_type,
            context_id=request.context_id,
        )

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return ScheduleResponse(
            task_id=result.get("id", result.get("task_id", "unknown")),
            scheduled_at=result.get(
                "run_at", result.get("scheduled_at", datetime.now(timezone.utc).isoformat())
            ),
            status=result.get("status", "scheduled"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to schedule task: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    role: str | None = None,
    framework: str | None = None,
    prefix: str = "",
    limit: int = 100,
):
    """
    List sessions from an agent service.

    Queries the specified agent service for session history.
    """
    try:
        client = get_http_client()
        resolved_framework = resolve_framework(role, framework, config.DEFAULT_FRAMEWORK)
        service_url = config.get_agent_service_url(resolved_framework)

        response = await client.get(
            f"{service_url}/sessions",
            params={"prefix": prefix, "limit": limit},
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        return SessionListResponse(
            sessions=result.get("sessions", []),
            count=result.get("count", 0),
        )

    except Exception as e:
        logger.exception(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks():
    """
    List scheduled tasks from the scheduler service.
    """
    try:
        client = get_http_client()

        response = await client.get(
            f"{config.SCHEDULER_SERVICE_URL}/tasks",
            timeout=30.0,
        )
        response.raise_for_status()
        result: Any = response.json()

        # Handle both list and dict responses from scheduler
        tasks: list[dict[str, Any]] = []
        if isinstance(result, list):
            tasks = result
        elif isinstance(result, dict):
            tasks = result.get("tasks", [])

        return TaskListResponse(
            tasks=tasks,
            count=len(tasks),
        )

    except Exception as e:
        logger.exception(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a scheduled task.
    """
    try:
        client = get_http_client()

        response = await client.delete(
            f"{config.SCHEDULER_SERVICE_URL}/tasks/{task_id}",
            timeout=30.0,
        )
        response.raise_for_status()
        return {"status": "cancelled", "task_id": task_id}

    except Exception as e:
        logger.exception(f"Failed to cancel task: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str):
    """
    Execute a scheduled task immediately.
    """
    try:
        client = get_http_client()

        response = await client.post(
            f"{config.SCHEDULER_SERVICE_URL}/tasks/{task_id}/run",
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    except Exception as e:
        logger.exception(f"Failed to run task: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
