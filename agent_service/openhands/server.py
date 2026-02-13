from __future__ import annotations

"""
OpenHands Agent Microservice.

FastAPI server exposing OpenHands team functionality via REST API.
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.config import AgentConfig
from agents.shared.db import close_db, get_postgres_store, init_db

from .team import OpenHandsTeam, create_team

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Request/Response Models
class RunRequest(BaseModel):
    """Request to run a task."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(
        None,
        description="Specific agent role (support_engineer, release_engineer, marketing_manager, product_manager, software_engineer)",
    )
    context_type: str = Field("api", description="Context type (issue, pr, slack, email, api)")
    context_id: str | None = Field(None, description="Context ID for session tracking")
    session_id: str | None = Field(None, description="Resume existing session")
    workspace: str | None = Field(None, description="Working directory for OpenHands")
    use_tools: bool = Field(
        True, description="Enable TerminalTool and FileEditorTool for agentic exploration"
    )
    skip_context_injection: bool = Field(
        False, description="Skip automatic context injection from Sentry/Gmail/etc"
    )


class RunResponse(BaseModel):
    """Response from task execution."""

    response: str
    session_id: str
    session_key: str
    framework: str = "openhands"
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}


class AsyncRunRequest(BaseModel):
    """Request to run a task asynchronously with callback."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(
        None,
        description="Specific agent role (support_engineer, release_engineer, marketing_manager, product_manager, software_engineer)",
    )
    context_type: str = Field("api", description="Context type (issue, pr, slack, email, api)")
    context_id: str | None = Field(None, description="Context ID for session tracking")
    session_id: str | None = Field(None, description="Resume existing session")
    workspace: str | None = Field(None, description="Working directory for OpenHands")
    use_tools: bool = Field(
        True, description="Enable TerminalTool and FileEditorTool for agentic exploration"
    )
    skip_context_injection: bool = Field(
        False, description="Skip automatic context injection from Sentry/Gmail/etc"
    )
    callback_url: str = Field(..., description="URL to POST results to when agent completes")
    callback_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque metadata passed through to the callback (e.g. channel, thread_ts)",
    )
    progress_url: str | None = Field(
        None,
        description="URL to POST progress updates to while agent is working (optional)",
    )
    execution_timeout: int = Field(
        600,
        description="Overall execution timeout in seconds (default: 600 = 10 min)",
    )


class AsyncRunResponse(BaseModel):
    """Immediate response from async task submission."""

    job_id: str
    status: str = "accepted"
    message: str = "Task accepted, will callback when complete"


class CallbackPayload(BaseModel):
    """Payload sent to callback_url when agent completes."""

    job_id: str
    status: str  # "completed", "failed", or "timeout"
    response: str = ""
    error: str | None = None
    session_id: str = ""
    session_key: str = ""
    framework: str = "openhands"
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}
    callback_metadata: dict[str, Any] = {}


class ProgressPayload(BaseModel):
    """Payload sent to progress_url while agent is working."""

    job_id: str
    status: str = "in_progress"
    step_number: int = 0
    step_summary: str = ""
    elapsed_seconds: int = 0
    callback_metadata: dict[str, Any] = {}


class SessionResponse(BaseModel):
    """Session details response."""

    session_id: str
    key: str
    framework: str
    role: str
    context_type: str
    context_id: str
    messages: list[dict[str, Any]]
    created_at: str | None
    updated_at: str | None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    framework: str
    version: str
    timestamp: str


# Global team instance
_team: OpenHandsTeam | None = None


def get_team() -> OpenHandsTeam:
    """Get or create OpenHands team."""
    global _team
    if _team is None:
        config = AgentConfig()
        _team = create_team(config)
    return _team


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting OpenHands service...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization failed (may not be available): {e}")

    # Pre-warm team
    try:
        get_team()
        logger.info("OpenHands team initialized")
    except Exception as e:
        logger.error(f"Failed to initialize team: {e}")

    yield

    # Cleanup
    logger.info("Shutting down OpenHands service...")
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="OpenHands Agent Service",
    description="OpenHands multi-agent service for VibeTeam",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        framework="openhands",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/run", response_model=RunResponse)
async def run_task(request: RunRequest):
    """Execute a task with the OpenHands team."""
    logger.info(
        f"Received task request: role={request.role}, context={request.context_type}:{request.context_id}"
    )
    logger.info(f"Task content: {request.task[:100]}...")
    start_time = time.time()

    try:
        team = get_team()

        # Generate context_id if not provided
        context_id = request.context_id or str(uuid.uuid4())[:8]

        # Determine role - let team route if not specified
        role = request.role

        # Run the task
        # Use asyncio.to_thread to run blocking agent code without blocking the event loop
        # This allows health checks to respond while the agent is processing
        if role:
            # Run with specific agent in a thread pool
            agent = team._get_agent(role)
            result = await asyncio.to_thread(
                agent.run,
                task=request.task,
                context_type=request.context_type,
                context_id=context_id,
                workspace=request.workspace,
                use_tools=request.use_tools,
                skip_context_injection=request.skip_context_injection,
            )
        else:
            # Let team route based on @mentions or keywords
            result = await team.run_async(
                task=request.task,
                context_type=request.context_type,
                context_id=context_id,
                workspace=request.workspace,
            )

        latency_ms = int((time.time() - start_time) * 1000)

        # Build session key
        agent_role = result.get("agent", role or "team")
        session_key = f"openhands:{agent_role}:{request.context_type}:{context_id}"

        # Store in PostgreSQL
        try:
            store = get_postgres_store()
            await store.save(
                {
                    "key": session_key,
                    "framework": "openhands",
                    "role": agent_role,
                    "context_type": request.context_type,
                    "context_id": context_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": request.task,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        {
                            "role": "assistant",
                            "content": result.get("response", ""),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ],
                }
            )
        except Exception as e:
            logger.warning(f"Failed to save session to PostgreSQL: {e}")

        return RunResponse(
            response=result.get("response", ""),
            session_id=result.get("session_id", context_id),
            session_key=session_key,
            framework="openhands",
            agents_used=[agent_role],
            metadata={
                "latency_ms": latency_ms,
                "message_count": 2,
                "workspace": request.workspace,
            },
        )

    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _send_progress(
    progress_url: str,
    job_id: str,
    step_number: int,
    step_summary: str,
    elapsed_seconds: int,
    callback_metadata: dict[str, Any],
) -> None:
    """Send a progress update to progress_url (best-effort, non-blocking)."""
    import httpx

    payload = ProgressPayload(
        job_id=job_id,
        step_number=step_number,
        step_summary=step_summary,
        elapsed_seconds=elapsed_seconds,
        callback_metadata=callback_metadata,
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                progress_url,
                json=payload.model_dump(),
                timeout=10.0,
            )
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to send progress update: {e}")


async def _execute_and_callback(
    job_id: str,
    request: AsyncRunRequest,
) -> None:
    """Execute agent task in background and POST results to callback_url.

    This runs as a fire-and-forget asyncio task. On completion, failure, or
    timeout, it sends the result to request.callback_url.

    Features:
    - Overall execution timeout (default 600s / 10 min) prevents infinite hangs
    - On timeout, extracts partial results from whatever events exist
    - Sends progress updates to request.progress_url if provided
    """
    import httpx

    start_time = time.time()
    context_id = request.context_id or str(uuid.uuid4())[:8]
    execution_timeout = request.execution_timeout

    try:
        team = get_team()
        role = request.role

        logger.info(
            f"[job={job_id}] Starting agent execution: role={role}, timeout={execution_timeout}s"
        )

        if role:
            agent = team._get_agent(role)
            # Wrap agent.run in asyncio.wait_for to enforce overall timeout.
            # This prevents the agent from hanging forever if an LLM call gets stuck.
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        agent.run,
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
                        workspace=request.workspace,
                        use_tools=request.use_tools,
                        skip_context_injection=request.skip_context_injection,
                        # Progress callback params — agents use these to send
                        # real-time updates to the gateway while working
                        progress_url=request.progress_url,
                        job_id=job_id,
                        callback_metadata=request.callback_metadata,
                    ),
                    timeout=execution_timeout,
                )
            except asyncio.TimeoutError:
                elapsed = int(time.time() - start_time)
                logger.error(
                    f"[job={job_id}] Agent execution timed out after {elapsed}s "
                    f"(limit={execution_timeout}s)"
                )
                agent_role = role or "team"

                # Send timeout callback
                payload = CallbackPayload(
                    job_id=job_id,
                    status="timeout",
                    error=f"Agent execution timed out after {elapsed}s",
                    response=(
                        f"I was working on this task but ran out of time after "
                        f"{elapsed} seconds. The operation was cancelled. "
                        f"Please try again or break the task into smaller steps."
                    ),
                    agents_used=[agent_role],
                    metadata={
                        "latency_ms": elapsed * 1000,
                        "timeout_seconds": execution_timeout,
                        "timed_out": True,
                    },
                    callback_metadata=request.callback_metadata,
                )
                # Jump to callback sending
                try:
                    async with httpx.AsyncClient() as client:
                        cb_response = await client.post(
                            request.callback_url,
                            json=payload.model_dump(),
                            timeout=30.0,
                        )
                        logger.info(
                            f"[job={job_id}] Timeout callback sent: "
                            f"status={cb_response.status_code}"
                        )
                except Exception as e:
                    logger.error(f"[job={job_id}] Failed to send timeout callback: {e}")
                return
        else:
            try:
                result = await asyncio.wait_for(
                    team.run_async(
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
                        workspace=request.workspace,
                    ),
                    timeout=execution_timeout,
                )
            except asyncio.TimeoutError:
                elapsed = int(time.time() - start_time)
                logger.error(f"[job={job_id}] Team execution timed out after {elapsed}s")
                payload = CallbackPayload(
                    job_id=job_id,
                    status="timeout",
                    error=f"Agent execution timed out after {elapsed}s",
                    response=(
                        f"I was working on this task but ran out of time after "
                        f"{elapsed} seconds. The operation was cancelled. "
                        f"Please try again or break the task into smaller steps."
                    ),
                    agents_used=["team"],
                    metadata={
                        "latency_ms": elapsed * 1000,
                        "timeout_seconds": execution_timeout,
                        "timed_out": True,
                    },
                    callback_metadata=request.callback_metadata,
                )
                try:
                    async with httpx.AsyncClient() as client:
                        cb_response = await client.post(
                            request.callback_url,
                            json=payload.model_dump(),
                            timeout=30.0,
                        )
                        logger.info(
                            f"[job={job_id}] Timeout callback sent: "
                            f"status={cb_response.status_code}"
                        )
                except Exception as e:
                    logger.error(f"[job={job_id}] Failed to send timeout callback: {e}")
                return

        latency_ms = int((time.time() - start_time) * 1000)
        agent_role = result.get("agent", role or "team")
        session_key = f"openhands:{agent_role}:{request.context_type}:{context_id}"

        # Save to PostgreSQL
        try:
            store = get_postgres_store()
            await store.save(
                {
                    "key": session_key,
                    "framework": "openhands",
                    "role": agent_role,
                    "context_type": request.context_type,
                    "context_id": context_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": request.task,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        {
                            "role": "assistant",
                            "content": result.get("response", ""),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ],
                }
            )
        except Exception as e:
            logger.warning(f"[job={job_id}] Failed to save session to PostgreSQL: {e}")

        # Build callback payload
        payload = CallbackPayload(
            job_id=job_id,
            status="completed",
            response=result.get("response", ""),
            session_id=result.get("session_id", context_id),
            session_key=session_key,
            agents_used=[agent_role],
            metadata={
                "latency_ms": latency_ms,
                "message_count": 2,
                "workspace": request.workspace,
                "model": result.get("model", ""),
            },
            callback_metadata=request.callback_metadata,
        )

        logger.info(
            f"[job={job_id}] Agent completed in {latency_ms}ms, "
            f"response_len={len(payload.response)}, sending callback"
        )

    except Exception as e:
        logger.error(f"[job={job_id}] Agent execution failed: {e}")
        payload = CallbackPayload(
            job_id=job_id,
            status="failed",
            error=str(e),
            callback_metadata=request.callback_metadata,
        )

    # POST result to callback URL
    try:
        async with httpx.AsyncClient() as client:
            cb_response = await client.post(
                request.callback_url,
                json=payload.model_dump(),
                timeout=30.0,
            )
            logger.info(
                f"[job={job_id}] Callback sent to {request.callback_url}: "
                f"status={cb_response.status_code}"
            )
    except Exception as e:
        logger.error(f"[job={job_id}] Failed to send callback to {request.callback_url}: {e}")


@app.post("/run/async", response_model=AsyncRunResponse)
async def run_task_async(request: AsyncRunRequest):
    """Accept a task and execute it asynchronously.

    Returns a job_id immediately. When the agent completes (or fails),
    the result is POSTed to request.callback_url.
    """
    job_id = str(uuid.uuid4())

    logger.info(
        f"[job={job_id}] Async task accepted: role={request.role}, "
        f"callback={request.callback_url}, context={request.context_type}:{request.context_id}"
    )

    # Fire and forget — agent runs in background
    asyncio.create_task(_execute_and_callback(job_id, request))

    return AsyncRunResponse(
        job_id=job_id,
        status="accepted",
        message="Task accepted, will callback when complete",
    )


@app.post("/run/stream")
async def run_task_stream(request: RunRequest):
    """Execute a task with streaming response (SSE)."""

    async def generate():
        try:
            team = get_team()
            context_id = request.context_id or str(uuid.uuid4())[:8]

            # Send start event
            yield f"data: {{'event': 'start', 'context_id': '{context_id}'}}\n\n"

            # Run the task
            if request.role:
                agent = team._get_agent(request.role)
                result = agent.run(
                    task=request.task,
                    context_type=request.context_type,
                    context_id=context_id,
                    workspace=request.workspace,
                )
            else:
                result = await team.run_async(
                    task=request.task,
                    context_type=request.context_type,
                    context_id=context_id,
                    workspace=request.workspace,
                )

            # Send result
            import json

            yield f"data: {json.dumps({'event': 'message', 'content': result.get('response', '')})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'session_id': result.get('session_id', context_id)})}\n\n"

        except Exception as e:
            import json

            yield f"data: {json.dumps({'event': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get session details by ID."""
    try:
        store = get_postgres_store()
        session = await store.load_by_id(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return SessionResponse(
            session_id=session["session_id"],
            key=session["key"],
            framework=session["framework"],
            role=session["role"],
            context_type=session["context_type"],
            context_id=session["context_id"],
            messages=session["messages"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/sessions")
async def list_sessions(prefix: str = "", limit: int = 100):
    """List sessions matching prefix."""
    try:
        store = get_postgres_store()
        sessions = await store.list_sessions(prefix=f"openhands:{prefix}", limit=limit)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting OpenHands service on {host}:{port}")

    uvicorn.run(
        "agent_service.openhands.server:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
