"""
SwarmOrchestrator - Manages multi-agent execution using the Swarm pattern.

The orchestrator coordinates agents in a swarm, handling tool-based handoffs
and maintaining shared state for full supervisor visibility.
Based on the AutoGen Swarm pattern.

Includes Langfuse tracing for observability:
- Trace for each run() call
- Child spans for each agent invocation
- Handoff events
- Token usage tracking
"""

import logging
from typing import Any

from vibeteam.agents import (
    BaseVibeAgent,
    MarketerAgent,
    ProductManagerAgent,
    ReleaseEngineerAgent,
    ReliabilityEngineerAgent,
    SoftwareEngineerAgent,
    SupportEngineerAgent,
)
from vibeteam.agents.supervisor import SupervisorAgent
from vibeteam.state import SharedMessageState
from vibeteam.tools.transfer import (
    TransferToSupervisorTool,
    is_handoff_result,
    parse_handoff,
)
from vibeteam.tracing import SwarmTrace, is_tracing_enabled, trace_swarm_run

logger = logging.getLogger(__name__)


# Agent key to class mapping
AGENT_REGISTRY: dict[str, type[BaseVibeAgent]] = {
    "pm": ProductManagerAgent,
    "swe": SoftwareEngineerAgent,
    "marketer": MarketerAgent,
    "support": SupportEngineerAgent,
    "sre": ReliabilityEngineerAgent,
    "release": ReleaseEngineerAgent,
}


