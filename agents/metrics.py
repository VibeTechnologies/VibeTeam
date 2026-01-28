"""
Metrics collection and reporting for multi-framework agent evaluation.

This module provides standardized metrics collection across OpenHands, CrewAI,
and AutoGen frameworks to enable fair comparison of agent performance.
"""

import json
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Thread-local storage for metrics context
_local = threading.local()


@dataclass
class TaskMetrics:
    """Metrics for a single task execution.

    Captures all relevant performance data for framework comparison:
    - Timing (latency)
    - Token usage (cost proxy)
    - Success/failure
    - Tool usage patterns
    - Error tracking
    """

    task_id: str
    framework: str  # "openhands" | "crewai" | "autogen"
    agent: str  # "release_engineer" | "marketing_manager" | "support_engineer"
    success: bool = False
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Additional context
    task_category: str = ""  # "unit" | "integration" | "stress"
    task_description: str = ""
    response_preview: str = ""  # First 200 chars of response

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskMetrics":
        """Create from dictionary."""
        data = data.copy()
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens


class MetricsCollector:
    """Collects and stores metrics across multiple task executions.

    Thread-safe collector that can be used across concurrent agent runs.
    Supports exporting to JSON and computing aggregate statistics.
    """

    def __init__(self, storage_path: str | Path | None = None):
        self._metrics: list[TaskMetrics] = []
        self._lock = threading.Lock()
        self.storage_path = Path(storage_path) if storage_path else Path(".metrics")
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def record(self, metrics: TaskMetrics) -> None:
        """Record a completed task's metrics."""
        with self._lock:
            self._metrics.append(metrics)

    def get_all(self) -> list[TaskMetrics]:
        """Get all recorded metrics."""
        with self._lock:
            return list(self._metrics)

    def get_by_framework(self, framework: str) -> list[TaskMetrics]:
        """Get metrics for a specific framework."""
        with self._lock:
            return [m for m in self._metrics if m.framework == framework]

    def get_by_agent(self, agent: str) -> list[TaskMetrics]:
        """Get metrics for a specific agent role."""
        with self._lock:
            return [m for m in self._metrics if m.agent == agent]

    def get_by_task_category(self, category: str) -> list[TaskMetrics]:
        """Get metrics for a specific task category."""
        with self._lock:
            return [m for m in self._metrics if m.task_category == category]

    def clear(self) -> None:
        """Clear all recorded metrics."""
        with self._lock:
            self._metrics.clear()

    def export_json(self, filepath: str | Path | None = None) -> str:
        """Export all metrics to JSON file.

        Returns the filepath where metrics were saved.
        """
        if filepath is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filepath = self.storage_path / f"metrics_{timestamp}.json"
        else:
            filepath = Path(filepath)

        with self._lock:
            data = {
                "exported_at": datetime.utcnow().isoformat(),
                "total_tasks": len(self._metrics),
                "metrics": [m.to_dict() for m in self._metrics],
            }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        return str(filepath)

    def import_json(self, filepath: str | Path) -> int:
        """Import metrics from JSON file.

        Returns number of metrics imported.
        """
        with open(filepath) as f:
            data = json.load(f)

        metrics_data = data.get("metrics", [])
        imported = [TaskMetrics.from_dict(m) for m in metrics_data]

        with self._lock:
            self._metrics.extend(imported)

        return len(imported)

    def compute_statistics(self) -> dict[str, Any]:
        """Compute aggregate statistics across all metrics.

        Returns statistics grouped by framework and agent.
        """
        with self._lock:
            metrics = list(self._metrics)

        if not metrics:
            return {"error": "No metrics recorded"}

        # Overall stats
        total = len(metrics)
        successes = sum(1 for m in metrics if m.success)

        stats = {
            "overall": {
                "total_tasks": total,
                "success_rate": successes / total if total > 0 else 0,
                "avg_latency_ms": sum(m.latency_ms for m in metrics) / total,
                "avg_tokens": sum(m.total_tokens for m in metrics) / total,
                "avg_tool_calls": sum(m.tool_calls for m in metrics) / total,
                "total_errors": sum(len(m.errors) for m in metrics),
            },
            "by_framework": {},
            "by_agent": {},
            "by_category": {},
        }

        # Stats by framework
        for framework in ["openhands", "crewai", "autogen"]:
            fw_metrics = [m for m in metrics if m.framework == framework]
            if fw_metrics:
                fw_total = len(fw_metrics)
                fw_successes = sum(1 for m in fw_metrics if m.success)
                stats["by_framework"][framework] = {
                    "total_tasks": fw_total,
                    "success_rate": fw_successes / fw_total,
                    "avg_latency_ms": sum(m.latency_ms for m in fw_metrics) / fw_total,
                    "avg_tokens": sum(m.total_tokens for m in fw_metrics) / fw_total,
                    "avg_tool_calls": sum(m.tool_calls for m in fw_metrics) / fw_total,
                    "p95_latency_ms": _percentile(
                        [m.latency_ms for m in fw_metrics], 95
                    ),
                }

        # Stats by agent
        for agent in ["release_engineer", "marketing_manager", "support_engineer"]:
            agent_metrics = [m for m in metrics if m.agent == agent]
            if agent_metrics:
                agent_total = len(agent_metrics)
                agent_successes = sum(1 for m in agent_metrics if m.success)
                stats["by_agent"][agent] = {
                    "total_tasks": agent_total,
                    "success_rate": agent_successes / agent_total,
                    "avg_latency_ms": sum(m.latency_ms for m in agent_metrics)
                    / agent_total,
                }

        # Stats by category
        for category in ["unit", "integration", "stress"]:
            cat_metrics = [m for m in metrics if m.task_category == category]
            if cat_metrics:
                cat_total = len(cat_metrics)
                cat_successes = sum(1 for m in cat_metrics if m.success)
                stats["by_category"][category] = {
                    "total_tasks": cat_total,
                    "success_rate": cat_successes / cat_total,
                    "avg_latency_ms": sum(m.latency_ms for m in cat_metrics)
                    / cat_total,
                }

        return stats

    def generate_report(self) -> str:
        """Generate a human-readable report of metrics."""
        stats = self.compute_statistics()

        if "error" in stats:
            return f"No metrics to report: {stats['error']}"

        lines = [
            "=" * 60,
            "MULTI-FRAMEWORK AGENT EVALUATION REPORT",
            "=" * 60,
            "",
            "OVERALL STATISTICS",
            "-" * 40,
            f"Total tasks:      {stats['overall']['total_tasks']}",
            f"Success rate:     {stats['overall']['success_rate']:.1%}",
            f"Avg latency:      {stats['overall']['avg_latency_ms']:.0f}ms",
            f"Avg tokens:       {stats['overall']['avg_tokens']:.0f}",
            f"Avg tool calls:   {stats['overall']['avg_tool_calls']:.1f}",
            f"Total errors:     {stats['overall']['total_errors']}",
            "",
            "BY FRAMEWORK",
            "-" * 40,
        ]

        for fw, fw_stats in stats["by_framework"].items():
            lines.extend(
                [
                    f"\n{fw.upper()}:",
                    f"  Tasks:          {fw_stats['total_tasks']}",
                    f"  Success rate:   {fw_stats['success_rate']:.1%}",
                    f"  Avg latency:    {fw_stats['avg_latency_ms']:.0f}ms",
                    f"  P95 latency:    {fw_stats['p95_latency_ms']:.0f}ms",
                    f"  Avg tokens:     {fw_stats['avg_tokens']:.0f}",
                ]
            )

        lines.extend(
            [
                "",
                "BY AGENT",
                "-" * 40,
            ]
        )

        for agent, agent_stats in stats["by_agent"].items():
            lines.extend(
                [
                    f"\n{agent}:",
                    f"  Tasks:          {agent_stats['total_tasks']}",
                    f"  Success rate:   {agent_stats['success_rate']:.1%}",
                    f"  Avg latency:    {agent_stats['avg_latency_ms']:.0f}ms",
                ]
            )

        if stats["by_category"]:
            lines.extend(
                [
                    "",
                    "BY TASK CATEGORY",
                    "-" * 40,
                ]
            )

            for cat, cat_stats in stats["by_category"].items():
                lines.extend(
                    [
                        f"\n{cat.upper()}:",
                        f"  Tasks:          {cat_stats['total_tasks']}",
                        f"  Success rate:   {cat_stats['success_rate']:.1%}",
                        f"  Avg latency:    {cat_stats['avg_latency_ms']:.0f}ms",
                    ]
                )

        lines.extend(
            [
                "",
                "=" * 60,
            ]
        )

        return "\n".join(lines)


