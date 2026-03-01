"""
AutoGen Agent Microservice.

FastAPI server exposing AutoGen team functionality via REST API.
"""

import contextlib
import logging
import os
import time
import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.config import AgentConfig
from agents.shared.db import close_db, get_postgres_store, init_db

from .team import AutoGenTeam, create_team

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_GITHUB_TOKEN_LOCK = threading.Lock()


def _resolve_role_for_token(role: str | None, task: str) -> str | None:
    if role:
        return role
    try:
        from agents.shared.role_resolver import parse_first_role_mention, route_by_keywords

        parsed = parse_first_role_mention(task)
        if parsed:
            return parsed
        return route_by_keywords(task)
    except Exception:
        return None


@contextlib.contextmanager
def _github_token_context(role: str | None):
    """Temporarily set role-specific GitHub token for gh/SDK usage."""
    if not role:
        yield
        return

    token = None
    try:
        from vibeteam.utils.github_app import get_installation_token_for_role

        token = get_installation_token_for_role(role)
    except Exception:
        token = None

    with _GITHUB_TOKEN_LOCK:
        old_env = {
            "VIBETEAM_AGENT_ROLE": os.environ.get("VIBETEAM_AGENT_ROLE"),
            "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN"),
            "GH_TOKEN": os.environ.get("GH_TOKEN"),
        }
        os.environ["VIBETEAM_AGENT_ROLE"] = role
        if token:
            os.environ["GITHUB_TOKEN"] = token
            os.environ["GH_TOKEN"] = token
        try:
            yield
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


# Request/Response Models
class RunRequest(BaseModel):
    """Request to run a task."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(
        None,
        description="Specific agent role (support_engineer, release_engineer, marketing_manager)",
    )
    context_type: str = Field("api", description="Context type (issue, pr, slack, email, api)")
    context_id: str | None = Field(None, description="Context ID for session tracking")
    session_id: str | None = Field(None, description="Resume existing session")


class RunResponse(BaseModel):
    """Response from task execution."""

    response: str
    session_id: str
    session_key: str
    framework: str = "autogen"
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}


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
_team: AutoGenTeam | None = None


def get_team() -> AutoGenTeam:
    """Get or create AutoGen team."""
    global _team
    if _team is None:
        config = AgentConfig()
        _team = create_team(config)
    return _team


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting AutoGen service...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization failed (may not be available): {e}")

    # Pre-warm team
    try:
        get_team()
        logger.info("AutoGen team initialized")
    except Exception as e:
        logger.error(f"Failed to initialize team: {e}")

    yield

    # Cleanup
    logger.info("Shutting down AutoGen service...")
    if _team:
        await _team.close()
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="AutoGen Agent Service",
    description="AutoGen multi-agent service for VibeTeam",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        framework="autogen",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/run", response_model=RunResponse)
async def run_task(request: RunRequest):
    """Execute a task with the AutoGen team."""
    start_time = time.time()

    try:
        team = get_team()

        # Generate context_id if not provided
        context_id = request.context_id or str(uuid.uuid4())[:8]

        role_for_token = _resolve_role_for_token(request.role, request.task)

        # Run the task
        with _github_token_context(role_for_token):
            if request.role:
                result = await team.run_single_agent_async(
                    task=request.task,
                    role=request.role,
                    context_type=request.context_type,
                    context_id=context_id,
                )
            else:
                result = await team.run_async(
                    task=request.task,
                    context_type=request.context_type,
                    context_id=context_id,
                )

        latency_ms = int((time.time() - start_time) * 1000)

        # Store in PostgreSQL
        try:
            store = get_postgres_store()
            await store.save(
                {
                    "key": result.get(
                        "session_key",
                        f"autogen:{request.role or 'team'}:{request.context_type}:{context_id}",
                    ),
                    "framework": "autogen",
                    "role": result.get("agent", request.role or "team"),
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
            session_key=result.get(
                "session_key",
                f"autogen:{request.role or 'team'}:{request.context_type}:{context_id}",
            ),
            framework="autogen",
            agents_used=result.get("agents", [result.get("agent", request.role or "team")]),
            metadata={
                "latency_ms": latency_ms,
                "message_count": result.get("message_count", 2),
            },
        )

    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/run/stream")
async def run_task_stream(request: RunRequest):
    """Execute a task with streaming response (SSE)."""

    async def generate():
        try:
            team = get_team()
            context_id = request.context_id or str(uuid.uuid4())[:8]
            role_for_token = _resolve_role_for_token(request.role, request.task)

            # Send start event
            yield f"data: {{'event': 'start', 'context_id': '{context_id}'}}\n\n"

            # Run the task
            with _github_token_context(role_for_token):
                if request.role:
                    result = await team.run_single_agent_async(
                        task=request.task,
                        role=request.role,
                        context_type=request.context_type,
                        context_id=context_id,
                    )
                else:
                    result = await team.run_async(
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
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
        sessions = await store.list_sessions(prefix=f"autogen:{prefix}", limit=limit)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run(
        "agents.autogen.server:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
