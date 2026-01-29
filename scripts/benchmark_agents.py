#!/usr/bin/env python3
"""
Consolidated Agent Benchmark Script

Benchmarks VibeTeam agents across multiple scenarios and frameworks.

Usage:
    python scripts/benchmark_agents.py --list                    # List available scenarios
    python scripts/benchmark_agents.py --scenario error-analysis # Run specific scenario
    python scripts/benchmark_agents.py --all                     # Run all scenarios
    python scripts/benchmark_agents.py --scenario error-analysis --frameworks autogen crewai

Scenarios:
    error-analysis  - Analyze GraphRecursionError from Sentry and propose fix
    sentry-summary  - Summarize Sentry issues for the week
    github-triage   - Triage GitHub issues with labels and priority
    release-notes   - Generate release notes from merged PRs
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


# ==============================================================================
# Scenario Definitions
# ==============================================================================

SCENARIOS = {
    "error-analysis": {
        "name": "Sentry Error Analysis",
        "description": "Analyze GraphRecursionError and propose a fix",
        "role": "support_engineer",
        "task": """A critical production error has been discovered in Sentry.

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
""",
    },
    "sentry-summary": {
        "name": "Weekly Sentry Summary",
        "description": "Summarize Sentry issues for the past week",
        "role": "support_engineer",
        "task": """Provide a comprehensive summary of Sentry issues for this week.

Include:
1. Total number of unresolved issues
2. Most frequent error types with counts
3. Critical/high priority issues that need immediate attention
4. Any patterns or trends you notice across issues
5. Recommended prioritization for the engineering team

Format the response as a clear, actionable report that could be shared in Slack.
Use the Sentry connector to fetch real issue data.
""",
    },
    "github-triage": {
        "name": "GitHub Issue Triage",
        "description": "Triage open GitHub issues with labels and priority",
        "role": "software_engineer",
        "task": """Review and triage the most recent open GitHub issues in the VibeTechnologies/VibeWebAgent repository.

For each issue:
1. Analyze the issue content and context
2. Suggest appropriate labels (bug, feature, enhancement, documentation, etc.)
3. Estimate priority (P0-Critical, P1-High, P2-Medium, P3-Low)
4. Identify if it's a bug, feature request, or question
5. Recommend next steps or assignee

Provide:
- A summary table of triaged issues
- Any issues that need immediate attention
- Patterns you notice across issues
- Recommendations for the team
""",
    },
    "release-notes": {
        "name": "Release Notes Generator",
        "description": "Generate release notes from merged PRs",
        "role": "release_engineer",
        "task": """Generate release notes for the upcoming release based on merged PRs.

Steps:
1. Fetch recently merged PRs from the repository
2. Categorize changes into: Features, Bug Fixes, Improvements, Breaking Changes
3. Extract key highlights for the changelog
4. Identify any migration steps needed

Output format:
## [Version X.Y.Z] - YYYY-MM-DD

### Features
- Feature descriptions...

### Bug Fixes
- Bug fix descriptions...

### Improvements
- Improvement descriptions...

### Breaking Changes
- Any breaking changes with migration notes...

