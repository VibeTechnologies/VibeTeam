"""
Gateway Middleware.

Provides rate limiting and metrics middleware for the FastAPI gateway.
"""

import logging
import os
import threading
import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)


# ==============================================================================
# Rate Limiting Middleware
# ==============================================================================


class EndpointRateLimiter:
    """
    Per-endpoint token bucket rate limiter.

    Each endpoint path has its own token bucket with configurable limits.
    Uses the same token bucket algorithm as the trigger rate limiter.
    """

    def __init__(self, default_max: int = 60, default_window: float = 60.0):
        self.default_max = default_max
        self.default_window = default_window
        self._buckets: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _get_bucket(self, key: str, max_requests: int, window: float) -> dict:
        """Get or create a bucket for a given key."""
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": float(max_requests),
                "last_refill": time.monotonic(),
                "max_requests": max_requests,
                "window": window,
            }
        return self._buckets[key]

    def allow(self, key: str, max_requests: int | None = None, window: float | None = None) -> bool:
        """Check if a request is allowed for the given key."""
        mr = max_requests or self.default_max
        w = window or self.default_window

        with self._lock:
            bucket = self._get_bucket(key, mr, w)
            now = time.monotonic()
            elapsed = now - bucket["last_refill"]
            bucket["tokens"] = min(
                bucket["max_requests"],
                bucket["tokens"] + elapsed * (bucket["max_requests"] / bucket["window"]),
            )
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return True
            return False

    def reset(self, key: str | None = None) -> None:
        """Reset rate limiter state (for testing)."""
        with self._lock:
            if key:
                self._buckets.pop(key, None)
            else:
                self._buckets.clear()


# Per-endpoint rate limit configuration.
# Format: path_prefix -> (max_requests, window_seconds)
# Endpoints not listed use the default (60 req/60s).
# Webhook endpoints from Slack/GitHub/Sentry get generous limits;
# API endpoints that trigger agent execution are more restricted.
ENDPOINT_RATE_LIMITS: dict[str, tuple[int, float]] = {
    # Webhook endpoints — external services send bursts
    "/slack/events": (120, 60.0),  # Slack may retry aggressively
    "/webhook": (120, 60.0),  # GitHub webhooks
    "/webhook/sentry": (60, 60.0),  # Sentry alerts
    # Callback endpoints — internal, from agent services
    "/callback/agent": (120, 60.0),  # Agent result callbacks
    "/callback/agent/progress": (300, 60.0),  # Progress updates are frequent
    # Trigger endpoint — already has its own limiter, but add global protection
    "/slack/trigger": (30, 60.0),
    # API endpoints — expensive (they launch agents)
    "/api/run": (10, 60.0),  # Direct agent execution
    "/api/schedule": (20, 60.0),  # Schedule tasks
    "/api/tasks": (60, 60.0),  # List/manage tasks (read-heavy)
    "/api/sessions": (60, 60.0),  # List sessions (read-heavy)
    # Health check — always generous
    "/health": (300, 60.0),
}

# Override from environment: RATE_LIMIT_DEFAULT_MAX, RATE_LIMIT_DEFAULT_WINDOW
_default_max = int(os.environ.get("RATE_LIMIT_DEFAULT_MAX", "60"))
_default_window = float(os.environ.get("RATE_LIMIT_DEFAULT_WINDOW", "60"))

# Shared rate limiter instance
_endpoint_limiter = EndpointRateLimiter(
    default_max=_default_max,
    default_window=_default_window,
)


def get_endpoint_limiter() -> EndpointRateLimiter:
    """Get the global endpoint rate limiter (for testing access)."""
    return _endpoint_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that applies per-endpoint rate limiting.

    Returns HTTP 429 with Retry-After header when rate limited.
    Skips rate limiting for health checks when RATE_LIMIT_SKIP_HEALTH=true.
    """

    def __init__(self, app, skip_health: bool = False):
        super().__init__(app)
        self.skip_health = skip_health or os.environ.get("RATE_LIMIT_SKIP_HEALTH", "").lower() in (
            "true",
            "1",
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip health check rate limiting if configured
        if self.skip_health and path == "/health":
            return await call_next(request)

        # Find the matching rate limit config
        max_req, window = ENDPOINT_RATE_LIMITS.get(path, (_default_max, _default_window))

        # Use path as the rate limit key (global per-endpoint, not per-IP)
        if not _endpoint_limiter.allow(path, max_req, window):
            logger.warning(f"Rate limit exceeded for {request.method} {path}")
            return Response(
                content=f'{{"detail":"Rate limit exceeded for {path}. Try again later."}}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(int(window))},
            )

        return await call_next(request)


# ==============================================================================
# Prometheus Metrics Middleware
# ==============================================================================

# Track request counts and latencies per endpoint
_request_counts: dict[str, int] = defaultdict(int)
_request_latencies: dict[str, list[float]] = defaultdict(list)
_request_errors: dict[str, int] = defaultdict(int)
_metrics_lock = threading.Lock()

# Max latency samples to keep per endpoint (rolling window)
_MAX_LATENCY_SAMPLES = 1000


def get_metrics_snapshot() -> dict:
    """
    Get current metrics snapshot.

    Returns a dict with request counts, error counts, and latency stats
    per endpoint. Used by the /metrics endpoint and Prometheus exporter.
    """
    with _metrics_lock:
        metrics = {}
        for path, count in _request_counts.items():
            latencies = _request_latencies.get(path, [])
            metrics[path] = {
                "request_count": count,
                "error_count": _request_errors.get(path, 0),
                "latency_avg_ms": (
                    round(sum(latencies) / len(latencies) * 1000, 2) if latencies else 0
                ),
                "latency_p95_ms": (
                    round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2)
                    if latencies
                    else 0
                ),
                "latency_p99_ms": (
                    round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2)
                    if latencies
                    else 0
                ),
            }
        return metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Lightweight metrics collection middleware.

    Tracks per-endpoint:
    - Request count
    - Error count (4xx/5xx)
    - Response latency (avg, p95, p99)

    Exposes data via get_metrics_snapshot() for the /metrics endpoint
    and optionally for Prometheus scraping via prometheus_client.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            with _metrics_lock:
                _request_counts[path] += 1
                _request_errors[path] += 1
            raise

        elapsed = time.monotonic() - start

        with _metrics_lock:
            _request_counts[path] += 1
            if response.status_code >= 400:
                _request_errors[path] += 1

            latencies = _request_latencies[path]
            latencies.append(elapsed)
            # Keep rolling window
            if len(latencies) > _MAX_LATENCY_SAMPLES:
                _request_latencies[path] = latencies[-_MAX_LATENCY_SAMPLES:]

        return response
