"""
Langfuse Integration Tests.

Verifies all 4 layers of the Langfuse integration:
1. vibeteam/__init__.py — _init_langfuse() auto-init on import
2. vibeteam/tracing.py — SwarmTrace, AgentSpan, get_langfuse_client()
3. agents/shared/langfuse_tools.py — LangfuseClient REST API wrapper
4. vibeteam/connectors/langfuse.py — LangfuseConnector (higher-level)

Run with:
    pytest tests/test_langfuse_integration.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

# ---------------------------------------------------------------------------
# 1. vibeteam/__init__.py — _init_langfuse()
# ---------------------------------------------------------------------------


class TestInitLangfuse:
    """Tests for _init_langfuse() in vibeteam/__init__.py."""

    def test_returns_false_when_no_keys(self):
        """Should return False when LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY are missing."""
        from vibeteam import _init_langfuse

        with patch.dict(os.environ, {}, clear=True):
            # Remove both keys
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            assert _init_langfuse() is False

    def test_returns_false_when_only_public_key(self):
        """Should return False when only LANGFUSE_PUBLIC_KEY is set."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test"}
        with patch.dict(os.environ, env, clear=True):
            assert _init_langfuse() is False

    def test_returns_false_when_only_secret_key(self):
        """Should return False when only LANGFUSE_SECRET_KEY is set."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            assert _init_langfuse() is False

    def test_returns_true_when_both_keys_present(self):
        """Should return True and add langfuse_otel to litellm.callbacks."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            mock_litellm = MagicMock()
            mock_litellm.callbacks = []
            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                result = _init_langfuse()
                assert result is True
                assert "langfuse_otel" in mock_litellm.callbacks

    def test_sets_langfuse_host_when_not_set(self):
        """Should set LANGFUSE_HOST to default when not already configured."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("LANGFUSE_HOST", None)
            os.environ.pop("LANGFUSE_BASE_URL", None)
            mock_litellm = MagicMock()
            mock_litellm.callbacks = []
            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                _init_langfuse()
                assert os.environ.get("LANGFUSE_HOST") == "https://langfuse.vibebrowser.app"

    def test_does_not_overwrite_existing_langfuse_host(self):
        """Should NOT overwrite LANGFUSE_HOST if already set."""
        from vibeteam import _init_langfuse

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_HOST": "https://custom.langfuse.host",
        }
        with patch.dict(os.environ, env, clear=True):
            mock_litellm = MagicMock()
            mock_litellm.callbacks = []
            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                _init_langfuse()
                assert os.environ["LANGFUSE_HOST"] == "https://custom.langfuse.host"

    def test_does_not_duplicate_callback(self):
        """Should not add langfuse_otel if it's already in callbacks."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            mock_litellm = MagicMock()
            mock_litellm.callbacks = ["langfuse_otel"]
            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                _init_langfuse()
                assert mock_litellm.callbacks.count("langfuse_otel") == 1

    def test_returns_false_when_litellm_not_installed(self):
        """Should return False gracefully when litellm is not importable."""
        from vibeteam import _init_langfuse

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            with patch.dict("sys.modules", {"litellm": None}):
                # Patch the import to raise ImportError
                with patch("builtins.__import__", side_effect=ImportError("no litellm")):
                    assert _init_langfuse() is False


# ---------------------------------------------------------------------------
# 2. vibeteam/tracing.py — is_tracing_enabled, get_langfuse_client, SwarmTrace
# ---------------------------------------------------------------------------


