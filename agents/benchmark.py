"""
Agent Benchmarking System.

Provides comprehensive evaluation of agent performance across frameworks with:
- Speed metrics (latency, time-to-first-token)
- Quality scoring (LLM-as-judge)
- Tool usage tracking (count, accuracy, efficiency)
- Cost estimation (tokens, API calls)

Usage:
    from agents.benchmark import Benchmark, BenchmarkTask

    # Define tasks
    tasks = [
        BenchmarkTask(
            task_id="sentry-summary",
            prompt="Provide a summary of Sentry issues for this week",
            expected_behavior="Should list issues, count them, identify patterns",
            evaluation_criteria=["accuracy", "completeness", "actionability"],
        ),
    ]

    # Run benchmark
    benchmark = Benchmark(frameworks=["autogen", "crewai", "openhands"])
    results = await benchmark.run(tasks)
    report = benchmark.generate_report(results)
"""

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx


# ==============================================================================
# Configuration
# ==============================================================================


class BenchmarkConfig:
    """Benchmark configuration from environment."""

    GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
    AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
    AZURE_API_BASE = os.getenv("AZURE_API_BASE", "")
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-08-01-preview")
    JUDGE_MODEL = os.getenv("BENCHMARK_JUDGE_MODEL", "gpt-5-2")
    REQUEST_TIMEOUT = float(os.getenv("BENCHMARK_TIMEOUT", "180"))
    OUTPUT_DIR = Path(os.getenv("BENCHMARK_OUTPUT_DIR", ".benchmarks"))


# ==============================================================================
# Data Models
# ==============================================================================


class QualityDimension(str, Enum):
    """Quality dimensions for LLM-as-judge evaluation."""

    ACCURACY = "accuracy"  # Factual correctness
    COMPLETENESS = "completeness"  # Addresses all parts of the task
    ACTIONABILITY = "actionability"  # Provides concrete next steps
    CLARITY = "clarity"  # Well-organized, easy to understand
    RELEVANCE = "relevance"  # Stays on topic, no hallucination
    EFFICIENCY = "efficiency"  # Concise, not verbose


@dataclass
class BenchmarkTask:
    """A task to benchmark agents against."""

    task_id: str
    prompt: str
    expected_behavior: str = ""
    evaluation_criteria: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)  # Tools that should be called
    role: str = "support_engineer"
    context_type: str = "benchmark"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolUsageMetrics:
    """Metrics about tool usage during task execution."""

    tools_called: list[str] = field(default_factory=list)
    tool_call_count: int = 0
    expected_tools_hit: int = 0  # How many expected tools were actually called
    unexpected_tools: list[str] = field(default_factory=list)
    tool_call_sequence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tool_accuracy(self) -> float:
        """Precision of tool calls vs expected tools."""
        if not self.tool_call_count:
            return 0.0
        return self.expected_tools_hit / self.tool_call_count

    @property
    def tool_recall(self) -> float:
        """Recall of expected tools that were called."""
        # This would need expected_tools count passed in
        return 0.0  # Placeholder

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools_called": self.tools_called,
            "tool_call_count": self.tool_call_count,
            "expected_tools_hit": self.expected_tools_hit,
            "unexpected_tools": self.unexpected_tools,
            "tool_accuracy": self.tool_accuracy,
        }


@dataclass
class QualityScores:
    """Quality scores from LLM-as-judge evaluation."""

    accuracy: float = 0.0
    completeness: float = 0.0
    actionability: float = 0.0
    clarity: float = 0.0
    relevance: float = 0.0
    efficiency: float = 0.0
    overall: float = 0.0
    judge_reasoning: str = ""
    judge_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def average(self) -> float:
        """Average of all dimension scores."""
        scores = [
            self.accuracy,
            self.completeness,
            self.actionability,
            self.clarity,
            self.relevance,
            self.efficiency,
        ]
        non_zero = [s for s in scores if s > 0]
        return sum(non_zero) / len(non_zero) if non_zero else 0.0


