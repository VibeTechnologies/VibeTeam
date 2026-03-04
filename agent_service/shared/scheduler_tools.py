from __future__ import annotations

"""
Scheduler tools for agents to schedule future tasks.
"""

import os
from typing import Any

import httpx

SCHEDULER_URL = os.getenv("SCHEDULER_SERVICE_URL", "http://scheduler-svc:8080")


async def schedule_task(
    task: str,
    delay_hours: int = 0,
    delay_minutes: int = 0,
    agent_service: str = "openhands-svc",
    role: str | None = None,
    context_type: str = "scheduled",
    context_id: str | None = None,
) -> dict[str, Any]:
    """
    Schedule a task for future execution.

    Args:
        task: The task description
        delay_hours: Hours from now to execute
        delay_minutes: Minutes from now to execute
        agent_service: Target service (openhands-svc or openclaw-svc)
        role: Specific agent role
        context_type: Context type for session tracking
        context_id: Context ID for session tracking

    Returns:
        Scheduling result with job_id
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SCHEDULER_URL}/tasks",
            json={
                "task": task,
                "delay_hours": delay_hours,
                "delay_minutes": delay_minutes,
                "agent_service": agent_service,
                "role": role,
                "context_type": context_type,
                "context_id": context_id,
            },
        )
        response.raise_for_status()
        return response.json()


def schedule_task_sync(
    task: str,
    delay_hours: int = 0,
    delay_minutes: int = 0,
    agent_service: str = "openhands-svc",
    role: str | None = None,
) -> dict[str, Any]:
    """Sync version of schedule_task for use as agent tool."""
    import asyncio

    return asyncio.run(schedule_task(task, delay_hours, delay_minutes, agent_service, role))