def _percentile(values: list[int | float], p: int) -> float:
    """Calculate percentile of a list of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


# Global collector instance
_global_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_collector(storage_path: str | Path | None = None) -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _global_collector
    with _collector_lock:
        if _global_collector is None:
            _global_collector = MetricsCollector(storage_path)
        return _global_collector


def reset_collector(storage_path: str | Path | None = None) -> MetricsCollector:
    """Reset and return a fresh metrics collector."""
    global _global_collector
    with _collector_lock:
        _global_collector = MetricsCollector(storage_path)
        return _global_collector


class MetricsContext:
    """Context manager for collecting metrics on a task execution.

    Usage:
        with MetricsContext("U1", "autogen", "release_engineer") as ctx:
            result = agent.run(task)
            ctx.set_success(True)
            ctx.set_tokens(result.input_tokens, result.output_tokens)
    """

    def __init__(
        self,
        task_id: str,
        framework: str,
        agent: str,
        task_category: str = "",
        task_description: str = "",
        collector: MetricsCollector | None = None,
    ):
        self.task_id = task_id
        self.framework = framework
        self.agent = agent
        self.task_category = task_category
        self.task_description = task_description
        self.collector = collector or get_collector()

        self._start_time: float = 0
        self._success = False
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_calls = 0
        self._errors: list[str] = []
        self._response_preview = ""

    def __enter__(self) -> "MetricsContext":
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        latency_ms = int((time.perf_counter() - self._start_time) * 1000)

        if exc_type is not None:
            self._success = False
            self._errors.append(f"{exc_type.__name__}: {exc_val}")

        metrics = TaskMetrics(
            task_id=self.task_id,
            framework=self.framework,
            agent=self.agent,
            success=self._success,
            latency_ms=latency_ms,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            tool_calls=self._tool_calls,
            errors=self._errors,
            task_category=self.task_category,
            task_description=self.task_description,
            response_preview=self._response_preview,
        )

        self.collector.record(metrics)

    def set_success(self, success: bool) -> None:
        """Mark task as successful or failed."""
        self._success = success

    def set_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Set token counts."""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Add to token counts (for multi-turn)."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def set_tool_calls(self, count: int) -> None:
        """Set tool call count."""
        self._tool_calls = count

    def increment_tool_calls(self, count: int = 1) -> None:
        """Increment tool call count."""
        self._tool_calls += count

    def add_error(self, error: str) -> None:
        """Record an error."""
        self._errors.append(error)

    def set_response_preview(self, response: str, max_length: int = 200) -> None:
        """Set response preview (truncated)."""
        self._response_preview = response[:max_length] if response else ""