@dataclass
class BenchmarkResult:
    """Complete result from a single benchmark run."""

    # Identification
    task_id: str
    framework: str
    role: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Response
    response: str = ""
    session_id: str = ""
    success: bool = False
    error: str | None = None

    # Speed metrics
    latency_ms: int = 0
    time_to_first_token_ms: int | None = None  # For streaming

    # Token usage (cost proxy)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Tool usage
    tool_usage: ToolUsageMetrics = field(default_factory=ToolUsageMetrics)

    # Quality scores (from LLM-as-judge)
    quality: QualityScores = field(default_factory=QualityScores)

    # Validation
    validation_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "framework": self.framework,
            "role": self.role,
            "timestamp": self.timestamp.isoformat(),
            "response": self.response,
            "session_id": self.session_id,
            "success": self.success,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "time_to_first_token_ms": self.time_to_first_token_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "tool_usage": self.tool_usage.to_dict(),
            "quality": self.quality.to_dict(),
            "validation_notes": self.validation_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkResult":
        """Reconstruct from dictionary."""
        data = data.copy()
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if isinstance(data.get("tool_usage"), dict):
            # Remove computed properties before reconstruction
            tool_data = {
                k: v
                for k, v in data["tool_usage"].items()
                if k not in ("tool_accuracy", "tool_recall")
            }
            data["tool_usage"] = ToolUsageMetrics(**tool_data)
        if isinstance(data.get("quality"), dict):
            data["quality"] = QualityScores(**data["quality"])
        return cls(**data)

    @property
    def composite_score(self) -> float:
        """
        Compute a composite score combining speed, quality, and efficiency.

        Weights:
        - Quality: 60% (most important)
        - Speed: 25% (latency normalized)
        - Efficiency: 15% (token usage normalized)
        """
        if not self.success:
            return 0.0

        # Quality component (0-1)
        quality_score = self.quality.average

        # Speed component (normalize latency, lower is better)
        # Assume 10s is "average", faster gets higher score
        speed_score = max(0, 1 - (self.latency_ms / 10000))

        # Efficiency component (fewer tokens is better)
        # Assume 2000 tokens is "average"
        efficiency_score = max(0, 1 - (self.total_tokens / 2000)) if self.total_tokens else 0.5

        return (quality_score * 0.6) + (speed_score * 0.25) + (efficiency_score * 0.15)


# ==============================================================================
# LLM-as-Judge Evaluator
# ==============================================================================


class QualityEvaluator:
    """Evaluates response quality using LLM-as-judge."""

    EVALUATION_PROMPT = """You are an expert evaluator for AI agent responses. 
Evaluate the following response on a scale of 0.0 to 1.0 for each dimension.

TASK:
{task}

EXPECTED BEHAVIOR:
{expected_behavior}

AGENT RESPONSE:
{response}

Evaluate on these dimensions:
1. ACCURACY (0.0-1.0): Is the information factually correct? Does it match reality?
2. COMPLETENESS (0.0-1.0): Does it address all parts of the task?
3. ACTIONABILITY (0.0-1.0): Does it provide concrete, actionable next steps?
4. CLARITY (0.0-1.0): Is it well-organized and easy to understand?
5. RELEVANCE (0.0-1.0): Does it stay on topic without hallucination?
6. EFFICIENCY (0.0-1.0): Is it concise without unnecessary verbosity?

Return your evaluation as JSON:
{{
  "accuracy": 0.0,
  "completeness": 0.0,
  "actionability": 0.0,
  "clarity": 0.0,
  "relevance": 0.0,
  "efficiency": 0.0,
  "overall": 0.0,
  "reasoning": "Brief explanation of your scores"
}}

Only return the JSON, no other text."""

    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()

    async def evaluate(
        self,
        task: BenchmarkTask,
        response: str,
    ) -> QualityScores:
        """Evaluate a response using LLM-as-judge."""
        if not response or len(response) < 10:
            return QualityScores(
                judge_reasoning="Response too short to evaluate",
                judge_model=self.config.JUDGE_MODEL,
            )

        prompt = self.EVALUATION_PROMPT.format(
            task=task.prompt,
            expected_behavior=task.expected_behavior or "Complete the task accurately",
            response=response[:4000],  # Truncate for token limits
        )

        try:
            scores_json = await self._call_llm(prompt)
            scores = self._parse_scores(scores_json)
            scores.judge_model = self.config.JUDGE_MODEL
            return scores
        except Exception as e:
            return QualityScores(
                judge_reasoning=f"Evaluation failed: {e}",
                judge_model=self.config.JUDGE_MODEL,
            )

    async def _call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI for evaluation."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.config.AZURE_API_BASE}/openai/deployments/{self.config.JUDGE_MODEL}/chat/completions",
                headers={
                    "api-key": self.config.AZURE_API_KEY,
                    "Content-Type": "application/json",
                },
                params={"api-version": self.config.AZURE_API_VERSION},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_scores(self, json_str: str) -> QualityScores:
        """Parse JSON scores from LLM response."""
        # Extract JSON from potential markdown code blocks
        json_match = re.search(r"\{[\s\S]*\}", json_str)
        if not json_match:
            raise ValueError("No JSON found in response")

        data = json.loads(json_match.group())

        return QualityScores(
            accuracy=float(data.get("accuracy", 0)),
            completeness=float(data.get("completeness", 0)),
            actionability=float(data.get("actionability", 0)),
            clarity=float(data.get("clarity", 0)),
            relevance=float(data.get("relevance", 0)),
            efficiency=float(data.get("efficiency", 0)),
            overall=float(data.get("overall", 0)),
            judge_reasoning=data.get("reasoning", ""),
        )


