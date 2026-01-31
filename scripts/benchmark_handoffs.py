#!/usr/bin/env python3
"""
Cross-Agent Handoff Benchmark Script

Evaluates how well agents delegate tasks to each other using transfer tools.
Tests handoff detection, correct tool usage, and context preservation across frameworks.

Usage:
    python scripts/benchmark_handoffs.py                    # Run all handoff scenarios
    python scripts/benchmark_handoffs.py --scenario support-to-swe
    python scripts/benchmark_handoffs.py --frameworks autogen crewai
    python scripts/benchmark_handoffs.py --list

Scenarios:
    support-to-swe    - Bug report that needs code fix (Support -> SWE)
    support-to-sre    - Infrastructure issue (Support -> SRE)
    swe-to-release    - Code merged, needs deployment (SWE -> Release)
    pm-to-swe         - Feature request needs implementation (PM -> SWE)

Reports:
    Generated in reports/ directory with format: handoff-report-{date}-{time}-{commit}.md
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
from dotenv import load_dotenv

# Load .env file before reading configuration
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Script paths
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
RUN_SLACK_AGENT_SCRIPT = SCRIPT_DIR / "run_slack_framework_agent.py"


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
# Handoff Scenario Definitions
# ==============================================================================

HANDOFF_SCENARIOS = {
    "support-to-swe": {
        "name": "Bug Report -> Code Fix",
        "description": "Support receives bug report requiring code changes",
        "source_role": "support_engineer",
        "expected_target": "swe",
        "task": """A customer reports: "When I try to use the voice command feature, 
the browser crashes immediately after I say 'navigate to'. This started 
happening after the last update. I'm on Chrome 121 on Windows 11."

Analyze this bug report and determine:
1. What investigation is needed?
2. If this requires code changes, hand off to the appropriate team member.
3. What context should be provided in the handoff?

Use your transfer tools if you need help from another team member.
""",
        "evaluation_criteria": [
            "Correctly identifies this as a code/implementation issue",
            "Uses transfer_to_swe tool to delegate",
            "Includes relevant context (voice command, Chrome version, crash symptom)",
            "Explains what investigation is needed",
        ],
    },
    "support-to-sre": {
        "name": "Infrastructure Issue -> SRE",
        "description": "Support receives report about API latency/availability",
        "source_role": "support_engineer",
        "expected_target": "sre",
        "task": """Multiple customers are reporting: "The extension is very slow today. 
Commands that usually complete in 2 seconds are now taking 10-15 seconds. 
Some users are seeing 'connection timeout' errors."

This seems to be affecting users across different regions. The issue started 
about 2 hours ago.

Analyze this situation and determine:
1. Is this a code bug or infrastructure issue?
2. Who should investigate this?
3. What information should be gathered?

Use your transfer tools if you need help from another team member.
""",
        "evaluation_criteria": [
            "Correctly identifies this as infrastructure/monitoring issue",
            "Uses transfer_to_sre tool to delegate",
            "Includes timing information (started 2 hours ago)",
            "Notes the multi-region impact",
        ],
    },
    "swe-to-release": {
        "name": "Code Complete -> Deployment",
        "description": "SWE has completed a fix and needs deployment",
        "source_role": "software_engineer",
        "expected_target": "release",
        "task": """You've just completed and merged PR #456 which fixes the GraphRecursionError 
that was causing crashes. The PR includes:
- Fix for the execute-reflect loop detection
- Added recursion depth limit of 100
- Unit tests covering edge cases

The fix has been reviewed, CI passed, and it's merged to master.

Determine the next steps:
1. What needs to happen for users to get this fix?
2. Who should handle the deployment?
3. What information do they need?

Use your transfer tools to hand off to the appropriate team member.
""",
        "evaluation_criteria": [
            "Correctly identifies need for deployment",
            "Uses transfer_to_release tool to delegate",
            "Includes PR number and fix summary",
            "Notes that CI passed and code is merged",
        ],
    },
    "pm-to-swe": {
        "name": "Feature Request -> Implementation",
        "description": "PM receives feature request needing implementation",
        "source_role": "product_manager",
        "expected_target": "swe",
        "task": """Analyze this customer feature request and delegate appropriately:

