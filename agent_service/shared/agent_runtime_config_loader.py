"""Load per-agent runtime configuration from agents/<AgentName>/config.json.

This module intentionally supports multiple MCP config dialects so teams can
reuse familiar syntax from Codex/Claude and OpenCode:

- ``mcpServers`` (camelCase; Codex/Claude-like)
- ``mcp_servers`` (snake_case)
- ``mcp`` (OpenCode-like)
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .agents_md_loader import resolve_agent_root

logger = logging.getLogger(__name__)


ENV_TOKEN_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
ENV_BRACE_PATTERN = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def load_agent_runtime_config(agent_name: str) -> dict[str, Any]:
    """Load ``config.json`` for the given agent role.

    Returns an empty dict when no config exists or parsing fails.
    """
    config_path = resolve_agent_root(agent_name) / "config.json"
    if not config_path.exists():
        return {}

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to parse %s: %s", config_path, e)
        return {}

    if not isinstance(raw, dict):
        logger.warning("Agent config at %s must be a JSON object", config_path)
        return {}

    return _resolve_env(raw)


def build_openhands_mcp_config(agent_config: dict[str, Any]) -> dict[str, Any] | None:
    """Build OpenHands-compatible ``mcp_config`` from agent config."""
    if not isinstance(agent_config, dict):
        return None

    # Codex/Claude style
    for key in ("mcpServers", "mcp_servers"):
        raw = agent_config.get(key)
        if isinstance(raw, dict):
            mcp_servers = _normalize_server_map(raw)
            return {"mcpServers": mcp_servers} if mcp_servers else None

    # OpenCode style
    raw_mcp = agent_config.get("mcp")
    if isinstance(raw_mcp, dict):
        mcp_servers = _normalize_server_map(raw_mcp)
        return {"mcpServers": mcp_servers} if mcp_servers else None

    return None


def _normalize_server_map(raw_map: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for name, raw_cfg in raw_map.items():
        server_name = str(name).strip()
        if not server_name:
            continue
        cfg = _normalize_server(raw_cfg)
        if cfg:
            normalized[server_name] = cfg
    return normalized


def _normalize_server(raw_cfg: Any) -> dict[str, Any] | None:
    if not isinstance(raw_cfg, dict):
        return None
    if raw_cfg.get("enabled") is False:
        return None

    cfg = dict(raw_cfg)
    server: dict[str, Any] = {}

    # Normalize command shape:
    # - Codex style: command + args
    # - OpenCode style: command as list
    command = cfg.get("command")
    if isinstance(command, list):
        command_parts = [str(part) for part in command if str(part)]
        if command_parts:
            server["command"] = command_parts[0]
            if len(command_parts) > 1:
                server["args"] = command_parts[1:]
    elif isinstance(command, str) and command.strip():
        server["command"] = command.strip()
        args = cfg.get("args")
        if isinstance(args, list):
            server["args"] = [str(part) for part in args]

    # Normalize environment keys (env vs environment)
    env = cfg.get("env")
    if not isinstance(env, dict):
        env = cfg.get("environment")
    if isinstance(env, dict):
        server["env"] = {str(k): str(v) for k, v in env.items()}

    # Remote/server options
    if isinstance(cfg.get("url"), str):
        server["url"] = cfg["url"]
    if isinstance(cfg.get("auth"), str):
        server["auth"] = cfg["auth"]

    # Preserve headers when provided by Codex/OpenCode style configs
    headers = cfg.get("headers")
    if not isinstance(headers, dict):
        headers = cfg.get("http_headers")
    if isinstance(headers, dict):
        server["headers"] = {str(k): str(v) for k, v in headers.items()}

    # Keep explicit type field when present (e.g., opencode remote/local)
    if isinstance(cfg.get("type"), str):
        server["type"] = cfg["type"]

    if "command" not in server and "url" not in server:
        return None
    return server


def _resolve_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    if not isinstance(value, str):
        return value

    # OpenCode style: {env:VAR}
    def _brace_repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.getenv(key, "")

    resolved = ENV_BRACE_PATTERN.sub(_brace_repl, value)

    # Shell-style: ${VAR} or ${VAR:-default}
    def _token_repl(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        env_value = os.getenv(key)
        if env_value is not None:
            return env_value
        return default or ""

    resolved = ENV_TOKEN_PATTERN.sub(_token_repl, resolved)
    return resolved

