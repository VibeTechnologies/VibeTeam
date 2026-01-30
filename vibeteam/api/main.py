"""
Supervisor Chat API - FastAPI application for VibeTeam chat interface.

Provides a ChatGPT-like API that routes requests through the Supervisor Agent
with Swarm orchestration. Compatible with LibreChat and other OpenAI-compatible clients.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from vibeteam.config import DEFAULT_MODEL
from vibeteam.swarm import SwarmOrchestrator, create_swarm_orchestrator

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    message: str = Field(..., description="The user's message")
    session_id: str | None = Field(None, description="Session ID for conversation continuity")
    context: dict[str, Any] | None = Field(None, description="Additional context")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    response: str = Field(..., description="The supervisor's response")
    session_id: str = Field(..., description="Session ID for continuity")
    agents_used: list[str] = Field(default_factory=list, description="Agents involved in response")
    iteration_count: int = Field(0, description="Number of swarm iterations")


class OpenAIChatMessage(BaseModel):
    """OpenAI-compatible chat message."""

    role: str
    content: str
    name: str | None = None


class OpenAIChatRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = "vibeteam-supervisor"
    messages: list[OpenAIChatMessage]
    temperature: float | None = 0.3
    max_tokens: int | None = 4096
    stream: bool = False


class OpenAIChatChoice(BaseModel):
    """OpenAI-compatible chat choice."""

    index: int = 0
    message: OpenAIChatMessage
    finish_reason: str = "stop"


class OpenAIChatResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[OpenAIChatChoice]
    usage: dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "vibeteam-supervisor"
    version: str = "1.0.0"
    timestamp: str


class SessionHistoryResponse(BaseModel):
    """Session history response."""

    session_id: str
    messages: list[dict[str, Any]]
    agents_used: list[str]
    iteration_count: int
    created_at: str


# ============================================================================
# Session Management
# ============================================================================


# In-memory session storage (use Redis in production)
_sessions: dict[str, SwarmOrchestrator] = {}


def get_or_create_orchestrator(session_id: str | None = None) -> SwarmOrchestrator:
    """
    Get or create an orchestrator for a session.

    Args:
        session_id: Optional session ID to resume

    Returns:
        SwarmOrchestrator instance
    """
    if session_id and session_id in _sessions:
        return _sessions[session_id]

    # Create new orchestrator
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    orchestrator = create_swarm_orchestrator(model=model)

    # Store in sessions
    _sessions[orchestrator.shared_state.session_id] = orchestrator

    return orchestrator


def cleanup_old_sessions(max_age_hours: int = 24) -> int:
    """
    Clean up old sessions to prevent memory leaks.

    Args:
        max_age_hours: Maximum session age in hours

    Returns:
        Number of sessions cleaned up
    """
    now = datetime.now(timezone.utc)
    to_remove = []

    for session_id, orchestrator in _sessions.items():
        age = (now - orchestrator.shared_state.created_at).total_seconds() / 3600
        if age > max_age_hours:
            to_remove.append(session_id)

    for session_id in to_remove:
        del _sessions[session_id]

    return len(to_remove)


# ============================================================================
# FastAPI Application
# ============================================================================


app = FastAPI(
    title="VibeTeam Supervisor API",
    description="Chat API for VibeTeam with Swarm-pattern orchestration",
    version="1.0.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        service="vibeteam-supervisor",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Chat with the VibeTeam Supervisor.

    The supervisor will route your request to appropriate team members
    and synthesize their responses.
    """
    try:
        # Get or create orchestrator
        orchestrator = get_or_create_orchestrator(request.session_id)

        # Run the swarm
        response = await orchestrator.run(request.message)

        return ChatResponse(
            response=response,
            session_id=orchestrator.shared_state.session_id,
            agents_used=orchestrator.get_agents_used(),
            iteration_count=orchestrator.iteration_count,
        )

    except Exception as e:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/v1/chat/completions", response_model=OpenAIChatResponse)
async def chat_completions(request: OpenAIChatRequest) -> OpenAIChatResponse:
    """
    OpenAI-compatible chat completions endpoint.

    This endpoint is compatible with LibreChat and other OpenAI clients.
    """
    try:
        # Extract the last user message
        user_message = ""
        session_id = None

        for msg in reversed(request.messages):
            if msg.role == "user":
                user_message = msg.content
                break

        if not user_message:
            raise HTTPException(status_code=400, detail="No user message found")

        # Get or create orchestrator
        orchestrator = get_or_create_orchestrator(session_id)

        # Add previous context from messages
        for msg in request.messages[:-1]:  # Exclude last message
            if msg.role in ("user", "assistant"):
                orchestrator.shared_state.add_message(
                    role=msg.role,
                    content=msg.content,
                    agent_name=msg.name,
                )

        # Run the swarm
        response = await orchestrator.run(user_message)

        return OpenAIChatResponse(
            id=f"chatcmpl-{orchestrator.shared_state.session_id[:8]}",
            created=int(datetime.now(timezone.utc).timestamp()),
            model=request.model,
            choices=[
                OpenAIChatChoice(
                    index=0,
                    message=OpenAIChatMessage(
                        role="assistant",
                        content=response,
                        name="supervisor",
                    ),
                    finish_reason="stop",
                )
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat completions error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/v1/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str) -> SessionHistoryResponse:
    """Get conversation history for a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    orchestrator = _sessions[session_id]
    state = orchestrator.shared_state

    return SessionHistoryResponse(
        session_id=session_id,
        messages=[m.to_dict() for m in state.messages],
        agents_used=state.agents_used,
        iteration_count=state.iteration_count,
        created_at=state.created_at.isoformat(),
    )


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    del _sessions[session_id]
    return {"status": "deleted", "session_id": session_id}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """
    List available models (OpenAI-compatible).

    Returns a single "vibeteam-supervisor" model.
    """
    return {
        "object": "list",
        "data": [
            {
                "id": "vibeteam-supervisor",
                "object": "model",
                "created": 1704067200,
                "owned_by": "vibeteam",
            }
        ],
    }


# ============================================================================
# CLI Entry Point
# ============================================================================


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the FastAPI server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
