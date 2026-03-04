"""
Standalone Langfuse tools for OpenHands and other agent frameworks.

This module provides Langfuse LLM observability functionality WITHOUT depending
on vibeteam package. It uses requests directly, making it suitable for
containerized deployments where only the agents/ directory is available.

Required environment variables:
- LANGFUSE_PUBLIC_KEY: Langfuse public key
- LANGFUSE_SECRET_KEY: Langfuse secret key
- LANGFUSE_BASE_URL (optional): Base URL for Langfuse API (default: https://langfuse.vibebrowser.app)

Required packages:
- requests
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

# Default Langfuse URL
DEFAULT_LANGFUSE_URL = "https://langfuse.vibebrowser.app"

# Thresholds for anomaly detection
LATENCY_WARNING_MS = 5000  # 5 seconds
LATENCY_CRITICAL_MS = 15000  # 15 seconds
ERROR_RATE_WARNING = 0.05  # 5%
ERROR_RATE_CRITICAL = 0.15  # 15%
TOKEN_BUDGET_WARNING = 0.80  # 80% of budget
TOKEN_BUDGET_CRITICAL = 0.95  # 95% of budget


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


class LangfuseClient:
    """
    Standalone Langfuse API client using requests directly.

    This is a self-contained implementation that doesn't depend on vibeteam.

    Usage:
        client = LangfuseClient()  # Uses env vars

        # Get statistics
        stats = client.get_stats(hours=24)

        # Detect anomalies
        anomalies = client.detect_anomalies(hours=6)
    """

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
    ):
        """
        Initialize Langfuse client.

        Args:
            public_key: Langfuse public key (or from LANGFUSE_PUBLIC_KEY env)
            secret_key: Langfuse secret key (or from LANGFUSE_SECRET_KEY env)
            base_url: Base URL for Langfuse API
        """
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
        self.base_url = (
            base_url
            or os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_URL")
            or DEFAULT_LANGFUSE_URL
        )

        if not self.public_key or not self.secret_key:
            raise ValueError(
                "Langfuse credentials required. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY env vars."
            )

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
        name: str | None = None,
    ) -> list[dict]:
        """Fetch recent traces from Langfuse."""
        params: dict = {
            "limit": limit,
            "orderBy": "timestamp.desc",
        }

        if name:
            params["name"] = name

        # Filter by time
        from_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        params["fromTimestamp"] = from_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        data = self._request("GET", "/traces", params=params)
        return data.get("data", [])

    def get_stats(self, hours: int = 1) -> LangfuseStats:
        """Get aggregated statistics for the specified period."""
        traces = self.get_traces(hours=hours, limit=100)  # API max is 100

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
        anomalies: list[LangfuseAnomaly] = []
        traces = self.get_traces(hours=hours, limit=100)  # API max is 100

        if not traces:
            logger.info("No traces found in the specified period")
            return anomalies

        # Collect metrics
        latencies = []
        errors = []
        total_tokens = 0
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        for trace in traces:
            latency = trace.get("latency", 0) or 0
            latencies.append((trace.get("id", ""), latency))
            total_tokens += (trace.get("usage", {}) or {}).get("totalTokens", 0) or 0

            if trace.get("level") == "ERROR" or trace.get("statusMessage"):
                errors.append(trace.get("id", ""))

        # Check latency anomalies
        high_latency_traces = [(tid, lat) for tid, lat in latencies if lat > LATENCY_WARNING_MS]

        if high_latency_traces:
            critical = [t for t in high_latency_traces if t[1] > LATENCY_CRITICAL_MS]
            avg_high = sum(t[1] for t in high_latency_traces) / len(high_latency_traces)

            anomalies.append(
                LangfuseAnomaly(
                    type="latency",
                    severity="critical" if critical else "warning",
                    message=f"{len(high_latency_traces)} traces with high latency (avg {avg_high:.0f}ms)",
                    value=avg_high,
                    threshold=LATENCY_WARNING_MS,
                    timestamp=now,
                    trace_ids=[t[0] for t in high_latency_traces[:5]],
                )
            )

        # Check error rate
        error_rate = len(errors) / len(traces) if traces else 0

        if error_rate > ERROR_RATE_WARNING:
            anomalies.append(
                LangfuseAnomaly(
                    type="error_rate",
                    severity=("critical" if error_rate > ERROR_RATE_CRITICAL else "warning"),
                    message=f"Error rate {error_rate:.1%} ({len(errors)}/{len(traces)} traces)",
                    value=error_rate,
                    threshold=ERROR_RATE_WARNING,
                    timestamp=now,
                    trace_ids=errors[:5],
                )
            )

        # Check token budget (extrapolate to daily)
        hourly_tokens = total_tokens / hours if hours > 0 else total_tokens
        projected_daily = hourly_tokens * 24
        budget_usage = projected_daily / daily_token_budget if daily_token_budget > 0 else 0

        if budget_usage > TOKEN_BUDGET_WARNING:
            anomalies.append(
                LangfuseAnomaly(
                    type="token_usage",
                    severity=("critical" if budget_usage > TOKEN_BUDGET_CRITICAL else "warning"),
                    message=f"Projected daily token usage: {projected_daily:,.0f} ({budget_usage:.0%} of budget)",
                    value=projected_daily,
                    threshold=daily_token_budget * TOKEN_BUDGET_WARNING,
                    timestamp=now,
                    trace_ids=[],
                )
            )

        return anomalies

    def health_check(self) -> bool:
        """Check if Langfuse is accessible."""
        try:
            resp = requests.get(f"{self.base_url}/api/public/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False


# ==============================================================================
# High-level functions for agents
# ==============================================================================


def _get_langfuse_client() -> LangfuseClient | tuple[None, str]:
    """Get or create Langfuse client."""
    try:
        return LangfuseClient()
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"Langfuse error: {e}"


async def get_langfuse_traces(
    limit: int = 10,
    min_latency_ms: int = 0,
    hours: int = 24,
) -> str:
    """Get recent traces from Langfuse.

    Args:
        limit: Maximum number of traces to return (default: 10)
        min_latency_ms: Filter traces with latency above this threshold (default: 0)
        hours: Time window in hours (default: 24)

    Returns:
        Formatted list of Langfuse traces or error message
    """
    result = _get_langfuse_client()
    if isinstance(result, tuple):
        return f"""
