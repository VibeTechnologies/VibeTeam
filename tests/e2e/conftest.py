"""
E2E Test Configuration and Fixtures - Real Agents and DeepEval Integration.

Provides fixtures for end-to-end tests using:
- Real agents (OpenHands, AutoGen, CrewAI)
- Real Slack integration
- Real GitHub integration
- DeepEval with G-Eval metrics using Azure GPT-5.2

Environment Variables Required:
- AZURE_OPENAI_API_KEY or AZURE_API_KEY
- AZURE_OPENAI_ENDPOINT or AZURE_API_BASE
- AZURE_API_VERSION (default: 2024-12-01-preview)
- BENCHMARK_JUDGE_MODEL (default: gpt-5-2)
- SLACK_BOT_TOKEN
- SLACK_DEFAULT_CHANNEL (optional)
- GITHUB_TOKEN

Install DeepEval: pip install deepeval>=1.0.0
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

if TYPE_CHECKING:
    from vibeteam.connectors.slack import SlackConnector
    from vibeteam.router.models import AgentRole


# ==============================================================================
# Azure GPT-5.2 Evaluator Configuration
# ==============================================================================


@dataclass
class EvaluatorConfig:
    """Configuration for Azure GPT-5.2 judge model."""

    api_key: str
    api_base: str
    api_version: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 2000

    @classmethod
    def from_env(cls) -> "EvaluatorConfig":
        """Create config from environment variables."""
        api_key = os.getenv("AZURE_OPENAI_API_KEY", os.getenv("AZURE_API_KEY", ""))
        api_base = os.getenv("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_API_BASE", ""))
        api_version = os.getenv("AZURE_API_VERSION", "2024-12-01-preview")
        model = os.getenv("BENCHMARK_JUDGE_MODEL", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-2"))

        if not api_key:
            raise ValueError("AZURE_API_KEY or AZURE_OPENAI_API_KEY environment variable not set")
        if not api_base:
            raise ValueError("AZURE_API_BASE or AZURE_OPENAI_ENDPOINT environment variable not set")

        # Ensure API base has protocol
        if not api_base.startswith(("http://", "https://")):
            api_base = f"https://{api_base}"

        return cls(
            api_key=api_key,
            api_base=api_base.rstrip("/"),
            api_version=api_version,
            model=model,
        )

    def get_endpoint_url(self) -> str:
        """Get the full endpoint URL for chat completions."""
        return f"{self.api_base}/openai/deployments/{self.model}/chat/completions"


@pytest.fixture(scope="session")
def evaluator_config() -> EvaluatorConfig:
    """Provide Azure GPT-5.2 evaluator configuration."""
    try:
        return EvaluatorConfig.from_env()
    except ValueError as e:
        pytest.skip(f"Azure OpenAI credentials not configured: {e}")


# ==============================================================================
# DeepEval Azure OpenAI Integration
# ==============================================================================

# Flag to track if DeepEval is available
DEEPEVAL_AVAILABLE = False
try:
    from deepeval.metrics import GEval
    from deepeval.models.base_model import DeepEvalBaseLLM
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    DEEPEVAL_AVAILABLE = True
except ImportError:
    # DeepEval not installed - will fall back to custom evaluator
    GEval = None
    DeepEvalBaseLLM = object  # type: ignore
    LLMTestCase = None
    LLMTestCaseParams = None


class AzureOpenAIModel(DeepEvalBaseLLM):
    """
    Azure OpenAI wrapper for DeepEval.

    Implements the DeepEvalBaseLLM interface to use Azure GPT-5.2 as the judge model.
    This allows DeepEval's GEval metrics to use Azure OpenAI for evaluation.
    """

    def __init__(self, config: EvaluatorConfig):
        self.config = config
        self._model_name = f"azure/{config.model}"

    def load_model(self):
        """Load the model (no-op for API-based model)."""
        return self

    def generate(self, prompt: str) -> str:
        """Generate a response synchronously."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self.a_generate(prompt))

    async def a_generate(self, prompt: str) -> str:
        """Generate a response asynchronously using Azure OpenAI."""
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                self.config.get_endpoint_url(),
                headers={
                    "api-key": self.config.api_key,
                    "Content-Type": "application/json",
                },
                params={"api-version": self.config.api_version},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.config.temperature,
                    "max_completion_tokens": self.config.max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def get_model_name(self) -> str:
        """Return the model name for logging."""
        return self._model_name


