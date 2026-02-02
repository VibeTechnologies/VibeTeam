"""Test harness for multi-agent team scenarios.

This module provides TeamTestHarness for running simulated multi-agent
conversations and converting results to DeepEval test cases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from vibeteam.lib.channel import ChannelMessage, SimulatedChannel
from vibeteam.lib.responsibility import ResponsibilityDetector

if TYPE_CHECKING:
    pass


@dataclass
class ScenarioResult:
    """Result of running a test scenario."""

    framework: str
    channel: SimulatedChannel
    initial_message: str
    agent_responses: dict[str, list[ChannelMessage]]
    elapsed_ms: int
    expected_agents: list[str] = field(default_factory=list)

    @property
    def total_messages(self) -> int:
        """Total number of messages in the conversation."""
        return len(self.channel.messages)

    @property
    def responding_agents(self) -> list[str]:
        """List of agents that responded."""
        return [role for role, msgs in self.agent_responses.items() if msgs]

    @property
    def correct_agents_responded(self) -> bool:
        """Check if the expected agents responded."""
        if not self.expected_agents:
            return True
        return all(agent in self.responding_agents for agent in self.expected_agents)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "framework": self.framework,
            "initial_message": self.initial_message,
            "elapsed_ms": self.elapsed_ms,
            "expected_agents": self.expected_agents,
            "responding_agents": self.responding_agents,
            "total_messages": self.total_messages,
            "correct_agents_responded": self.correct_agents_responded,
            "transcript": self.channel.to_transcript(),
        }

    def to_deepeval_test_case(self):
        """Convert to DeepEval ConversationalTestCase.

        Returns:
            ConversationalTestCase for evaluation

        Note:
            Requires deepeval to be installed.
        """
        try:
            from deepeval.test_case import ConversationalTestCase
        except ImportError:
            raise ImportError(
                "deepeval is required for to_deepeval_test_case(). "
                "Install with: pip install deepeval"
            ) from None

        turns = self.channel.to_deepeval_turns()

        return ConversationalTestCase(
            turns=turns,
            additional_metadata={
                "framework": self.framework,
                "expected_agents": self.expected_agents,
                "elapsed_ms": self.elapsed_ms,
                "correct_agents_responded": self.correct_agents_responded,
            },
        )


class MockAgent:
    """Mock agent for testing without real LLM calls.

    Simulates agent behavior with predefined responses based on role.
    """

    def __init__(self, role: str):
        self.role = role
        self.responsibility_detector = ResponsibilityDetector(agent_role=role, use_llm=False)
        self._response_templates = self._get_response_templates()

    def _get_response_templates(self) -> dict[str, str]:
        """Get role-specific response templates."""
        templates = {
            "software_engineer": "I'll investigate the code issue. {action}",
            "release_engineer": "I'll handle the deployment. {action}",
            "support_engineer": "I'll address the customer issue. {action}",
            "product_manager": "I'll prioritize this in our backlog. {action}",
            "marketing_manager": "I'll prepare the announcement. {action}",
        }
        return templates.get(self.role, "I'll look into this. {action}")

    async def evaluate_message(self, message: ChannelMessage) -> bool:
        """Check if this agent should respond to the message.

        Args:
            message: The message to evaluate

        Returns:
            True if this agent should respond
        """
        claim = await self.responsibility_detector.should_claim(message)
        return claim.should_claim

    async def generate_response(self, message: ChannelMessage) -> str:
        """Generate a response to the message.

        Args:
            message: The message to respond to

        Returns:
            Response string
        """
        # Simple mock response based on role
        action = self._determine_action(message.content)
        template = self._response_templates
        if isinstance(template, str):
            return template.format(action=action)
        return f"I'm taking this - {action}"

    def _determine_action(self, content: str) -> str:
        """Determine action based on content."""
        content_lower = content.lower()

        if "error" in content_lower or "bug" in content_lower:
            return "Fixing the issue now."
        if "deploy" in content_lower:
            return "Initiating deployment."
        if "customer" in content_lower:
            return "Contacting the customer."
        if "feature" in content_lower:
            return "Adding to backlog."
        if "announce" in content_lower:
            return "Drafting announcement."

        return "Working on it."


class TeamTestHarness:
    """Test harness for running multi-agent scenarios.

    Simulates the full message flow:
    1. User posts to channel
    2. All agents receive and evaluate
    3. Agents claim responsibility and work
    4. Agents coordinate via channel
    5. Task completes

    Attributes:
        framework: Agent framework to use ("autogen", "crewai", "openhands", "opencode", "mock")
        channel: Simulated channel for messages
        agents: Dict of agent role to agent instance
    """

    AGENT_ROLES = [
        "software_engineer",
        "release_engineer",
        "support_engineer",
        "product_manager",
        "marketing_manager",
    ]

    def __init__(self, framework: str = "mock"):
        """Initialize the test harness.

        Args:
            framework: Agent framework to use. Use "mock" for testing
                      without real LLM calls.
        """
        self.framework = framework
        self.channel = SimulatedChannel(name="test-team-channel")
        self.agents: dict[str, Any] = {}
        self._setup_agents()

    def _setup_agents(self) -> None:
        """Initialize all team agents."""
        for role in self.AGENT_ROLES:
            agent = self._create_agent(role)
            self.agents[role] = agent

            # Subscribe agent to channel messages
            async def on_message(msg: ChannelMessage, agent=agent, role=role) -> None:
                await self._on_message(agent, role, msg)

            self.channel.subscribe(on_message)

    def _create_agent(self, role: str) -> Any:
        """Create an agent for the given role.

        Args:
            role: Agent role (e.g., "software_engineer")

        Returns:
            Agent instance
        """
        if self.framework == "mock":
            return MockAgent(role)

        # For real frameworks, import and create the appropriate agent
        if self.framework == "crewai":
            return self._create_crewai_agent(role)
        elif self.framework == "autogen":
            return self._create_autogen_agent(role)
        elif self.framework == "openhands":
            return self._create_openhands_agent(role)
        elif self.framework == "opencode":
            return self._create_opencode_agent(role)
        else:
            # Default to mock
            return MockAgent(role)

    def _create_crewai_agent(self, role: str) -> Any:
        """Create a CrewAI agent."""
        # Import CrewAI agents
        try:
            if role == "software_engineer":
                from agents.crewai.software_engineer import create_software_engineer

                return create_software_engineer()
            elif role == "release_engineer":
                from agents.crewai.release_engineer import create_release_engineer

                return create_release_engineer()
            elif role == "support_engineer":
                from agents.crewai.support_engineer import create_support_engineer

                return create_support_engineer()
            elif role == "product_manager":
                from agents.crewai.product_manager import create_product_manager

                return create_product_manager()
            else:
                return MockAgent(role)
        except ImportError:
            return MockAgent(role)

    def _create_autogen_agent(self, role: str) -> Any:
        """Create an AutoGen agent."""
        try:
            if role == "software_engineer":
                from agents.autogen.software_engineer import create_software_engineer

                return create_software_engineer()
            elif role == "release_engineer":
                from agents.autogen.release_engineer import create_release_engineer

                return create_release_engineer()
            elif role == "support_engineer":
                from agents.autogen.support_engineer import create_support_engineer

                return create_support_engineer()
            elif role == "product_manager":
                from agents.autogen.product_manager import create_product_manager

                return create_product_manager()
            else:
                return MockAgent(role)
        except ImportError:
            return MockAgent(role)

    def _create_openhands_agent(self, role: str) -> Any:
        """Create an OpenHands agent."""
        try:
            if role == "software_engineer":
                from agents.openhands.software_engineer import create_software_engineer

                return create_software_engineer()
            elif role == "release_engineer":
                from agents.openhands.release_engineer import create_release_engineer

                return create_release_engineer()
            elif role == "support_engineer":
                from agents.openhands.support_engineer import create_support_engineer

                return create_support_engineer()
            elif role == "product_manager":
                from agents.openhands.product_manager import create_product_manager

                return create_product_manager()
            elif role == "marketing_manager":
                from agents.openhands.marketing_manager import create_marketing_manager

                return create_marketing_manager()
            else:
                return MockAgent(role)
        except ImportError:
            return MockAgent(role)

    def _create_opencode_agent(self, role: str) -> Any:
        """Create an OpenCode agent."""
        try:
            if role == "software_engineer":
                from agents.opencode.software_engineer import create_software_engineer

                return create_software_engineer()
            elif role == "release_engineer":
                from agents.opencode.release_engineer import create_release_engineer

                return create_release_engineer()
            elif role == "support_engineer":
                from agents.opencode.support_engineer import create_support_engineer

                return create_support_engineer()
            elif role == "product_manager":
                from agents.opencode.product_manager import create_product_manager

                return create_product_manager()
            elif role == "marketing_manager":
                from agents.opencode.marketing_manager import create_marketing_manager

                return create_marketing_manager()
            else:
                return MockAgent(role)
        except ImportError:
            return MockAgent(role)

    async def _on_message(self, agent: Any, role: str, message: ChannelMessage) -> None:
        """Handle incoming message for an agent.

        Args:
            agent: The agent instance
            role: The agent's role
            message: The incoming message
        """
        # Skip messages from this agent (no self-reply)
        if message.author == role:
            return

        # Skip if message is from "system"
        if message.author == "system":
            return

        # Check if agent should respond
        if isinstance(agent, MockAgent):
            should_respond = await agent.evaluate_message(message)
            if should_respond:
                response = await agent.generate_response(message)
                self.channel.post(
                    author=role,
                    content=response,
                    reply_to=message.id,
                )
        else:
            # For real agents, use their run method
            # This is a simplified version - real implementation would
            # integrate with the agent's actual API
            pass

    async def run_scenario(
        self,
        initial_message: str,
        timeout: float = 5.0,
        expected_agents: list[str] | None = None,
    ) -> ScenarioResult:
        """Run a test scenario.

        Args:
            initial_message: The user's initial message
            timeout: Maximum time to wait for agents (seconds)
            expected_agents: Which agents we expect to respond

        Returns:
            ScenarioResult with conversation and metadata
        """
        start_time = time.perf_counter()

        # Clear any previous messages
        self.channel.clear()

        # Create the initial user message
        initial_msg = ChannelMessage(
            id="msg_0001",
            author="user",
            content=initial_message,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            mentions=[],
            reply_to=None,
        )
        self.channel.messages.append(initial_msg)

        # Process message with each agent synchronously (for testing)
        # This avoids async timing issues with create_task
        for role, agent in self.agents.items():
            if isinstance(agent, MockAgent):
                should_respond = await agent.evaluate_message(initial_msg)
                if should_respond:
                    response = await agent.generate_response(initial_msg)
                    self.channel.post(
                        author=role,
                        content=response,
                        reply_to=initial_msg.id,
                    )

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # Collect results
        agent_responses = {
            role: self.channel.get_messages_by_author(role) for role in self.agents.keys()
        }

        return ScenarioResult(
            framework=self.framework,
            channel=self.channel,
            initial_message=initial_message,
            agent_responses=agent_responses,
            elapsed_ms=elapsed_ms,
            expected_agents=expected_agents or [],
        )

    def reset(self) -> None:
        """Reset the harness for a new scenario."""
        self.channel.clear()


def create_handoff_test_case(scenario: ScenarioResult):
    """Convert a scenario result to a DeepEval ConversationalTestCase.

    Args:
        scenario: The scenario result to convert

    Returns:
        ConversationalTestCase for evaluation

    Note:
        This is a convenience function that wraps scenario.to_deepeval_test_case()
    """
    return scenario.to_deepeval_test_case()
