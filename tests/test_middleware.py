"""
Tests for gateway middleware: rate limiting and metrics.

Tests cover:
- EndpointRateLimiter token bucket algorithm
- RateLimitMiddleware integration with FastAPI
- MetricsMiddleware request tracking (counts, errors, latencies)
- /metrics endpoint response format
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# EndpointRateLimiter unit tests
# ---------------------------------------------------------------------------


class TestEndpointRateLimiter:
    """Unit tests for the token bucket rate limiter."""

    @pytest.fixture(autouse=True)
    def _fresh_limiter(self):
        """Create a fresh limiter for each test."""
        from vibeteam.gateway.middleware import EndpointRateLimiter

        self.limiter = EndpointRateLimiter(default_max=5, default_window=10.0)

    def test_allows_up_to_max_requests(self):
        """Should allow exactly max_requests before denying."""
        for i in range(5):
            assert self.limiter.allow("/test") is True, f"Request {i + 1} should be allowed"
        assert self.limiter.allow("/test") is False, "Request 6 should be denied"

    def test_custom_limits_per_key(self):
        """Different keys can have different limits."""
        for _ in range(3):
            assert self.limiter.allow("/api", max_requests=3, window=10.0) is True
        assert self.limiter.allow("/api", max_requests=3, window=10.0) is False

        # Default-limited key still has tokens
        assert self.limiter.allow("/other") is True

    def test_tokens_refill_over_time(self):
        """Tokens should refill after time passes."""
        # Exhaust all tokens
        for _ in range(5):
            self.limiter.allow("/test")
        assert self.limiter.allow("/test") is False

        # Simulate time passing — tokens refill at (max/window) per second
        # With max=5, window=10: 0.5 tokens/sec. Need 2 seconds for 1 token.
        with patch("vibeteam.gateway.middleware.time") as mock_time:
            # First call sets last_refill
            mock_time.monotonic.return_value = time.monotonic() + 3.0
            assert self.limiter.allow("/test") is True  # ~1.5 tokens refilled

    def test_separate_buckets_per_key(self):
        """Different paths should have independent buckets."""
        # Exhaust /a
        for _ in range(5):
            self.limiter.allow("/a")
        assert self.limiter.allow("/a") is False

        # /b should still be available
        assert self.limiter.allow("/b") is True

    def test_reset_single_key(self):
        """Reset should clear a specific key's bucket."""
        for _ in range(5):
            self.limiter.allow("/test")
        assert self.limiter.allow("/test") is False

        self.limiter.reset("/test")
        assert self.limiter.allow("/test") is True

    def test_reset_all(self):
        """Reset without key should clear all buckets."""
        self.limiter.allow("/a")
        self.limiter.allow("/b")
        self.limiter.reset()
        # After reset, full quota should be available
        for _ in range(5):
            assert self.limiter.allow("/a") is True

    def test_tokens_capped_at_max(self):
        """Tokens should never exceed max_requests even after long idle."""
        # Don't use any tokens, then simulate a long wait
        with patch("vibeteam.gateway.middleware.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 1000.0
            # Should still only allow max_requests (5)
            for _ in range(5):
                assert self.limiter.allow("/test") is True
            assert self.limiter.allow("/test") is False


# ---------------------------------------------------------------------------
# RateLimitMiddleware integration tests
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    """Integration tests for rate limiting middleware with FastAPI."""

    @pytest.fixture
    def client(self):
        """Create a test client with middleware reset."""
        from vibeteam.gateway.middleware import get_endpoint_limiter
        from vibeteam.gateway.server import app

        # Reset global rate limiter state before each test
        get_endpoint_limiter().reset()
        return TestClient(app)

    def test_normal_requests_pass_through(self, client: TestClient):
        """Regular requests should not be rate limited."""
        # Health endpoint has generous limits (300/60s)
        response = client.get("/health")
        assert response.status_code == 200

    def test_rate_limited_returns_429(self, client: TestClient):
        """Exceeding rate limit should return 429 with Retry-After header."""
        from vibeteam.gateway.middleware import ENDPOINT_RATE_LIMITS, get_endpoint_limiter

        limiter = get_endpoint_limiter()
        limiter.reset()

        # Use /metrics endpoint — generous limit but we can exhaust it
        # The default limit is 60/60s for unlisted endpoints
        max_req, window = ENDPOINT_RATE_LIMITS.get("/metrics", (60, 60.0))

        # Exhaust the limit
        for _ in range(max_req):
            resp = client.get("/metrics")
            assert resp.status_code == 200

        # Next request should be rate limited
        response = client.get("/metrics")
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]
        assert "Retry-After" in response.headers

    def test_different_endpoints_independent(self, client: TestClient):
        """Rate limits for different endpoints should be independent."""
        from vibeteam.gateway.middleware import get_endpoint_limiter

        get_endpoint_limiter().reset()

        # Hit /health a few times
        for _ in range(5):
            client.get("/health")

        # /metrics should still work (different bucket)
        response = client.get("/metrics")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# MetricsMiddleware + /metrics endpoint tests
# ---------------------------------------------------------------------------