@pytest.fixture(scope="session")
def azure_deepeval_model(evaluator_config: EvaluatorConfig) -> AzureOpenAIModel:
    """Provide Azure OpenAI model for DeepEval."""
    if not DEEPEVAL_AVAILABLE:
        pytest.skip("DeepEval not installed. Install with: pip install deepeval>=1.0.0")
    return AzureOpenAIModel(evaluator_config)


# ==============================================================================
# G-Eval Metrics as per requirements.md
# ==============================================================================

# Per-agent thresholds from requirements.md
AGENT_THRESHOLDS = {
    "software_engineer": {
        "task_completion": 0.75,
        "handoff_quality": 0.70,
        "professionalism": 0.70,
    },
    "release_engineer": {"task_completion": 0.75, "handoff_quality": 0.70, "professionalism": 0.70},
    "support_engineer": {"task_completion": 0.75, "handoff_quality": 0.70, "professionalism": 0.80},
    "product_manager": {"task_completion": 0.70, "handoff_quality": 0.70, "professionalism": 0.80},
    "marketing_manager": {
        "task_completion": 0.70,
        "handoff_quality": 0.65,
        "professionalism": 0.85,
    },
}


def get_threshold(role: str, metric: str) -> float:
    """Get the threshold for a specific agent role and metric."""
    role_thresholds = AGENT_THRESHOLDS.get(role, AGENT_THRESHOLDS["software_engineer"])
    return role_thresholds.get(metric, 0.7)


def create_task_completion_metric(model: AzureOpenAIModel, role: str = "software_engineer"):
    """
    Create a TaskCompletion G-Eval metric.

    Evaluates: Did the agent complete the requested task?
    """
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="TaskCompletion",
        criteria=(
            "Did the agent complete the requested task? Consider tool usage, "
            "output quality, and whether the user's intent was satisfied."
        ),
        evaluation_steps=[
            "Check if the agent understood the task correctly",
            "Verify the agent took appropriate actions",
            "Assess if the output is helpful and accurate",
            "Determine if the task was completed or needs follow-up",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=get_threshold(role, "task_completion"),
        model=model,
    )


def create_handoff_quality_metric(model: AzureOpenAIModel, role: str = "software_engineer"):
    """
    Create a HandoffQuality G-Eval metric.

    Evaluates: Was context preserved during handoff?
    """
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="HandoffQuality",
        criteria=(
            "Was context preserved during handoff? Did the receiving agent "
            "understand the task without re-explanation?"
        ),
        evaluation_steps=[
            "Check if the handoff was clearly signaled with @/RoleName mention",
            "Verify sufficient context was provided for the receiving agent",
            "Assess if the receiving agent could understand and continue the task",
            "Determine if any critical information was lost in the handoff",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=get_threshold(role, "handoff_quality"),
        model=model,
    )


def create_professionalism_metric(model: AzureOpenAIModel, role: str = "software_engineer"):
    """
    Create a Professionalism G-Eval metric.

    Evaluates: Clear, concise, professional communication.
    """
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="Professionalism",
        criteria=("Clear, concise, professional communication. Appropriate tone for the audience."),
        evaluation_steps=[
            "Check if the response is clear and well-structured",
            "Verify the tone is professional and appropriate",
            "Assess if the language is concise without unnecessary jargon",
            "Determine if the response would be suitable for a workplace context",
        ],
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=get_threshold(role, "professionalism"),
        model=model,
    )


def create_tool_usage_metric(model: AzureOpenAIModel):
    """
    Create a ToolUsage G-Eval metric.

    Evaluates: Did the agent use appropriate tools?
    """
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="ToolUsage",
        criteria=(
            "Did the agent use appropriate tools? Were tools called with correct parameters?"
        ),
        evaluation_steps=[
            "Check if the agent identified which tools were needed",
            "Verify the agent used the correct tools for the task",
            "Assess if tool parameters were appropriate",
            "Determine if tool results were interpreted correctly",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=model,
    )


