"""
Langfuse Tracing for SwarmOrchestrator.

Provides observability for multi-agent execution:
- Trace for each SwarmOrchestrator.run() call
- Child spans for each agent invocation
- Handoff events logged as span events
- Token usage tracked per agent

Uses Langfuse SDK v3 with start_span/start_as_current_span API.
"""

import logging
import os
from contextlib import contextmanager
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Generator, TypeVar

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse._client.span import LangfuseSpan

logger = logging.getLogger(__name__)

# Type variable for decorator
F = TypeVar("F", bound=Callable[..., Any])

# Global Langfuse client (lazy initialized)
_langfuse_client: "Langfuse | None" = None
_tracing_enabled: bool | None = None


def is_tracing_enabled() -> bool:
    """Check if Langfuse tracing is enabled and configured."""
    global _tracing_enabled

    if _tracing_enabled is not None:
        return _tracing_enabled

    # Check if explicitly disabled
    if os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower() == "false":
        _tracing_enabled = False
        return False

    # Check if credentials are configured
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")

    _tracing_enabled = bool(public_key and secret_key)

    if not _tracing_enabled:
        logger.debug("Langfuse tracing disabled: credentials not configured")

    return _tracing_enabled


def get_langfuse_client() -> "Langfuse | None":
    """Get or create the Langfuse client."""
    global _langfuse_client

    if not is_tracing_enabled():
        return None

    if _langfuse_client is not None:
        return _langfuse_client

    try:
        from langfuse import Langfuse

        host = os.environ.get("LANGFUSE_HOST") or os.environ.get(
            "LANGFUSE_BASE_URL", "https://langfuse.vibebrowser.app"
        )

        _langfuse_client = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
            host=host,
        )
        logger.info(f"Langfuse client initialized (host: {host})")
        return _langfuse_client
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse client: {e}")
        return None


def flush_traces() -> None:
    """Flush any pending traces to Langfuse."""
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse traces: {e}")


@contextmanager
def trace_swarm_run(
    session_id: str,
    user_message: str,
    model: str,
    max_iterations: int,
) -> Generator["SwarmTrace", None, None]:
    """
    Create a trace for a SwarmOrchestrator.run() call.

    Args:
        session_id: Unique session identifier
        user_message: The user's input message
        model: LLM model being used
        max_iterations: Maximum iterations configured

    Yields:
        SwarmTrace object for recording spans and events
    """
    trace = SwarmTrace(
        session_id=session_id,
        user_message=user_message,
        model=model,
        max_iterations=max_iterations,
    )

    try:
        yield trace
    finally:
        trace.end()