# ==============================================================================
# Response Validator
# ==============================================================================


class ResponseValidator:
    """Validates responses for common issues."""

    ERROR_PATTERNS = [
        r"(?i)error:",
        r"(?i)exception:",
        r"(?i)failed to",
        r"(?i)module not available",
        r"(?i)i'm sorry",
        r"(?i)i cannot",
        r"(?i)i'm unable",
        r"(?i)i don't have access",
    ]

    SUCCESS_PATTERNS = [
        r"\d+\s*(issues?|errors?)",  # Contains counts
        r"(?i)(total|count|found)",
        r"(?i)(summary|report|analysis)",
        r"(?i)(critical|high|medium|low)\s*priority",
    ]

    def validate(self, response: str) -> tuple[bool, list[str]]:
        """
        Validate a response.

        Returns:
            (is_valid, validation_notes)
        """
        notes = []

        # Check for error patterns
        for pattern in self.ERROR_PATTERNS:
            if re.search(pattern, response):
                notes.append(f"Error pattern detected: {pattern}")
                return False, notes

        # Check response length
        if len(response) < 50:
            notes.append("Response too short (< 50 chars)")
            return False, notes

        # Check for success patterns
        success_patterns_found = 0
        for pattern in self.SUCCESS_PATTERNS:
            if re.search(pattern, response):
                success_patterns_found += 1
                notes.append(f"Contains: {pattern}")

        if success_patterns_found >= 2:
            return True, notes

        # Borderline - check structure
        if "##" in response or "1." in response or "-" in response:
            notes.append("Has structured formatting")
            return True, notes

        notes.append("Insufficient success indicators")
        return False, notes


# ==============================================================================
# Benchmark Runner
# ==============================================================================