=== Langfuse Traces (last {hours}h) ===
Filter: latency >= {min_latency_ms}ms

Langfuse not configured: {result[1]}

To enable Langfuse:
1. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables
2. Ensure Langfuse server is accessible

For now, please describe the observability data you want to analyze.
"""

    client = result

    try:
        stats = client.get_stats(hours=hours)
        anomalies = client.detect_anomalies(hours=hours)

        output = f"=== Langfuse Stats (last {hours}h) ===\n\n"
        output += f"Total Traces: {stats.total_traces}\n"
        output += f"Total Tokens: {stats.total_tokens:,}\n"
        output += f"Avg Latency: {stats.avg_latency_ms:.0f}ms\n"
        output += f"Error Count: {stats.error_count}\n"
        output += f"Error Rate: {stats.error_rate:.1%}\n"
        output += f"Cost (USD): ${stats.cost_usd:.2f}\n\n"

        if anomalies:
            output += f"=== Anomalies Detected ({len(anomalies)}) ===\n\n"
            for anomaly in anomalies:
                output += f"**[{anomaly.severity.upper()}] {anomaly.type}**\n"
                output += f"  {anomaly.message}\n"
                output += f"  Value: {anomaly.value:.2f} (threshold: {anomaly.threshold:.2f})\n"
                if anomaly.trace_ids:
                    output += f"  Trace IDs: {', '.join(anomaly.trace_ids[:3])}\n"
                output += "\n"
        else:
            output += "No anomalies detected.\n"

        return output

    except Exception as e:
        return f"Error fetching Langfuse traces: {e}"


async def get_langfuse_stats(hours: int = 24) -> str:
    """Get aggregated stats from Langfuse.

    Args:
        hours: Time window in hours (default: 24)

    Returns:
        Formatted statistics or error message
    """
    result = _get_langfuse_client()
    if isinstance(result, tuple):
        return f"Langfuse not configured: {result[1]}"

    client = result

    try:
        stats = client.get_stats(hours=hours)

        return f"""
=== Langfuse Stats (last {hours}h) ===
Total Traces: {stats.total_traces}
Total Tokens: {stats.total_tokens:,}
Average Latency: {stats.avg_latency_ms:.0f}ms
Error Count: {stats.error_count}
Error Rate: {stats.error_rate:.1%}
Estimated Cost: ${stats.cost_usd:.2f}
"""

    except Exception as e:
        return f"Error fetching Langfuse stats: {e}"


async def detect_langfuse_anomalies(hours: int = 24) -> str:
    """Detect anomalies in Langfuse traces.

    Args:
        hours: Time window in hours (default: 24)

    Returns:
        List of detected anomalies or success message
    """
    result = _get_langfuse_client()
    if isinstance(result, tuple):
        return f"Langfuse not configured: {result[1]}"

    client = result

    try:
        anomalies = client.detect_anomalies(hours=hours)

        if not anomalies:
            return f"No anomalies detected in the last {hours} hours."

        output = f"=== Anomalies Detected (last {hours}h) ===\n\n"
        for anomaly in anomalies:
            output += f"**[{anomaly.severity.upper()}] {anomaly.type}**\n"
            output += f"  Message: {anomaly.message}\n"
            output += f"  Value: {anomaly.value:.2f} (threshold: {anomaly.threshold:.2f})\n"
            output += f"  Time: {anomaly.timestamp}\n"
            if anomaly.trace_ids:
                output += f"  Sample traces: {', '.join(anomaly.trace_ids[:5])}\n"
            output += "\n"

        return output

    except Exception as e:
        return f"Error detecting anomalies: {e}"


def get_langfuse_context(hours: int = 6) -> str:
    """Get Langfuse context for agent prompts.

    Provides current observability state as a formatted summary.

    Args:
        hours: Time window in hours

    Returns:
        Formatted context string for agent prompts
    """
    result = _get_langfuse_client()
    if isinstance(result, tuple):
        return f"## LLM Observability Status\n\nLangfuse not configured: {result[1]}"

    client = result

    try:
        stats = client.get_stats(hours=hours)
        anomalies = client.detect_anomalies(hours=hours)

        context = f"## LLM Observability (last {hours}h)\n\n"
        context += f"- **Traces**: {stats.total_traces}\n"
        context += f"- **Tokens**: {stats.total_tokens:,}\n"
        context += f"- **Avg Latency**: {stats.avg_latency_ms:.0f}ms\n"
        context += f"- **Error Rate**: {stats.error_rate:.1%}\n"
        context += f"- **Cost**: ${stats.cost_usd:.2f}\n\n"

        if anomalies:
            context += f"### Anomalies ({len(anomalies)})\n\n"
            for anomaly in anomalies:
                context += f"- **[{anomaly.severity}]** {anomaly.type}: {anomaly.message}\n"
        else:
            context += "No anomalies detected.\n"

        return context

    except Exception as e:
        return f"## LLM Observability Status\n\nError loading Langfuse data: {e}"