### Contributors
- List of contributors to this release
""",
    },
}

FRAMEWORKS = ["autogen", "crewai", "openhands"]


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class FrameworkResult:
    """Result from running a single framework."""

    framework: str
    response: str
    latency_ms: int
    success: bool
    error: str | None = None


# ==============================================================================
# Agent Runner
# ==============================================================================


def get_agent_class(framework: str, role: str):
    """Import and return the agent class for the given framework and role."""
    if framework == "autogen":
        if role == "support_engineer":
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif role == "software_engineer":
            from agents.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
        elif role == "release_engineer":
            from agents.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
    elif framework == "crewai":
        if role == "support_engineer":
            from agents.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif role == "software_engineer":
            from agents.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
        elif role == "release_engineer":
            from agents.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
    elif framework == "openhands":
        if role == "support_engineer":
            from agents.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif role == "software_engineer":
            from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

            return OpenHandsSoftwareEngineer
        elif role == "release_engineer":
            from agents.openhands.release_engineer import OpenHandsReleaseEngineer

            return OpenHandsReleaseEngineer
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


# ==============================================================================
# Output Formatting
# ==============================================================================


def print_header(text: str, char: str = "=", width: int = 70) -> None:
    """Print a formatted header."""
    print(f"\n{char * width}")
    print(text)
    print(f"{char * width}")


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
    print_header("COMPARISON SUMMARY")
    print(f"{'Framework':<15} {'Status':<10} {'Latency':<15} {'Response Len':<15}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: x.latency_ms):
        status = "PASS" if r.success else "FAIL"
        latency = f"{r.latency_ms}ms"
        resp_len = f"{len(r.response)} chars" if r.response else "0 chars"
        print(f"{r.framework.upper():<15} {status:<10} {latency:<15} {resp_len:<15}")

    print("=" * 70)


# ==============================================================================
# Benchmark Runner
# ==============================================================================


async def run_scenario(
    scenario_id: str,
    frameworks: list[str],
    timeout: float,
    output_json: bool = False,
) -> dict[str, Any]:
    """Run a single scenario across all frameworks."""
    scenario = SCENARIOS[scenario_id]

    print_header(f"SCENARIO: {scenario['name']}")
    print(f"Description: {scenario['description']}")
    print(f"Role: {scenario['role']}")
    print(f"Timeout: {timeout}s per framework")
    print(f"Frameworks: {', '.join(frameworks)}")

    results: list[FrameworkResult] = []
    responses: dict[str, str] = {}

    # Run each framework sequentially (to avoid rate limits)
    for framework in frameworks:
        print(f"\n>>> Running {framework.upper()} {scenario['role']}...")
        result = await run_agent(framework, scenario["role"], scenario["task"], timeout)
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
        task=scenario["task"],
        responses=responses,
    )

    if not output_json:
        print(str(eval_result))

    # Prepare output
    output = {
        "scenario": scenario_id,
        "scenario_name": scenario["name"],
        "role": scenario["role"],
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
        print_header(f"WINNER: {eval_result.winner.upper()}", char="-")
        print(f"Reasoning: {eval_result.reasoning}")

    return output


async def run_all_scenarios(
    frameworks: list[str],
    timeout: float,
    output_json: bool = False,
) -> dict[str, Any]:
    """Run all scenarios and produce aggregate results."""
    all_results = {}
    winners = {}

    for scenario_id in SCENARIOS:
        result = await run_scenario(scenario_id, frameworks, timeout, output_json)
        all_results[scenario_id] = result
        winners[scenario_id] = result["winner"]

    # Summary
    if not output_json:
        print_header("AGGREGATE RESULTS")
        print(f"{'Scenario':<20} {'Winner':<15}")
        print("-" * 40)
        for scenario_id, winner in winners.items():
            print(f"{scenario_id:<20} {winner.upper():<15}")

        # Count wins
        win_counts = {}
        for winner in winners.values():
            win_counts[winner] = win_counts.get(winner, 0) + 1

        print("-" * 40)
        print("Win counts:")
        for fw, count in sorted(win_counts.items(), key=lambda x: -x[1]):
            print(f"  {fw.upper()}: {count} wins")

    return {
        "scenarios": all_results,
        "winners": winners,
        "summary": {fw: list(winners.values()).count(fw) for fw in set(winners.values())},
    }


def list_scenarios() -> None:
    """List all available scenarios."""
    print_header("AVAILABLE SCENARIOS")
    print(f"{'ID':<20} {'Name':<30} {'Role':<20}")
    print("-" * 70)
    for scenario_id, scenario in SCENARIOS.items():
        print(f"{scenario_id:<20} {scenario['name']:<30} {scenario['role']:<20}")
    print()
    print("Usage examples:")
    print("  python scripts/benchmark_agents.py --scenario error-analysis")
    print(
        "  python scripts/benchmark_agents.py --scenario sentry-summary --frameworks autogen crewai"
    )
    print("  python scripts/benchmark_agents.py --all")


# ==============================================================================
# CLI
# ==============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark VibeTeam agents across scenarios and frameworks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/benchmark_agents.py --list
  python scripts/benchmark_agents.py --scenario error-analysis
  python scripts/benchmark_agents.py --scenario sentry-summary --timeout 300
  python scripts/benchmark_agents.py --all --json
  python scripts/benchmark_agents.py --scenario github-triage --frameworks autogen crewai
        """,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available scenarios",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        choices=list(SCENARIOS.keys()),
        help="Scenario to run",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios",
    )
    parser.add_argument(
        "--frameworks",
        nargs="+",
        default=FRAMEWORKS,
        choices=FRAMEWORKS,
        help=f"Frameworks to benchmark (default: {' '.join(FRAMEWORKS)})",
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

    if args.list:
        list_scenarios()
        return

    if args.all:
        await run_all_scenarios(args.frameworks, args.timeout, args.json)
        return

    if args.scenario:
        await run_scenario(args.scenario, args.frameworks, args.timeout, args.json)
        return

    # No action specified, show help
    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
