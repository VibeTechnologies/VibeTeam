"""
Agent configuration helpers backed by agents/agents.yaml.

This module provides role metadata, framework routing, and OpenClaw agent ID
resolution for services that need to respect agents/agents.yaml configuration.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent_service.shared.role_resolver import AgentRole


@dataclass(frozen=True)
class AgentEntry:
    role: AgentRole
    display_name: str
    framework: str | None = None
    openclaw_agent_id: str | None = None
    slack_handle: str | None = None
    agent_dir: str | None = None
    prompt_path: str | None = None


AGENTS_CONFIG_PATH = os.environ.get("AGENTS_CONFIG_PATH", "agents/agents.yaml")
FRAMEWORK_ALIASES = {
    "autogen": "openhands",
    "crewai": "openhands",
}
PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")

GITHUB_PLACEHOLDER_KEYS = {
    "app_id": "GITHUB_APP_ID",
    "installation_id": "GITHUB_APP_INSTALLATION_ID",
    "private_key": "GITHUB_APP_PRIVATE_KEY",
    "webhook_secret": "GITHUB_WEBHOOK_SECRET",
    "bot_username": "GITHUB_APP_BOT_USERNAME",
}

SLACK_PLACEHOLDER_KEYS = {
    "bot_token": "SLACK_BOT_TOKEN",
    "assistant_token": "SLACK_ASSISTANT_TOKEN",
    "signing_secret": "SLACK_SIGNING_SECRET",
}


def _repo_root() -> Path:
    """Return repository root relative to this module, independent of process CWD."""
    return Path(__file__).resolve().parent.parent


def _get_agents_config_path() -> Path:
    path = Path(AGENTS_CONFIG_PATH)
    if path.is_absolute():
        return path

    # Prefer CWD-relative path when available (dev workflows), but git-sync based
    # deployments can invalidate process CWD between revisions. Fall back to a
    # stable module-relative repository root in that case.
    try:
        cwd_candidate = Path.cwd() / path
        if cwd_candidate.exists():
            return cwd_candidate
    except FileNotFoundError:
        pass

    return _repo_root() / path


def _get_agents_config_dir() -> Path:
    return _get_agents_config_path().parent


def _placeholder_env_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = PLACEHOLDER_PATTERN.match(value.strip())
    return match.group(1) if match else None


def _default_role_suffix(role: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", role.strip().upper()).strip("_")


def _load_agents_config() -> dict[str, Any]:
    path = _get_agents_config_path()
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
    prompt_path = raw.get("prompt_path")
    base_dir = _get_agents_config_dir()
    if agent_dir:
        try:
            agent_path = Path(str(agent_dir))
            if not agent_path.is_absolute():
                agent_dir = str(base_dir / agent_path)
        except Exception:
            pass
    if prompt_path:
        try:
            prompt_path_obj = Path(str(prompt_path))
            if not prompt_path_obj.is_absolute():
                prompt_path = str(base_dir / prompt_path_obj)
        except Exception:
            pass
    display = slack_handle or role.replace("_", " ").title()
    return AgentEntry(
        role=role,  # type: ignore[arg-type]
        display_name=display,
        framework=raw.get("framework"),
        openclaw_agent_id=raw.get("openclaw_agent_id"),
        slack_handle=slack_handle,
        agent_dir=agent_dir,
        prompt_path=prompt_path,
    )


def resolve_openclaw_agent_id(role: str | None) -> str | None:
    entry = get_agent_entry(role)
    if not entry:
        return None
    return entry.openclaw_agent_id


def normalize_framework_name(framework: str | None) -> str | None:
    """Normalize framework names and apply legacy aliases."""
    if framework is None:
        return None
    normalized = framework.strip().lower()
    if not normalized:
        return None
    return FRAMEWORK_ALIASES.get(normalized, normalized)


def resolve_framework(role: str | None, framework_override: str | None, default: str) -> str:
    override = normalize_framework_name(framework_override)
    if override:
        return override
    entry = get_agent_entry(role)
    if entry and entry.framework:
        return normalize_framework_name(entry.framework) or "openhands"
    return normalize_framework_name(default) or "openhands"


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


def list_agents() -> list[AgentEntry]:
    agents = _get_agents_map()
    entries: list[AgentEntry] = []
    for role in agents.keys():
        entry = get_agent_entry(role)
        if entry:
            entries.append(entry)
    return entries


def get_role_secret_placeholders(role: str | None) -> dict[str, str]:
    """Return env-var names referenced by role credential placeholders in agents.yaml.

    Placeholders are expected as strings in `${ENV_VAR_NAME}` form under:
      agents.<role>.credentials.github_app.<field>
      agents.<role>.credentials.slack.<field>

    Missing placeholders are filled with conventional defaults derived from role name.
    """
    if not role:
        return {}

    agents = _get_agents_map()
    raw = agents.get(role, {})
    if not isinstance(raw, dict):
        raw = {}

    credentials = raw.get("credentials", {})
    if not isinstance(credentials, dict):
        credentials = {}
    github = credentials.get("github_app", {})
    slack = credentials.get("slack", {})
    if not isinstance(github, dict):
        github = {}
    if not isinstance(slack, dict):
        slack = {}

    suffix = _default_role_suffix(role)
    resolved: dict[str, str] = {}

    for key, prefix in GITHUB_PLACEHOLDER_KEYS.items():
        env_name = _placeholder_env_name(github.get(key)) or f"{prefix}_{suffix}"
        resolved[f"github.{key}"] = env_name

    for key, prefix in SLACK_PLACEHOLDER_KEYS.items():
        env_name = _placeholder_env_name(slack.get(key)) or f"{prefix}_{suffix}"
        resolved[f"slack.{key}"] = env_name

    return resolved


def get_role_secret_suffixes() -> dict[str, str]:
    """Return role -> env suffix inferred from agents.yaml github app placeholders."""
    suffixes: dict[str, str] = {}
    for role in _get_agents_map().keys():
        placeholders = get_role_secret_placeholders(role)
        app_id_key = placeholders.get("github.app_id", "")
        prefix = "GITHUB_APP_ID_"
        if app_id_key.startswith(prefix):
            suffix = app_id_key[len(prefix) :]
            if suffix:
                suffixes[role] = suffix
                continue
        suffixes[role] = _default_role_suffix(role)
    return suffixes


def list_role_secret_env_vars() -> set[str]:
    """Return all role-scoped env var names referenced by agents.yaml placeholders."""
    env_vars: set[str] = set()
    for role in _get_agents_map().keys():
        env_vars.update(get_role_secret_placeholders(role).values())
    return env_vars


__all__ = [
    "AgentEntry",
    "get_agent_entry",
    "resolve_openclaw_agent_id",
    "normalize_framework_name",
    "resolve_framework",
    "get_slack_handle",
    "get_agent_dir",
    "get_prompt_path",
    "list_agents",
    "get_role_secret_placeholders",
    "get_role_secret_suffixes",
    "list_role_secret_env_vars",
]