class SwarmOrchestrator:
    """
    Orchestrates multi-agent execution using the Swarm pattern.

    Features:
    - Tool-based agent handoffs (deterministic)
    - Shared message state (full supervisor visibility)
    - Maximum iteration limits (prevents infinite loops)
    - Langfuse tracing integration
    - Session management for multi-turn conversations

    Example:
        ```python
        state = SharedMessageState()
        orchestrator = SwarmOrchestrator(state)
        response = await orchestrator.run("Fix the login bug from Sentry")
        ```
    """

    def __init__(
        self,
        shared_state: SharedMessageState | None = None,
        model: str = "azure/gpt-4.1",
        max_iterations: int = 20,
        enable_tracing: bool = True,
    ):
        """
        Initialize the SwarmOrchestrator.

        Args:
            shared_state: Shared message state (creates new if None)
            model: LLM model to use for all agents
            max_iterations: Maximum iterations before stopping (prevents loops)
            enable_tracing: Whether to enable Langfuse tracing
        """
        self.shared_state = shared_state or SharedMessageState()
        self.model = model
        self.max_iterations = max_iterations
        self.enable_tracing = enable_tracing

        # Initialize supervisor
        self.supervisor = SupervisorAgent(
            shared_state=self.shared_state,
            model=model,
        )

        # Initialize agents with transfer tools
        self.agents: dict[str, BaseVibeAgent] = {}
        self._initialize_agents()

        # Current agent being executed
        self.current_agent: BaseVibeAgent = self.supervisor
        self.iteration_count = 0

    def _initialize_agents(self) -> None:
        """Initialize all agents with transfer tools."""
        for key, agent_class in AGENT_REGISTRY.items():
            agent = agent_class(model=self.model)

            # Add transfer to supervisor tool so agents can hand back
            agent.add_tool(TransferToSupervisorTool())

            self.agents[key] = agent
            logger.debug(f"Initialized agent: {agent.name} ({key})")

        # Add supervisor as an alias
        self.agents["supervisor"] = self.supervisor

        logger.info(f"SwarmOrchestrator initialized with {len(self.agents)} agents")

    def get_agent(self, key: str) -> BaseVibeAgent:
        """
        Get an agent by key.

        Args:
            key: Agent key (swe, sre, pm, supervisor, etc.)

        Returns:
            The agent instance, or supervisor as fallback
        """
        if key == "supervisor" or key == "pm":
            return self.supervisor
        return self.agents.get(key, self.supervisor)

    async def run(self, user_message: str) -> str:
        """
        Run the swarm until completion or max iterations.

        The orchestrator:
        1. Adds the user message to shared state
        2. Runs the current agent (starts with supervisor)
        3. If agent returns a handoff, switches to target agent
        4. Continues until supervisor returns without handoff
        5. Returns the final response

        Includes Langfuse tracing when enabled.

        Args:
            user_message: The user's request

        Returns:
            The final response from the supervisor
        """
        # Add user message to shared state
        self.shared_state.add_message("user", user_message)

        # Start with supervisor
        self.current_agent = self.supervisor
        self.shared_state.current_agent = "supervisor"

        # Create trace if tracing is enabled
        trace: SwarmTrace | None = None
        if self.enable_tracing and is_tracing_enabled():
            trace = SwarmTrace(
                session_id=self.shared_state.session_id,
                user_message=user_message,
                model=self.model,
                max_iterations=self.max_iterations,
            )

        try:
            response = await self._run_loop(trace)
            if trace:
                trace.end(
                    output=response,
                    agents_used=self.get_agents_used(),
                    iterations=self.iteration_count,
                    success=True,
                )
            return response
        except Exception as e:
            if trace:
                trace.record_error("orchestrator", e, self.iteration_count)
                trace.end(
                    output=str(e),
                    agents_used=self.get_agents_used(),
                    iterations=self.iteration_count,
                    success=False,
                )
            raise

    async def _run_loop(self, trace: SwarmTrace | None = None) -> str:
        """
        Execute the main agent loop.

        Args:
            trace: Optional Langfuse trace for observability

        Returns:
            The final response from the supervisor
        """
        for iteration in range(self.max_iterations):
            self.iteration_count = iteration + 1
            self.shared_state.iteration_count = self.iteration_count
            agent_key = self._get_agent_key(self.current_agent)

            logger.info(
                f"Iteration {self.iteration_count}/{self.max_iterations}: "
                f"Running {self.current_agent.name}"
            )

            # Find current task
            task = self._get_current_task()

            # Run current agent with tracing
            try:
                if trace:
                    with trace.start_agent_span(
                        agent_name=self.current_agent.name,
                        agent_key=agent_key,
                        iteration=self.iteration_count,
                        task=task,
                    ) as span:
                        response = await self._run_agent(self.current_agent)
                        span.set_output(response)
                else:
                    response = await self._run_agent(self.current_agent)
            except Exception as e:
                logger.exception(f"Agent {self.current_agent.name} failed")
                if trace:
                    trace.record_error(self.current_agent.name, e, self.iteration_count)
                self.shared_state.add_message(
                    "system",
                    f"Agent error: {str(e)}",
                    agent_name=self.current_agent.name,
                )
                # Fall back to supervisor
                if self.current_agent != self.supervisor:
                    self.current_agent = self.supervisor
                    continue
                else:
                    return f"I encountered an error: {str(e)}"

            # Check for handoff signal
            if is_handoff_result(response):
                parsed = parse_handoff(response)
                if parsed:
                    target, handoff_task = parsed
                    logger.info(f"Handoff: {self.current_agent.name} -> {target}")

                    # Record handoff in trace
                    if trace:
                        trace.record_handoff(
                            from_agent=agent_key,
                            to_agent=target,
                            task=handoff_task,
                            iteration=self.iteration_count,
                        )

                    # Record handoff in shared state
                    self.shared_state.add_handoff(
                        from_agent=agent_key,
                        to_agent=target,
                        task=handoff_task,
                    )

                    # Switch to target agent
                    self.current_agent = self.get_agent(target)
                    continue

            # No handoff - add response to state
            self.shared_state.add_message(
                "assistant",
                response,
                agent_name=agent_key,
            )

            # If supervisor and no handoff, this is the final response
            if self.current_agent == self.supervisor:
                return response

        # Max iterations reached
        logger.warning(f"Max iterations ({self.max_iterations}) reached")
        return (
            "I apologize, but I wasn't able to complete this task within the allowed steps. "
            "Please try breaking down your request into smaller parts."
        )

    def _get_current_task(self) -> str:
        """Get the current task from shared state."""
        for msg in reversed(self.shared_state.messages):
            if msg.role == "user":
                return msg.content
            if msg.metadata.get("type") == "handoff" and msg.metadata.get(
                "to"
            ) == self._get_agent_key(self.current_agent):
                return msg.metadata.get("task", "")
        return "Continue with the current task based on the conversation."

    async def _run_agent(self, agent: BaseVibeAgent) -> str:
        """
        Run an agent with shared state context.

        Args:
            agent: The agent to run

        Returns:
            The agent's response
        """
        # Get context from shared state
        context_messages = self.shared_state.get_context_for_agent(agent.name)

        # Get current task
        task = self._get_current_task()

        # For supervisor, use run_with_state if available
        if isinstance(agent, SupervisorAgent):
            return await agent.run_with_state(self.shared_state, task)

        # For other agents, run with task
        return await agent.run(task)

    def _get_agent_key(self, agent: BaseVibeAgent) -> str:
        """Get the key for an agent."""
        for key, a in self.agents.items():
            if a is agent:
                return key
        if agent == self.supervisor:
            return "supervisor"
        return "unknown"

    def get_agents_used(self) -> list[str]:
        """Get list of agents used in this session."""
        return self.shared_state.agents_used.copy()

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the orchestrator state."""
        return {
            "session_id": self.shared_state.session_id,
            "current_agent": self._get_agent_key(self.current_agent),
            "iteration_count": self.iteration_count,
            "max_iterations": self.max_iterations,
            "agents_used": self.get_agents_used(),
            "message_count": len(self.shared_state.messages),
            "model": self.model,
        }

    def reset(self) -> None:
        """Reset the orchestrator for a new conversation."""
        self.shared_state.clear()
        self.current_agent = self.supervisor
        self.iteration_count = 0

        # Reset all agents
        for agent in self.agents.values():
            agent.reset()
        self.supervisor.reset()

        logger.info("SwarmOrchestrator reset")


def create_swarm_orchestrator(
    model: str = "azure/gpt-4.1",
    max_iterations: int = 20,
) -> SwarmOrchestrator:
    """
    Create a new SwarmOrchestrator with default settings.

    Args:
        model: LLM model to use
        max_iterations: Maximum iterations

    Returns:
        Configured SwarmOrchestrator
    """
    return SwarmOrchestrator(
        shared_state=SharedMessageState(),
        model=model,
        max_iterations=max_iterations,
    )
