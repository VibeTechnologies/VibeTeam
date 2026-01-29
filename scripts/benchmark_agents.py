#!/usr/bin/env python3
"""
Consolidated Agent Benchmark Script

Benchmarks VibeTeam agents across multiple scenarios and frameworks.
Generates markdown evaluation reports.

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

Reports:
    Generated in reports/ directory with format: evaluation-report-{date}-{time}-{commit}.md
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==============================================================================
# Configuration
# ==============================================================================


class BenchmarkConfig:
    """Benchmark configuration from environment."""

    AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_API_KEY", ""))
    AZURE_API_BASE = os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_API_BASE", ""))
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-08-01-preview")
    JUDGE_MODEL = os.getenv(
        "BENCHMARK_JUDGE_MODEL", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-2")
    )
    REPORTS_DIR = Path(os.getenv("BENCHMARK_REPORTS_DIR", "reports"))

    @classmethod
    def get_azure_api_base(cls) -> str:
        """Get AZURE_API_BASE with protocol validation."""
        base = cls.AZURE_API_BASE
        if not base:
            raise ValueError("AZURE_API_BASE environment variable not set")
        if not base.startswith(("http://", "https://")):
            raise ValueError(
                f"AZURE_API_BASE must start with 'http://' or 'https://'. Got: '{base}'"
            )
        return base.rstrip("/")


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


@dataclass
class ComparativeScore:
    """Score for a single agent from comparative evaluation."""

    framework: str
    score: int  # 0-5 scale
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComparativeResult:
    """Result from comparative LLM-as-judge evaluation."""

    task: str
    scores: dict[str, ComparativeScore]  # framework -> score
    winner: str
    reasoning: str
    judge_model: str
    evaluation_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task[:200],
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "winner": self.winner,
            "reasoning": self.reasoning,
            "judge_model": self.judge_model,
            "evaluation_time_ms": self.evaluation_time_ms,
        }

    def __str__(self) -> str:
        lines = [
            "=" * 60,
            "LLM-AS-JUDGE EVALUATION RESULTS",
            "=" * 60,
            "",
        ]
        for fw, score in sorted(self.scores.items(), key=lambda x: x[1].score, reverse=True):
            lines.append(f"{fw.upper()}: {score.score}/5")
            lines.append(f"  Feedback: {score.feedback}")
            lines.append("")

        lines.extend(
            [
                "-" * 60,
                f"WINNER: {self.winner.upper()}",
                f"Reasoning: {self.reasoning}",
                "-" * 60,
                f"Judge: {self.judge_model} | Time: {self.evaluation_time_ms}ms",
            ]
        )
        return "\n".join(lines)


# ==============================================================================
# Comparative Evaluator (LLM-as-Judge)
# ==============================================================================


class ComparativeEvaluator:
    """
    Evaluates multiple agent responses side-by-side using LLM-as-judge.

    Uses a simple 0-5 scoring scale:
    - 0: Failed completely or error
    - 1: Attempted but mostly wrong
    - 2: Partially correct, missing key elements
    - 3: Acceptable, addresses main points
    - 4: Good, comprehensive and accurate
    - 5: Excellent, exceeds expectations
    """

    COMPARATIVE_PROMPT = """You are an expert evaluator comparing AI agent responses to the same task.

TASK:
{task}

AGENT RESPONSES:

=== AUTOGEN ===
{autogen_response}

=== CREWAI ===
{crewai_response}

=== OPENHANDS ===
{openhands_response}

Score each agent from 0-5 based on how well they completed the task:
- 0: Failed completely, error, or refused to answer
- 1: Attempted but mostly wrong or unhelpful
- 2: Partially correct but missing key elements
- 3: Acceptable, addresses the main points adequately
- 4: Good, comprehensive and accurate response
- 5: Excellent, exceeds expectations with actionable insights

Consider:
- Accuracy: Is the information correct and not hallucinated?
- Completeness: Does it address all parts of the task?
- Usefulness: Is the response actionable and helpful?
- Clarity: Is it well-organized and easy to understand?

