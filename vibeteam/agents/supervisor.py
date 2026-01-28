"""
SupervisorAgent - Orchestrates the VibeTeam using Swarm pattern.

The Supervisor Agent extends ProductManagerAgent with orchestration capabilities.
It can delegate tasks to specialized agents and synthesize their outputs.
Based on the AutoGen Swarm pattern with tool-based handoffs.
"""

import logging
from typing import Any

from vibeteam.agents.product_manager import ProductManagerAgent
from vibeteam.state import SharedMessageState
from vibeteam.tools.transfer import (
    TransferToMarketerTool,
    TransferToReleaseTool,
    TransferToSRETool,
    TransferToSupportTool,
    TransferToSWETool,
    is_handoff_result,
    parse_handoff,
)

logger = logging.getLogger(__name__)


class SupervisorAgent(ProductManagerAgent):
    """
    Supervisor Agent - Orchestrates the VibeTeam.

    Based on ProductManager with added orchestration capabilities:
    - Transfer tools for delegation to other agents
    - Shared state management
    - Multi-turn conversation handling
    - Result synthesis from sub-agents

    The Supervisor sees all messages from sub-agents in the shared state,
    enabling true collaborative workflows.
    """

    name = "Curie (Supervisor)"
    profile = "Product Manager & Team Supervisor"
    goal = "Orchestrate the VibeTeam to accomplish user goals effectively"
    model = "azure/gpt-4.1"
    temperature = 0.3  # Slightly lower for more consistent routing decisions

    def __init__(
        self,
        shared_state: SharedMessageState | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the Supervisor Agent.

        Args:
            shared_state: Shared message state for swarm visibility
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        # Add transfer tools for delegation
        self.add_tool(TransferToSWETool())
        self.add_tool(TransferToSRETool())
        self.add_tool(TransferToReleaseTool())
        self.add_tool(TransferToSupportTool())
        self.add_tool(TransferToMarketerTool())

        # Shared state for swarm coordination
        self.shared_state = shared_state

    def _get_system_prompt(self) -> str:
        """Custom system prompt for Supervisor with orchestration focus."""
        return f"""You are {self.name}, the {self.profile} of VibeTeam.

ROLE:
You orchestrate an autonomous AI team to accomplish user goals. You are both the
Product Manager and the team's supervisor/coordinator.

TEAM MEMBERS:
- **Ada (SWE)**: Software Engineer - code implementation, bug fixes, code review, PRs
- **Heisenberg (SRE)**: Reliability Engineer - monitoring, Sentry errors, incidents, infrastructure
- **Jenkins (Release)**: Release Engineer - deployments, versioning, changelogs
- **Watson (Support)**: Support Engineer - customer issues, documentation, FAQs
- **Bernays (Marketer)**: Marketer - social media, announcements, content

YOUR RESPONSIBILITIES:
1. Understand user requests and break them into actionable tasks
2. Delegate to appropriate team members using transfer tools
3. Synthesize results from team members for the user
4. Make product decisions when needed
5. Provide final answers to the user

DELEGATION GUIDELINES:
- Use `transfer_to_swe` for coding tasks, bug fixes, implementations
- Use `transfer_to_sre` for monitoring, Sentry errors, production issues
- Use `transfer_to_release` for deployments, releases, changelogs
- Use `transfer_to_support` for customer issues, documentation
- Use `transfer_to_marketer` for social posts, announcements

WORKFLOW:
1. Analyze the user's request
2. Decide if you can handle it directly (product questions, simple answers) or need to delegate
3. If delegating, use the appropriate transfer tool with a clear task description
4. After receiving results from sub-agents, synthesize and present to user
5. If the task is complete, provide a final response

RULES:
- Always explain your delegation decisions briefly
- Summarize sub-agent results for the user
- For simple queries, respond directly without delegation
- If unsure which agent to use, choose the most relevant one
- Complete tasks before returning to the user

Available tools: {", ".join(t.name for t in self.tools)}
"""

    async def run_with_state(
        self,
        shared_state: SharedMessageState,
        task: str | None = None,
    ) -> str:
        """
        Run the supervisor with shared state context.

        This method is used by the SwarmOrchestrator to run the supervisor
        with full visibility into the shared conversation state.

        Args:
            shared_state: The shared message state
            task: Optional new task to process (if None, continues from state)

        Returns:
            The supervisor's response (may be a handoff signal or final answer)
        """
        self.shared_state = shared_state

        # Build messages from shared state
        context_messages = shared_state.get_context_for_agent("supervisor")

        # If there's a new task, add it
        if task:
            context_messages.append({"role": "user", "content": task})

        # Reset conversation and rebuild with shared context
        self._init_system_prompt()
        for msg in context_messages:
            if msg["role"] != "system":  # System prompt already set
                from vibeteam.agents.base import Message

                self.conversation.append(
                    Message(
                        role=msg["role"],
                        content=msg["content"],
                        name=msg.get("name"),
                    )
                )

        # Run the agent
        response = await self.run(task or "Continue with the current context.")
        return response

    def delegate_to(self, agent_key: str, task: str) -> str:
        """
        Create a delegation message for a specific agent.

        This is a convenience method for programmatic delegation.

        Args:
            agent_key: The agent to delegate to (swe, sre, release, support, marketer)
            task: The task to delegate

        Returns:
            The handoff signal string
        """
        from vibeteam.tools.transfer import HANDOFF_PREFIX

        return f"{HANDOFF_PREFIX}{agent_key}:{task}"


def is_supervisor_response_final(response: str) -> bool:
    """
    Check if a supervisor response is a final answer (not a handoff).

    Args:
        response: The supervisor's response string

    Returns:
        True if this is a final answer, False if it's a handoff
    """
    return not is_handoff_result(response)


def get_handoff_target(response: str) -> tuple[str, str] | None:
    """
    Extract handoff target and task from a supervisor response.

    Args:
        response: The supervisor's response string

    Returns:
        Tuple of (agent_key, task) if handoff, None if not
    """
    return parse_handoff(response)
