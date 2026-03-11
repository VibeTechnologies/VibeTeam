"""
Pytest configuration and fixtures for multi-framework agent tests.

Provides shared fixtures for:
- Metrics collection
- Test categorization
- LLM integration test markers
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env file from project root before any tests run
_project_root = Path(__file__).parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from agent_service.metrics import reset_collector


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that make real LLM API calls",
    )
    parser.addoption(
        "--run-stress",
        action="store_true",
        default=False,
        help="Run stress tests (slower, more expensive)",
    )
    parser.addoption(
        "--export-metrics",
        type=str,
        default=None,
        help="Export metrics to specified JSON file after tests",
    )
    parser.addoption(
        "--export-benchmark",
        type=str,
        default=None,
        help="Export benchmark results to specified JSON file",
    )


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line("markers", "integration: mark test as requiring real LLM API calls")
    config.addinivalue_line("markers", "stress: mark test as a stress test (slow, expensive)")
    config.addinivalue_line("markers", "unit_task: mark test as a unit task (U1-U7)")
    config.addinivalue_line("markers", "integration_task: mark test as an integration task (I1-I3)")

    # Integration tests in this repo use chat-completions-oriented clients (AutoGen/CrewAI).
    # If the default deployment is a responses-only Codex model, switch to a chat deployment.
    if config.getoption("--run-integration"):
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        if "codex" in deployment.lower():
            fallback = (
                os.getenv("AZURE_INTEGRATION_OPENAI_DEPLOYMENT")
                or os.getenv("AZURE_CHAT_OPENAI_DEPLOYMENT")
                or "gpt-4.1"
            )
            os.environ["AZURE_OPENAI_DEPLOYMENT"] = fallback
            print(
                "[pytest] --run-integration: "
                f"switched AZURE_OPENAI_DEPLOYMENT from '{deployment}' to '{fallback}'."
            )


def pytest_collection_modifyitems(config, items):
    """Skip integration/stress tests unless explicitly enabled."""
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not config.getoption("--run-stress"):
        skip_stress = pytest.mark.skip(reason="need --run-stress option to run")
        for item in items:
            if "stress" in item.keywords:
                item.add_marker(skip_stress)


def pytest_sessionstart(session):
    """Initialize metrics collector at session start."""
    # Reset collector for fresh metrics
    metrics_path = Path(".metrics") / "test_run"
    reset_collector(metrics_path)


def pytest_sessionfinish(session, exitstatus):
    """Export metrics after test session if requested."""
    export_path = session.config.getoption("--export-metrics")
    if export_path:
        from agent_service.metrics import get_collector

        collector = get_collector()
        if collector.get_all():
            filepath = collector.export_json(export_path)
            print(f"\nMetrics exported to: {filepath}")
            print(collector.generate_report())


@pytest.fixture(scope="session")
def metrics_collector():
    """Provide the global metrics collector."""
    from agent_service.metrics import get_collector

    return get_collector()


@pytest.fixture(scope="session")
def azure_credentials():
    """Check Azure OpenAI credentials are available."""
    api_key = os.getenv("AZURE_API_KEY")
    api_base = os.getenv("AZURE_API_BASE")

    if not api_key or not api_base:
        pytest.skip("Azure OpenAI credentials not configured")

    return {
        "api_key": api_key,
        "api_base": api_base,
        "api_version": os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
    }


@pytest.fixture(scope="session")
def openhands_runtime_status() -> tuple[bool, str | None]:
    """Return (available, reason) for OpenHands runtime dependencies."""
    try:
        from agent_service.openhands.support_engineer import OpenHandsSupportEngineer

        # Instantiate once to ensure imports and constructor wiring are valid.
        OpenHandsSupportEngineer()
        return True, None
    except Exception as exc:
        return False, str(exc)


@pytest.fixture(scope="session")
def require_openhands_runtime(openhands_runtime_status):
    """Require OpenHands runtime dependencies for integration tests.

    Critical OpenHands paths must execute in CI and local validation. If runtime
    bootstrap fails, fail fast instead of silently skipping the test.
    """
    available, reason = openhands_runtime_status
    if not available:
        pytest.fail(f"OpenHands runtime unavailable in this environment: {reason}")


@pytest.fixture
def temp_directory(tmp_path):
    """Provide a temporary directory for file operations."""
    return tmp_path


@pytest.fixture
def sample_files(tmp_path):
    """Create sample files for testing."""
    # Create a few test files
    (tmp_path / "readme.md").write_text("# Test Project\n\nThis is a test.")
    (tmp_path / "config.json").write_text('{"version": "1.0.0"}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")

    return tmp_path


# Test task definitions from design.md
UNIT_TASKS = {
    "U1": {
        "agent": "release_engineer",
        "task": "List all files in /tmp directory",
        "success_criteria": lambda r: (
            "/tmp" in r.lower() or "file" in r.lower() or "dir" in r.lower()
        ),
    },
    "U2": {
        "agent": "release_engineer",
        "task": "Create a file at {path}/test.txt with content 'Hello World'",
        "success_criteria": lambda r: (
            "success" in r.lower() or "created" in r.lower() or "wrote" in r.lower()
        ),
    },
    "U3": {
        "agent": "release_engineer",
        "task": "Execute the command 'echo Integration Test Passed'",
        "success_criteria": lambda r: "integration test passed" in r.lower(),
    },
    "U4": {
        "agent": "marketing_manager",
        "task": "Analyze the sentiment of this text: 'I absolutely love this product, it changed my life!'",
        "success_criteria": lambda r: "positive" in r.lower(),
    },
    "U5": {
        "agent": "marketing_manager",
        "task": "Draft a Twitter post announcing a new AI feature release. Keep it under 280 characters.",
        "success_criteria": lambda r: len(r) > 10 and len(r) < 400,
    },
    "U6": {
        "agent": "support_engineer",
        "task": "Create a support ticket for customer@test.com with subject 'Login Issue' and priority high",
        "success_criteria": lambda r: "ticket" in r.lower() or "tkt" in r.lower(),
    },
    "U7": {
        "agent": "support_engineer",
        "task": "Draft an email response to a customer asking about account password reset",
        "success_criteria": lambda r: (
            "password" in r.lower() or "reset" in r.lower() or "email" in r.lower()
        ),
    },
}

INTEGRATION_TASKS = {
    "I1": {
        "agents": ["release_engineer", "marketing_manager"],
        "task": "Deploy version 2.0 to production and draft an announcement tweet",
        "success_criteria": lambda r: (
            ("deploy" in r.lower() or "version" in r.lower())
            and ("tweet" in r.lower() or "post" in r.lower() or "announce" in r.lower())
        ),
    },
    "I2": {
        "agents": ["support_engineer", "release_engineer"],
        "task": "There's a critical error in production. Identify the issue from Sentry and prepare a hotfix",
        "success_criteria": lambda r: (
            "error" in r.lower() or "fix" in r.lower() or "issue" in r.lower()
        ),
    },
    "I3": {
        "agents": ["release_engineer", "marketing_manager", "support_engineer"],
        "task": "Prepare a full release: bump version, deploy, announce on social media, and notify customers",
        "success_criteria": lambda r: True,  # Complex task, just check completion
    },
}


@pytest.fixture
def unit_tasks():
    """Provide unit task definitions."""
    return UNIT_TASKS


@pytest.fixture
def integration_tasks():
    """Provide integration task definitions."""
    return INTEGRATION_TASKS