class SwarmTrace:
    """
    Trace for a SwarmOrchestrator run.

    Manages the root trace and child spans for agent invocations.
    """

    def __init__(
        self,
        session_id: str,
        user_message: str,
        model: str,
        max_iterations: int,
    ):
        self.session_id = session_id
        self.user_message = user_message
        self.model = model
        self.max_iterations = max_iterations

        self._trace: Any = None
        self._current_span: Any = None
        self._agent_spans: dict[str, Any] = {}
        self._total_tokens: int = 0
        self._agent_tokens: dict[str, int] = {}
        self._started = False

        self._start_trace()

    def _start_trace(self) -> None:
        """Start the root trace/span."""
        client = get_langfuse_client()
        if not client:
            return

        try:
            # Langfuse SDK v3 uses start_span (not trace)
            # The root span acts as the trace
            self._trace = client.start_span(
                name="swarm-orchestrator-run",
                input={"user_message": self.user_message},
                metadata={
                    "model": self.model,
                    "max_iterations": self.max_iterations,
                    "session_id": self.session_id,
                },
            )
            # Update trace-level metadata
            client.update_current_trace(
                session_id=self.session_id,
                tags=["swarm", "multi-agent"],
            )
            self._started = True
            logger.debug(f"Started Langfuse trace for session: {self.session_id}")
        except Exception as e:
            logger.warning(f"Failed to start Langfuse trace: {e}")

    def start_agent_span(
        self,
        agent_name: str,
        agent_key: str,
        iteration: int,
        task: str,
    ) -> "AgentSpan":
        """
        Start a span for an agent invocation.

        Args:
            agent_name: Human-readable agent name
            agent_key: Agent key (swe, pm, etc.)
            iteration: Current iteration number
            task: Task being executed

        Returns:
            AgentSpan context manager
        """
        return AgentSpan(
            trace=self,
            agent_name=agent_name,
            agent_key=agent_key,
            iteration=iteration,
            task=task,
        )

    def record_handoff(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        iteration: int,
    ) -> None:
        """
        Record a handoff event.

        Args:
            from_agent: Source agent key
            to_agent: Target agent key
            task: Delegated task
            iteration: Current iteration number
        """
        if not self._trace:
            return

        try:
            # Create an event on the current span
            self._trace.create_event(
                name="agent-handoff",
                input={
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "task": task,
                },
                metadata={
                    "iteration": iteration,
                    "handoff_type": "tool-based",
                },
            )
            logger.debug(f"Recorded handoff: {from_agent} -> {to_agent}")
        except Exception as e:
            logger.warning(f"Failed to record handoff event: {e}")

    def record_error(
        self,
        agent_name: str,
        error: Exception,
        iteration: int,
    ) -> None:
        """
        Record an error event.

        Args:
            agent_name: Agent that encountered error
            error: The exception
            iteration: Current iteration number
        """
        if not self._trace:
            return

        try:
            self._trace.create_event(
                name="agent-error",
                level="ERROR",
                input={
                    "agent": agent_name,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                },
                metadata={
                    "iteration": iteration,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to record error event: {e}")

    def add_tokens(self, agent_key: str, tokens: int) -> None:
        """
        Add token usage for an agent.

        Args:
            agent_key: Agent key
            tokens: Number of tokens used
        """
        self._total_tokens += tokens
        self._agent_tokens[agent_key] = self._agent_tokens.get(agent_key, 0) + tokens

    def end(
        self,
        output: str | None = None,
        agents_used: list[str] | None = None,
        iterations: int = 0,
        success: bool = True,
    ) -> None:
        """
        End the trace with final output.

        Args:
            output: Final response from orchestrator
            agents_used: List of agents that were invoked
            iterations: Total iterations used
            success: Whether the run completed successfully
        """
        if not self._trace:
            return

        try:
            self._trace.update(
                output=output or "",
                metadata={
                    "agents_used": agents_used or [],
                    "iterations": iterations,
                    "total_tokens": self._total_tokens,
                    "tokens_per_agent": self._agent_tokens,
                    "success": success,
                },
            )
            # End the span
            self._trace.end()

            # Flush to ensure trace is sent
            flush_traces()
            logger.debug(f"Ended Langfuse trace for session: {self.session_id}")
        except Exception as e:
            logger.warning(f"Failed to end Langfuse trace: {e}")


class AgentSpan:
    """
    Context manager for an agent invocation span.

    Tracks:
    - Agent execution time
    - Input task
    - Output response
    - Token usage
    - Errors
    """

    def __init__(
        self,
        trace: SwarmTrace,
        agent_name: str,
        agent_key: str,
        iteration: int,
        task: str,
    ):
        self.trace = trace
        self.agent_name = agent_name
        self.agent_key = agent_key
        self.iteration = iteration
        self.task = task

        self._span: Any = None
        self._tokens: int = 0

    def __enter__(self) -> "AgentSpan":
        """Start the agent span."""
        if not self.trace._trace:
            return self

        try:
            self._span = self.trace._trace.start_span(
                name=f"agent-{self.agent_key}",
                input={"task": self.task},
                metadata={
                    "agent_name": self.agent_name,
                    "agent_key": self.agent_key,
                    "iteration": self.iteration,
                },
            )
            self.trace._current_span = self._span
            self.trace._agent_spans[self.agent_key] = self._span
        except Exception as e:
            logger.warning(f"Failed to start agent span: {e}")

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """End the agent span."""
        # Always record tokens even if span is None
        if self._tokens > 0:
            self.trace.add_tokens(self.agent_key, self._tokens)

        if not self._span:
            return

        try:
            if exc_val:
                # Record error
                self._span.update(
                    level="ERROR",
                    status_message=str(exc_val),
                    metadata={
                        "error_type": type(exc_val).__name__ if exc_val else None,
                    },
                )
            else:
                self._span.end()

            self.trace._current_span = None
        except Exception as e:
            logger.warning(f"Failed to end agent span: {e}")

    def set_output(self, output: str) -> None:
        """Set the agent's output."""
        if self._span:
            try:
                self._span.update(output=output)
            except Exception as e:
                logger.warning(f"Failed to set span output: {e}")

    def set_tokens(self, tokens: int) -> None:
        """Set token usage for this agent invocation."""
        self._tokens = tokens

    def add_event(self, name: str, data: dict[str, Any] | None = None) -> None:
        """Add an event to the span."""
        if self._span:
            try:
                self._span.create_event(name=name, input=data or {})
            except Exception as e:
                logger.warning(f"Failed to add span event: {e}")


def observe_agent(func: F) -> F:
    """
    Decorator to observe agent execution with Langfuse.

    Can be applied to agent run methods for automatic tracing.
    Falls back gracefully if Langfuse is not configured.
    """
    if not is_tracing_enabled():
        return func

    try:
        from langfuse import observe

        return observe(name=func.__name__, as_type="agent")(func)
    except ImportError:
        return func
    except Exception as e:
        logger.warning(f"Failed to apply observe decorator: {e}")
        return func
