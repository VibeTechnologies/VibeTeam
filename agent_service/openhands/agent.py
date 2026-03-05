from __future__ import annotations

"""Unified OpenHands role runtime facade.

This module provides a single ``Agent`` entry point that resolves role-specific
implementations behind one interface. Role instructions/tooling remain driven by
``agents/agents.yaml`` plus ``agents/<AgentDir>/AGENTS.md`` and skills.
"""

from typing import Any

from agent_service.config import AgentConfig

from .marketing_manager import OpenHandsMarketingManager
from .product_manager import OpenHandsProductManager
from .release_engineer import OpenHandsReleaseEngineer
from .software_engineer import OpenHandsSoftwareEngineer
from .support_engineer import OpenHandsSupportEngineer


class Agent:
    """Single OpenHands runtime interface for all roles."""

    def __init__(self, role: str, config: AgentConfig | None = None):
        self.role = role
        self._impl = self._build_impl(role, config)

    @staticmethod
    def _build_impl(role: str, config: AgentConfig | None = None) -> Any:
        if role == "release_engineer":
            return OpenHandsReleaseEngineer(config)
        if role == "marketing_manager":
            return OpenHandsMarketingManager(config)
        if role == "support_engineer":
            return OpenHandsSupportEngineer(config)
        if role == "product_manager":
            return OpenHandsProductManager(config)
        if role == "software_engineer":
            return OpenHandsSoftwareEngineer(config)
        raise ValueError(f"Unknown agent role: {role}")

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._impl.run(
            task=task,
            context_type=context_type,
            context_id=context_id,
            workspace=workspace,
            **kwargs,
        )

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._impl.run_async(
            task=task,
            context_type=context_type,
            context_id=context_id,
            workspace=workspace,
            **kwargs,
        )
