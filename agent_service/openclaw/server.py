"""
OpenClaw Agent Microservice.

FastAPI server exposing OpenClaw gateway execution via WebSocket RPC.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import time
import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from agents.shared.integration_checks import validate_required_integrations
except Exception:  # Optional for minimal images
    validate_required_integrations = None  # type: ignore[assignment]

if validate_required_integrations is None:
    def validate_required_integrations(service_name: str) -> None:  # type: ignore[no-redef]
        missing: list[str] = []
        if not os.environ.get("SENTRY_AUTH_TOKEN"):
            missing.append("SENTRY_AUTH_TOKEN (Sentry API auth token)")
        if not os.environ.get("GITHUB_TOKEN"):
            missing.append("GITHUB_TOKEN")
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", ".secrets/gmail-credentials.json")
        token_path = os.environ.get("GMAIL_TOKEN_PATH", ".secrets/gmail-token.json")
        if not os.path.exists(creds_path):
            missing.append(f"GMAIL_CREDENTIALS_PATH missing: {creds_path}")
        if not os.path.exists(token_path):
            missing.append(f"GMAIL_TOKEN_PATH missing: {token_path}")
        if missing:
            details = "\n- ".join(missing)
            raise RuntimeError(
                f"[{service_name}] Required integrations not configured:\n- {details}\n"
                "Service will not start until these are provided."
            )

try:
    from agents.shared.db import close_db, get_postgres_store, init_db
except Exception:
    close_db = None
    get_postgres_store = None
    init_db = None

try:
    from vibeteam.agents_config import get_agent_entry, resolve_openclaw_agent_id
except Exception:  # Fallback for images missing vibeteam.agents_config

    def get_agent_entry(_role: str | None):  # type: ignore[override]
        return None

    def resolve_openclaw_agent_id(_role: str | None) -> str | None:  # type: ignore[override]
        return None


try:
    from vibeteam.agents_config import get_agent_entry, resolve_openclaw_agent_id
except Exception:  # Fallback for images missing vibeteam.agents_config

    def get_agent_entry(_role: str | None):  # type: ignore[override]
        return None

    def resolve_openclaw_agent_id(_role: str | None) -> str | None:  # type: ignore[override]
        return None


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


# ==============================================================================
# Configuration
# ==============================================================================


def _build_ws_url() -> str:
    explicit = os.environ.get("OPENCLAW_WS_URL", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("OPENCLAW_GATEWAY_URL", "http://openclaw-gateway:18789").strip()
    if base.startswith(("ws://", "wss://")):
        return base
    if base.startswith(("http://", "https://")):
        parsed = urlparse(base)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        host = parsed.netloc
        path = parsed.path if parsed.path not in ("", "/") else ""
        return f"{scheme}://{host}{path}"
    host, sep, path = base.partition("/")
    path = f"/{path}" if sep and path else ""
    return f"ws://{host}{path}"


def _build_origin() -> str | None:
    explicit = os.environ.get("OPENCLAW_WS_ORIGIN", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("OPENCLAW_GATEWAY_URL", "http://openclaw-gateway:18789").strip()
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


OPENCLAW_GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
OPENCLAW_WS_URL = _build_ws_url()
OPENCLAW_WS_ORIGIN = _build_origin()
OPENCLAW_CONNECT_TIMEOUT = int(os.environ.get("OPENCLAW_CONNECT_TIMEOUT_SECONDS", "15"))
OPENCLAW_AGENT_TIMEOUT = int(os.environ.get("OPENCLAW_AGENT_TIMEOUT_SECONDS", "1800"))


# ==============================================================================
# No context injection: tasks are passed through unchanged.
# ==============================================================================


# ==============================================================================
# Request/Response Models
# ==============================================================================


class RunRequest(BaseModel):
    """Request to run a task."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(
        None,
        description="Specific agent role (support_engineer, release_engineer, product_manager)",
    )
    context_type: str = Field("api", description="Context type (issue, pr, slack, email, api)")
    context_id: str | None = Field(None, description="Context ID for session tracking")
    session_key: str | None = Field(None, description="Override OpenClaw session key")
    openclaw_agent_id: str | None = Field(None, description="Override OpenClaw agent id")


class RunResponse(BaseModel):
    """Response from task execution."""

    response: str
    session_id: str
    session_key: str
    framework: str = "openclaw"
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}