class TestIsTracingEnabled:
    """Tests for is_tracing_enabled()."""

    def setup_method(self):
        """Reset cached state before each test."""
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_enabled_when_both_keys_present(self):
        from vibeteam.tracing import is_tracing_enabled

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            assert is_tracing_enabled() is True

    def test_disabled_when_keys_missing(self):
        from vibeteam.tracing import is_tracing_enabled

        with patch.dict(os.environ, {}, clear=True):
            assert is_tracing_enabled() is False

    def test_disabled_when_explicitly_disabled(self):
        from vibeteam.tracing import is_tracing_enabled

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_TRACING_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            assert is_tracing_enabled() is False

    def test_caches_result(self):
        """Should cache the result and not re-check env vars."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import is_tracing_enabled

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            assert is_tracing_enabled() is True
            # Should still be True even if we remove keys (cached)
            assert tracing_mod._tracing_enabled is True


class TestGetLangfuseClient:
    """Tests for get_langfuse_client()."""

    def setup_method(self):
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_returns_none_when_tracing_disabled(self):
        from vibeteam.tracing import get_langfuse_client

        with patch.dict(os.environ, {}, clear=True):
            assert get_langfuse_client() is None

    def test_creates_client_when_configured(self):
        from vibeteam.tracing import get_langfuse_client

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_HOST": "https://test.langfuse.example",
        }
        mock_langfuse_cls = MagicMock()
        mock_client = MagicMock()
        mock_langfuse_cls.return_value = mock_client

        with patch.dict(os.environ, env, clear=True):
            with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_cls)}):
                result = get_langfuse_client()
                assert result is mock_client
                mock_langfuse_cls.assert_called_once_with(
                    public_key="pk-test",
                    secret_key="sk-test",
                    host="https://test.langfuse.example",
                )

    def test_returns_cached_client(self):
        """Second call should return the same client (singleton)."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import get_langfuse_client

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        mock_client = MagicMock()
        tracing_mod._tracing_enabled = True
        tracing_mod._langfuse_client = mock_client

        with patch.dict(os.environ, env, clear=True):
            result = get_langfuse_client()
            assert result is mock_client

    def test_returns_none_on_import_error(self):
        from vibeteam.tracing import get_langfuse_client

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            with patch.dict("sys.modules", {"langfuse": None}):
                with patch("builtins.__import__", side_effect=ImportError("no langfuse")):
                    result = get_langfuse_client()
                    assert result is None


class TestSwarmTrace:
    """Tests for SwarmTrace class."""

    def setup_method(self):
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_init_without_client(self):
        """SwarmTrace should be safe to use when no Langfuse client is available."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(
                session_id="test-session",
                user_message="hello",
                model="gpt-4",
                max_iterations=10,
            )
            assert trace.session_id == "test-session"
            assert trace._trace is None
            assert trace._started is False

    def test_trace_swarm_run_context_manager(self):
        """trace_swarm_run should yield a SwarmTrace and call end()."""
        from vibeteam.tracing import trace_swarm_run

        with patch.dict(os.environ, {}, clear=True):
            with trace_swarm_run(
                session_id="ctx-test",
                user_message="test",
                model="gpt-4",
                max_iterations=5,
            ) as trace:
                assert trace.session_id == "ctx-test"
                assert trace.model == "gpt-4"
            # end() should have been called (no error because _trace is None)

    def test_add_tokens(self):
        """add_tokens should accumulate totals correctly."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            trace.add_tokens("swe", 100)
            trace.add_tokens("pm", 200)
            trace.add_tokens("swe", 50)
            assert trace._total_tokens == 350
            assert trace._agent_tokens == {"swe": 150, "pm": 200}

    def test_record_handoff_safe_without_trace(self):
        """record_handoff should not raise when _trace is None."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            # Should not raise
            trace.record_handoff(from_agent="swe", to_agent="pm", task="review", iteration=1)

    def test_record_error_safe_without_trace(self):
        """record_error should not raise when _trace is None."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            trace.record_error(agent_name="swe", error=RuntimeError("boom"), iteration=1)

    def test_end_safe_without_trace(self):
        """end() should not raise when _trace is None."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            trace.end(output="done", agents_used=["swe"], iterations=3, success=True)

    def test_start_agent_span_returns_agent_span(self):
        """start_agent_span should return an AgentSpan."""
        from vibeteam.tracing import AgentSpan, SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            span = trace.start_agent_span(
                agent_name="Software Engineer",
                agent_key="swe",
                iteration=1,
                task="fix bug",
            )
            assert isinstance(span, AgentSpan)
            assert span.agent_key == "swe"
            assert span.task == "fix bug"

    def test_swarm_trace_with_mock_client(self):
        """Full trace lifecycle with a mocked Langfuse client."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import SwarmTrace

        mock_client = MagicMock()
        mock_span = MagicMock()
        mock_client.start_span.return_value = mock_span

        tracing_mod._tracing_enabled = True
        tracing_mod._langfuse_client = mock_client

        try:
            trace = SwarmTrace(
                session_id="full-test",
                user_message="deploy to prod",
                model="gpt-4",
                max_iterations=10,
            )
            assert trace._started is True
            assert trace._trace is mock_span

            # Record a handoff
            trace.record_handoff(from_agent="swe", to_agent="re", task="deploy", iteration=1)
            mock_span.create_event.assert_called_once()
            call_kwargs = mock_span.create_event.call_args
            assert call_kwargs.kwargs["name"] == "agent-handoff"

            # Record an error
            mock_span.create_event.reset_mock()
            trace.record_error(agent_name="swe", error=ValueError("bad value"), iteration=2)
            mock_span.create_event.assert_called_once()

            # End trace
            trace.end(
                output="deployed",
                agents_used=["swe", "re"],
                iterations=3,
                success=True,
            )
            mock_span.update.assert_called_once()
            mock_span.end.assert_called_once()
            mock_client.flush.assert_called_once()
        finally:
            tracing_mod._tracing_enabled = None
            tracing_mod._langfuse_client = None


