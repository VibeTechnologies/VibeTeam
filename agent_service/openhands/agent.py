from __future__ import annotations

"""
Generic OpenHands agent implementation.

Behavior is driven by:
- agents/shared/AGENTS.md
- agents/<AgentName>/AGENTS.md
- agents/<AgentName>/config.json
"""

import logging
import os
import tempfile
from typing import Any

from agent_service.config import AgentConfig
from agent_service.sessions import get_or_create_session, get_session_store
from agent_service.shared.agent_runtime_config_loader import (
    build_openhands_mcp_config,
    load_agent_runtime_config,
)
from agent_service.shared.agents_md_loader import compose_agent_context, resolve_agent_root
from agent_service.shared.llm import LLM, AzureLLM

from .utils import build_condenser, extract_response_from_events, get_prompt_path

try:
    from openhands.sdk import Agent as OpenHandsSDKAgent, LocalConversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    OpenHandsSDKAgent = None
    LocalConversation = None
    Tool = None
    TerminalTool = None
    FileEditorTool = None


logger = logging.getLogger(__name__)


def _role_display_name(role: str) -> str:
    return "".join(part.capitalize() for part in role.split("_"))


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


class Agent:
    """Generic OpenHands role agent loaded from agents/${agent_name}."""

    def __init__(self, role: str, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")
        self.role = role
        self.agent_name = role
        self.agent_path = resolve_agent_root(role)
        self.config = config or AgentConfig()
        self.runtime_config = load_agent_runtime_config(role)
        logger.info(
            "Configured OpenHands Agent role=%s agent_path=%s",
            self.role,
            self.agent_path,
        )

    def _create_llm(self) -> LLM:
        llm_cfg = self.runtime_config.get("llm")
        if not isinstance(llm_cfg, dict):
            llm_cfg = {}

        model_name = (
            llm_cfg.get("model")
            or self.runtime_config.get("model")
            or self.config.llm.model
            or "gpt-5.2"
        )
        if isinstance(model_name, str) and not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": self.config.llm.api_key,
            "base_url": self.config.llm.api_base,
            "api_version": llm_cfg.get("api_version")
            or self.runtime_config.get("api_version")
            or os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            "max_output_tokens": _as_int(
                llm_cfg.get("max_output_tokens")
                or self.runtime_config.get("max_output_tokens")
                or self.config.llm.max_tokens,
                4096,
            ),
            "timeout": _as_int(
                llm_cfg.get("timeout") or self.runtime_config.get("timeout"),
                300,
            ),
            "num_retries": _as_int(
                llm_cfg.get("num_retries") or self.runtime_config.get("num_retries"),
                3,
            ),
        }

        reasoning_effort = llm_cfg.get("reasoning_effort") or self.runtime_config.get(
            "reasoning_effort"
        )
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        thinking_budget = llm_cfg.get("extended_thinking_budget") or self.runtime_config.get(
            "extended_thinking_budget"
        )
        if thinking_budget is not None:
            kwargs["extended_thinking_budget"] = _as_int(thinking_budget, 0)

        return AzureLLM(**kwargs)

    def _create_openhands_agent(self, llm: LLM, use_tools: bool = True) -> OpenHandsSDKAgent:
        fallback_context = (
            f"You are the {_role_display_name(self.role)}. "
            "Follow repository AGENTS.md and skills."
        )
        agent_context = compose_agent_context(self.role, fallback_context=fallback_context)

        mcp_config = build_openhands_mcp_config(self.runtime_config)

        agent_kwargs: dict[str, Any] = {
            "llm": llm,
            "condenser": build_condenser(llm),
            "system_prompt_filename": get_prompt_path(),
            "system_prompt_kwargs": {
                "agent_context": agent_context,
            },
        }
        if use_tools and mcp_config and mcp_config.get("mcpServers"):
            agent_kwargs["mcp_config"] = mcp_config

        tools = []
        if use_tools:
            tools = [
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ]

        return OpenHandsSDKAgent(tools=tools, **agent_kwargs)

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role=self.role,
            context_type=context_type,
            context_id=context_id,
        )

        llm = self._create_llm()
        use_tools = _as_bool(
            kwargs.get("use_tools", self.runtime_config.get("use_tools")),
            True,
        )
        agent = self._create_openhands_agent(llm, use_tools=use_tools)

        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        conversation = None
        try:
            callbacks = []
            progress_url = kwargs.get("progress_url")
            if progress_url:
                from .progress import create_progress_callback

                callbacks.append(
                    create_progress_callback(
                        progress_url=progress_url,
                        job_id=kwargs.get("job_id", ""),
                        callback_metadata=kwargs.get("callback_metadata", {}),
                        on_progress=kwargs.get("progress_heartbeat"),
                    )
                )
            elif kwargs.get("progress_heartbeat"):
                from .progress import create_heartbeat_callback

                callbacks.append(
                    create_heartbeat_callback(on_progress=kwargs.get("progress_heartbeat"))
                )

            max_iterations = _as_int(
                kwargs.get("max_iterations", self.runtime_config.get("max_iterations")),
                30,
            )
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
                callbacks=callbacks or None,
                max_iteration_per_run=max_iterations,
            )

            conversation.send_message(f"Task: {task}")
            conversation.run()
            response = extract_response_from_events(conversation.state.events)
            if not response.strip():
                response = "I completed the task but have no output to share."

            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            model_name = (
                self.runtime_config.get("model")
                or (self.runtime_config.get("llm") or {}).get("model")
                or self.config.llm.model
                or "gpt-5.2"
            )
            result = {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": self.role,
                "model": model_name,
                "workspace": workspace_path,
            }
            logger.info(
                "OpenHands Agent completed role=%s agent_path=%s session_id=%s",
                self.role,
                self.agent_path,
                result["session_id"],
            )
            return result
        finally:
            if temp_dir:
                try:
                    if conversation is not None:
                        conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(
            self.run,
            task,
            context_type,
            context_id,
            workspace,
            **kwargs,
        )


def create_agent(role: str, config: AgentConfig | None = None) -> Agent:
    return Agent(role=role, config=config)


def create_software_engineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("software_engineer", config=config)


def create_release_engineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("release_engineer", config=config)


def create_support_engineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("support_engineer", config=config)


def create_product_manager(config: AgentConfig | None = None) -> Agent:
    return create_agent("product_manager", config=config)


def create_marketing_manager(config: AgentConfig | None = None) -> Agent:
    return create_agent("marketing_manager", config=config)
