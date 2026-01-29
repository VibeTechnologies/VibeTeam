#!/usr/bin/env python3
"""
Benchmark: Sentry Error to Fix Workflow

Tests the complete autonomous workflow across all frameworks:
1. Support Engineer discovers and analyzes Sentry error
2. Software Engineer investigates and proposes a fix

Usage:
    python scripts/benchmark_sentry_fix.py
    python scripts/benchmark_sentry_fix.py --timeout 300
    python scripts/benchmark_sentry_fix.py --json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.benchmark import ComparativeEvaluator, ComparativeResult


FRAMEWORKS = ["autogen", "crewai", "openhands"]

# The real Sentry error to analyze - includes stack trace for analysis even if API fails
SENTRY_ERROR_TASK = """A critical production error has been discovered in Sentry.

Error Details:
- Sentry Issue ID: 6996178791
- Error Type: GraphRecursionError
- Message: "Recursion limit of 512 reached without hitting a stop condition"
- Project: vibe-web-agent
- Status: Unresolved

Stack Trace (from Sentry event):
```
GraphRecursionError: Recursion limit of 512 reached without hitting a stop condition.
  at langgraph.pregel.Pregel._execute (pregel.py:892)
  at langgraph.pregel.Pregel.stream (pregel.py:743)
  at langgraph.pregel.Pregel.invoke (pregel.py:682)
  at VibeLangchainAgent.run (VibeLangchainAgent.ts:444)
  at ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)
  at ExecuteReflectGraph.processStep (ExecuteReflectGraph.ts:203)
  at ReactGraph.execute (ReactGraph.ts:89)
```

Context from Sentry breadcrumbs:
- User action: "Navigating to product page"
- Browser: Chrome 120
- Agent mode: "execute-reflect"
- Last tool call: "browser_click"

Your Task:
1. Analyze the stack trace to identify the root cause
2. Determine which code path is causing the infinite recursion  
3. Propose a concrete fix with code changes
4. Assess the severity and recommend priority level

Provide a comprehensive analysis including:
- Error summary with impact assessment  
- Root cause analysis from the stack trace
- Specific code changes to fix the issue
- Testing recommendations
"""


@dataclass
class FrameworkResult:
    """Result from running a single framework."""

    framework: str
    response: str
    latency_ms: int
    success: bool
    error: str | None = None


def get_agent_class(framework: str, role: str):
    """Import and return the agent class for the given framework and role."""
    if framework == "autogen":
        if role == "support_engineer":
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif role == "software_engineer":
            from agents.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
    elif framework == "crewai":
        if role == "support_engineer":
            from agents.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif role == "software_engineer":
            from agents.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
    elif framework == "openhands":
        if role == "support_engineer":
            from agents.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif role == "software_engineer":
            from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

            return OpenHandsSoftwareEngineer
    raise ValueError(f"Unknown framework/role: {framework}/{role}")


async def run_agent(framework: str, role: str, task: str, timeout: float) -> FrameworkResult:
    """Run an agent with the given task and return results."""
    start_time = time.perf_counter()

    try:
        agent_class = get_agent_class(framework, role)
        agent = agent_class()

        # Run with timeout
        result = await asyncio.wait_for(agent.run_async(task=task), timeout=timeout)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return FrameworkResult(
            framework=framework,
            response=result.get("response", ""),
            latency_ms=latency_ms,
            success=True,
        )
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return FrameworkResult(
            framework=framework,
            response="",
            latency_ms=latency_ms,
            success=False,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return FrameworkResult(
            framework=framework,
            response="",
            latency_ms=latency_ms,
            success=False,
            error=str(e),
        )


def print_result_box(result: FrameworkResult) -> None:
    """Print a single framework result in a box."""
    status = "PASS" if result.success else "FAIL"
    print(f"\n{'=' * 70}")
    print(f"FRAMEWORK: {result.framework.upper()}")
    print(f"STATUS:    [{status}]")
    print(f"LATENCY:   {result.latency_ms}ms ({result.latency_ms / 1000:.1f}s)")

    if result.error:
        print(f"ERROR:     {result.error}")

    print(f"{'─' * 70}")
    print("RESPONSE:")
    print(f"{'─' * 70}")

    # Truncate response for display
    response = result.response[:2000] if result.response else "(No response)"
    print(response)
    if len(result.response) > 2000:
        print(f"\n... (truncated, {len(result.response)} chars total)")

    print(f"{'=' * 70}")


def print_comparison_table(results: list[FrameworkResult]) -> None:
    """Print a comparison table of all results."""
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Framework':<15} {'Status':<10} {'Latency':<15} {'Response Len':<15}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: x.latency_ms):
        status = "PASS" if r.success else "FAIL"
        latency = f"{r.latency_ms}ms"
        resp_len = f"{len(r.response)} chars" if r.response else "0 chars"
        print(f"{r.framework.upper():<15} {status:<10} {latency:<15} {resp_len:<15}")

    print("=" * 70)


async def run_benchmark(timeout: float, output_json: bool = False) -> dict[str, Any]:
    """Run the complete Sentry fix benchmark across all frameworks."""
    print("=" * 70)
    print("SENTRY ERROR TO FIX BENCHMARK")
    print("=" * 70)
    print(f"Task: Analyze GraphRecursionError and propose fix")
    print(f"Sentry Issue ID: 6996178791")
    print(f"Timeout: {timeout}s per framework")
    print(f"Frameworks: {', '.join(FRAMEWORKS)}")
    print("=" * 70)

    results: list[FrameworkResult] = []
    responses: dict[str, str] = {}

    # Run each framework sequentially (to avoid rate limits)
    for framework in FRAMEWORKS:
        print(f"\n>>> Running {framework.upper()} Support Engineer...")
        result = await run_agent(framework, "support_engineer", SENTRY_ERROR_TASK, timeout)
        results.append(result)
        responses[framework] = result.response

        if not output_json:
            print_result_box(result)

    # Print comparison table
    if not output_json:
        print_comparison_table(results)

    # Run LLM-as-judge comparative evaluation
    print("\n>>> Running LLM-as-Judge Comparative Evaluation...")
    evaluator = ComparativeEvaluator()
    eval_result: ComparativeResult = await evaluator.evaluate(
        task=SENTRY_ERROR_TASK,
        responses=responses,
    )

    if not output_json:
        print(str(eval_result))

    # Prepare final output
    output = {
        "benchmark": "sentry-error-to-fix",
        "task": SENTRY_ERROR_TASK[:200] + "...",
        "sentry_issue_id": "6996178791",
        "timeout_seconds": timeout,
        "results": [
            {
                "framework": r.framework,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "response_length": len(r.response),
                "error": r.error,
            }
            for r in results
        ],
        "evaluation": eval_result.to_dict(),
        "winner": eval_result.winner,
    }

    if output_json:
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "=" * 70)
        print(f"WINNER: {eval_result.winner.upper()}")
        print(f"Reasoning: {eval_result.reasoning}")
        print("=" * 70)

    return output


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Sentry Error to Fix workflow across frameworks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/benchmark_sentry_fix.py
  python scripts/benchmark_sentry_fix.py --timeout 300
  python scripts/benchmark_sentry_fix.py --json
        """,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180,
        help="Timeout in seconds per framework (default: 180)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON only",
    )

    args = parser.parse_args()

    await run_benchmark(timeout=args.timeout, output_json=args.json)


if __name__ == "__main__":
    asyncio.run(main())
