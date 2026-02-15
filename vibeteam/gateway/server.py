"""
VibeTeam Gateway Server.

FastAPI server that receives external events and routes them to agent microservices.
Replaces the subprocess-based approach with HTTP calls to autogen-svc/crewai-svc.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# Configuration
# ==============================================================================


class GatewayConfig:
    """Gateway configuration from environment variables."""

    # Agent service URLs
    AUTOGEN_SERVICE_URL = os.environ.get("AUTOGEN_SERVICE_URL", "http://autogen-svc:8080")
    CREWAI_SERVICE_URL = os.environ.get("CREWAI_SERVICE_URL", "http://crewai-svc:8080")
    OPENHANDS_SERVICE_URL = os.environ.get("OPENHANDS_SERVICE_URL", "http://openhands-svc:8080")
    SCHEDULER_SERVICE_URL = os.environ.get("SCHEDULER_SERVICE_URL", "http://scheduler-svc:8080")
    # OpenHands selected as default based on benchmark results (100% success, 0.80 composite)
    # See docs/research.md Section 16 for detailed analysis
    DEFAULT_FRAMEWORK = os.environ.get("DEFAULT_FRAMEWORK", "openhands")

    # GitHub configuration
    GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    BOT_USERNAME = os.environ.get("GITHUB_BOT_USERNAME", "vibeteam-bot[bot]")
    GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
    GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    GITHUB_APP_INSTALLATION_ID = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

    # Slack configuration
    SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

    # Trigger API authentication (for /slack/trigger, /discord/trigger, etc.)
    # Set this to a shared secret to protect trigger endpoints from unauthorized access.
    # The eval script and other callers must send this as a Bearer token.
    SLACK_TRIGGER_SECRET = os.environ.get("SLACK_TRIGGER_SECRET", "")

    # Sentry configuration
    SENTRY_CLIENT_SECRET = os.environ.get("SENTRY_CLIENT_SECRET", "")

    # Gateway self-URL (for callback URLs sent to agent services)
    # In K8s, the gateway is accessible at http://vibeteam-gateway:8080 via service DNS
    GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://vibeteam-gateway:8080")

    # Shared secret for authenticating agent callbacks to /callback/agent.
    # The gateway sends this in callback_metadata; the agent echoes it back.
    # If empty, callback authentication is disabled (dev/test mode).
    CALLBACK_SECRET = os.environ.get("CALLBACK_SECRET", "")

    @classmethod
    def get_agent_service_url(cls, framework: str | None = None) -> str:
        """Get the URL for the specified agent framework."""
        fw = framework or cls.DEFAULT_FRAMEWORK
        if fw == "crewai":
            return cls.CREWAI_SERVICE_URL
        elif fw == "openhands":
            return cls.OPENHANDS_SERVICE_URL
        return cls.AUTOGEN_SERVICE_URL


config = GatewayConfig()


# ==============================================================================
# Request/Response Models
# ==============================================================================


class RunRequest(BaseModel):
    """Request to run a task via the gateway."""

    task: str = Field(..., description="The task to execute")
    role: str | None = Field(
        None,
        description="Agent role (support_engineer, release_engineer, software_engineer, etc.)",
    )
    framework: str | None = Field(None, description="Agent framework (autogen, crewai, openhands)")
    context_type: str = Field("api", description="Context type")
    context_id: str | None = Field(None, description="Context ID")
    stream: bool = Field(False, description="Stream the response (SSE)")


class RunResponse(BaseModel):
    """Response from task execution."""

    response: str
    session_id: str
    framework: str
    agents_used: list[str] = []
    metadata: dict[str, Any] = {}


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    timestamp: str
    services: dict[str, str] = {}


# ==============================================================================
# HTTP Client
# ==============================================================================

# Global HTTP client for connection pooling
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create async HTTP client with robust connection settings."""
    global _http_client
    if _http_client is None:
        # Configure connection limits for reliability
        # Disable keepalive to avoid stale connection issues in K8s cross-node networking
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=0,  # Disable keepalive - new connection per request
            keepalive_expiry=5.0,  # Short expiry if any keepalive
        )
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),  # Longer connect timeout for K8s DNS
            limits=limits,
        )
    return _http_client


async def close_http_client() -> None:
    """Close the HTTP client."""
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