Return ONLY valid JSON in this exact format:
{{
  "autogen": {{"score": 0, "feedback": "Brief explanation"}},
  "crewai": {{"score": 0, "feedback": "Brief explanation"}},
  "openhands": {{"score": 0, "feedback": "Brief explanation"}},
  "winner": "framework_name",
  "reasoning": "One sentence explaining why this framework won"
}}"""

    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()

    async def evaluate(
        self,
        task: str,
        responses: dict[str, str],
    ) -> ComparativeResult:
        """
        Evaluate multiple agent responses side-by-side.

        Args:
            task: The original task/prompt given to agents
            responses: Dict mapping framework name to response text

        Returns:
            ComparativeResult with scores for each framework
        """
        start_time = time.perf_counter()

        # Ensure we have all three frameworks (use empty string if missing)
        autogen_resp = responses.get("autogen", "(No response)")[:3000]
        crewai_resp = responses.get("crewai", "(No response)")[:3000]
        openhands_resp = responses.get("openhands", "(No response)")[:3000]

        prompt = self.COMPARATIVE_PROMPT.format(
            task=task[:1000],
            autogen_response=autogen_resp,
            crewai_response=crewai_resp,
            openhands_response=openhands_resp,
        )

        try:
            result_json = await self._call_llm(prompt)
            result = self._parse_result(result_json)
            result.task = task[:200]
            result.judge_model = self.config.JUDGE_MODEL
            result.evaluation_time_ms = int((time.perf_counter() - start_time) * 1000)
            return result
        except Exception as e:
            # Return error result
            return ComparativeResult(
                task=task[:200],
                scores={
                    fw: ComparativeScore(framework=fw, score=0, feedback=f"Evaluation error: {e}")
                    for fw in ["autogen", "crewai", "openhands"]
                },
                winner="none",
                reasoning=f"Evaluation failed: {e}",
                judge_model=self.config.JUDGE_MODEL,
                evaluation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    async def _call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI for comparative evaluation."""
        api_base = self.config.get_azure_api_base()
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{api_base}/openai/deployments/{self.config.JUDGE_MODEL}/chat/completions",
                headers={
                    "api-key": self.config.AZURE_API_KEY,
                    "Content-Type": "application/json",
                },
                params={"api-version": self.config.AZURE_API_VERSION},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_completion_tokens": 800,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_result(self, json_str: str) -> ComparativeResult:
        """Parse JSON result from LLM response."""
        # Extract JSON from potential markdown code blocks
        json_match = re.search(r"\{[\s\S]*\}", json_str)
        if not json_match:
            raise ValueError("No JSON found in LLM response")

        data = json.loads(json_match.group())

        scores = {}
        for framework in ["autogen", "crewai", "openhands"]:
            fw_data = data.get(framework, {})
            scores[framework] = ComparativeScore(
                framework=framework,
                score=int(fw_data.get("score", 0)),
                feedback=str(fw_data.get("feedback", "No feedback")),
            )

        return ComparativeResult(
            task="",
            scores=scores,
            winner=str(data.get("winner", "unknown")),
            reasoning=str(data.get("reasoning", "No reasoning provided")),
            judge_model="",
        )


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

        # For OpenHands, disable tools to prevent agentic exploration loop
        # that causes timeouts. This makes it respond directly like other frameworks.
        run_kwargs: dict[str, Any] = {"task": task}
        if framework == "openhands":
            run_kwargs["use_tools"] = False

        # Run with timeout
        result = await asyncio.wait_for(agent.run_async(**run_kwargs), timeout=timeout)

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
# Markdown Report Generation
# ==============================================================================


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def generate_markdown_report(
    scenario_id: str,
    scenario: dict[str, Any],
    results: list[FrameworkResult],
    eval_result: ComparativeResult,
) -> str:
    """Generate a markdown evaluation report."""
    now = datetime.now(timezone.utc)
    commit = get_git_commit()

    lines = [
        f"# Agent Benchmark Evaluation Report",
        "",
        f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Commit**: `{commit}`",
        f"**Scenario**: {scenario['name']} (`{scenario_id}`)",
        f"**Role**: {scenario['role']}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Framework | Status | Latency | Score | Response Length |",
        "|-----------|--------|---------|-------|-----------------|",
    ]

    for r in sorted(
        results,
        key=lambda x: -eval_result.scores.get(
            x.framework, ComparativeScore(x.framework, 0, "")
        ).score,
    ):
        score = eval_result.scores.get(r.framework, ComparativeScore(r.framework, 0, "N/A"))
        status = "PASS" if r.success else "FAIL"
        lines.append(
            f"| {r.framework.upper()} | {status} | {r.latency_ms}ms | {score.score}/5 | {len(r.response)} chars |"
        )

    lines.extend(
        [
            "",
            f"**Winner**: {eval_result.winner.upper()}",
            "",
            f"**Reasoning**: {eval_result.reasoning}",
            "",
            "---",
            "",
            "## Task",
            "",
            "```",
            scenario["task"],
            "```",
            "",
            "---",
            "",
        ]
    )

    # Add each framework's response
    for r in results:
        score = eval_result.scores.get(r.framework, ComparativeScore(r.framework, 0, "N/A"))
        lines.extend(
            [
                f"## {r.framework.upper()} Response",
                "",
                f"**Score**: {score.score}/5",
                f"**Feedback**: {score.feedback}",
                f"**Latency**: {r.latency_ms}ms",
                "",
            ]
        )

        if r.error:
            lines.extend(
                [
                    f"**Error**: {r.error}",
                    "",
                ]
            )

        if r.response:
            lines.extend(
                [
                    "### Output",
                    "",
                    "```",
                    r.response,
                    "```",
                    "",
                ]
            )
        else:
            lines.append("*(No response)*\n")

        lines.append("---\n")

    # Evaluation metadata
    lines.extend(
        [
            "## Evaluation Metadata",
            "",
            f"- **Judge Model**: {eval_result.judge_model}",
            f"- **Evaluation Time**: {eval_result.evaluation_time_ms}ms",
            "",
        ]
    )

    return "\n".join(lines)


