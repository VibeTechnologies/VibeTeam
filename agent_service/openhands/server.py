from __future__ import annotations

"""
OpenHands Agent Microservice.

FastAPI server exposing OpenHands team functionality via REST API.
"""

import asyncio
import contextlib
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_service.config import AgentConfig
from agent_service.shared.db import close_db, get_postgres_store, init_db
from agent_service.shared.integration_checks import validate_required_integrations

from .team import OpenHandsTeam, create_team
from .utils import (
    coerce_text,
    configure_text_truncation,
    configure_textcontent_json_serialization,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_GITHUB_TOKEN_LOCK = threading.Lock()


def _format_exception_message(exc: Exception) -> str:
    """Build a non-empty, callback-safe error message."""
    if isinstance(exc, HTTPException):
        detail = getattr(exc, "detail", None)
        if detail is not None:
            text = str(detail).strip()
            if text:
                return text
        status_code = getattr(exc, "status_code", None)
        if status_code:
            return f"HTTP {status_code}"

    text = str(exc).strip()
    if text:
        return text
    return exc.__class__.__name__


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


def _disable_prompt_cache_retention() -> None:
    flag = os.environ.get("OPENHANDS_DISABLE_PROMPT_CACHE_RETENTION")
    if flag is not None:
        enabled = flag.lower() in {"1", "true", "yes"}
    else:
        enabled = bool(os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("AZURE_API_BASE"))
    if not enabled:
        return

    try:
        from openhands.sdk.llm import llm as llm_module
        from openhands.sdk.llm.options import chat_options, responses_options
    except Exception as exc:
        logger.warning("Failed to patch prompt_cache_retention: %s", exc)
        return

    def _strip_prompt_cache_retention(payload: dict) -> dict:
        payload.pop("prompt_cache_retention", None)
        return payload

    original_responses = responses_options.select_responses_options
    if not getattr(original_responses, "_vibeteam_patched", False):

        def _patched_responses(*args, **kwargs):  # type: ignore[no-untyped-def]
            out = original_responses(*args, **kwargs)
            if isinstance(out, dict):
                return _strip_prompt_cache_retention(out)
            return out

        _patched_responses._vibeteam_patched = True  # type: ignore[attr-defined]
        responses_options.select_responses_options = _patched_responses
        llm_module.select_responses_options = _patched_responses

    original_chat = chat_options.select_chat_options
    if not getattr(original_chat, "_vibeteam_patched", False):

        def _patched_chat(*args, **kwargs):  # type: ignore[no-untyped-def]
            out = original_chat(*args, **kwargs)
            if isinstance(out, dict):
                return _strip_prompt_cache_retention(out)
            return out

        _patched_chat._vibeteam_patched = True  # type: ignore[attr-defined]
        chat_options.select_chat_options = _patched_chat
        llm_module.select_chat_options = _patched_chat

    logger.info("Prompt cache retention disabled for Azure OpenHands runs.")


def _resolve_token_role(team: OpenHandsTeam, request: RunRequest) -> str | None:
    if request.role:
        return request.role
    try:
        role = team.parse_mention(request.task)
        if role:
            return role
        return team.route_by_keywords(request.task)
    except Exception:
        return None


# Concurrency control: limit the number of simultaneous agent executions
# to prevent resource exhaustion when multiple jobs arrive concurrently.
# Default: 3 concurrent jobs (configurable via MAX_CONCURRENT_JOBS env var).
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "3"))
_job_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazily create the semaphore (must be created inside event loop)."""
    global _job_semaphore
    if _job_semaphore is None:
        _job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        logger.info(f"Initialized job semaphore with max_concurrent_jobs={MAX_CONCURRENT_JOBS}")
    return _job_semaphore


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
    max_iterations: int = Field(
        30,
        description="Maximum agent iterations (tool calls) before forced stop (default: 30)",
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
    callback_url: str = Field(..., description="URL to POST results to when agent completes")
    callback_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque metadata passed through to the callback (e.g. channel, thread_ts)",
    )
    progress_url: str | None = Field(
        None,
        description="URL to POST progress updates to while agent is working (optional)",
    )
    execution_timeout: int | None = Field(
        600,
        description=(
            "Execution timeout in seconds. If progress updates are enabled, this is treated "
            "as an idle timeout (no progress within the window). Otherwise it is a hard cap. "
            "Use 0 or null to disable timeout enforcement."
        ),
    )
    max_iterations: int = Field(
        30,
        description="Maximum agent iterations (tool calls) before forced stop (default: 30)",
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
    _disable_prompt_cache_retention()
    try:
        validate_required_integrations("openhands-svc")
    except Exception as e:
        logger.error(str(e))
        raise

    # Raise OpenHands TextContent limit to avoid premature truncation.
    configure_text_truncation()
    # Patch OpenHands JSON serialization to avoid TextContent crashes.
    configure_textcontent_json_serialization()

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
    idle_timeout_raw = os.getenv("OPENHANDS_SYNC_IDLE_TIMEOUT_SECONDS", "")
    idle_timeout: int | None = None
    if idle_timeout_raw:
        try:
            idle_timeout = int(idle_timeout_raw)
        except ValueError:
            idle_timeout = None
    if idle_timeout is not None and idle_timeout <= 0:
        idle_timeout = None
    last_progress: dict[str, float] = {"time": start_time}

    def _progress_heartbeat() -> None:
        last_progress["time"] = time.time()

    async def _run_with_idle_timeout(run_fn):
        task = asyncio.create_task(asyncio.to_thread(run_fn))
        while True:
            done, _ = await asyncio.wait({task}, timeout=1.0)
            if done:
                return done.pop().result()
            if idle_timeout is None:
                continue
            if time.time() - last_progress["time"] > idle_timeout:
                task.cancel()
                raise asyncio.TimeoutError()

    try:
        team = get_team()

        # Generate context_id if not provided
        context_id = request.context_id or str(uuid.uuid4())[:8]

        # Determine role - let team route if not specified
        role = request.role
        role_for_token = _resolve_token_role(team, request)

        # Run the task
        # Use asyncio.to_thread to run blocking agent code without blocking the event loop
        # This allows health checks to respond while the agent is processing
        if role:
            # Run with specific agent in a thread pool
            agent = team._get_agent(role)

            def _run_agent():
                with _github_token_context(role_for_token):
                    return agent.run(
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
                        workspace=request.workspace,
                        use_tools=request.use_tools,
                        max_iterations=request.max_iterations,
                        progress_heartbeat=_progress_heartbeat,
                    )

            if idle_timeout is None:
                result = await asyncio.to_thread(_run_agent)
            else:
                result = await _run_with_idle_timeout(_run_agent)
        else:
            # Let team route based on @mentions or keywords
            with _github_token_context(role_for_token):
                result = await team.run_async(
                    task=request.task,
                    context_type=request.context_type,
                    context_id=context_id,
                    workspace=request.workspace,
                )

        latency_ms = int((time.time() - start_time) * 1000)
        response_text = coerce_text(result.get("response", ""))

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
                            "content": response_text,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ],
                }
            )
        except Exception as e:
            logger.warning(f"Failed to save session to PostgreSQL: {e}")

        return RunResponse(
            response=response_text,
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

    except asyncio.TimeoutError:
        elapsed_ms = int((time.time() - start_time) * 1000)
        agent_role = role or "team"
        session_key = f"openhands:{agent_role}:{request.context_type}:{context_id}"
        timeout_detail = ""
        if idle_timeout is not None:
            timeout_detail = f"No progress for {idle_timeout} seconds (idle timeout). "

        return RunResponse(
            response=(
                "I was working on this task but had to stop due to inactivity. "
                f"{timeout_detail}Please try again or break the task into smaller steps."
            ),
            session_id=context_id,
            session_key=session_key,
            framework="openhands",
            agents_used=[agent_role],
            metadata={
                "latency_ms": elapsed_ms,
                "message_count": 2,
                "workspace": request.workspace,
                "timed_out": True,
                "timeout_seconds": idle_timeout,
                "timeout_mode": "idle",
            },
        )
    except Exception as e:
        logger.exception("Task execution failed")
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
    - Timeout is treated as idle timeout when progress updates are enabled
    - On timeout, extracts partial results from whatever events exist
    - Sends progress updates to request.progress_url if provided
    - Concurrency limited by semaphore to prevent resource exhaustion
    """
    import httpx

    semaphore = _get_semaphore()
    logger.info(
        f"[job={job_id}] Waiting for semaphore "
        f"(active={MAX_CONCURRENT_JOBS - semaphore._value}/{MAX_CONCURRENT_JOBS})"
    )

    async with semaphore:
        start_time = time.time()
        context_id = request.context_id or str(uuid.uuid4())[:8]
        execution_timeout = request.execution_timeout
        if execution_timeout is not None and execution_timeout <= 0:
            execution_timeout = None
        last_progress: dict[str, float] = {"time": start_time}
        progress_enabled = bool(request.progress_url)
        timeout_provided = "execution_timeout" in request.model_fields_set
        if progress_enabled and not timeout_provided:
            # No hard/idle timeout by default when progress updates are enabled.
            # This avoids canceling long-running jobs that are actively working.
            execution_timeout = None

        def _progress_heartbeat() -> None:
            last_progress["time"] = time.time()

        async def _run_with_idle_timeout(run_fn):
            task = asyncio.create_task(asyncio.to_thread(run_fn))
            while True:
                done, _ = await asyncio.wait({task}, timeout=1.0)
                if done:
                    return done.pop().result()
                if execution_timeout is None:
                    continue
                if time.time() - last_progress["time"] > execution_timeout:
                    task.cancel()
                    raise asyncio.TimeoutError()

        try:
            team = get_team()
            role = request.role

            timeout_log = f"{execution_timeout}s" if execution_timeout is not None else "disabled"
            logger.info(
                f"[job={job_id}] Starting agent execution: role={role}, timeout={timeout_log}"
            )

            if role:
                agent = team._get_agent(role)
                # Wrap agent.run in asyncio.wait_for to enforce overall timeout.
                # This prevents the agent from hanging forever if an LLM call gets stuck.
                try:

                    def _run_agent():
                        return agent.run(
                            task=request.task,
                            context_type=request.context_type,
                            context_id=context_id,
                            workspace=request.workspace,
                            use_tools=request.use_tools,
                            max_iterations=request.max_iterations,
                            # Progress callback params — agents use these to send
                            # real-time updates to the gateway while working
                            progress_url=request.progress_url,
                            job_id=job_id,
                            callback_metadata=request.callback_metadata,
                            progress_heartbeat=_progress_heartbeat if progress_enabled else None,
                        )

                    if progress_enabled:
                        result = await _run_with_idle_timeout(_run_agent)
                    else:
                        if execution_timeout is None:
                            result = await asyncio.to_thread(_run_agent)
                        else:
                            result = await asyncio.wait_for(
                                asyncio.to_thread(_run_agent),
                                timeout=execution_timeout,
                            )
                except asyncio.TimeoutError:
                    elapsed = int(time.time() - start_time)
                    logger.error(
                        f"[job={job_id}] Agent execution timed out after {elapsed}s "
                        f"(limit={execution_timeout}s, progress_enabled={progress_enabled})"
                    )
                    agent_role = role or "team"

                    # Send timeout callback
                    timeout_detail = (
                        f"No progress for {execution_timeout} seconds (idle timeout). "
                        if progress_enabled
                        else f"Exceeded {execution_timeout} seconds (hard timeout). "
                    )
                    payload = CallbackPayload(
                        job_id=job_id,
                        status="timeout",
                        error=f"Agent execution timed out after {elapsed}s",
                        response=(
                            f"I was working on this task but timed out. {timeout_detail}"
                            f"Please try again or break the task into smaller steps."
                        ),
                        agents_used=[agent_role],
                        metadata={
                            "latency_ms": elapsed * 1000,
                            "timeout_seconds": execution_timeout,
                            "timeout_mode": "idle" if progress_enabled else "absolute",
                            "timed_out": True,
                        },
                        callback_metadata=request.callback_metadata,
                    )
                    # Jump to callback sending (with retry for resilience)
                    for attempt in range(3):
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
                            break  # Success — exit retry loop
                        except Exception as e:
                            logger.error(
                                f"[job={job_id}] Failed to send timeout callback "
                                f"(attempt {attempt + 1}/3): {repr(e)}"
                            )
                            if attempt < 2:
                                await asyncio.sleep(2**attempt)  # Exponential backoff
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
                    for attempt in range(3):
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
                            break
                        except Exception as e:
                            logger.error(
                                f"[job={job_id}] Failed to send timeout callback "
                                f"(attempt {attempt + 1}/3): {repr(e)}"
                            )
                            if attempt < 2:
                                await asyncio.sleep(2**attempt)
                    return

            latency_ms = int((time.time() - start_time) * 1000)
            agent_role = result.get("agent", role or "team")
            response_text = coerce_text(result.get("response", ""))
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
                                "content": response_text,
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
                response=response_text,
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
            logger.exception(f"[job={job_id}] Agent execution failed")
            payload = CallbackPayload(
                job_id=job_id,
                status="failed",
                error=_format_exception_message(e),
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
            logger.error(
                f"[job={job_id}] Failed to send callback to {request.callback_url}: {repr(e)}"
            )


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
            role_for_token = _resolve_token_role(team, request)

            # Send start event
            yield f"data: {{'event': 'start', 'context_id': '{context_id}'}}\n\n"

            # Run the task
            if request.role:
                agent = team._get_agent(request.role)
                with _github_token_context(role_for_token):
                    result = agent.run(
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
                        workspace=request.workspace,
                    )
            else:
                with _github_token_context(role_for_token):
                    result = await team.run_async(
                        task=request.task,
                        context_type=request.context_type,
                        context_id=context_id,
                        workspace=request.workspace,
                    )

            # Send result
            import json

            response_text = coerce_text(result.get("response", ""))
            yield f"data: {json.dumps({'event': 'message', 'content': response_text})}\n\n"
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