class Benchmark:
    """
    Runs benchmarks across multiple frameworks.

    Usage:
        benchmark = Benchmark(frameworks=["autogen", "crewai", "openhands"])
        results = await benchmark.run(tasks)
        print(benchmark.generate_report(results))
    """

    def __init__(
        self,
        frameworks: list[str] | None = None,
        gateway_url: str | None = None,
        evaluate_quality: bool = True,
    ):
        self.frameworks = frameworks or ["autogen", "crewai", "openhands"]
        self.gateway_url = gateway_url or BenchmarkConfig.GATEWAY_URL
        self.evaluate_quality = evaluate_quality
        self.validator = ResponseValidator()
        self.evaluator = QualityEvaluator() if evaluate_quality else None
        self.config = BenchmarkConfig()

    async def run(
        self,
        tasks: list[BenchmarkTask],
        parallel: bool = False,
    ) -> list[BenchmarkResult]:
        """
        Run benchmark tasks across all frameworks.

        Args:
            tasks: List of benchmark tasks
            parallel: Run frameworks in parallel (faster but may hit rate limits)

        Returns:
            List of BenchmarkResult for each task/framework combination
        """
        results = []

        for task in tasks:
            if parallel:
                # Run all frameworks in parallel
                framework_results = await asyncio.gather(
                    *[self._run_single(task, fw) for fw in self.frameworks],
                    return_exceptions=True,
                )
                for i, result in enumerate(framework_results):
                    if isinstance(result, Exception):
                        results.append(
                            BenchmarkResult(
                                task_id=task.task_id,
                                framework=self.frameworks[i],
                                role=task.role,
                                success=False,
                                error=str(result),
                            )
                        )
                    else:
                        results.append(result)
            else:
                # Run sequentially
                for framework in self.frameworks:
                    result = await self._run_single(task, framework)
                    results.append(result)

        return results

    async def _run_single(
        self,
        task: BenchmarkTask,
        framework: str,
    ) -> BenchmarkResult:
        """Run a single task on a single framework."""
        result = BenchmarkResult(
            task_id=task.task_id,
            framework=framework,
            role=task.role,
        )

        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=self.config.REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{self.gateway_url}/api/run",
                    json={
                        "task": task.prompt,
                        "role": task.role,
                        "framework": framework,
                        "context_type": task.context_type,
                        "context_id": task.task_id,
                    },
                )
                response.raise_for_status()
                data = response.json()

            result.latency_ms = int((time.perf_counter() - start_time) * 1000)
            result.response = data.get("response", "")
            result.session_id = data.get("session_id", "")

            # Extract token usage if available
            metadata = data.get("metadata", {})
            result.input_tokens = metadata.get("input_tokens", 0)
            result.output_tokens = metadata.get("output_tokens", 0)
            result.total_tokens = result.input_tokens + result.output_tokens

            # Extract tool usage if available
            if "tools_called" in metadata:
                result.tool_usage = ToolUsageMetrics(
                    tools_called=metadata.get("tools_called", []),
                    tool_call_count=len(metadata.get("tools_called", [])),
                )

            # Validate response
            is_valid, notes = self.validator.validate(result.response)
            result.success = is_valid
            result.validation_notes = notes

            # Quality evaluation
            if self.evaluate_quality and self.evaluator and is_valid:
                result.quality = await self.evaluator.evaluate(task, result.response)

        except httpx.TimeoutException:
            result.latency_ms = int((time.perf_counter() - start_time) * 1000)
            result.error = "Request timed out"
            result.success = False
        except Exception as e:
            result.latency_ms = int((time.perf_counter() - start_time) * 1000)
            result.error = str(e)
            result.success = False

        return result

    def generate_report(self, results: list[BenchmarkResult]) -> str:
        """Generate a human-readable benchmark report."""
        lines = [
            "=" * 70,
            "AGENT BENCHMARK REPORT",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "=" * 70,
            "",
        ]

        # Group by task
        tasks = {}
        for r in results:
            if r.task_id not in tasks:
                tasks[r.task_id] = []
            tasks[r.task_id].append(r)

        for task_id, task_results in tasks.items():
            lines.extend(
                [
                    f"TASK: {task_id}",
                    "-" * 50,
                ]
            )

            for r in sorted(task_results, key=lambda x: x.composite_score, reverse=True):
                status = "PASS" if r.success else "FAIL"
                lines.extend(
                    [
                        f"  {r.framework.upper()}:",
                        f"    Status:     [{status}]",
                        f"    Latency:    {r.latency_ms}ms",
                        f"    Tokens:     {r.total_tokens}",
                        f"    Tools:      {r.tool_usage.tool_call_count}",
                    ]
                )

                if r.success and r.quality.overall > 0:
                    lines.extend(
                        [
                            f"    Quality:    {r.quality.overall:.2f}",
                            f"      Accuracy:      {r.quality.accuracy:.2f}",
                            f"      Completeness:  {r.quality.completeness:.2f}",
                            f"      Actionability: {r.quality.actionability:.2f}",
                            f"      Clarity:       {r.quality.clarity:.2f}",
                            f"    Composite:  {r.composite_score:.2f}",
                        ]
                    )

                if r.error:
                    lines.append(f"    Error:      {r.error[:50]}")

                lines.append("")

        # Summary
        lines.extend(
            [
                "=" * 70,
                "SUMMARY BY FRAMEWORK",
                "=" * 70,
            ]
        )

        for framework in self.frameworks:
            fw_results = [r for r in results if r.framework == framework]
            if not fw_results:
                continue

            successes = sum(1 for r in fw_results if r.success)
            avg_latency = sum(r.latency_ms for r in fw_results) / len(fw_results)
            avg_quality = sum(r.quality.overall for r in fw_results if r.success) / max(
                1, successes
            )
            avg_composite = sum(r.composite_score for r in fw_results) / len(fw_results)

            lines.extend(
                [
                    f"{framework.upper()}:",
                    f"  Success Rate:    {successes}/{len(fw_results)} ({100 * successes / len(fw_results):.0f}%)",
                    f"  Avg Latency:     {avg_latency:.0f}ms",
                    f"  Avg Quality:     {avg_quality:.2f}",
                    f"  Avg Composite:   {avg_composite:.2f}",
                    "",
                ]
            )

        # Winner determination
        framework_scores = {}
        for framework in self.frameworks:
            fw_results = [r for r in results if r.framework == framework]
            if fw_results:
                framework_scores[framework] = sum(r.composite_score for r in fw_results) / len(
                    fw_results
                )

        if framework_scores:
            winner = max(framework_scores, key=lambda x: framework_scores[x])
            lines.extend(
                [
                    "-" * 50,
                    f"WINNER: {winner.upper()} (composite score: {framework_scores[winner]:.2f})",
                    "-" * 50,
                ]
            )

        return "\n".join(lines)

    def export_results(
        self,
        results: list[BenchmarkResult],
        filepath: str | Path | None = None,
    ) -> str:
        """Export results to JSON file."""
        if filepath is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            self.config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            filepath = self.config.OUTPUT_DIR / f"benchmark_{timestamp}.json"
        else:
            filepath = Path(filepath)

        data = {
            "benchmark_time": datetime.now(timezone.utc).isoformat(),
            "frameworks": self.frameworks,
            "result_count": len(results),
            "results": [r.to_dict() for r in results],
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        return str(filepath)


# ==============================================================================
# Predefined Benchmark Tasks
# ==============================================================================

SENTRY_SUMMARY_TASK = BenchmarkTask(
    task_id="sentry-weekly-summary",
    prompt="""Provide a summary of Sentry issues for this week.

Include:
1. Total number of unresolved issues
2. Most frequent error types
3. Critical/high priority issues that need immediate attention
4. Any patterns or trends you notice

Format the response as a clear, actionable report.""",
    expected_behavior="Should list issue counts, categorize by severity, identify patterns",
    evaluation_criteria=["accuracy", "completeness", "actionability"],
    expected_tools=["get_sentry_issues", "get_sentry_issue_details"],
    role="support_engineer",
)

GITHUB_ISSUE_TRIAGE_TASK = BenchmarkTask(
    task_id="github-issue-triage",
    prompt="""Review and triage the most recent open GitHub issues.

For each issue:
1. Suggest appropriate labels
2. Estimate priority (P0-P3)
3. Identify if it's a bug, feature request, or question
4. Recommend next steps

Provide a summary of the triage results.""",
    expected_behavior="Should analyze issues, apply labels, prioritize, suggest actions",
    evaluation_criteria=["accuracy", "completeness", "actionability"],
    expected_tools=["list_issues", "get_issue"],
    role="software_engineer",
)

RELEASE_NOTES_TASK = BenchmarkTask(
    task_id="release-notes",
    prompt="""Generate release notes for the upcoming release.

Include:
1. List of merged PRs since last release
2. Categorized changes (features, fixes, improvements)
3. Breaking changes highlighted
4. Migration notes if needed

Format as markdown suitable for GitHub releases.""",
    expected_behavior="Should list PRs, categorize changes, format as release notes",
    evaluation_criteria=["accuracy", "completeness", "clarity"],
    expected_tools=["list_prs", "get_commits"],
    role="release_engineer",
)

# Standard benchmark suite
STANDARD_TASKS = [
    SENTRY_SUMMARY_TASK,
    GITHUB_ISSUE_TRIAGE_TASK,
    RELEASE_NOTES_TASK,
]


# ==============================================================================
# CLI Interface
# ==============================================================================


async def main():
    """Run benchmark from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Run agent benchmarks")
    parser.add_argument(
        "--frameworks",
        nargs="+",
        default=["autogen", "crewai", "openhands"],
        help="Frameworks to benchmark",
    )
    parser.add_argument(
        "--gateway-url",
        default="http://localhost:8080",
        help="Gateway URL",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["sentry-weekly-summary"],
        help="Task IDs to run",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--no-quality",
        action="store_true",
        help="Skip quality evaluation (faster)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run frameworks in parallel",
    )

    args = parser.parse_args()

    # Select tasks
    task_map = {t.task_id: t for t in STANDARD_TASKS}
    tasks = [task_map[tid] for tid in args.tasks if tid in task_map]

    if not tasks:
        print(f"No valid tasks found. Available: {list(task_map.keys())}")
        return

    # Run benchmark
    benchmark = Benchmark(
        frameworks=args.frameworks,
        gateway_url=args.gateway_url,
        evaluate_quality=not args.no_quality,
    )

    print(f"Running benchmark with {len(tasks)} tasks across {len(args.frameworks)} frameworks...")
    results = await benchmark.run(tasks, parallel=args.parallel)

    # Generate report
    report = benchmark.generate_report(results)
    print(report)

    # Export results
    if args.output:
        filepath = benchmark.export_results(results, args.output)
        print(f"\nResults exported to: {filepath}")


if __name__ == "__main__":
    asyncio.run(main())
