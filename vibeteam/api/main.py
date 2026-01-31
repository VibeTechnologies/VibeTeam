"""
Supervisor Chat API - FastAPI application for VibeTeam chat interface.

NOTE: This API is currently deprecated pending migration to the new
router-based architecture. See vibeteam/router/ for the new system.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
# Session Management (Stubbed)
# ============================================================================


_sessions: dict[str, Any] = {}


# ============================================================================
# FastAPI Application
# ============================================================================


app = FastAPI(
    title="VibeTeam Supervisor API",
    description="Chat API for VibeTeam (deprecated - migrating to router-based architecture)",
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

    NOTE: This endpoint is deprecated. Use Discord/Slack bots with the new
    router-based architecture instead.
    """
    raise HTTPException(
        status_code=501,
        detail="This API is deprecated. Use Discord/Slack bots with @RoleName mentions instead.",
    )


@app.post("/v1/chat/completions", response_model=OpenAIChatResponse)
async def chat_completions(request: OpenAIChatRequest) -> OpenAIChatResponse:
    """
    OpenAI-compatible chat completions endpoint.

    NOTE: This endpoint is deprecated.
    """
    raise HTTPException(
        status_code=501,
        detail="This API is deprecated. Use Discord/Slack bots with @RoleName mentions instead.",
    )


@app.get("/v1/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str) -> SessionHistoryResponse:
    """Get conversation history for a session."""
    raise HTTPException(
        status_code=501,
        detail="This API is deprecated. Session history is now managed per-platform.",
    )


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a session."""
    raise HTTPException(
        status_code=501,
        detail="This API is deprecated.",
    )


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