class TestAgentSpan:
    """Tests for AgentSpan class."""

    def setup_method(self):
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_context_manager_without_trace(self):
        """AgentSpan should work as context manager even without Langfuse."""
        from vibeteam.tracing import SwarmTrace

        with patch.dict(os.environ, {}, clear=True):
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            span = trace.start_agent_span(
                agent_name="SWE", agent_key="swe", iteration=1, task="test"
            )
            with span as s:
                s.set_output("done")
                s.set_tokens(100)
                s.add_event("tool_call", {"tool": "grep"})

    def test_context_manager_with_mock_trace(self):
        """AgentSpan should create child span on the trace."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import SwarmTrace

        mock_client = MagicMock()
        mock_root_span = MagicMock()
        mock_child_span = MagicMock()
        mock_client.start_span.return_value = mock_root_span
        mock_root_span.start_span.return_value = mock_child_span

        tracing_mod._tracing_enabled = True
        tracing_mod._langfuse_client = mock_client

        try:
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)

            span = trace.start_agent_span(
                agent_name="SWE", agent_key="swe", iteration=1, task="fix bug"
            )
            with span as s:
                s.set_output("fixed!")
                s.set_tokens(500)

            # Child span should have been created
            mock_root_span.start_span.assert_called_once()
            call_kwargs = mock_root_span.start_span.call_args
            assert call_kwargs.kwargs["name"] == "agent-swe"

            # Output should have been set
            mock_child_span.update.assert_called()

            # Span should have ended
            mock_child_span.end.assert_called_once()

            # Tokens should be accumulated on the trace
            assert trace._total_tokens == 500
            assert trace._agent_tokens["swe"] == 500
        finally:
            tracing_mod._tracing_enabled = None
            tracing_mod._langfuse_client = None

    def test_records_error_on_exception(self):
        """AgentSpan should record error metadata if an exception occurs."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import SwarmTrace

        mock_client = MagicMock()
        mock_root_span = MagicMock()
        mock_child_span = MagicMock()
        mock_client.start_span.return_value = mock_root_span
        mock_root_span.start_span.return_value = mock_child_span

        tracing_mod._tracing_enabled = True
        tracing_mod._langfuse_client = mock_client

        try:
            trace = SwarmTrace(session_id="test", user_message="", model="gpt-4", max_iterations=5)
            span = trace.start_agent_span(
                agent_name="SWE", agent_key="swe", iteration=1, task="buggy task"
            )
            with pytest.raises(RuntimeError, match="agent crashed"):
                with span:
                    raise RuntimeError("agent crashed")

            # Should have recorded error, not called end()
            mock_child_span.update.assert_called()
            update_kwargs = mock_child_span.update.call_args.kwargs
            assert update_kwargs["level"] == "ERROR"
            assert "agent crashed" in update_kwargs["status_message"]
            mock_child_span.end.assert_not_called()
        finally:
            tracing_mod._tracing_enabled = None
            tracing_mod._langfuse_client = None


