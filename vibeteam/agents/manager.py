import logging
from typing import Any

from vibeteam.router.models import AgentRole

logger = logging.getLogger(__name__)


class AgentSessionManager:
    """Manages agent sessions for each role."""

    def __init__(self, framework: str = "crewai"):
        self.framework = framework
        self._sessions: dict[str, Any] = {}  # role -> agent instance

    def get_agent(self, role: AgentRole):
        """Get or create an agent for a role."""
        if role in self._sessions:
            return self._sessions[role]

        agent = self._create_agent(role)
        self._sessions[role] = agent
        return agent

    def _create_agent(self, role: AgentRole):
        """Create an agent instance for a role."""
        if self.framework == "crewai":
            return self._create_crewai_agent(role)
        elif self.framework == "autogen":
            return self._create_autogen_agent(role)
        elif self.framework == "openhands":
            return self._create_openhands_agent(role)
        else:
            return self._create_vibeteam_agent(role)

    def _create_vibeteam_agent(self, role: AgentRole):
        """Create a vibeteam agent."""
        from vibeteam.agents import (
            ProductManagerAgent,
            ReleaseEngineerAgent,
            SoftwareEngineerAgent,
            SupportEngineerAgent,
        )

        agents = {
            "software_engineer": SoftwareEngineerAgent,
            "release_engineer": ReleaseEngineerAgent,
            "support_engineer": SupportEngineerAgent,
            "product_manager": ProductManagerAgent,
            "marketing_manager": ProductManagerAgent,
        }
        agent_class = agents.get(role)
        if agent_class:
            return agent_class()
        raise ValueError(f"No agent class for role: {role}")

    def _create_crewai_agent(self, role: AgentRole):
        """Create a CrewAI agent."""
        try:
            from agents.agent_service.crewai import (
                create_marketing_manager,
                create_product_manager,
                create_release_engineer,
                create_software_engineer,
                create_support_engineer,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning("CrewAI not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)

    def _create_autogen_agent(self, role: AgentRole):
        """Create an AutoGen agent."""
        try:
            from agents.agent_service.autogen import (
                create_marketing_manager,
                create_product_manager,
                create_release_engineer,
                create_software_engineer,
                create_support_engineer,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning("AutoGen not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)

    def _create_openhands_agent(self, role: AgentRole):
        """Create an OpenHands agent."""
        try:
            from agents.agent_service.openhands import (
                create_marketing_manager,
                create_product_manager,
                create_release_engineer,
                create_software_engineer,
                create_support_engineer,
            )

            creators = {
                "software_engineer": create_software_engineer,
                "release_engineer": create_release_engineer,
                "support_engineer": create_support_engineer,
                "product_manager": create_product_manager,
                "marketing_manager": create_marketing_manager,
            }
            creator = creators.get(role)
            if creator:
                return creator()
        except ImportError:
            logger.warning("OpenHands not available, falling back to vibeteam agents")
        return self._create_vibeteam_agent(role)
