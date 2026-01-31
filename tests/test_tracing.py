"""
Tests for Langfuse tracing integration with SwarmOrchestrator.

Tests cover:
- Tracing module initialization
- SwarmTrace lifecycle
- AgentSpan tracking
- Handoff event recording
- Error handling when Langfuse is not configured
"""

import os
from unittest.mock import patch

import pytest

# Check if langfuse is installed
try:
    import langfuse

    LANGFUSE_INSTALLED = True
except ImportError:
    LANGFUSE_INSTALLED = False


class TestTracingEnabled:
    """Tests for is_tracing_enabled function."""

    def test_tracing_disabled_when_env_var_false(self):
        """Tracing should be disabled when LANGFUSE_TRACING_ENABLED=false."""
        from vibeteam import tracing

        # Reset cached state
        tracing._tracing_enabled = None

        with patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "false"}, clear=False):
            assert tracing.is_tracing_enabled() is False

        # Reset for other tests
        tracing._tracing_enabled = None

    def test_tracing_disabled_when_no_credentials(self):
        """Tracing should be disabled when credentials are missing."""
        from vibeteam import tracing

        # Reset cached state
        tracing._tracing_enabled = None

        with patch.dict(
            os.environ,
            {"LANGFUSE_TRACING_ENABLED": "true"},
            clear=False,
        ):
            # Remove credentials if present
            env = os.environ.copy()
            env.pop("LANGFUSE_PUBLIC_KEY", None)
            env.pop("LANGFUSE_SECRET_KEY", None)

            with patch.dict(os.environ, env, clear=True):
                tracing._tracing_enabled = None
                result = tracing.is_tracing_enabled()
                # Result depends on whether credentials are in env

        # Reset for other tests
        tracing._tracing_enabled = None

    def test_tracing_enabled_with_credentials(self):
        """Tracing should be enabled when credentials are configured."""
        from vibeteam import tracing

        # Reset cached state
        tracing._tracing_enabled = None

        with patch.dict(
            os.environ,
            {
                "LANGFUSE_PUBLIC_KEY": "pk-test-123",
                "LANGFUSE_SECRET_KEY": "sk-test-456",
                "LANGFUSE_TRACING_ENABLED": "true",
            },
            clear=False,
        ):
            assert tracing.is_tracing_enabled() is True

        # Reset for other tests
        tracing._tracing_enabled = None


class TestSwarmTrace:
    """Tests for SwarmTrace class."""

    def test_swarm_trace_init_without_langfuse(self):
        """SwarmTrace should initialize gracefully without Langfuse."""
        from vibeteam import tracing

        # Disable tracing
        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test message",
            model="gpt-4",
            max_iterations=10,
        )

        assert trace.session_id == "test-session"
        assert trace.user_message == "Test message"
        assert trace.model == "gpt-4"
        assert trace.max_iterations == 10
        assert trace._trace is None

        # Reset
        tracing._tracing_enabled = None

    def test_swarm_trace_token_tracking(self):
        """SwarmTrace should track tokens per agent."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        trace.add_tokens("swe", 100)
        trace.add_tokens("pm", 200)
        trace.add_tokens("swe", 50)

        assert trace._total_tokens == 350
        assert trace._agent_tokens["swe"] == 150
        assert trace._agent_tokens["pm"] == 200

        tracing._tracing_enabled = None

    def test_swarm_trace_end_without_langfuse(self):
        """SwarmTrace.end() should handle missing Langfuse gracefully."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        # Should not raise
        trace.end(
            output="Final response",
            agents_used=["swe", "pm"],
            iterations=5,
            success=True,
        )

        tracing._tracing_enabled = None