class TestFlushTraces:
    """Tests for flush_traces()."""

    def setup_method(self):
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_flush_no_client(self):
        """flush_traces should not raise when no client is available."""
        from vibeteam.tracing import flush_traces

        with patch.dict(os.environ, {}, clear=True):
            flush_traces()  # Should not raise

    def test_flush_calls_client(self):
        """flush_traces should call client.flush()."""
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import flush_traces

        mock_client = MagicMock()
        tracing_mod._tracing_enabled = True
        tracing_mod._langfuse_client = mock_client

        try:
            flush_traces()
            mock_client.flush.assert_called_once()
        finally:
            tracing_mod._tracing_enabled = None
            tracing_mod._langfuse_client = None


class TestObserveAgent:
    """Tests for observe_agent decorator."""

    def setup_method(self):
        import vibeteam.tracing as tracing_mod

        tracing_mod._tracing_enabled = None
        tracing_mod._langfuse_client = None

    def test_returns_original_func_when_disabled(self):
        from vibeteam.tracing import observe_agent

        with patch.dict(os.environ, {}, clear=True):

            def my_func():
                pass

            result = observe_agent(my_func)
            assert result is my_func

    def test_returns_decorated_func_when_enabled(self):
        import vibeteam.tracing as tracing_mod
        from vibeteam.tracing import observe_agent

        tracing_mod._tracing_enabled = True

        mock_observe = MagicMock()
        mock_decorated = MagicMock()
        mock_observe.return_value.return_value = mock_decorated

        mock_langfuse_mod = MagicMock()
        mock_langfuse_mod.observe = mock_observe

        try:
            with patch.dict("sys.modules", {"langfuse": mock_langfuse_mod}):

                def my_func():
                    pass

                result = observe_agent(my_func)
                assert result is mock_decorated
        finally:
            tracing_mod._tracing_enabled = None


# ---------------------------------------------------------------------------
# 3. agents/shared/langfuse_tools.py — LangfuseClient
# ---------------------------------------------------------------------------