async def call_agent_service(
    task: str,
    role: str | None = None,
    framework: str | None = None,
    context_type: str = "api",
    context_id: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """
    Call an agent microservice to execute a task.

    Args:
        task: Task description
        role: Agent role (determines routing)
        framework: Agent framework (autogen, crewai)
        context_type: Context type for session tracking
        context_id: Context ID for session tracking
        stream: Whether to stream the response

    Returns:
        Agent response dict
    """
    import asyncio
    import time

    start_time = time.time()
    service_url = config.get_agent_service_url(framework)
    endpoint = "/run/stream" if stream else "/run"
    fw = framework or config.DEFAULT_FRAMEWORK

    logger.info(
        f"[TIMING] Agent call started: role={role}, framework={fw}, context={context_type}:{context_id}"
    )

    payload = {
        "task": task,
        "role": role,
        "context_type": context_type,
        "context_id": context_id,
    }

    # For openhands, add parameters
    if fw == "openhands":
        payload["use_tools"] = True
        # Enable context injection so agents get Sentry/Gmail/Langfuse data
        payload["skip_context_injection"] = False

    # Retry logic for transient connection failures
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            # Get a fresh client reference for each attempt (handles stale connections)
            client = get_http_client()
            attempt_start = time.time()
            logger.debug(f"Calling {service_url}{endpoint} (attempt {attempt + 1}/{max_retries})")
            response = await client.post(
                f"{service_url}{endpoint}",
                json=payload,
                timeout=1800.0,  # 30 min for agents running agentic loops
            )
            response.raise_for_status()
            result = response.json()

            # Log timing metrics
            total_time = time.time() - start_time
            attempt_time = time.time() - attempt_start
            logger.info(
                f"[TIMING] Agent call completed: role={role}, "
                f"total={total_time:.1f}s, http={attempt_time:.1f}s, "
                f"response_len={len(result.get('response', ''))}"
            )

            # Include timing in result metadata
            if "metadata" not in result:
                result["metadata"] = {}
            result["metadata"]["gateway_timing"] = {
                "total_seconds": round(total_time, 2),
                "http_seconds": round(attempt_time, 2),
                "attempts": attempt + 1,
            }

            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"Agent service error: {e.response.status_code} - {e.response.text}")
            return {
                "error": f"Agent service error: {e.response.status_code}",
                "detail": e.response.text,
            }
        except httpx.RequestError as e:
            last_error = e
            error_type = type(e).__name__
            # Don't retry on ReadTimeout - the agent is processing, not down.
            # Retrying would just queue another 15-min wait.
            if isinstance(e, httpx.ReadTimeout):
                logger.error(
                    f"Agent call timed out after {time.time() - start_time:.0f}s "
                    f"[{error_type}] to {service_url}: {e}"
                )
                break
            if attempt < max_retries - 1:
                logger.warning(
                    f"Connection failed (attempt {attempt + 1}/{max_retries}) "
                    f"[{error_type}] to {service_url}: {e}"
                )
                # Reset the HTTP client on connection errors to clear stale connections
                await close_http_client()
                await asyncio.sleep(1.0 * (attempt + 1))  # Longer backoff
                continue
            break

    # All retries exhausted
    logger.error(
        f"Failed to connect to {service_url} after {max_retries} attempts: "
        f"[{type(last_error).__name__}] {last_error}"
    )
    return {
        "error": f"Failed to connect to agent service: {last_error}",
    }


async def call_agent_service_async(
    task: str,
    role: str | None = None,
    framework: str | None = None,
    context_type: str = "api",
    context_id: str | None = None,
    callback_url: str = "",
    callback_metadata: dict[str, Any] | None = None,
    progress_url: str | None = None,
    skip_context_injection: bool = False,
) -> dict[str, Any]:
    """
    Submit a task to the agent service asynchronously.

    Unlike call_agent_service(), this returns immediately with a job_id.
    The agent service runs the task in the background and POSTs results
    to callback_url when done.

    Args:
        task: Task description
        role: Agent role
        framework: Agent framework
        context_type: Context type for session tracking
        context_id: Context ID for session tracking
        callback_url: URL where agent should POST results
        callback_metadata: Opaque data passed through to callback
        progress_url: URL where agent should POST progress updates (optional)
        skip_context_injection: If True, skip pre-fetched kubectl/Sentry context
            injection. Used for focused tasks like health checks where the task
            prompt already contains all necessary instructions.

    Returns:
        {"job_id": "...", "status": "accepted"} or {"error": "..."}
    """
    import time

    start_time = time.time()
    service_url = config.get_agent_service_url(framework)
    fw = framework or config.DEFAULT_FRAMEWORK

    logger.info(
        f"[ASYNC] Submitting task: role={role}, framework={fw}, "
        f"context={context_type}:{context_id}, callback={callback_url}"
    )

    payload: dict[str, Any] = {
        "task": task,
        "role": role,
        "context_type": context_type,
        "context_id": context_id,
        "callback_url": callback_url,
        "callback_metadata": callback_metadata or {},
    }

    # For openhands, add parameters
    if fw == "openhands":
        payload["use_tools"] = True
        payload["skip_context_injection"] = skip_context_injection

    # Pass progress_url so agent service can send intermediate updates
    if progress_url:
        payload["progress_url"] = progress_url

    try:
        client = get_http_client()
        response = await client.post(
            f"{service_url}/run/async",
            json=payload,
            timeout=30.0,  # Should return immediately — 30s is generous
        )
        response.raise_for_status()
        result = response.json()

        elapsed = time.time() - start_time
        logger.info(
            f"[ASYNC] Task accepted in {elapsed:.1f}s: job_id={result.get('job_id')}, role={role}"
        )
        return result

    except httpx.HTTPStatusError as e:
        logger.error(f"[ASYNC] Agent service error: {e.response.status_code} - {e.response.text}")
        return {
            "error": f"Agent service error: {e.response.status_code}",
            "detail": e.response.text,
        }
    except httpx.RequestError as e:
        logger.error(f"[ASYNC] Failed to connect to {service_url}: {e}")
        return {"error": f"Failed to connect to agent service: {e}"}