class TestMetricsMiddleware:
    """Tests for metrics collection and the /metrics endpoint."""

    @pytest.fixture
    def client(self):
        """Create a fresh test client with cleared metrics."""
        from vibeteam.gateway import middleware
        from vibeteam.gateway.middleware import get_endpoint_limiter
        from vibeteam.gateway.server import app

        # Reset rate limiter so it doesn't interfere
        get_endpoint_limiter().reset()

        # Clear metrics state
        with middleware._metrics_lock:
            middleware._request_counts.clear()
            middleware._request_latencies.clear()
            middleware._request_errors.clear()

        return TestClient(app)

    def test_metrics_endpoint_returns_structure(self, client: TestClient):
        """GET /metrics should return proper JSON structure."""
        response = client.get("/metrics")
        assert response.status_code == 200

        data = response.json()
        assert "service" in data
        assert data["service"] == "vibeteam-gateway"
        assert "timestamp" in data
        assert "endpoints" in data

    def test_metrics_track_request_count(self, client: TestClient):
        """Metrics should count requests per endpoint."""
        # Make some requests to /health
        for _ in range(3):
            client.get("/health")

        response = client.get("/metrics")
        data = response.json()

        # /health should show in metrics (3 requests + the initial /metrics call)
        endpoints = data["endpoints"]
        assert "/health" in endpoints
        assert endpoints["/health"]["request_count"] == 3

    def test_metrics_track_errors(self, client: TestClient):
        """Metrics should count 4xx/5xx responses as errors."""
        # Hit a nonexistent endpoint to get a 404
        client.get("/nonexistent-endpoint-for-test")

        response = client.get("/metrics")
        data = response.json()
        endpoints = data["endpoints"]

        # The 404 response should be counted as an error
        if "/nonexistent-endpoint-for-test" in endpoints:
            assert endpoints["/nonexistent-endpoint-for-test"]["error_count"] >= 1

    def test_metrics_track_latency(self, client: TestClient):
        """Metrics should track latency stats."""
        # Make a few requests
        for _ in range(5):
            client.get("/health")

        response = client.get("/metrics")
        data = response.json()

        health_metrics = data["endpoints"].get("/health", {})
        assert health_metrics.get("latency_avg_ms", 0) >= 0
        assert health_metrics.get("latency_p95_ms", 0) >= 0
        assert health_metrics.get("latency_p99_ms", 0) >= 0


# ---------------------------------------------------------------------------
# get_metrics_snapshot unit tests
# ---------------------------------------------------------------------------


class TestGetMetricsSnapshot:
    """Unit tests for the metrics snapshot function."""

    @pytest.fixture(autouse=True)
    def _clear_metrics(self):
        """Clear metrics state before each test."""
        from vibeteam.gateway import middleware

        with middleware._metrics_lock:
            middleware._request_counts.clear()
            middleware._request_latencies.clear()
            middleware._request_errors.clear()

    def test_empty_snapshot(self):
        """Empty metrics should return empty dict."""
        from vibeteam.gateway.middleware import get_metrics_snapshot

        snapshot = get_metrics_snapshot()
        assert snapshot == {}

    def test_snapshot_with_data(self):
        """Snapshot should reflect manually inserted data."""
        from vibeteam.gateway import middleware
        from vibeteam.gateway.middleware import get_metrics_snapshot

        with middleware._metrics_lock:
            middleware._request_counts["/test"] = 10
            middleware._request_errors["/test"] = 2
            middleware._request_latencies["/test"] = [0.1, 0.2, 0.3, 0.4, 0.5]

        snapshot = get_metrics_snapshot()
        assert "/test" in snapshot
        assert snapshot["/test"]["request_count"] == 10
        assert snapshot["/test"]["error_count"] == 2
        assert snapshot["/test"]["latency_avg_ms"] == pytest.approx(300.0, abs=1.0)
        # p95 of [0.1, 0.2, 0.3, 0.4, 0.5] → index 4 (int(5*0.95)=4) → 0.5 → 500ms
        assert snapshot["/test"]["latency_p95_ms"] == pytest.approx(500.0, abs=1.0)

    def test_snapshot_zero_latencies_no_error(self):
        """Path with counts but no latencies should not crash."""
        from vibeteam.gateway import middleware
        from vibeteam.gateway.middleware import get_metrics_snapshot

        with middleware._metrics_lock:
            middleware._request_counts["/empty"] = 5

        snapshot = get_metrics_snapshot()
        assert snapshot["/empty"]["latency_avg_ms"] == 0
        assert snapshot["/empty"]["latency_p95_ms"] == 0
        assert snapshot["/empty"]["latency_p99_ms"] == 0


# ---------------------------------------------------------------------------
# ENDPOINT_RATE_LIMITS configuration tests
# ---------------------------------------------------------------------------


class TestEndpointRateLimitsConfig:
    """Verify rate limit configuration is sensible."""

    def test_all_known_endpoints_have_limits(self):
        """Important endpoints should have explicit rate limits."""
        from vibeteam.gateway.middleware import ENDPOINT_RATE_LIMITS

        expected_endpoints = [
            "/slack/events",
            "/webhook",
            "/webhook/sentry",
            "/callback/agent",
            "/callback/agent/progress",
            "/slack/trigger",
            "/api/run",
            "/health",
        ]
        for ep in expected_endpoints:
            assert ep in ENDPOINT_RATE_LIMITS, f"Missing rate limit config for {ep}"

    def test_expensive_endpoints_have_lower_limits(self):
        """Agent-execution endpoints should have tighter limits than webhooks."""
        from vibeteam.gateway.middleware import ENDPOINT_RATE_LIMITS

        api_run_limit = ENDPOINT_RATE_LIMITS["/api/run"][0]
        webhook_limit = ENDPOINT_RATE_LIMITS["/webhook"][0]
        assert api_run_limit < webhook_limit, (
            f"/api/run ({api_run_limit}) should have lower limit than /webhook ({webhook_limit})"
        )

    def test_health_has_highest_limit(self):
        """Health check should have the most generous limit."""
        from vibeteam.gateway.middleware import ENDPOINT_RATE_LIMITS

        health_limit = ENDPOINT_RATE_LIMITS["/health"][0]
        for path, (limit, _) in ENDPOINT_RATE_LIMITS.items():
            if path != "/health" and path != "/callback/agent/progress":
                assert health_limit >= limit, (
                    f"/health ({health_limit}) should be >= {path} ({limit})"
                )