class TestLangfuseToolsClient:
    """Tests for LangfuseClient in agents/shared/langfuse_tools.py."""

    def test_init_with_explicit_keys(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(
            public_key="pk-test", secret_key="sk-test", base_url="https://lf.example.com"
        )
        assert client.public_key == "pk-test"
        assert client.secret_key == "sk-test"
        assert client.base_url == "https://lf.example.com"

    def test_init_from_env_vars(self):
        from agents.shared.langfuse_tools import LangfuseClient

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-env",
            "LANGFUSE_SECRET_KEY": "sk-env",
            "LANGFUSE_BASE_URL": "https://lf-env.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            client = LangfuseClient()
            assert client.public_key == "pk-env"
            assert client.secret_key == "sk-env"
            assert client.base_url == "https://lf-env.example.com"

    def test_init_uses_default_url(self):
        from agents.shared.langfuse_tools import DEFAULT_LANGFUSE_URL, LangfuseClient

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            client = LangfuseClient()
            assert client.base_url == DEFAULT_LANGFUSE_URL

    def test_init_strips_trailing_slash(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com/"
        )
        assert not client.base_url.endswith("/")

    def test_init_raises_without_keys(self):
        from agents.shared.langfuse_tools import LangfuseClient

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Langfuse credentials required"):
                LangfuseClient()

    def test_request_builds_correct_url(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "agents.shared.langfuse_tools.requests.request", return_value=mock_response
        ) as mock_req:
            client._request("GET", "/traces", params={"limit": 10})
            mock_req.assert_called_once_with(
                "GET",
                "https://lf.example.com/api/public/traces",
                auth=("pk", "sk"),
                timeout=30,
                params={"limit": 10},
            )

    def test_get_traces_sends_params(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        with patch.object(client, "_request", return_value={"data": []}) as mock_req:
            result = client.get_traces(hours=6, limit=50, name="test")
            assert result == []
            call_kwargs = mock_req.call_args
            assert call_kwargs.kwargs["params"]["limit"] == 50
            assert call_kwargs.kwargs["params"]["name"] == "test"
            assert "fromTimestamp" in call_kwargs.kwargs["params"]

    def test_get_stats_empty_traces(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        with patch.object(client, "get_traces", return_value=[]):
            stats = client.get_stats(hours=1)
            assert stats.total_traces == 0
            assert stats.total_tokens == 0
            assert stats.avg_latency_ms == 0
            assert stats.error_count == 0
            assert stats.error_rate == 0
            assert stats.cost_usd == 0
            assert stats.period_hours == 1

    def test_get_stats_computes_correctly(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        traces = [
            {
                "id": "t1",
                "usage": {"totalTokens": 100},
                "latency": 1000,
                "level": "DEFAULT",
                "calculatedTotalCost": 0.01,
            },
            {
                "id": "t2",
                "usage": {"totalTokens": 200},
                "latency": 3000,
                "level": "ERROR",
                "statusMessage": None,
                "calculatedTotalCost": 0.02,
            },
            {
                "id": "t3",
                "usage": None,
                "latency": None,
                "statusMessage": "timeout",
                "calculatedTotalCost": None,
            },
        ]

        with patch.object(client, "get_traces", return_value=traces):
            stats = client.get_stats(hours=1)
            assert stats.total_traces == 3
            assert stats.total_tokens == 300
            # Latency: (1000 + 3000) / 3 = 1333.33
            assert abs(stats.avg_latency_ms - 1333.33) < 1
            assert stats.error_count == 2  # t2 (ERROR level), t3 (statusMessage)
            assert abs(stats.error_rate - 2 / 3) < 0.01
            assert abs(stats.cost_usd - 0.03) < 0.001

    def test_detect_anomalies_no_traces(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        with patch.object(client, "get_traces", return_value=[]):
            anomalies = client.detect_anomalies(hours=1)
            assert anomalies == []

    def test_detect_anomalies_high_latency(self):
        from agents.shared.langfuse_tools import (
            LATENCY_CRITICAL_MS,
            LATENCY_WARNING_MS,
            LangfuseClient,
        )

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        traces = [
            {"id": "t1", "latency": LATENCY_WARNING_MS + 1000, "usage": {}, "level": "DEFAULT"},
            {"id": "t2", "latency": LATENCY_CRITICAL_MS + 1000, "usage": {}, "level": "DEFAULT"},
            {"id": "t3", "latency": 500, "usage": {}, "level": "DEFAULT"},
        ]

        with patch.object(client, "get_traces", return_value=traces):
            anomalies = client.detect_anomalies(hours=1)
            latency_anomalies = [a for a in anomalies if a.type == "latency"]
            assert len(latency_anomalies) == 1
            assert latency_anomalies[0].severity == "critical"  # has one > critical

    def test_detect_anomalies_high_error_rate(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        # 60% error rate (well above 5% threshold)
        traces = [
            {"id": f"t{i}", "latency": 100, "usage": {}, "level": "ERROR"} for i in range(6)
        ] + [{"id": f"ok{i}", "latency": 100, "usage": {}, "level": "DEFAULT"} for i in range(4)]

        with patch.object(client, "get_traces", return_value=traces):
            anomalies = client.detect_anomalies(hours=1)
            error_anomalies = [a for a in anomalies if a.type == "error_rate"]
            assert len(error_anomalies) == 1
            assert error_anomalies[0].severity == "critical"  # 60% > 15%

    def test_detect_anomalies_token_budget(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        # 1 hour of data with 50k tokens => projected 1.2M/day (> 80% of 1M budget)
        traces = [
            {"id": "t1", "latency": 100, "usage": {"totalTokens": 50000}, "level": "DEFAULT"},
        ]

        with patch.object(client, "get_traces", return_value=traces):
            anomalies = client.detect_anomalies(hours=1, daily_token_budget=1_000_000)
            token_anomalies = [a for a in anomalies if a.type == "token_usage"]
            assert len(token_anomalies) == 1
            assert token_anomalies[0].severity == "critical"  # 1.2M > 95% of 1M

    def test_health_check_success(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("agents.shared.langfuse_tools.requests.get", return_value=mock_response):
            assert client.health_check() is True

    def test_health_check_failure(self):
        from agents.shared.langfuse_tools import LangfuseClient

        client = LangfuseClient(public_key="pk", secret_key="sk", base_url="https://lf.example.com")

        with patch(
            "agents.shared.langfuse_tools.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert client.health_check() is False


class TestLangfuseToolsHighLevel:
    """Tests for high-level functions in agents/shared/langfuse_tools.py."""

    def test_get_langfuse_client_returns_client(self):
        from agents.shared.langfuse_tools import _get_langfuse_client

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            result = _get_langfuse_client()
            assert not isinstance(result, tuple)

    def test_get_langfuse_client_returns_error_tuple(self):
        from agents.shared.langfuse_tools import _get_langfuse_client

        with patch.dict(os.environ, {}, clear=True):
            result = _get_langfuse_client()
            assert isinstance(result, tuple)
            assert result[0] is None
            assert "credentials" in result[1].lower()

    @pytest.mark.asyncio
    async def test_get_langfuse_traces_no_creds(self):
        from agents.shared.langfuse_tools import get_langfuse_traces

        with patch.dict(os.environ, {}, clear=True):
            result = await get_langfuse_traces(hours=1)
            assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_get_langfuse_stats_no_creds(self):
        from agents.shared.langfuse_tools import get_langfuse_stats

        with patch.dict(os.environ, {}, clear=True):
            result = await get_langfuse_stats(hours=1)
            assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_detect_langfuse_anomalies_no_creds(self):
        from agents.shared.langfuse_tools import detect_langfuse_anomalies

        with patch.dict(os.environ, {}, clear=True):
            result = await detect_langfuse_anomalies(hours=1)
            assert "not configured" in result.lower()

    def test_get_langfuse_context_no_creds(self):
        from agents.shared.langfuse_tools import get_langfuse_context

        with patch.dict(os.environ, {}, clear=True):
            result = get_langfuse_context(hours=1)
            assert "not configured" in result.lower()

    def test_get_langfuse_context_with_mock(self):
        from agents.shared.langfuse_tools import LangfuseStats, get_langfuse_context

        mock_stats = LangfuseStats(
            total_traces=42,
            total_tokens=10000,
            avg_latency_ms=500,
            error_count=2,
            error_rate=0.047,
            cost_usd=0.15,
            period_hours=6,
        )

        with patch("agents.shared.langfuse_tools._get_langfuse_client") as mock_get:
            mock_client = MagicMock()
            mock_client.get_stats.return_value = mock_stats
            mock_client.detect_anomalies.return_value = []
            mock_get.return_value = mock_client

            result = get_langfuse_context(hours=6)
            assert "42" in result
            assert "10,000" in result
            assert "No anomalies" in result


# ---------------------------------------------------------------------------
# 4. vibeteam/connectors/langfuse.py — LangfuseConnector
# ---------------------------------------------------------------------------


class TestLangfuseConnector:
    """Tests for LangfuseConnector class."""

    def test_init_with_explicit_keys(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk-test", secret_key="sk-test", base_url="https://lf.example.com"
        )
        assert conn.public_key == "pk-test"
        assert conn.secret_key == "sk-test"
        assert conn.base_url == "https://lf.example.com"

    def test_init_from_env(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-env",
            "LANGFUSE_SECRET_KEY": "sk-env",
        }
        with patch.dict(os.environ, env, clear=True):
            conn = LangfuseConnector()
            assert conn.public_key == "pk-env"
            assert conn.secret_key == "sk-env"
            assert conn.base_url == "https://langfuse.vibebrowser.app"

    def test_init_raises_without_keys(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
                LangfuseConnector()

    def test_strips_trailing_slash(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com/"
        )
        assert not conn.base_url.endswith("/")

    def test_request_builds_correct_url(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "vibeteam.connectors.langfuse.requests.request", return_value=mock_response
        ) as mock_req:
            conn._request("GET", "/traces", params={"limit": 10})
            mock_req.assert_called_once_with(
                "GET",
                "https://lf.example.com/api/public/traces",
                auth=("pk", "sk"),
                timeout=30,
                params={"limit": 10},
            )

    def test_get_stats_empty(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        with patch.object(conn, "get_traces", return_value=[]):
            stats = conn.get_stats(hours=1)
            assert stats.total_traces == 0

    def test_get_stats_with_data(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        traces = [
            {
                "id": "t1",
                "usage": {"totalTokens": 500},
                "latency": 2000,
                "level": "DEFAULT",
                "calculatedTotalCost": 0.05,
            },
            {
                "id": "t2",
                "usage": {"totalTokens": 300},
                "latency": 1000,
                "level": "DEFAULT",
                "calculatedTotalCost": 0.03,
            },
        ]

        with patch.object(conn, "get_traces", return_value=traces):
            stats = conn.get_stats(hours=1)
            assert stats.total_traces == 2
            assert stats.total_tokens == 800
            assert stats.avg_latency_ms == 1500
            assert stats.error_count == 0
            assert abs(stats.cost_usd - 0.08) < 0.001

    def test_detect_anomalies_no_traces(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        with patch.object(conn, "get_traces", return_value=[]):
            anomalies = conn.detect_anomalies(hours=1)
            assert anomalies == []

    def test_detect_anomalies_latency(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        traces = [
            {"id": "slow1", "latency": 20000, "usage": {}, "level": "DEFAULT"},
            {"id": "fast1", "latency": 100, "usage": {}, "level": "DEFAULT"},
        ]

        with patch.object(conn, "get_traces", return_value=traces):
            anomalies = conn.detect_anomalies(hours=1)
            latency = [a for a in anomalies if a.type == "latency"]
            assert len(latency) == 1
            assert "slow1" in latency[0].trace_ids

    def test_get_daily_summary(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        with patch.object(conn, "get_traces", return_value=[]):
            summary = conn.get_daily_summary()
            assert summary["period"] == "24h"
            assert summary["health"] == "healthy"
            assert summary["stats"]["traces"] == 0

    def test_health_check_success(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("vibeteam.connectors.langfuse.requests.get", return_value=mock_response):
            assert conn.health_check() is True

    def test_health_check_failure(self):
        from vibeteam.connectors.langfuse import LangfuseConnector

        conn = LangfuseConnector(
            public_key="pk", secret_key="sk", base_url="https://lf.example.com"
        )

        with patch(
            "vibeteam.connectors.langfuse.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert conn.health_check() is False


# ---------------------------------------------------------------------------
# Cross-layer consistency tests
# ---------------------------------------------------------------------------


class TestCrossLayerConsistency:
    """Verify consistency across the 4 Langfuse integration layers."""

    def test_default_urls_match(self):
        """All layers should agree on the default Langfuse URL."""
        from agents.shared.langfuse_tools import DEFAULT_LANGFUSE_URL

        # The __init__.py uses "https://langfuse.vibebrowser.app" directly
        # The tracing.py uses "https://langfuse.vibebrowser.app" as fallback
        # The connector uses "https://langfuse.vibebrowser.app" as default
        # The tools module uses DEFAULT_LANGFUSE_URL
        assert DEFAULT_LANGFUSE_URL == "https://langfuse.vibebrowser.app"

    def test_env_var_names_consistent(self):
        """All layers should read the same env var names."""
        # Read the source to verify env var usage
        # All modules should check LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
        # This is a documentation/consistency test
        import inspect

        import vibeteam.__init__ as init_mod
        import vibeteam.tracing as tracing_mod

        init_source = inspect.getsource(init_mod._init_langfuse)
        assert "LANGFUSE_PUBLIC_KEY" in init_source
        assert "LANGFUSE_SECRET_KEY" in init_source

        tracing_source = inspect.getsource(tracing_mod.is_tracing_enabled)
        assert "LANGFUSE_PUBLIC_KEY" in tracing_source
        assert "LANGFUSE_SECRET_KEY" in tracing_source

    def test_anomaly_thresholds_consistent(self):
        """LangfuseClient and LangfuseConnector should use matching thresholds."""
        from agents.shared.langfuse_tools import (
            ERROR_RATE_CRITICAL,
            ERROR_RATE_WARNING,
            LATENCY_CRITICAL_MS,
            LATENCY_WARNING_MS,
            TOKEN_BUDGET_CRITICAL,
            TOKEN_BUDGET_WARNING,
        )
        from vibeteam.connectors.langfuse import LangfuseConnector

        assert LATENCY_WARNING_MS == LangfuseConnector.LATENCY_WARNING_MS
        assert LATENCY_CRITICAL_MS == LangfuseConnector.LATENCY_CRITICAL_MS
        assert ERROR_RATE_WARNING == LangfuseConnector.ERROR_RATE_WARNING
        assert ERROR_RATE_CRITICAL == LangfuseConnector.ERROR_RATE_CRITICAL
        assert TOKEN_BUDGET_WARNING == LangfuseConnector.TOKEN_BUDGET_WARNING
        assert TOKEN_BUDGET_CRITICAL == LangfuseConnector.TOKEN_BUDGET_CRITICAL
