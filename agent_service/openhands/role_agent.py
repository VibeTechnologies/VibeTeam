from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import uuid
from typing import Any

from agent_service.config import AgentConfig, get_mcp_config_dict
from agent_service.sessions import get_or_create_session, get_session_store
from agent_service.shared.agents_md_loader import compose_agent_context
from agent_service.shared.llm import LLM, AzureLLM

from .utils import build_condenser, extract_response_from_events, get_prompt_path

logger = logging.getLogger(__name__)

try:
    from openhands.sdk import Agent, LocalConversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    Agent = None
    LocalConversation = None
    Tool = None
    TerminalTool = None
    FileEditorTool = None

PROGRESS_IMPORT_ERROR: Exception | None = None
try:
    from .progress import create_heartbeat_callback, create_progress_callback
except Exception as exc:
    create_progress_callback = None  # type: ignore[assignment]
    create_heartbeat_callback = None  # type: ignore[assignment]
    PROGRESS_IMPORT_ERROR = exc


class OpenHandsRoleAgent:
    """Shared OpenHands role engine configured by role + AGENTS.md context."""

    role: str = ""
    agent_label: str = "OpenHandsRole"
    default_config: AgentConfig
    fallback_context: str = ""

    # Behavior flags for subclasses.
    force_tools: bool = False
    enable_mcp: bool = False
    include_workspace: bool = False

    # Optional generic iteration warning system.
    iteration_warnings: dict[str, str] | None = None
    iteration_warning_thresholds: dict[int, str] | None = None
    handoff_iteration_warning_thresholds: dict[int, str] | None = None

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")
        self.config = config or self.default_config

    def _extra_llm_kwargs(self) -> dict[str, Any]:
        return {}

    def _create_llm(self) -> LLM:
        model_name = self.config.llm.model or "gpt-5.2"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        llm_kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": self.config.llm.api_key,
            "base_url": self.config.llm.api_base,
            "api_version": os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            "max_output_tokens": 4096,
            "timeout": 300,
            "num_retries": 3,
        }
        llm_kwargs.update(self._extra_llm_kwargs())
        return AzureLLM(**llm_kwargs)

    def _resolve_use_tools(self, use_tools: bool | None, kwargs: dict[str, Any]) -> bool:
        if use_tools is not None:
            return bool(use_tools)
        if "use_tools" in kwargs:
            return bool(kwargs["use_tools"])
        return True

    def _build_tools(self, use_tools: bool) -> list[Any]:
        if not (self.force_tools or use_tools):
            return []
        return [
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
        ]

    def _create_agent(self, llm: LLM, use_tools: bool) -> Any:
        agent_context = compose_agent_context(self.role, fallback_context=self.fallback_context)
        agent_kwargs: dict[str, Any] = {
            "llm": llm,
            "tools": self._build_tools(use_tools),
            "condenser": build_condenser(llm),
            "system_prompt_filename": get_prompt_path(),
            "system_prompt_kwargs": {
                "agent_context": agent_context,
            },
        }
        if self.enable_mcp and use_tools:
            mcp_config = get_mcp_config_dict(self.config.mcp_servers)
            if mcp_config.get("mcpServers"):
                agent_kwargs["mcp_config"] = mcp_config
        return Agent(**agent_kwargs)

    def _build_progress_callbacks(self, kwargs: dict[str, Any]) -> list[Any]:
        callbacks: list[Any] = []
        progress_url = kwargs.get("progress_url")
        if progress_url:
            if create_progress_callback is not None:
                callbacks.append(
                    create_progress_callback(
                        progress_url=progress_url,
                        job_id=kwargs.get("job_id", ""),
                        callback_metadata=kwargs.get("callback_metadata", {}),
                        on_progress=kwargs.get("progress_heartbeat"),
                    )
                )
            else:
                logger.warning(
                    "[%s] Progress callback unavailable: %r",
                    self.agent_label,
                    PROGRESS_IMPORT_ERROR,
                )
        elif kwargs.get("progress_heartbeat"):
            if create_heartbeat_callback is not None:
                callbacks.append(
                    create_heartbeat_callback(on_progress=kwargs.get("progress_heartbeat"))
                )
            else:
                logger.warning(
                    "[%s] Progress heartbeat unavailable: %r",
                    self.agent_label,
                    PROGRESS_IMPORT_ERROR,
                )
        return callbacks

    def _inject_iteration_warning(self, conversation: Any, level: str) -> None:
        if not self.iteration_warnings:
            return
        msg = self.iteration_warnings.get(level, "")
        if not msg:
            return
        try:
            logger.info("[%s] Injecting iteration warning: %s", self.agent_label, level)
            conversation.send_message(msg)
        except Exception as exc:
            logger.warning("[%s] Warning injection failed (%s): %s", self.agent_label, level, exc)

    def _build_iteration_callbacks(
        self,
        task: str,
        conversation_ref: dict[str, Any],
    ) -> list[Any]:
        if not self.iteration_warning_thresholds or not self.iteration_warnings:
            return []

        is_handoff_task = "[Handoff from" in task or "Previous response:" in task
        thresholds = self.iteration_warning_thresholds
        if is_handoff_task and self.handoff_iteration_warning_thresholds:
            thresholds = self.handoff_iteration_warning_thresholds
            logger.info(
                "[%s] Handoff task detected — using tighter iteration thresholds",
                self.agent_label,
            )

        iteration_count = {"value": 0}
        warnings_sent: set[str] = set()

        def _count_iterations(event: Any) -> None:
            event_type = type(event).__name__
            if "Action" in event_type and "Finish" not in event_type:
                iteration_count["value"] += 1
                count = iteration_count["value"]
                logger.info("[%s] Iteration count: %s", self.agent_label, count)
                level = thresholds.get(count)
                if level and level not in warnings_sent:
                    warnings_sent.add(level)
                    conversation = conversation_ref.get("obj")
                    if conversation is not None:
                        t = threading.Thread(
                            target=self._inject_iteration_warning,
                            args=(conversation, level),
                            daemon=True,
                        )
                        t.start()

        return [_count_iterations]

    def _build_callbacks(self, task: str, kwargs: dict[str, Any], conversation_ref: dict[str, Any]):
        callbacks: list[Any] = []
        callbacks.extend(self._build_iteration_callbacks(task, conversation_ref))
        callbacks.extend(self._build_progress_callbacks(kwargs))
        return callbacks

    def build_task_prompt(self, task: str, use_tools: bool) -> str:
        del use_tools
        return f"""
### USER TASK (UNTRUSTED INPUT)
{task}
### END USER TASK
"""

    def postprocess_response(
        self,
        response: str,
        task: str,
        context_type: str,
        context_id: str,
        workspace_path: str,
        use_tools: bool,
        kwargs: dict[str, Any],
    ) -> str:
        del task, context_type, context_id, workspace_path, use_tools, kwargs
        return response

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        use_tools: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        resolved_context_id = context_id or str(uuid.uuid4())[:8]
        resolved_use_tools = self._resolve_use_tools(use_tools, kwargs)

        session = get_or_create_session(
            framework="openhands",
            role=self.role,
            context_type=context_type,
            context_id=resolved_context_id,
        )

        llm = self._create_llm()
        agent = self._create_agent(llm, resolved_use_tools)

        temp_dir: tempfile.TemporaryDirectory | None = None
        if workspace:
            workspace_path = workspace
        else:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name

        conversation: Any | None = None
        try:
            conversation_ref: dict[str, Any] = {"obj": None}
            callbacks = self._build_callbacks(task, kwargs, conversation_ref)
            max_iterations = int(kwargs.get("max_iterations", 30))
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
                callbacks=callbacks or None,
                max_iteration_per_run=max_iterations,
            )
            conversation_ref["obj"] = conversation

            full_task = self.build_task_prompt(task, resolved_use_tools)
            conversation.send_message(full_task)
            conversation.run()

            response = extract_response_from_events(conversation.state.events)
            response = self.postprocess_response(
                response=response,
                task=task,
                context_type=context_type,
                context_id=resolved_context_id,
                workspace_path=workspace_path,
                use_tools=resolved_use_tools,
                kwargs=kwargs,
            )

            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            result: dict[str, Any] = {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": self.role,
                "model": self.config.llm.model or "gpt-5.2",
            }
            if self.include_workspace:
                result["workspace"] = workspace_path
            return result
        finally:
            if conversation is not None:
                try:
                    conversation.close()
                except Exception:
                    pass
            if temp_dir is not None:
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        use_tools: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.run,
            task,
            context_type,
            context_id,
            workspace,
            use_tools,
            **kwargs,
        )