def create_context_preservation_metric(model: AzureOpenAIModel):
    """
    Create a ContextPreservation G-Eval metric.

    Evaluates: Does agent maintain conversation context across messages?
    """
    if not DEEPEVAL_AVAILABLE:
        return None

    return GEval(
        name="ContextPreservation",
        criteria=(
            "Does the agent maintain conversation context across messages in a thread? "
            "Are previous messages and context referenced appropriately?"
        ),
        evaluation_steps=[
            "Check if the agent references relevant prior context",
            "Verify the agent maintains continuity with previous messages",
            "Assess if the agent tracks the overall conversation goal",
            "Determine if context is appropriately summarized when needed",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
        model=model,
    )


@pytest.fixture
def task_completion_metric(azure_deepeval_model: AzureOpenAIModel):
    """Provide TaskCompletion metric with default thresholds."""
    return create_task_completion_metric(azure_deepeval_model)


@pytest.fixture
def handoff_quality_metric(azure_deepeval_model: AzureOpenAIModel):
    """Provide HandoffQuality metric with default thresholds."""
    return create_handoff_quality_metric(azure_deepeval_model)


@pytest.fixture
def professionalism_metric(azure_deepeval_model: AzureOpenAIModel):
    """Provide Professionalism metric with default thresholds."""
    return create_professionalism_metric(azure_deepeval_model)


@pytest.fixture
def tool_usage_metric(azure_deepeval_model: AzureOpenAIModel):
    """Provide ToolUsage metric."""
    return create_tool_usage_metric(azure_deepeval_model)


@pytest.fixture
def context_preservation_metric(azure_deepeval_model: AzureOpenAIModel):
    """Provide ContextPreservation metric."""
    return create_context_preservation_metric(azure_deepeval_model)


# ==============================================================================
# NOTE: GPT52Evaluator has been removed. Use DeepEval GEval metrics instead.
# See: create_task_completion_metric, create_handoff_quality_metric, etc.
# ==============================================================================


# ==============================================================================
# Real Slack Connector Fixture
# ==============================================================================


@pytest.fixture(scope="session")
def slack_connector():
    """
    Provide a real SlackConnector instance.

    Requires SLACK_BOT_TOKEN environment variable.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        pytest.skip("SLACK_BOT_TOKEN not set - skipping Slack integration tests")

    from vibeteam.connectors.slack import SlackConnector

    return SlackConnector(token=token)


@pytest.fixture
def slack_test_channel() -> str:
    """Get the test channel for Slack E2E tests."""
    return os.getenv("SLACK_TEST_CHANNEL", os.getenv("SLACK_DEFAULT_CHANNEL", "#ai-team-test"))


# ==============================================================================
# Real Agent Fixtures
# ==============================================================================


def get_agent_class(framework: str, role: str):
    """Import and return the agent class for the given framework and role."""
    if framework == "autogen":
        if role == "software_engineer":
            from agents.autogen.software_engineer import AutoGenSoftwareEngineer

            return AutoGenSoftwareEngineer
        elif role == "support_engineer":
            from agents.autogen.support_engineer import AutoGenSupportEngineer

            return AutoGenSupportEngineer
        elif role == "release_engineer":
            from agents.autogen.release_engineer import AutoGenReleaseEngineer

            return AutoGenReleaseEngineer
        elif role == "product_manager":
            from agents.autogen.product_manager import AutoGenProductManager

            return AutoGenProductManager
        elif role == "marketing_manager":
            from agents.autogen.marketing_manager import AutoGenMarketingManager

            return AutoGenMarketingManager
    elif framework == "crewai":
        if role == "software_engineer":
            from agents.crewai.software_engineer import CrewAISoftwareEngineer

            return CrewAISoftwareEngineer
        elif role == "support_engineer":
            from agents.crewai.support_engineer import CrewAISupportEngineer

            return CrewAISupportEngineer
        elif role == "release_engineer":
            from agents.crewai.release_engineer import CrewAIReleaseEngineer

            return CrewAIReleaseEngineer
        elif role == "product_manager":
            from agents.crewai.product_manager import CrewAIProductManager

            return CrewAIProductManager
        elif role == "marketing_manager":
            from agents.crewai.marketing_manager import CrewAIMarketingManager

            return CrewAIMarketingManager
    elif framework == "openhands":
        if role == "software_engineer":
            from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

            return OpenHandsSoftwareEngineer
        elif role == "support_engineer":
            from agents.openhands.support_engineer import OpenHandsSupportEngineer

            return OpenHandsSupportEngineer
        elif role == "release_engineer":
            from agents.openhands.release_engineer import OpenHandsReleaseEngineer

            return OpenHandsReleaseEngineer
        elif role == "product_manager":
            from agents.openhands.product_manager import OpenHandsProductManager

            return OpenHandsProductManager
        elif role == "marketing_manager":
            from agents.openhands.marketing_manager import OpenHandsMarketingManager

            return OpenHandsMarketingManager

    raise ValueError(f"Unknown framework/role: {framework}/{role}")


class RealAgentRunner:
    """
    Runner for real agents across all frameworks.

    Provides a unified interface to run agents and collect responses.
    """

    def __init__(self, framework: str = "openhands", timeout: float = 180.0):
        self.framework = framework
        self.timeout = timeout
        self.call_history: list[dict] = []

    async def run(
        self,
        role: str,
        task: str,
        context_type: str = "e2e_test",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a real agent with the given task.

        Args:
            role: Agent role (software_engineer, support_engineer, etc.)
            task: Task description
            context_type: Context type for session
            context_id: Context ID for session
            **kwargs: Additional arguments for agent

        Returns:
            Agent response dict with 'response', 'session_id', etc.
        """
        start_time = time.perf_counter()

        try:
            agent_class = get_agent_class(self.framework, role)
            agent = agent_class()

            result = await asyncio.wait_for(
                agent.run_async(
                    task=task,
                    context_type=context_type,
                    context_id=context_id,
                    **kwargs,
                ),
                timeout=self.timeout,
            )

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            call_record = {
                "framework": self.framework,
                "role": role,
                "task": task,
                "response": result.get("response", ""),
                "session_id": result.get("session_id", ""),
                "latency_ms": latency_ms,
                "success": True,
                "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.call_history.append(call_record)

            return {
                **result,
                "latency_ms": latency_ms,
                "success": True,
            }

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            error = f"Timeout after {self.timeout}s"
            self.call_history.append(
                {
                    "framework": self.framework,
                    "role": role,
                    "task": task,
                    "response": "",
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {
                "response": "",
                "success": False,
                "error": error,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            self.call_history.append(
                {
                    "framework": self.framework,
                    "role": role,
                    "task": task,
                    "response": "",
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {
                "response": "",
                "success": False,
                "error": str(e),
                "latency_ms": latency_ms,
            }

    async def run_parallel(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Run multiple agents in parallel.

        Args:
            tasks: List of task dicts, each with:
                - role: Agent role
                - task: Task description
                - context_type: Context type (optional)
                - context_id: Context ID (optional)
                - **kwargs: Additional arguments

        Returns:
            List of agent response dicts in same order as tasks
        """

        async def run_single(task_dict: dict[str, Any]) -> dict[str, Any]:
            return await self.run(
                role=task_dict["role"],
                task=task_dict["task"],
                context_type=task_dict.get("context_type", "e2e_test"),
                context_id=task_dict.get("context_id"),
                **{
                    k: v
                    for k, v in task_dict.items()
                    if k not in ("role", "task", "context_type", "context_id")
                },
            )

        results = await asyncio.gather(*[run_single(t) for t in tasks])
        return list(results)


@pytest.fixture
def openhands_runner() -> RealAgentRunner:
    """Provide OpenHands agent runner (falls back to AutoGen if OpenHands unavailable).

    OpenHands requires Python 3.12+, so on Python 3.11 we fall back to AutoGen.
    """
    import sys

    if sys.version_info < (3, 12):
        # OpenHands requires Python 3.12+, use AutoGen as fallback
        return RealAgentRunner(framework="autogen", timeout=180.0)
    return RealAgentRunner(framework="openhands", timeout=180.0)


@pytest.fixture
def autogen_runner() -> RealAgentRunner:
    """Provide AutoGen agent runner."""
    return RealAgentRunner(framework="autogen", timeout=180.0)


@pytest.fixture
def crewai_runner() -> RealAgentRunner:
    """Provide CrewAI agent runner."""
    return RealAgentRunner(framework="crewai", timeout=180.0)


@pytest.fixture
def agent_runner(request) -> RealAgentRunner:
    """Provide agent runner based on --framework option or default to openhands."""
    framework = getattr(request, "param", None) or os.getenv("AGENT_FRAMEWORK", "openhands")
    return RealAgentRunner(framework=framework, timeout=180.0)


# ==============================================================================
# GitHub Connector Fixture
# ==============================================================================


@pytest.fixture(scope="session")
def github_token() -> str:
    """Get GitHub token from environment."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        pytest.skip("GITHUB_TOKEN not set - skipping GitHub integration tests")
    return token


@pytest.fixture(scope="session")
def github_test_repo() -> str:
    """Get the test repository for GitHub E2E tests."""
    return os.getenv("GITHUB_TEST_REPO", "VibeTechnologies/VibeWebAgent")


# ==============================================================================
# Test Scenarios
# ==============================================================================


@pytest.fixture
def slack_routing_scenarios():
    """
    Real test scenarios for Slack routing.

    These will be posted to real Slack and processed by real agents.
    """
    return [
        {
            "name": "openhands_swe_github_issue",
            "message": "/SoftwareEngineer list the 3 most recent open GitHub issues",
            "expected_role": "software_engineer",
            "description": "Test OpenHands SWE can use gh CLI to list issues",
            "evaluation_criteria": {
                "must_contain": ["issue", "#"],
                "must_not_contain": ["error", "failed"],
                "min_length": 50,
            },
        },
        {
            "name": "openhands_release_deploy_status",
            "message": "/ReleaseEngineer what is the current deployment status? List recent releases.",
            "expected_role": "release_engineer",
            "description": "Test OpenHands Release can check deployment status",
            "evaluation_criteria": {
                "must_contain": ["release", "deploy"],
                "min_length": 30,
            },
        },
        {
            "name": "openhands_support_analyze",
            "message": "/SupportEngineer analyze this customer issue: API returning 503 errors for 10 users",
            "expected_role": "support_engineer",
            "description": "Test OpenHands Support can analyze customer issues",
            "evaluation_criteria": {
                "must_contain": ["503", "error"],
                "min_length": 50,
            },
        },
        {
            "name": "openhands_pm_backlog",
            "message": "/ProductManager add a feature request: dark mode for dashboard",
            "expected_role": "product_manager",
            "description": "Test OpenHands PM can handle feature requests",
            "evaluation_criteria": {
                "must_contain": ["dark mode", "feature"],
                "min_length": 30,
            },
        },
    ]


@pytest.fixture
def github_routing_scenarios():
    """
    Real test scenarios for GitHub webhook routing.
    """
    return [
        {
            "name": "issue_comment_swe_mention",
            "event": "issue_comment",
            "body": "/SoftwareEngineer can you review the implementation approach here?",
            "expected_role": "software_engineer",
            "description": "Issue comment with SWE mention",
        },
        {
            "name": "issue_comment_release_deploy",
            "event": "issue_comment",
            "body": "/ReleaseEngineer this fix is ready, please deploy to staging",
            "expected_role": "release_engineer",
            "description": "Issue comment requesting deployment",
        },
    ]


@pytest.fixture
def handoff_chain_scenarios():
    """
    Real test scenarios for multi-agent handoff chains.

    These test the full handoff flow with real agents.
    """
    return [
        {
            "name": "support_to_swe_bug",
            "initial_agent": "support_engineer",
            "initial_message": (
                "Customer ACME Corp reports: Login page shows blank screen after update. "
                "Error in console: 'undefined is not a function'. 50 users affected. "
                "Please investigate the bug."
            ),
            "expected_chain": ["support_engineer", "software_engineer"],
            "description": "Support identifies bug, hands off to SWE for code investigation",
        },
        {
            "name": "swe_to_release_deploy",
            "initial_agent": "software_engineer",
            "initial_message": (
                "I've fixed the login bug in PR #789. Tests pass. "
                "Ready for staging deployment. Please deploy and verify."
            ),
            "expected_chain": ["software_engineer", "release_engineer"],
            "description": "SWE completes fix, hands off to release for deployment",
        },
        {
            "name": "full_incident_response",
            "initial_agent": "support_engineer",
            "initial_message": (
                "URGENT: Production API Gateway returning 503 errors. "
                "Multiple customers affected including ACME, Contoso, and Fabrikam. "
                "Sentry shows GraphRecursionError spike. Need immediate investigation, "
                "fix, deployment, and customer notification."
            ),
            "expected_chain": [
                "support_engineer",
                "software_engineer",
                "release_engineer",
                "support_engineer",
            ],
            "description": "Full incident response chain with multiple handoffs",
        },
    ]


# ==============================================================================
# G-Eval Evaluation Prompts
# ==============================================================================


TASK_COMPLETION_PROMPT = """You are evaluating an AI agent's response to a task.

TASK: {task}
AGENT ROLE: {role}
RESPONSE: {response}

Evaluate the following criteria (score 0.0 to 1.0):

1. TASK_UNDERSTANDING: Did the agent understand what was being asked?
2. ACTION_TAKEN: Did the agent take appropriate actions to complete the task?
3. RESULT_QUALITY: Is the response helpful and accurate?
4. TOOL_USAGE: Did the agent use available tools effectively? (if applicable)
5. COMPLETENESS: Is the response complete, or does it need follow-up?

Return ONLY valid JSON:
{{
    "task_understanding": 0.0,
    "action_taken": 0.0,
    "result_quality": 0.0,
    "tool_usage": 0.0,
    "completeness": 0.0,
    "overall_score": 0.0,
    "feedback": "Brief explanation of scores"
}}"""


HANDOFF_QUALITY_PROMPT = """You are evaluating a multi-agent handoff in an AI system.

SCENARIO: {scenario}
INITIAL TASK: {task}
HANDOFF FROM: {from_agent}
HANDOFF TO: {to_agent}

FROM_AGENT RESPONSE:
{from_response}

TO_AGENT RESPONSE:
{to_response}

Evaluate the following criteria (score 0.0 to 1.0):

1. HANDOFF_DETECTION: Was the need for handoff correctly identified?
2. CONTEXT_PRESERVATION: Was sufficient context passed to the receiving agent?
3. RECEIVING_AGENT_UNDERSTANDING: Did the receiving agent understand the handoff?
4. CONTINUITY: Was there continuity in addressing the original task?
5. PROFESSIONALISM: Were communications professional and clear?

Return ONLY valid JSON:
{{
    "handoff_detection": 0.0,
    "context_preservation": 0.0,
    "receiving_agent_understanding": 0.0,
    "continuity": 0.0,
    "professionalism": 0.0,
    "overall_score": 0.0,
    "feedback": "Brief explanation of scores"
}}"""


@pytest.fixture
def task_completion_prompt() -> str:
    """Provide the task completion evaluation prompt template."""
    return TASK_COMPLETION_PROMPT


@pytest.fixture
def handoff_quality_prompt() -> str:
    """Provide the handoff quality evaluation prompt template."""
    return HANDOFF_QUALITY_PROMPT


# ==============================================================================
# Router Fixture
# ==============================================================================


@pytest.fixture
def router():
    """Provide a Router instance for parsing /RoleName mentions."""
    from vibeteam.router.router import Router

    return Router()


# ==============================================================================
# Pytest Configuration
# ==============================================================================


def pytest_addoption(parser):
    """Add custom command line options for E2E tests."""
    parser.addoption(
        "--framework",
        action="store",
        default="openhands",
        choices=["openhands", "autogen", "crewai", "all"],
        help="Agent framework to test (default: openhands)",
    )
    parser.addoption(
        "--post-to-slack",
        action="store_true",
        default=False,
        help="Actually post messages to Slack (default: False)",
    )
    parser.addoption(
        "--agent-timeout",
        type=float,
        default=180.0,
        help="Timeout for agent execution in seconds (default: 180)",
    )


@pytest.fixture
def framework(request) -> str:
    """Get the framework to test from command line option."""
    return request.config.getoption("--framework")


@pytest.fixture
def should_post_to_slack(request) -> bool:
    """Check if we should post to real Slack."""
    return request.config.getoption("--post-to-slack")


@pytest.fixture
def agent_timeout(request) -> float:
    """Get the agent timeout from command line option."""
    return request.config.getoption("--agent-timeout")