@contextmanager
def track_task(
    task_id: str,
    framework: str,
    agent: str,
    task_category: str = "",
    task_description: str = "",
):
    """Convenience context manager for tracking task metrics.

    Usage:
        with track_task("U1", "autogen", "release_engineer") as ctx:
            result = agent.run(task)
            ctx.set_success(True)
    """
    ctx = MetricsContext(
        task_id=task_id,
        framework=framework,
        agent=agent,
        task_category=task_category,
        task_description=task_description,
    )
    with ctx:
        yield ctx


def timed_execution(
    task_id: str,
    framework: str,
    agent: str,
    task_category: str = "",
) -> Callable:
    """Decorator for automatically tracking task execution metrics.

    Usage:
        @timed_execution("U1", "autogen", "release_engineer", "unit")
        async def test_list_files():
            result = await agent.run_async("List files in /tmp")
            return result
    """

    def decorator(func: Callable) -> Callable:
        import asyncio
        import functools

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with MetricsContext(
                task_id=task_id,
                framework=framework,
                agent=agent,
                task_category=task_category,
                task_description=func.__doc__ or func.__name__,
            ) as ctx:
                try:
                    result = func(*args, **kwargs)
                    ctx.set_success(True)
                    return result
                except Exception as e:
                    ctx.add_error(str(e))
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with MetricsContext(
                task_id=task_id,
                framework=framework,
                agent=agent,
                task_category=task_category,
                task_description=func.__doc__ or func.__name__,
            ) as ctx:
                try:
                    result = await func(*args, **kwargs)
                    ctx.set_success(True)
                    return result
                except Exception as e:
                    ctx.add_error(str(e))
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent Metrics Manager")
    parser.add_argument("--export", type=str, help="Export metrics to JSON file")
    parser.add_argument("--import-file", type=str, help="Import metrics from JSON file")
    parser.add_argument(
        "--report", action="store_true", help="Generate and print report"
    )
    parser.add_argument("--stats", action="store_true", help="Print statistics as JSON")

    args = parser.parse_args()

    collector = get_collector()

    if args.import_file:
        count = collector.import_json(args.import_file)
        print(f"Imported {count} metrics from {args.import_file}")

    if args.export:
        filepath = collector.export_json(args.export)
        print(f"Exported metrics to {filepath}")

    if args.report:
        print(collector.generate_report())

    if args.stats:
        print(json.dumps(collector.compute_statistics(), indent=2))