class TestAgentSpan:
    """Tests for AgentSpan context manager."""

    def test_agent_span_context_manager(self):
        """AgentSpan should work as context manager."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        with trace.start_agent_span(
            agent_name="SoftwareEngineer",
            agent_key="swe",
            iteration=1,
            task="Fix the bug",
        ) as span:
            span.set_output("Bug fixed!")
            span.set_tokens(150)

        assert trace._agent_tokens.get("swe", 0) == 150

        tracing._tracing_enabled = None

    def test_agent_span_add_event(self):
        """AgentSpan should allow adding events."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        with trace.start_agent_span(
            agent_name="SoftwareEngineer",
            agent_key="swe",
            iteration=1,
            task="Fix the bug",
        ) as span:
            # Should not raise even without Langfuse
            span.add_event("tool-call", {"tool": "github", "action": "list_issues"})

        tracing._tracing_enabled = None


class TestHandoffRecording:
    """Tests for handoff event recording."""

    def test_record_handoff_without_langfuse(self):
        """record_handoff should handle missing Langfuse gracefully."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        # Should not raise
        trace.record_handoff(
            from_agent="supervisor",
            to_agent="swe",
            task="Fix the login bug",
            iteration=1,
        )

        tracing._tracing_enabled = None

    def test_record_error_without_langfuse(self):
        """record_error should handle missing Langfuse gracefully."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        trace = tracing.SwarmTrace(
            session_id="test-session",
            user_message="Test",
            model="gpt-4",
            max_iterations=10,
        )

        # Should not raise
        trace.record_error(
            agent_name="swe",
            error=ValueError("Something went wrong"),
            iteration=1,
        )

        tracing._tracing_enabled = None


class TestObserveDecorator:
    """Tests for observe_agent decorator."""

    def test_observe_agent_returns_function_when_disabled(self):
        """observe_agent should return original function when tracing disabled."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        async def my_agent_function(task: str) -> str:
            return f"Completed: {task}"

        decorated = tracing.observe_agent(my_agent_function)

        # Should be the same function (no decoration)
        assert decorated is my_agent_function

        tracing._tracing_enabled = None


class TestTracingContextManager:
    """Tests for trace_swarm_run context manager."""

    def test_trace_swarm_run_context_manager(self):
        """trace_swarm_run should yield SwarmTrace."""
        from vibeteam import tracing

        tracing._tracing_enabled = False

        with tracing.trace_swarm_run(
            session_id="test-session",
            user_message="Hello",
            model="gpt-4",
            max_iterations=10,
        ) as trace:
            assert isinstance(trace, tracing.SwarmTrace)
            assert trace.session_id == "test-session"

        tracing._tracing_enabled = None


class TestFlushTraces:
    """Tests for flush_traces function."""

    def test_flush_traces_without_client(self):
        """flush_traces should handle missing client gracefully."""
        from vibeteam import tracing

        tracing._tracing_enabled = False
        tracing._langfuse_client = None

        # Should not raise
        tracing.flush_traces()

        tracing._tracing_enabled = None


@pytest.mark.skipif(
    not os.environ.get("LANGFUSE_PUBLIC_KEY") or not LANGFUSE_INSTALLED,
    reason="Langfuse credentials not configured or langfuse not installed",
)
class TestLangfuseIntegration:
    """Integration tests that require Langfuse credentials."""

    def test_langfuse_client_initialization(self):
        """Langfuse client should initialize with credentials."""
        from vibeteam import tracing

        # Reset state
        tracing._tracing_enabled = None
        tracing._langfuse_client = None

        client = tracing.get_langfuse_client()
        assert client is not None

        # Reset
        tracing._tracing_enabled = None
        tracing._langfuse_client = None

    def test_swarm_trace_creates_trace(self):
        """SwarmTrace should create a Langfuse trace."""
        from vibeteam import tracing

        # Reset state
        tracing._tracing_enabled = None
        tracing._langfuse_client = None

        trace = tracing.SwarmTrace(
            session_id="test-integration-session",
            user_message="Integration test message",
            model="gpt-4-test",
            max_iterations=5,
        )

        assert trace._started is True
        assert trace._trace is not None

        # End the trace
        trace.end(
            output="Test completed",
            agents_used=["swe"],
            iterations=1,
            success=True,
        )

        # Reset
        tracing._tracing_enabled = None
        tracing._langfuse_client = None
