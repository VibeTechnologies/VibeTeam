"""
SupervisorAgent - Orchestrates the VibeTeam using natural @mention handoffs.

The Supervisor Agent extends ProductManagerAgent with orchestration capabilities.
It coordinates tasks by naturally mentioning other agents in responses.
"""

import logging
from typing import Any

from vibeteam.agents.product_manager import ProductManagerAgent
from vibeteam.state import SharedMessageState

logger = logging.getLogger(__name__)

# Natural @mention instructions for agent handoffs
HANDOFF_INSTRUCTIONS = """
## Team Collaboration

When you need another team member's help, @mention them in your response:
- @SoftwareEngineer - for code implementation, bug fixes, PRs
- @ReleaseEngineer - for deployments and releases
- @SupportEngineer - for customer communication
- @SiteReliabilityEngineer - for monitoring, Sentry errors, infrastructure
- @MarketingManager - for announcements and content

Example: "I've analyzed the request. @SoftwareEngineer please implement the login validation fix."

The mentioned agent will automatically pick up the conversation.
"""


class SupervisorAgent(ProductManagerAgent):
    """
    Supervisor Agent - Orchestrates the VibeTeam.

    Based on ProductManager with added orchestration capabilities:
    - Natural @mention handoffs to other agents
    - Shared state management
    - Multi-turn conversation handling
    - Result synthesis from sub-agents

    The Supervisor sees all messages from sub-agents in the shared state,
    enabling true collaborative workflows.
    """

    name = "ProductManager"
    profile = "Product Manager & Team Supervisor"
    goal = "Orchestrate the VibeTeam to accomplish user goals effectively"

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

        # Shared state for coordination
        self.shared_state = shared_state

    def _get_system_prompt(self) -> str:
        """Custom system prompt for Supervisor with orchestration focus."""
        return f"""You are {self.name}, the {self.profile} of VibeTeam.

ROLE:
You orchestrate an autonomous AI team to accomplish user goals. You are both the
Product Manager and the team's supervisor/coordinator.

TEAM MEMBERS:
- **SoftwareEngineer**: Code implementation, bug fixes, code review, PRs
- **SiteReliabilityEngineer**: Monitoring, Sentry errors, incidents, infrastructure
- **ReleaseEngineer**: Deployments, versioning, changelogs
- **SupportEngineer**: Customer issues, documentation, FAQs
- **MarketingManager**: Social media, announcements, content

YOUR RESPONSIBILITIES:
1. Understand user requests and break them into actionable tasks
2. Delegate to appropriate team members by @mentioning them
3. Synthesize results from team members for the user
4. Make product decisions when needed
5. Provide final answers to the user

{HANDOFF_INSTRUCTIONS}

WORKFLOW:
1. Analyze the user's request
2. Decide if you can handle it directly (product questions, simple answers) or need to delegate
3. If delegating, @mention the appropriate agent with a clear task description
4. After receiving results from other agents, synthesize and present to user
5. If the task is complete, provide a final response

RULES:
- Always explain your delegation decisions briefly
- Summarize agent results for the user
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

        This method is used to run the supervisor with full visibility
        into the shared conversation state.

        Args:
            shared_state: The shared message state
            task: Optional new task to process (if None, continues from state)

        Returns:
            The supervisor's response
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
