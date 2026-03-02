"""
Agent configuration helpers backed by agents.yaml.

This module provides role metadata, framework routing, and OpenClaw agent ID
resolution for services that need to respect agents.yaml configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agents.shared.role_resolver import AgentRole


@dataclass(frozen=True)
class AgentEntry:
    role: AgentRole
    display_name: str
    framework: str | None = None
    openclaw_agent_id: str | None = None
    slack_handle: str | None = None
    agent_dir: str | None = None
    prompt_path: str | None = None
    skip_context_injection: bool | None = None


AGENTS_CONFIG_PATH = os.environ.get("AGENTS_CONFIG_PATH", "agents.yaml")


def _load_agents_config() -> dict[str, Any]:
    path = Path(AGENTS_CONFIG_PATH)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _get_agents_map() -> dict[str, dict[str, Any]]:
    config = _load_agents_config()
    agents = config.get("agents", {}) if isinstance(config, dict) else {}
    return agents if isinstance(agents, dict) else {}


def get_agent_entry(role: str | None) -> AgentEntry | None:
    if not role:
        return None
    agents = _get_agents_map()
    raw = agents.get(role, {})
    if not isinstance(raw, dict):
        raw = {}
    slack_handle = raw.get("slack_handle")
    agent_dir = raw.get("agent_dir")
    skip_context_injection_raw = raw.get("skip_context_injection")
    skip_context_injection = (
        skip_context_injection_raw
        if isinstance(skip_context_injection_raw, bool)
        else None
    )
    display = slack_handle or role.replace("_", " ").title()
    return AgentEntry(
        role=role,  # type: ignore[arg-type]
        display_name=display,
        framework=raw.get("framework"),
        openclaw_agent_id=raw.get("openclaw_agent_id"),
        slack_handle=slack_handle,
        agent_dir=agent_dir,
        prompt_path=raw.get("prompt_path"),
        skip_context_injection=skip_context_injection,
    )


def resolve_openclaw_agent_id(role: str | None) -> str | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    return entry.openclaw_agent_id


def resolve_framework(role: str | None, framework_override: str | None, default: str) -> str:
    if framework_override:
        return framework_override
    entry = get_agent_entry(role)
    if entry and entry.framework:
        return entry.framework
    return default


def get_slack_handle(role: str | None) -> str | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    return entry.slack_handle or entry.display_name


def get_prompt_path(role: str | None) -> str | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    if entry.prompt_path:
        return entry.prompt_path
    if entry.agent_dir:
        try:
            return str(Path(entry.agent_dir) / "AGENTS.md")
        except Exception:
            return None
    return None


def get_agent_dir(role: str | None) -> str | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    if entry.agent_dir:
        return entry.agent_dir
    if entry.prompt_path:
        try:
            return str(Path(entry.prompt_path).parent)
        except Exception:
            return None
    return None


def get_skip_context_injection(role: str | None) -> bool | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    return entry.skip_context_injection


def list_agents() -> list[AgentEntry]:
    agents = _get_agents_map()
    entries: list[AgentEntry] = []
    for role in agents.keys():
        entry = get_agent_entry(role)
        if entry:
            entries.append(entry)
    return entries


__all__ = [
    "AgentEntry",
    "get_agent_entry",
    "resolve_openclaw_agent_id",
    "resolve_framework",
    "get_slack_handle",
    "get_agent_dir",
    "get_prompt_path",
    "get_skip_context_injection",
    "list_agents",
]
