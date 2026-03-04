#!/usr/bin/env python3
"""
Run a VibeTeam agent with a task and display results.

Usage:
    python scripts/run_agent.py <framework> <task>
    python scripts/run_agent.py autogen "List 3 GitHub issues"
    python scripts/run_agent.py crewai "List 3 GitHub issues"
    python scripts/run_agent.py openhands "List 3 GitHub issues"
    python scripts/run_agent.py all "List 3 GitHub issues"

Options:
    --role       Agent role: software_engineer (default), support_engineer, release_engineer
    --json       Output as JSON
    --timeout    Timeout in seconds (default: 180)
"""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


FRAMEWORKS = ["autogen", "crewai", "openhands"]
ROLES = ["software_engineer", "support_engineer", "release_engineer"]


def get_agent_factory(framework: str, role: str):
    """Import and return a zero-arg agent factory for framework/role."""
    if framework == "autogen":
        if role == "software_engineer":
            from agent_service.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
        elif role == "support_engineer":
            from agent_service.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif role == "release_engineer":
            from agent_service.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
    elif framework == "crewai":
        if role == "software_engineer":
            from agent_service.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
        elif role == "support_engineer":
            from agent_service.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif role == "release_engineer":
            from agent_service.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
    elif framework == "openhands":
        from agent_service.openhands import create_agent

        return lambda: create_agent(role)

    raise ValueError(f"Unknown framework/role: {framework}/{role}")


async def run_agent(framework: str, role: str, task: str, timeout: float) -> dict[str, Any]:
    """Run an agent with the given task and return results."""
    start_time = time.perf_counter()

    try:
        agent_factory = get_agent_factory(framework, role)
        agent = agent_factory()

        # Run with timeout
        result = await asyncio.wait_for(agent.run_async(task=task), timeout=timeout)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "framework": framework,
            "role": role,
            "task": task,
            "response": result.get("response", ""),
            "session_id": result.get("session_id", ""),
            "latency_ms": latency_ms,
            "success": True,
            "error": None,
        }
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "framework": framework,
            "role": role,
            "task": task,
            "response": "",
            "session_id": "",
            "latency_ms": latency_ms,
            "success": False,
            "error": f"Timeout after {timeout}s",
        }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "framework": framework,
            "role": role,
            "task": task,
            "response": "",
            "session_id": "",
            "latency_ms": latency_ms,
            "success": False,
            "error": str(e),
        }


def print_result(result: dict[str, Any], output_json: bool = False) -> None:
    """Print the result in human-readable or JSON format."""
    if output_json:
        print(json.dumps(result, indent=2))
        return

    print(f"\n{'=' * 60}")
    print(f"FRAMEWORK: {result['framework'].upper()}")
    print(f"ROLE: {result['role']}")
    print(f"LATENCY: {result['latency_ms']}ms")
    print(f"SUCCESS: {result['success']}")

    if result["error"]:
        print(f"ERROR: {result['error']}")

    print(f"\n{'─' * 60}")
    print("RESPONSE:")
    print(f"{'─' * 60}")
    print(result["response"])
    print(f"{'=' * 60}\n")


async def main():
    parser = argparse.ArgumentParser(
        description="Run a VibeTeam agent with a task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_agent.py autogen "List 3 GitHub issues"
  python scripts/run_agent.py crewai "Summarize Sentry errors" --role support_engineer
  python scripts/run_agent.py all "List open PRs" --json
  python scripts/run_agent.py openhands "Create release notes" --role release_engineer
        """,
    )
    parser.add_argument(
        "framework",
        choices=FRAMEWORKS + ["all"],
        help="Framework to use (autogen, crewai, openhands, or 'all')",
    )
    parser.add_argument("task", help="Task description for the agent")
    parser.add_argument(
        "--role",
        choices=ROLES,
        default="software_engineer",
        help="Agent role (default: software_engineer)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--timeout", type=float, default=180, help="Timeout in seconds (default: 180)"
    )

    args = parser.parse_args()

    frameworks = FRAMEWORKS if args.framework == "all" else [args.framework]

    results = []
    for framework in frameworks:
        if not args.json:
            print(f"Running {framework.upper()} {args.role}...")

        result = await run_agent(framework, args.role, args.task, args.timeout)
        results.append(result)

        if not args.json:
            print_result(result)

    if args.json:
        if len(results) == 1:
            print(json.dumps(results[0], indent=2))
        else:
            print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