async def call_scheduler_service(
    task: str,
    run_at: str | None = None,
    role: str | None = None,
    framework: str | None = None,
    context_type: str = "api",
    context_id: str | None = None,
) -> dict[str, Any]:
    """
    Schedule a task via the scheduler service.

    Args:
        task: Task description
        run_at: ISO datetime to run (None for immediate)
        role: Agent role
        framework: Agent framework
        context_type: Context type
        context_id: Context ID

    Returns:
        Scheduler response dict
    """
    client = get_http_client()

    payload = {
        "task": task,
        "role": role,
        "agent_service": (
            "autogen-svc" if framework not in ("crewai", "openhands") else f"{framework}-svc"
        ),
        "context_type": context_type,
        "context_id": context_id,
    }
    if run_at:
        payload["run_at"] = run_at

    try:
        response = await client.post(
            f"{config.SCHEDULER_SERVICE_URL}/tasks",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Scheduler service error: {e.response.status_code} - {e.response.text}")
        return {"error": f"Scheduler error: {e.response.status_code}"}
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to scheduler: {e}")
        return {"error": f"Failed to connect to scheduler: {e}"}


async def check_service_health(url: str) -> str:
    """Check if a service is healthy."""
    client = get_http_client()
    try:
        response = await client.get(f"{url}/health", timeout=5.0)
        if response.status_code == 200:
            return "healthy"
        return f"unhealthy ({response.status_code})"
    except Exception as e:
        return f"unreachable ({e})"


# ==============================================================================
# Application Lifecycle
# ==============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting VibeTeam Gateway...")
    logger.info(f"AutoGen service: {config.AUTOGEN_SERVICE_URL}")
    logger.info(f"CrewAI service: {config.CREWAI_SERVICE_URL}")
    logger.info(f"OpenHands service: {config.OPENHANDS_SERVICE_URL}")
    logger.info(f"Scheduler service: {config.SCHEDULER_SERVICE_URL}")
    logger.info(f"Default framework: {config.DEFAULT_FRAMEWORK}")

    yield

    logger.info("Shutting down VibeTeam Gateway...")
    await close_http_client()


# ==============================================================================
# FastAPI Application
# ==============================================================================

app = FastAPI(
    title="VibeTeam Gateway",
    description="Routes external events to VibeTeam agent microservices",
    version="2.0.0",
    lifespan=lifespan,
)

# ==============================================================================
# Middleware (applied in reverse order — last added runs first)
# ==============================================================================

from vibeteam.gateway.middleware import MetricsMiddleware, RateLimitMiddleware

# Metrics first (outermost), then rate limiting
app.add_middleware(RateLimitMiddleware, skip_health=True)
app.add_middleware(MetricsMiddleware)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with downstream service status."""
    # Check downstream services
    services = {
        "autogen-svc": await check_service_health(config.AUTOGEN_SERVICE_URL),
        "crewai-svc": await check_service_health(config.CREWAI_SERVICE_URL),
        "openhands-svc": await check_service_health(config.OPENHANDS_SERVICE_URL),
        "scheduler-svc": await check_service_health(config.SCHEDULER_SERVICE_URL),
    }

    # Overall status is healthy if gateway is running
    # (downstream unhealthy is a warning, not a failure)
    return HealthResponse(
        status="healthy",
        service="vibeteam-gateway",
        timestamp=datetime.now(timezone.utc).isoformat(),
        services=services,
    )


@app.get("/metrics")
async def metrics():
    """
    Metrics endpoint for monitoring.

    Returns per-endpoint request counts, error counts, and latency percentiles.
    Compatible with Prometheus JSON exporter or direct scraping.
    """
    from vibeteam.gateway.middleware import get_metrics_snapshot

    return {
        "service": "vibeteam-gateway",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": get_metrics_snapshot(),
    }


# ==============================================================================
# Import and register routers
# ==============================================================================

# Import routers after app is created to avoid circular imports
from vibeteam.gateway.routes.api import router as api_router
from vibeteam.gateway.routes.github import router as github_router
from vibeteam.gateway.routes.sentry import router as sentry_router
from vibeteam.gateway.routes.slack import router as slack_router

app.include_router(github_router)  # type: ignore[has-type]
app.include_router(slack_router)  # type: ignore[has-type]
app.include_router(sentry_router)  # type: ignore[has-type]
app.include_router(api_router, prefix="/api")  # type: ignore[has-type]


# ==============================================================================
# Entry Point
# ==============================================================================


def main() -> None:
    """Run the gateway server."""
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting gateway on {host}:{port}")
    uvicorn.run(
        "vibeteam.gateway.server:app",
        host=host,
        port=port,
        reload=os.environ.get("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