class AsyncRunRequest(BaseModel):
    """Request to run a task asynchronously with callback."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(None, description="Agent role")
    context_type: str = Field("api", description="Context type")
    context_id: str | None = Field(None, description="Context ID")
    session_key: str | None = Field(None, description="Override OpenClaw session key")
    openclaw_agent_id: str | None = Field(None, description="Override OpenClaw agent id")
    callback_url: str = Field(..., description="URL to POST results to when agent completes")
    callback_metadata: dict[str, Any] = Field(default_factory=dict)
    progress_url: str | None = Field(None, description="Optional progress callback URL")
    execution_timeout: int | None = Field(
        None, description="Execution timeout in seconds (default from env)"
    )


class AsyncRunResponse(BaseModel):
    """Immediate response from async task submission."""

    job_id: str
    status: str = "accepted"
    message: str = "Task accepted, will callback when complete"


class CallbackPayload(BaseModel):
    """Payload sent to callback_url when agent completes."""

    job_id: str
    status: str
    response: str = ""
    error: str | None = None
    session_id: str = ""
    session_key: str = ""
    framework: str = "openclaw"
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}
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


# ==============================================================================
# OpenClaw WebSocket Client
# ==============================================================================


def _build_session_key(agent_id: str, context_type: str, context_id: str) -> str:
    ctx_type = (context_type or "api").strip().lower() or "api"
    ctx_id = (context_id or "unknown").strip() or "unknown"
    return f"agent:{agent_id}:vibeteam:{ctx_type}:{ctx_id}"


def _extract_assistant_text(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    delta = data.get("delta")
    text = data.get("text")
    if isinstance(delta, str):
        return delta
    if isinstance(text, str):
        return text
    return ""


async def _openclaw_handshake(ws: websockets.WebSocketClientProtocol) -> None:
    # OpenClaw gateways emit a connect.challenge event on new connections.
    # Respond by sending a connect request as the first request frame.
    challenge_deadline = time.time() + OPENCLAW_CONNECT_TIMEOUT
    nonce: str | None = None
    while time.time() < challenge_deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=OPENCLAW_CONNECT_TIMEOUT)
        frame = json.loads(raw)
        if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
            payload = frame.get("payload") or {}
            nonce = payload.get("nonce")
            break
    if not nonce:
        raise RuntimeError("OpenClaw connect challenge missing nonce")

    connect_id = str(uuid.uuid4())
    connect_params: dict[str, Any] = {
        "minProtocol": 3,
        "maxProtocol": 3,
        "client": {
            "id": "openclaw-control-ui",
            "displayName": "vibeteam-openclaw-svc",
            "version": "1.0.0",
            "platform": "vibeteam",
            "mode": "ui",
            "instanceId": connect_id,
        },
        "role": "operator",
        "scopes": ["operator.admin", "operator.read", "operator.write"],
    }
    if OPENCLAW_GATEWAY_TOKEN:
        connect_params["auth"] = {"token": OPENCLAW_GATEWAY_TOKEN}

    await ws.send(
        json.dumps(
            {
                "type": "req",
                "id": connect_id,
                "method": "connect",
                "params": connect_params,
            }
        )
    )

    while True:
        raw = await ws.recv()
        frame = json.loads(raw)
        if frame.get("type") == "res" and frame.get("id") == connect_id:
            if not frame.get("ok"):
                raise RuntimeError(f"OpenClaw connect failed: {frame.get('error')}")
            return


async def run_openclaw_task(
    task: str,
    agent_id: str,
    session_key: str,
    timeout_seconds: int | None = None,
) -> tuple[str, dict[str, Any]]:
    timeout_seconds = timeout_seconds or OPENCLAW_AGENT_TIMEOUT
    deadline = time.time() + max(1, int(timeout_seconds))
    response_parts: list[str] = []
    status = "ok"
    error: str | None = None

    extra_headers: dict[str, str] = {}
    if OPENCLAW_WS_ORIGIN:
        extra_headers["Origin"] = OPENCLAW_WS_ORIGIN

    connect_kwargs: dict[str, Any] = {
        "open_timeout": OPENCLAW_CONNECT_TIMEOUT,
        "ping_interval": 20,
        "ping_timeout": 20,
        "max_size": 10 * 1024 * 1024,
    }
    if extra_headers:
        connect_params = inspect.signature(websockets.connect).parameters
        if "additional_headers" in connect_params:
            connect_kwargs["additional_headers"] = extra_headers
        else:
            connect_kwargs["extra_headers"] = extra_headers

    async with websockets.connect(OPENCLAW_WS_URL, **connect_kwargs) as ws:
        await _openclaw_handshake(ws)

        run_id = str(uuid.uuid4())
        agent_params: dict[str, Any] = {
            "message": task,
            "agentId": agent_id,
            "sessionKey": session_key,
            "idempotencyKey": run_id,
        }
        await ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": run_id,
                    "method": "agent",
                    "params": agent_params,
                }
            )
        )

        while True:
            timeout = max(0.1, deadline - time.time())
            if timeout <= 0:
                status = "timeout"
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                status = "timeout"
                break
            frame = json.loads(raw)

            if frame.get("type") == "res" and frame.get("id") == run_id:
                if not frame.get("ok"):
                    err = frame.get("error") or {}
                    raise RuntimeError(f"OpenClaw agent request failed: {err}")
                continue

            if frame.get("type") == "event" and frame.get("event") == "agent":
                payload = frame.get("payload") or {}
                if payload.get("runId") != run_id:
                    continue
                stream = payload.get("stream")
                if stream == "assistant":
                    text = _extract_assistant_text(payload)
                    if text:
                        response_parts.append(text)
                elif stream == "lifecycle":
                    phase = (payload.get("data") or {}).get("phase")
                    if phase in ("end", "error"):
                        status = "error" if phase == "error" else "ok"
                        error = (payload.get("data") or {}).get("error")
                        break

    response_text = "".join(response_parts).strip()
    metadata = {"status": status, "error": error, "agent_id": agent_id}
    return response_text, metadata


# ==============================================================================
# FastAPI App
# ==============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting OpenClaw service...")
    if validate_required_integrations:
        try:
            validate_required_integrations("openclaw-svc")
        except Exception as e:
            logger.error(str(e))
            raise
    if init_db:
        try:
            await init_db()
        except Exception as e:
            logger.warning("Database initialization failed (may not be available): %s", e)
    yield
    logger.info("Shutting down OpenClaw service...")
    if close_db:
        await close_db()


app = FastAPI(
    title="OpenClaw Agent Service",
    description="OpenClaw gateway proxy service for VibeTeam",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        framework="openclaw",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/run", response_model=RunResponse)
async def run_task(request: RunRequest):
    start_time = time.time()
    try:
        context_id = request.context_id or str(uuid.uuid4())[:8]
        role_for_token = _resolve_role_for_token(request.role, request.task)
        entry = get_agent_entry(request.role) if request.role else None
        agent_id = (
            request.openclaw_agent_id
            or resolve_openclaw_agent_id(request.role)
            or (entry.openclaw_agent_id if entry else None)
            or "product-manager"
        )
        session_key = request.session_key or _build_session_key(
            agent_id, request.context_type, context_id
        )

        task = request.task

        with _github_token_context(role_for_token):
            response_text, metadata = await run_openclaw_task(
                task=task,
                agent_id=agent_id,
                session_key=session_key,
            )

        latency_ms = int((time.time() - start_time) * 1000)

        # Store session in DB (namespaced key) when available
        if get_postgres_store:
            try:
                store = get_postgres_store()
                await store.save(
                    {
                        "key": f"openclaw:{session_key}",
                        "framework": "openclaw",
                        "role": request.role or "product_manager",
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
                                "content": response_text,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        ],
                        "metadata": {"openclaw_session_key": session_key, **metadata},
                    }
                )
            except Exception as e:
                logger.warning("Failed to save session to PostgreSQL: %s", e)

        return RunResponse(
            response=response_text,
            session_id=context_id,
            session_key=session_key,
            agents_used=[agent_id],
            metadata={"latency_ms": latency_ms, **metadata},
        )

    except Exception as e:
        logger.exception(f"OpenClaw task failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _execute_and_callback(job_id: str, request: AsyncRunRequest) -> None:
    try:
        result = await run_task(
            RunRequest(
                task=request.task,
                role=request.role,
                context_type=request.context_type,
                context_id=request.context_id,
                session_key=request.session_key,
                openclaw_agent_id=request.openclaw_agent_id,
            )
        )
        payload = CallbackPayload(
            job_id=job_id,
            status="completed",
            response=result.response,
            session_id=result.session_id,
            session_key=result.session_key,
            agents_used=result.agents_used,
            metadata=result.metadata,
            callback_metadata=request.callback_metadata,
        )
    except Exception as e:
        payload = CallbackPayload(
            job_id=job_id,
            status="failed",
            error=str(e),
            callback_metadata=request.callback_metadata,
        )

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                request.callback_url,
                json=payload.model_dump(),
                timeout=30.0,
            )
    except Exception as e:
        logger.error(f"[job={job_id}] Failed to send callback: {repr(e)}")


@app.post("/run/async", response_model=AsyncRunResponse)
async def run_task_async(request: AsyncRunRequest):
    job_id = str(uuid.uuid4())
    logger.info(
        f"[job={job_id}] Async task accepted: role={request.role}, "
        f"context={request.context_type}:{request.context_id}"
    )
    asyncio.create_task(_execute_and_callback(job_id, request))
    return AsyncRunResponse(job_id=job_id)


@app.post("/run/stream")
async def run_task_stream(request: RunRequest):
    async def generate():
        context_id = request.context_id or str(uuid.uuid4())[:8]
        yield f'data: {{"event": "start", "context_id": "{context_id}"}}\n\n'
        try:
            result = await run_task(request)
            payload = {
                "event": "message",
                "content": result.response,
                "session_id": result.session_id,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'session_id': result.session_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    try:
        if not get_postgres_store:
            raise HTTPException(status_code=404, detail="Session store unavailable")
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
    try:
        if not get_postgres_store:
            return {"sessions": [], "count": 0}
        store = get_postgres_store()
        sessions = await store.list_sessions(prefix=f"openclaw:{prefix}", limit=limit)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