def save_markdown_report(content: str, scenario_id: str) -> Path:
    """Save markdown report to file."""
    now = datetime.now(timezone.utc)
    commit = get_git_commit()

    # Create reports directory
    reports_dir = BenchmarkConfig.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename: evaluation-report-{date}-{time}-{commit}.md
    filename = f"evaluation-report-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{commit}.md"
    filepath = reports_dir / filename

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


# ==============================================================================
# Benchmark Runner
# ==============================================================================


async def run_scenario(
    scenario_id: str,
    frameworks: list[str],
    timeout: float,
    output_json: bool = False,
    save_report: bool = True,
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

    # Generate and save markdown report
    if save_report:
        report_content = generate_markdown_report(scenario_id, scenario, results, eval_result)
        report_path = save_markdown_report(report_content, scenario_id)
        print(f"\n>>> Report saved: {report_path}")

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
                "response": r.response,
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
    save_report: bool = True,
) -> dict[str, Any]:
    """Run all scenarios and produce aggregate results."""
    all_results = {}
    winners = {}

    for scenario_id in SCENARIOS:
        result = await run_scenario(scenario_id, frameworks, timeout, output_json, save_report)
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
        win_counts: dict[str, int] = {}
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
  python scripts/benchmark_agents.py --scenario error-analysis --no-report
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
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip generating markdown report",
    )

    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return

    if args.all:
        await run_all_scenarios(
            args.frameworks, args.timeout, args.json, save_report=not args.no_report
        )
        return

    if args.scenario:
        await run_scenario(
            args.scenario, args.frameworks, args.timeout, args.json, save_report=not args.no_report
        )
        return

    # No action specified, show help
    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
