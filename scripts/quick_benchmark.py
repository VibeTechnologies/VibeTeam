#!/usr/bin/env python3
"""
Quick Benchmark: Run all frameworks with a simple task and compare.

Usage:
    python scripts/quick_benchmark.py
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FRAMEWORKS = ["autogen", "crewai", "openhands"]

QUICK_TASK = """Analyze this production error and propose a fix:

Error: GraphRecursionError - "Recursion limit of 512 reached without hitting a stop condition"

Stack trace:
  at langgraph.pregel.Pregel._execute (pregel.py:892)
  at langgraph.pregel.Pregel.stream (pregel.py:743)
  at VibeLangchainAgent.run (VibeLangchainAgent.ts:444)
  at ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)
  at ReactGraph.execute (ReactGraph.ts:89)

Context: Agent in "execute-reflect" mode, last action was browser_click.

Provide:
1. Root cause analysis (2-3 sentences)
2. Proposed fix (code snippet or approach)
3. Priority level (P0-P3)
"""


@dataclass
class Result:
    framework: str
    response: str
    latency_ms: int
    success: bool
    error: str | None = None


def get_agent_class(framework: str):
    """Import and return the agent class."""
    if framework == "autogen":
        from agents.autogen.support_engineer import AutoGenSupportEngineer

        return AutoGenSupportEngineer
    elif framework == "crewai":
        from agents.crewai.support_engineer import CrewAISupportEngineer

        return CrewAISupportEngineer
    elif framework == "openhands":
        from agents.openhands.support_engineer import OpenHandsSupportEngineer

        return OpenHandsSupportEngineer
    raise ValueError(f"Unknown framework: {framework}")


async def run_agent(framework: str, task: str, timeout: float) -> Result:
    """Run an agent with timeout."""
    start = time.perf_counter()
    try:
        agent_class = get_agent_class(framework)
        agent = agent_class()
        result = await asyncio.wait_for(agent.run_async(task=task), timeout=timeout)
        return Result(
            framework=framework,
            response=result.get("response", ""),
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=True,
        )
    except asyncio.TimeoutError:
        return Result(
            framework=framework,
            response="",
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        return Result(
            framework=framework,
            response="",
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            error=str(e)[:100],
        )


async def main():
    print("=" * 70)
    print("QUICK BENCHMARK: GraphRecursionError Analysis")
    print("=" * 70)

    results = []

    for fw in FRAMEWORKS:
        print(f"\n>>> Running {fw.upper()}...")
        result = await run_agent(fw, QUICK_TASK, timeout=60)
        results.append(result)

        status = "PASS" if result.success else "FAIL"
        print(f"    Status: {status} | Latency: {result.latency_ms}ms")
        if result.error:
            print(f"    Error: {result.error}")
        if result.response:
            preview = result.response[:300].replace("\n", " ")
            print(f"    Preview: {preview}...")

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Framework':<15} {'Status':<8} {'Latency':<12} {'Response':<10}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: (not x.success, x.latency_ms)):
        status = "PASS" if r.success else "FAIL"
        latency = f"{r.latency_ms}ms"
        resp = f"{len(r.response)} chars"
        print(f"{r.framework.upper():<15} {status:<8} {latency:<12} {resp:<10}")

    # Determine winner (fastest successful)
    successful = [r for r in results if r.success]
    if successful:
        winner = min(successful, key=lambda x: x.latency_ms)
        print(f"\nFastest successful: {winner.framework.upper()} ({winner.latency_ms}ms)")

    print("=" * 70)

    # Return JSON for programmatic use
    return {
        "results": [
            {
                "framework": r.framework,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "response_length": len(r.response),
                "error": r.error,
            }
            for r in results
        ]
    }


if __name__ == "__main__":
    asyncio.run(main())