"I'd love to have a keyboard shortcut to quickly toggle the extension on/off. 
Currently I have to click the extension icon and then click the toggle. 
A simple Ctrl+Shift+V would be much faster for my workflow."

Steps:
1. Analyze the feasibility and value of this request
2. If it should be implemented, assign priority
3. Hand off to the appropriate team member for implementation

Use your transfer tools to delegate implementation work.
""",
        "evaluation_criteria": [
            "Analyzes the feature request value/feasibility",
            "Uses transfer_to_swe tool to delegate implementation",
            "Provides clear requirements/acceptance criteria",
            "Assigns or suggests priority level",
        ],
    },
}

FRAMEWORKS = ["autogen", "crewai", "openhands"]


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class HandoffResult:
    """Result from running a handoff scenario."""

    framework: str
    response: str
    latency_ms: int
    success: bool
    error: str | None = None
    # Handoff detection
    used_transfer_tool: bool = False
    target_agent: str | None = None
    handoff_context: str | None = None


@dataclass
class HandoffScore:
    """Score for a handoff from evaluation."""

    framework: str
    score: int  # 0-5 scale
    used_correct_tool: bool
    target_correct: bool
    context_quality: int  # 0-5
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HandoffEvalResult:
    """Result from handoff evaluation."""

    scenario: str
    scores: dict[str, HandoffScore]  # framework -> score
    winner: str
    reasoning: str
    judge_model: str
    evaluation_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "winner": self.winner,
            "reasoning": self.reasoning,
            "judge_model": self.judge_model,
            "evaluation_time_ms": self.evaluation_time_ms,
        }


# ==============================================================================
# Handoff Detection
# ==============================================================================


def detect_handoff(response: str) -> tuple[bool, str | None, str | None]:
    """
    Detect if response contains a handoff.

    Returns:
        (used_transfer: bool, target_agent: str | None, context: str | None)
    """
    # Pattern 1: HANDOFF:agent:context format (internal)
    handoff_match = re.search(r"HANDOFF:(\w+):(.+?)(?:\n|$)", response, re.DOTALL)
    if handoff_match:
        return True, handoff_match.group(1), handoff_match.group(2).strip()

    # Pattern 2: @agent mention format (Slack)
    mention_match = re.search(
        r"@(swe|sre|release|support|pm|supervisor)\b", response, re.IGNORECASE
    )
    if mention_match:
        # Extract context after the mention
        context_start = mention_match.end()
        context = response[context_start : context_start + 500].strip()
        return True, mention_match.group(1).lower(), context

    # Pattern 3: "transfer_to_X" tool call pattern in response
    tool_match = re.search(
        r"transfer_to_(swe|sre|release|support|supervisor|marketer|pm)", response, re.IGNORECASE
    )
    if tool_match:
        # Try to extract context from the response
        return True, tool_match.group(1).lower(), None

    # Pattern 4: Natural language handoff indicators
    handoff_indicators = [
        (r"handing (?:this )?off to (\w+)", 1),
        (r"delegating to (\w+)", 1),
        (r"escalating to (\w+)", 1),
        (r"the (\w+ engineer|swe|sre) should handle", 1),
    ]
    for pattern, group in handoff_indicators:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            target = match.group(group).lower()
            # Normalize target names
            if "software" in target or target == "swe":
                target = "swe"
            elif "reliability" in target or "site" in target or target == "sre":
                target = "sre"
            elif "release" in target:
                target = "release"
            elif "support" in target:
                target = "support"
            return True, target, None

    return False, None, None


# ==============================================================================
# Handoff Evaluator (LLM-as-Judge)
# ==============================================================================


class HandoffEvaluator:
    """
    Evaluates handoff quality using LLM-as-judge.

    Scores handoffs on:
    - Correct identification of need to delegate
    - Use of correct transfer tool
    - Quality of context provided in handoff
    - Overall appropriateness
    """

    HANDOFF_EVAL_PROMPT = """You are an expert evaluator assessing AI agents' ability to delegate tasks appropriately.

SCENARIO: {scenario_name}
{scenario_description}

EXPECTED BEHAVIOR:
- Source agent: {source_role}
- Should delegate to: {expected_target}
- Evaluation criteria:
{criteria}

AGENT RESPONSES:

=== AUTOGEN ===
{autogen_response}

=== CREWAI ===
{crewai_response}

=== OPENHANDS ===
{openhands_response}

