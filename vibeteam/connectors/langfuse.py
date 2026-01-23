"""
Langfuse Connector - LLM observability and anomaly detection.

Monitors:
- Trace latency (flag if > threshold)
- Error rates
- Token usage vs budget
- Model distribution
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class LangfuseAnomaly:
    """Represents a detected anomaly in Langfuse traces."""

    type: str  # latency, error_rate, token_usage, model_error
    severity: str  # warning, critical
    message: str
    value: float
    threshold: float
    timestamp: str
    trace_ids: list[str]


@dataclass
class LangfuseStats:
    """Aggregated stats from Langfuse."""

    total_traces: int
    total_tokens: int
    avg_latency_ms: float
    error_count: int
    error_rate: float
    cost_usd: float
    period_hours: int


class LangfuseConnector:
    """
    Connector for Langfuse LLM observability platform.

    Provides:
    - Trace statistics
    - Anomaly detection
    - Cost tracking
    """

    # Thresholds for anomaly detection
    LATENCY_WARNING_MS = 5000  # 5 seconds
    LATENCY_CRITICAL_MS = 15000  # 15 seconds
    ERROR_RATE_WARNING = 0.05  # 5%
    ERROR_RATE_CRITICAL = 0.15  # 15%
    TOKEN_BUDGET_WARNING = 0.80  # 80% of budget
    TOKEN_BUDGET_CRITICAL = 0.95  # 95% of budget

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
        self.base_url = (
            base_url
            or os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_URL")
            or "https://langfuse.vibebrowser.app"
        )

        if not self.public_key or not self.secret_key:
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY required")

        # Remove trailing slash
        self.base_url = self.base_url.rstrip("/")

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make authenticated request to Langfuse API."""
        url = f"{self.base_url}/api/public{endpoint}"

        if not self.public_key or not self.secret_key:
            raise ValueError("Langfuse credentials not configured")

        auth: tuple[str, str] = (self.public_key, self.secret_key)

        try:
            resp = requests.request(method, url, auth=auth, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Langfuse API error: {e}")
            raise

    def get_traces(
        self,
        hours: int = 1,
        limit: int = 100,
        name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch recent traces from Langfuse."""
        params = {
            "limit": limit,
            "orderBy": "timestamp.desc",
        }

        if name:
            params["name"] = name

        # Filter by time
        from_time = datetime.utcnow() - timedelta(hours=hours)
        params["fromTimestamp"] = from_time.isoformat() + "Z"

        data = self._request("GET", "/traces", params=params)
        return data.get("data", [])

    def get_stats(self, hours: int = 1) -> LangfuseStats:
        """Get aggregated statistics for the specified period."""
        traces = self.get_traces(hours=hours, limit=500)

        if not traces:
            return LangfuseStats(
                total_traces=0,
                total_tokens=0,
                avg_latency_ms=0,
                error_count=0,
                error_rate=0,
                cost_usd=0,
                period_hours=hours,
            )

        total_traces = len(traces)
        total_tokens = 0
        total_latency = 0
        error_count = 0
        total_cost = 0

        for trace in traces:
            # Token usage
            usage = trace.get("usage", {}) or {}
            total_tokens += usage.get("totalTokens", 0) or 0

            # Latency (endTime - startTime)
            if trace.get("latency"):
                total_latency += trace["latency"]

            # Errors
            if trace.get("level") == "ERROR" or trace.get("statusMessage"):
                error_count += 1

            # Cost
            total_cost += trace.get("calculatedTotalCost", 0) or 0

        avg_latency = total_latency / total_traces if total_traces > 0 else 0
        error_rate = error_count / total_traces if total_traces > 0 else 0

        return LangfuseStats(
            total_traces=total_traces,
            total_tokens=total_tokens,
            avg_latency_ms=avg_latency,
            error_count=error_count,
            error_rate=error_rate,
            cost_usd=total_cost,
            period_hours=hours,
        )

    def detect_anomalies(
        self,
        hours: int = 1,
        daily_token_budget: int = 1_000_000,
    ) -> list[LangfuseAnomaly]:
        """
        Detect anomalies in Langfuse traces.

        Checks:
        - High latency traces
        - Error rate spikes
        - Token budget usage
        """
        anomalies = []
        traces = self.get_traces(hours=hours, limit=500)

        if not traces:
            logger.info("No traces found in the specified period")
            return anomalies

        # Collect metrics
        latencies = []
        errors = []
        total_tokens = 0
        now = datetime.utcnow().isoformat() + "Z"

        for trace in traces:
            latency = trace.get("latency", 0) or 0
            latencies.append((trace.get("id", ""), latency))
            total_tokens += (trace.get("usage", {}) or {}).get("totalTokens", 0) or 0

            if trace.get("level") == "ERROR" or trace.get("statusMessage"):
                errors.append(trace.get("id", ""))

        # Check latency anomalies
        high_latency_traces = [
            (tid, lat) for tid, lat in latencies if lat > self.LATENCY_WARNING_MS
        ]

        if high_latency_traces:
            critical = [t for t in high_latency_traces if t[1] > self.LATENCY_CRITICAL_MS]
            avg_high = sum(t[1] for t in high_latency_traces) / len(high_latency_traces)

            anomalies.append(
                LangfuseAnomaly(
                    type="latency",
                    severity="critical" if critical else "warning",
                    message=f"{len(high_latency_traces)} traces with high latency (avg {avg_high:.0f}ms)",
                    value=avg_high,
                    threshold=self.LATENCY_WARNING_MS,
                    timestamp=now,
                    trace_ids=[t[0] for t in high_latency_traces[:5]],
                )
            )

        # Check error rate
        error_rate = len(errors) / len(traces) if traces else 0

        if error_rate > self.ERROR_RATE_WARNING:
            anomalies.append(
                LangfuseAnomaly(
                    type="error_rate",
                    severity="critical" if error_rate > self.ERROR_RATE_CRITICAL else "warning",
                    message=f"Error rate {error_rate:.1%} ({len(errors)}/{len(traces)} traces)",
                    value=error_rate,
                    threshold=self.ERROR_RATE_WARNING,
                    timestamp=now,
                    trace_ids=errors[:5],
                )
            )

        # Check token budget (extrapolate to daily)
        hourly_tokens = total_tokens / hours if hours > 0 else total_tokens
        projected_daily = hourly_tokens * 24
        budget_usage = projected_daily / daily_token_budget if daily_token_budget > 0 else 0

        if budget_usage > self.TOKEN_BUDGET_WARNING:
            anomalies.append(
                LangfuseAnomaly(
                    type="token_usage",
                    severity="critical" if budget_usage > self.TOKEN_BUDGET_CRITICAL else "warning",
                    message=f"Projected daily token usage: {projected_daily:,.0f} ({budget_usage:.0%} of budget)",
                    value=projected_daily,
                    threshold=daily_token_budget * self.TOKEN_BUDGET_WARNING,
                    timestamp=now,
                    trace_ids=[],
                )
            )

        return anomalies

    def get_daily_summary(self) -> dict:
        """Get daily summary for reporting."""
        stats = self.get_stats(hours=24)
        anomalies = self.detect_anomalies(hours=24)

        return {
            "period": "24h",
            "stats": {
                "traces": stats.total_traces,
                "tokens": stats.total_tokens,
                "avg_latency_ms": round(stats.avg_latency_ms, 2),
                "error_rate": round(stats.error_rate, 4),
                "cost_usd": round(stats.cost_usd, 4),
            },
            "anomalies": [
                {
                    "type": a.type,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in anomalies
            ],
            "health": "degraded" if anomalies else "healthy",
        }

    def health_check(self) -> bool:
        """Check if Langfuse is accessible."""
        try:
            resp = requests.get(f"{self.base_url}/api/public/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