For each agent, evaluate:

1. **Used Correct Tool** (true/false): Did the agent use transfer_to_{expected_target} or equivalent?
2. **Target Correct** (true/false): Did the agent delegate to the right team member ({expected_target})?
3. **Context Quality** (0-5): How well did the agent preserve and communicate relevant context?
   - 0: No context provided
   - 1-2: Missing critical information
   - 3: Basic context provided
   - 4: Good context with key details
   - 5: Excellent context with all relevant info
4. **Overall Score** (0-5): Overall handoff quality
   - 0: Failed to delegate when needed
   - 1: Wrong delegation target
   - 2: Right target but poor context
   - 3: Acceptable handoff
   - 4: Good handoff with clear context
   - 5: Excellent handoff with comprehensive context

Return ONLY valid JSON in this exact format:
{{
  "autogen": {{"score": 0, "used_correct_tool": false, "target_correct": false, "context_quality": 0, "feedback": "Brief explanation"}},
  "crewai": {{"score": 0, "used_correct_tool": false, "target_correct": false, "context_quality": 0, "feedback": "Brief explanation"}},
  "openhands": {{"score": 0, "used_correct_tool": false, "target_correct": false, "context_quality": 0, "feedback": "Brief explanation"}},
  "winner": "framework_name",
  "reasoning": "One sentence explaining why this framework won"
}}"""

    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()

    async def evaluate(
        self,
        scenario_id: str,
        scenario: dict[str, Any],
        responses: dict[str, str],
    ) -> HandoffEvalResult:
        """Evaluate handoff quality across frameworks."""
        start_time = time.perf_counter()

        # Format criteria as bullet list
        criteria_formatted = "\n".join(f"  - {c}" for c in scenario.get("evaluation_criteria", []))

        # Truncate responses for prompt
        autogen_resp = responses.get("autogen", "(No response)")[:3000]
        crewai_resp = responses.get("crewai", "(No response)")[:3000]
        openhands_resp = responses.get("openhands", "(No response)")[:3000]

        prompt = self.HANDOFF_EVAL_PROMPT.format(
            scenario_name=scenario["name"],
            scenario_description=scenario["description"],
            source_role=scenario["source_role"],
            expected_target=scenario["expected_target"],
            criteria=criteria_formatted,
            autogen_response=autogen_resp,
            crewai_response=crewai_resp,
            openhands_response=openhands_resp,
        )

        try:
            result_json = await self._call_llm(prompt)
            result = self._parse_result(result_json, scenario_id)
            result.judge_model = self.config.JUDGE_MODEL
            result.evaluation_time_ms = int((time.perf_counter() - start_time) * 1000)
            return result
        except Exception as e:
            return HandoffEvalResult(
                scenario=scenario_id,
                scores={
                    fw: HandoffScore(
                        framework=fw,
                        score=0,
                        used_correct_tool=False,
                        target_correct=False,
                        context_quality=0,
                        feedback=f"Evaluation error: {e}",
                    )
                    for fw in ["autogen", "crewai", "openhands"]
                },
                winner="none",
                reasoning=f"Evaluation failed: {e}",
                judge_model=self.config.JUDGE_MODEL,
                evaluation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    async def _call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI for evaluation."""
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
                    "max_completion_tokens": 1000,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_result(self, json_str: str, scenario_id: str) -> HandoffEvalResult:
        """Parse JSON result from LLM response."""
        json_match = re.search(r"\{[\s\S]*\}", json_str)
        if not json_match:
            raise ValueError("No JSON found in LLM response")

        data = json.loads(json_match.group())

        scores = {}
        for framework in ["autogen", "crewai", "openhands"]:
            fw_data = data.get(framework, {})
            scores[framework] = HandoffScore(
                framework=framework,
                score=int(fw_data.get("score", 0)),
                used_correct_tool=bool(fw_data.get("used_correct_tool", False)),
                target_correct=bool(fw_data.get("target_correct", False)),
                context_quality=int(fw_data.get("context_quality", 0)),
                feedback=str(fw_data.get("feedback", "No feedback")),
            )

        return HandoffEvalResult(
            scenario=scenario_id,
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
    role_map = {
        "support_engineer": "support_engineer",
        "software_engineer": "software_engineer",
        "release_engineer": "release_engineer",
        "product_manager": "product_manager",
    }

    mapped_role = role_map.get(role, role)

    if framework == "autogen":
        if mapped_role == "support_engineer":
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif mapped_role == "software_engineer":
            from agents.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
        elif mapped_role == "release_engineer":
            from agents.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
        elif mapped_role == "product_manager":
            from agents.autogen.product_manager import AutoGenProductManager

            return AutoGenProductManager
    elif framework == "crewai":
        if mapped_role == "support_engineer":
            from agents.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif mapped_role == "software_engineer":
            from agents.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
        elif mapped_role == "release_engineer":
            from agents.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
        elif mapped_role == "product_manager":
            from agents.crewai.product_manager import CrewAIProductManager

            return CrewAIProductManager
    elif framework == "openhands":
        if mapped_role == "support_engineer":
            from agents.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif mapped_role == "software_engineer":
            from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

            return OpenHandsSoftwareEngineer
        elif mapped_role == "release_engineer":
            from agents.openhands.release_engineer import OpenHandsReleaseEngineer

            return OpenHandsReleaseEngineer
        elif mapped_role == "product_manager":
            from agents.openhands.product_manager import OpenHandsProductManager

            return OpenHandsProductManager

    raise ValueError(f"Unknown framework/role: {framework}/{role}")


async def run_agent(framework: str, role: str, task: str, timeout: float) -> HandoffResult:
    """Run an agent and detect handoff behavior."""
    start_time = time.perf_counter()

    try:
        agent_class = get_agent_class(framework, role)
        agent = agent_class()

        # Run with appropriate kwargs
        run_kwargs: dict[str, Any] = {"task": task}
        if framework == "openhands":
            # Enable tools for handoff detection (we want to see transfer tool usage)
            run_kwargs["use_tools"] = True
            run_kwargs["skip_context_injection"] = True

        result = await asyncio.wait_for(agent.run_async(**run_kwargs), timeout=timeout)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        response = result.get("response", "")

        # Detect handoff in response
        used_transfer, target, context = detect_handoff(response)

        return HandoffResult(
            framework=framework,
            response=response,
            latency_ms=latency_ms,
            success=True,
            used_transfer_tool=used_transfer,
            target_agent=target,
            handoff_context=context,
        )
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return HandoffResult(
            framework=framework,
            response="",
            latency_ms=latency_ms,
            success=False,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return HandoffResult(
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


def print_handoff_result(result: HandoffResult, expected_target: str) -> None:
    """Print a single handoff result."""
    status = "PASS" if result.success else "FAIL"
    handoff_status = "YES" if result.used_transfer_tool else "NO"
    target_correct = "YES" if result.target_agent == expected_target else "NO"

    print(f"\n{'=' * 70}")
    print(f"FRAMEWORK: {result.framework.upper()}")
    print(f"STATUS:    [{status}]")
    print(f"LATENCY:   {result.latency_ms}ms")
    print(
        f"HANDOFF:   {handoff_status} -> {result.target_agent or 'none'} (expected: {expected_target})"
    )
    print(f"CORRECT:   {target_correct}")

    if result.error:
        print(f"ERROR:     {result.error}")

    print(f"{'─' * 70}")
    print("RESPONSE (first 1000 chars):")
    print(f"{'─' * 70}")
    response = result.response[:1000] if result.response else "(No response)"
    print(response)
    if len(result.response) > 1000:
        print(f"\n... (truncated, {len(result.response)} chars total)")
    print(f"{'=' * 70}")


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
    results: list[HandoffResult],
    eval_result: HandoffEvalResult,
) -> str:
    """Generate markdown handoff evaluation report."""
    now = datetime.now(timezone.utc)
    commit = get_git_commit()

    lines = [
        f"# Cross-Agent Handoff Evaluation Report",
        "",
        f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Commit**: `{commit}`",
        f"**Scenario**: {scenario['name']} (`{scenario_id}`)",
        f"**Source Role**: {scenario['source_role']}",
        f"**Expected Target**: {scenario['expected_target']}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Framework | Status | Latency | Handoff? | Target | Correct? | Score | Context |",
        "|-----------|--------|---------|----------|--------|----------|-------|---------|",
    ]

    for r in sorted(
        results,
        key=lambda x: -eval_result.scores.get(
            x.framework, HandoffScore(x.framework, 0, False, False, 0, "")
        ).score,
    ):
        score = eval_result.scores.get(
            r.framework, HandoffScore(r.framework, 0, False, False, 0, "N/A")
        )
        status = "PASS" if r.success else "FAIL"
        handoff = "Yes" if r.used_transfer_tool else "No"
        target = r.target_agent or "-"
        correct = "Yes" if r.target_agent == scenario["expected_target"] else "No"
        lines.append(
            f"| {r.framework.upper()} | {status} | {r.latency_ms}ms | {handoff} | {target} | {correct} | {score.score}/5 | {score.context_quality}/5 |"
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
            "## Evaluation Criteria",
            "",
        ]
    )

    for criterion in scenario.get("evaluation_criteria", []):
        lines.append(f"- {criterion}")

    lines.extend(
        [
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
        score = eval_result.scores.get(
            r.framework, HandoffScore(r.framework, 0, False, False, 0, "N/A")
        )
        lines.extend(
            [
                f"## {r.framework.upper()} Response",
                "",
                f"**Score**: {score.score}/5 | **Context Quality**: {score.context_quality}/5",
                f"**Used Correct Tool**: {score.used_correct_tool} | **Target Correct**: {score.target_correct}",
                f"**Feedback**: {score.feedback}",
                f"**Latency**: {r.latency_ms}ms",
                "",
            ]
        )

        if r.error:
            lines.append(f"**Error**: {r.error}\n")

        if r.used_transfer_tool:
            lines.append(f"**Handoff Detected**: -> {r.target_agent}")
            if r.handoff_context:
                lines.extend(
                    [
                        "",
                        "**Handoff Context**:",
                        "```",
                        r.handoff_context[:500],
                        "```",
                    ]
                )

        if r.response:
            lines.extend(
                [
                    "",
                    "### Full Response",
                    "",
                    "```",
                    r.response[:2000],
                    "```"
                    if len(r.response) <= 2000
                    else f"```\n... (truncated, {len(r.response)} chars)",
                    "",
                ]
            )

        lines.append("---\n")

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

    reports_dir = BenchmarkConfig.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"handoff-report-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{commit}.md"
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
    """Run a single handoff scenario across all frameworks."""
    scenario = HANDOFF_SCENARIOS[scenario_id]

    print_header(f"HANDOFF SCENARIO: {scenario['name']}")
    print(f"Description: {scenario['description']}")
    print(f"Source: {scenario['source_role']} -> Expected Target: {scenario['expected_target']}")
    print(f"Timeout: {timeout}s per framework")
    print(f"Frameworks: {', '.join(frameworks)}")

    results: list[HandoffResult] = []
    responses: dict[str, str] = {}

    for framework in frameworks:
        print(f"\n>>> Running {framework.upper()} {scenario['source_role']}...")
        result = await run_agent(framework, scenario["source_role"], scenario["task"], timeout)
        results.append(result)
        responses[framework] = result.response

        if not output_json:
            print_handoff_result(result, scenario["expected_target"])

    # Run LLM-as-judge evaluation
    print("\n>>> Running LLM-as-Judge Handoff Evaluation...")
    evaluator = HandoffEvaluator()
    eval_result = await evaluator.evaluate(scenario_id, scenario, responses)

    if not output_json:
        print_header("HANDOFF EVALUATION RESULTS")
        for fw, score in sorted(eval_result.scores.items(), key=lambda x: -x[1].score):
            print(f"{fw.upper()}: {score.score}/5")
            print(
                f"  Tool Correct: {score.used_correct_tool} | Target Correct: {score.target_correct}"
            )
            print(f"  Context Quality: {score.context_quality}/5")
            print(f"  Feedback: {score.feedback}")
            print()
        print(f"WINNER: {eval_result.winner.upper()}")
        print(f"Reasoning: {eval_result.reasoning}")

    # Save report
    if save_report:
        report = generate_markdown_report(scenario_id, scenario, results, eval_result)
        report_path = save_markdown_report(report, scenario_id)
        print(f"\n>>> Report saved: {report_path}")

    output = {
        "scenario": scenario_id,
        "scenario_name": scenario["name"],
        "source_role": scenario["source_role"],
        "expected_target": scenario["expected_target"],
        "results": [
            {
                "framework": r.framework,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "used_transfer_tool": r.used_transfer_tool,
                "target_agent": r.target_agent,
                "target_correct": r.target_agent == scenario["expected_target"],
                "error": r.error,
            }
            for r in results
        ],
        "evaluation": eval_result.to_dict(),
        "winner": eval_result.winner,
    }

    if output_json:
        print(json.dumps(output, indent=2))

    return output


async def run_all_scenarios(
    frameworks: list[str],
    timeout: float,
    output_json: bool = False,
    save_report: bool = True,
) -> dict[str, Any]:
    """Run all handoff scenarios."""
    all_results = {}
    winners = {}

    for scenario_id in HANDOFF_SCENARIOS:
        result = await run_scenario(scenario_id, frameworks, timeout, output_json, save_report)
        all_results[scenario_id] = result
        winners[scenario_id] = result["winner"]

    if not output_json:
        print_header("AGGREGATE HANDOFF RESULTS")
        print(f"{'Scenario':<20} {'Winner':<15}")
        print("-" * 40)
        for scenario_id, winner in winners.items():
            print(f"{scenario_id:<20} {winner.upper():<15}")

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
    """List available handoff scenarios."""
    print_header("AVAILABLE HANDOFF SCENARIOS")
    print(f"{'ID':<20} {'Name':<30} {'Source':<20} {'Target':<10}")
    print("-" * 80)
    for sid, s in HANDOFF_SCENARIOS.items():
        print(f"{sid:<20} {s['name']:<30} {s['source_role']:<20} {s['expected_target']:<10}")
    print()
    print("Usage examples:")
    print("  python scripts/benchmark_handoffs.py --scenario support-to-swe")
    print("  python scripts/benchmark_handoffs.py --all")
    print("  python scripts/benchmark_handoffs.py --frameworks autogen crewai")
    print("  python scripts/benchmark_handoffs.py --e2e --scenario support-to-swe")


# ==============================================================================
# E2E Slack Testing
# ==============================================================================


# Map role names to agent short names for the Slack runner
ROLE_TO_AGENT_KEY = {
    "support_engineer": "support",
    "software_engineer": "swe",
    "release_engineer": "release",
    "product_manager": "pm",
    "site_reliability_engineer": "sre",
    "marketing_manager": "marketer",
}

# Map expected targets to agent keys
TARGET_TO_AGENT_KEY = {
    "swe": "swe",
    "sre": "sre",
    "release": "release",
    "support": "support",
    "pm": "pm",
    "marketer": "marketer",
}


class E2EHandoffTester:
    """
    End-to-end handoff testing via real Slack.

    Starts agent processes, posts test message to Slack, and verifies
    that the correct handoff chain occurs.
    """

    def __init__(
        self,
        framework: str,
        channel: str | None = None,
        poll_interval: int = 3,
        timeout: float = 180.0,
    ):
        self.framework = framework
        self.channel = channel or os.getenv("SLACK_CHANNEL", "#ai-team-test")
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.processes: list[subprocess.Popen] = []
        self.connector = None

    def setup(self):
        """Set up Slack connector."""
        from vibeteam.connectors.slack import SlackConnector

        self.connector = SlackConnector()
        print(f"[E2E] Slack connected, channel: {self.channel}")

    def start_agent(self, agent_key: str) -> subprocess.Popen:
        """Start an agent as a Slack listener subprocess."""
        cmd = [
            sys.executable,
            str(RUN_SLACK_AGENT_SCRIPT),
            "--framework",
            self.framework,
            "--agent",
            agent_key,
            "--channel",
            self.channel,
            "--poll-interval",
            str(self.poll_interval),
        ]
        print(f"[E2E] Starting {self.framework}/{agent_key}: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.processes.append(process)
        return process

    def stop_all_agents(self):
        """Stop all running agent processes."""
        print(f"[E2E] Stopping {len(self.processes)} agent processes...")
        for proc in self.processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception as e:
                print(f"[E2E] Error stopping process: {e}")
        self.processes = []

    def post_test_message(self, agent_key: str, task: str) -> str:
        """Post a test message to Slack mentioning the agent. Returns thread_ts."""
        if self.connector is None:
            raise RuntimeError("Slack connector not initialized. Call setup() first.")
        message = f"@{agent_key} {task}"
        result = self.connector.post_message(
            channel=self.channel,
            text=message,
        )
        ts = result.ts  # SlackMessage.ts attribute
        print(f"[E2E] Posted test message (ts={ts}): {message[:100]}...")
        return ts

    def get_thread_messages(self, thread_ts: str) -> list[dict[str, Any]]:
        """Get all messages in a thread."""
        if self.connector is None:
            raise RuntimeError("Slack connector not initialized. Call setup() first.")
        messages = self.connector.get_thread_replies(
            channel=self.channel,
            thread_ts=thread_ts,
        )
        return [{"text": m.text, "user": m.user, "ts": m.ts, "is_bot": m.is_bot} for m in messages]

    def wait_for_handoff(
        self,
        thread_ts: str,
        expected_target: str,
        max_wait: float,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """
        Wait for a handoff to occur in the thread.

        Returns (success, messages) where success is True if the expected
        target was @mentioned in the thread.
        """
        start_time = time.perf_counter()
        last_message_count = 0

        while (time.perf_counter() - start_time) < max_wait:
            messages = self.get_thread_messages(thread_ts)

            if len(messages) > last_message_count:
                last_message_count = len(messages)
                print(f"[E2E] Thread has {len(messages)} messages")

                # Check if expected target was mentioned
                for msg in messages:
                    text = msg.get("text", "").lower()
                    # Check for @mention of target
                    if f"@{expected_target}" in text:
                        print(f"[E2E] Found handoff to @{expected_target}!")
                        return True, messages

                    # Also check for transfer_to pattern in response
                    if f"transfer_to_{expected_target}" in text:
                        print(f"[E2E] Found transfer_to_{expected_target} in response")
                        return True, messages

            time.sleep(self.poll_interval)

        print(f"[E2E] Timeout waiting for handoff to {expected_target}")
        return False, self.get_thread_messages(thread_ts)

    async def run_scenario(
        self,
        scenario_id: str,
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        """Run an E2E test for a handoff scenario."""
        source_role: str = scenario["source_role"]
        expected_target: str = scenario["expected_target"]
        task: str = scenario["task"]

        # Get agent keys with explicit type handling
        source_agent_key: str = ROLE_TO_AGENT_KEY.get(source_role) or source_role
        target_agent_key: str = TARGET_TO_AGENT_KEY.get(expected_target) or expected_target

        print_header(f"E2E TEST: {scenario['name']}")
        print(f"Framework: {self.framework}")
        print(f"Source: {source_agent_key} -> Expected Target: {target_agent_key}")
        print(f"Channel: {self.channel}")

        start_time = time.perf_counter()

        try:
            # Start both source and target agents
            print("\n>>> Starting agents...")
            self.start_agent(source_agent_key)
            if source_agent_key != target_agent_key:
                self.start_agent(target_agent_key)

            # Give agents time to initialize
            await asyncio.sleep(3)

            # Post test message
            print("\n>>> Posting test message...")
            thread_ts = self.post_test_message(source_agent_key, task)

            # Wait for handoff
            print("\n>>> Waiting for handoff...")
            success, messages = self.wait_for_handoff(
                thread_ts=thread_ts,
                expected_target=target_agent_key,
                max_wait=self.timeout,
            )

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Analyze messages for handoff detection
            handoff_detected = False
            handoff_context = None
            for msg in messages:
                text = msg.get("text", "")
                if msg.get("is_bot"):  # Bot message
                    used_transfer, target, context = detect_handoff(text)
                    if used_transfer and target == expected_target:
                        handoff_detected = True
                        handoff_context = context
                        break

            result = {
                "scenario": scenario_id,
                "framework": self.framework,
                "success": success,
                "handoff_detected": handoff_detected,
                "expected_target": expected_target,
                "latency_ms": latency_ms,
                "message_count": len(messages),
                "thread_ts": thread_ts,
                "channel": self.channel,
                "handoff_context": handoff_context,
                "messages": [
                    {"text": m.get("text", "")[:500], "bot": bool(m.get("is_bot"))}
                    for m in messages
                ],
            }

            # Print result
            status = "PASS" if success else "FAIL"
            print(f"\n{'=' * 60}")
            print(f"RESULT: [{status}]")
            print(f"Handoff detected: {handoff_detected}")
            print(f"Latency: {latency_ms}ms")
            print(f"Messages in thread: {len(messages)}")
            print(f"{'=' * 60}")

            return result

        finally:
            # Cleanup
            self.stop_all_agents()


async def run_e2e_scenario(
    scenario_id: str,
    framework: str,
    channel: str | None = None,
    timeout: float = 180.0,
    output_json: bool = False,
) -> dict[str, Any]:
    """Run an E2E handoff test for a scenario."""
    scenario = HANDOFF_SCENARIOS[scenario_id]

    tester = E2EHandoffTester(
        framework=framework,
        channel=channel,
        timeout=timeout,
    )
    tester.setup()

    result = await tester.run_scenario(scenario_id, scenario)

    if output_json:
        print(json.dumps(result, indent=2))

    return result


async def run_all_e2e_scenarios(
    framework: str,
    channel: str | None = None,
    timeout: float = 180.0,
    output_json: bool = False,
) -> dict[str, Any]:
    """Run E2E tests for all handoff scenarios."""
    results = {}
    summary = {"passed": 0, "failed": 0}

    for scenario_id in HANDOFF_SCENARIOS:
        print(f"\n{'#' * 70}")
        print(f"# SCENARIO: {scenario_id}")
        print(f"{'#' * 70}")

        result = await run_e2e_scenario(
            scenario_id=scenario_id,
            framework=framework,
            channel=channel,
            timeout=timeout,
            output_json=False,
        )
        results[scenario_id] = result

        if result["success"]:
            summary["passed"] += 1
        else:
            summary["failed"] += 1

        # Brief pause between scenarios
        await asyncio.sleep(5)

    # Print summary
    print_header("E2E TEST SUMMARY")
    print(f"Framework: {framework}")
    print(f"Passed: {summary['passed']}/{len(HANDOFF_SCENARIOS)}")
    print(f"Failed: {summary['failed']}/{len(HANDOFF_SCENARIOS)}")
    print()

    for scenario_id, result in results.items():
        status = "PASS" if result["success"] else "FAIL"
        print(f"  [{status}] {scenario_id}: {result['latency_ms']}ms")

    output = {
        "framework": framework,
        "scenarios": results,
        "summary": summary,
    }

    if output_json:
        print(json.dumps(output, indent=2))

    return output


# ==============================================================================
# CLI
# ==============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark cross-agent handoff behavior",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Unit testing (simulated handoffs)
  python scripts/benchmark_handoffs.py --list
  python scripts/benchmark_handoffs.py --scenario support-to-swe
  python scripts/benchmark_handoffs.py --all
  python scripts/benchmark_handoffs.py --frameworks autogen crewai --timeout 120

  # E2E testing (real Slack)
  python scripts/benchmark_handoffs.py --e2e --scenario support-to-swe --framework autogen
  python scripts/benchmark_handoffs.py --e2e --all --framework autogen --channel "#ai-team-test"
        """,
    )
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--scenario", type=str, choices=list(HANDOFF_SCENARIOS.keys()))
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--frameworks", nargs="+", default=FRAMEWORKS, choices=FRAMEWORKS)
    parser.add_argument(
        "--framework", type=str, choices=FRAMEWORKS, help="Single framework for E2E tests"
    )
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--no-report", action="store_true", help="Skip markdown report")
    # E2E testing options
    parser.add_argument("--e2e", action="store_true", help="Run E2E tests via real Slack")
    parser.add_argument("--channel", type=str, default=None, help="Slack channel for E2E tests")

    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return

    # E2E testing mode
    if args.e2e:
        framework = args.framework or args.frameworks[0]
        if args.all:
            await run_all_e2e_scenarios(
                framework=framework,
                channel=args.channel,
                timeout=args.timeout,
                output_json=args.json,
            )
            return
        elif args.scenario:
            await run_e2e_scenario(
                scenario_id=args.scenario,
                framework=framework,
                channel=args.channel,
                timeout=args.timeout,
                output_json=args.json,
            )
            return
        else:
            print("E2E mode requires --scenario or --all")
            parser.print_help()
            return

    # Standard (simulated) testing mode
    if args.all:
        await run_all_scenarios(args.frameworks, args.timeout, args.json, not args.no_report)
        return

    if args.scenario:
        await run_scenario(
            args.scenario, args.frameworks, args.timeout, args.json, not args.no_report
        )
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
