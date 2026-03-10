"""Helpers for mapping JSON secret payloads to environment-style key/value pairs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

ROLE_SUFFIXES: dict[str, str] = {
    "software_engineer": "SOFTWARE_ENGINEER",
    "support_engineer": "SUPPORT_ENGINEER",
    "release_engineer": "RELEASE_ENGINEER",
    "product_manager": "PRODUCT_MANAGER",
    "marketing_manager": "MARKETING_MANAGER",
}

ROLE_ALIASES: dict[str, str] = {
    "softwareengineer": "software_engineer",
    "software_engineer": "software_engineer",
    "swe": "software_engineer",
    "supportengineer": "support_engineer",
    "support_engineer": "support_engineer",
    "support": "support_engineer",
    "releaseengineer": "release_engineer",
    "release_engineer": "release_engineer",
    "release": "release_engineer",
    "productmanager": "product_manager",
    "product_manager": "product_manager",
    "product": "product_manager",
    "marketingmanager": "marketing_manager",
    "marketing_manager": "marketing_manager",
    "marketing": "marketing_manager",
}


def parse_json_payload(raw: str | None, *, source_name: str) -> dict[str, Any]:
    """Parse an optional JSON object payload from a secret value."""
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - exercised by tests
        raise ValueError(f"{source_name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{source_name} must be a JSON object")
    return payload


def _normalize_role(role: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", role.strip().lower()).strip("_")
    if not normalized:
        return None
    return ROLE_ALIASES.get(normalized, normalized if normalized in ROLE_SUFFIXES else None)


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    as_text = value if isinstance(value, str) else str(value)
    return as_text if as_text != "" else None


def _first_value(data: Mapping[str, Any], names: list[str]) -> str | None:
    for name in names:
        if name in data:
            value = _string_value(data[name])
            if value is not None:
                return value
    return None


def _env_keys(payload: Mapping[str, Any], prefix: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and key.startswith(prefix):
            as_text = _string_value(value)
            if as_text is not None:
                env[key] = as_text
    return env


def _roles_object(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    maybe_roles = payload.get("roles")
    if isinstance(maybe_roles, Mapping):
        return maybe_roles
    return payload


def flatten_github_role_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    """Flatten GitHub role payload JSON into env-style key/value pairs."""
    direct = _env_keys(payload, "GITHUB_")
    if direct:
        return direct

    env: dict[str, str] = {}
    for role_name, role_data in _roles_object(payload).items():
        if not isinstance(role_name, str) or not isinstance(role_data, Mapping):
            continue
        role = _normalize_role(role_name)
        if role is None:
            continue
        suffix = ROLE_SUFFIXES[role]
        app_id = _first_value(
            role_data,
            ["app_id", "appId", "github_app_id", "githubAppId", "id"],
        )
        install_id = _first_value(
            role_data,
            ["installation_id", "installationId", "github_app_installation_id"],
        )
        private_key = _first_value(
            role_data,
            ["private_key", "privateKey", "github_app_private_key"],
        )
        webhook_secret = _first_value(
            role_data,
            ["webhook_secret", "webhookSecret", "github_webhook_secret"],
        )
        bot_username = _first_value(
            role_data,
            ["bot_username", "botUsername", "github_bot_username"],
        )

        if app_id is not None:
            env[f"GITHUB_APP_ID_{suffix}"] = app_id
        if install_id is not None:
            env[f"GITHUB_APP_INSTALLATION_ID_{suffix}"] = install_id
        if private_key is not None:
            env[f"GITHUB_APP_PRIVATE_KEY_{suffix}"] = private_key
        if webhook_secret is not None:
            env[f"GITHUB_WEBHOOK_SECRET_{suffix}"] = webhook_secret
        if bot_username is not None:
            env[f"GITHUB_APP_BOT_USERNAME_{suffix}"] = bot_username

    return env


def flatten_slack_role_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    """Flatten Slack role payload JSON into env-style key/value pairs."""
    direct = _env_keys(payload, "SLACK_")
    if direct:
        return direct

    env: dict[str, str] = {}
    for role_name, role_data in _roles_object(payload).items():
        if not isinstance(role_name, str) or not isinstance(role_data, Mapping):
            continue

        role_key = role_name.strip().lower()
        suffix = None
        if role_key not in {"default", "global", "fallback"}:
            normalized_role = _normalize_role(role_name)
            if normalized_role is None:
                continue
            suffix = ROLE_SUFFIXES[normalized_role]

        bot_token = _first_value(role_data, ["bot_token", "botToken", "token"])
        assistant_token = _first_value(
            role_data,
            ["assistant_token", "assistantToken", "status_token"],
        )
        signing_secret = _first_value(
            role_data,
            ["signing_secret", "signingSecret"],
        )
        trigger_secret = _first_value(
            role_data,
            ["trigger_secret", "triggerSecret"],
        )
        status_text = _first_value(
            role_data,
            ["assistant_status_text", "assistantStatusText"],
        )

        if bot_token is not None:
            key = "SLACK_BOT_TOKEN" if suffix is None else f"SLACK_BOT_TOKEN_{suffix}"
            env[key] = bot_token
        if assistant_token is not None:
            key = "SLACK_ASSISTANT_TOKEN" if suffix is None else f"SLACK_ASSISTANT_TOKEN_{suffix}"
            env[key] = assistant_token
        if signing_secret is not None:
            key = "SLACK_SIGNING_SECRET" if suffix is None else f"SLACK_SIGNING_SECRET_{suffix}"
            env[key] = signing_secret
        if suffix is None and trigger_secret is not None:
            env["SLACK_TRIGGER_SECRET"] = trigger_secret
        if suffix is None and status_text is not None:
            env["SLACK_ASSISTANT_STATUS_TEXT"] = status_text

    return env


def collect_prefixed_env(env: Mapping[str, str], prefixes: tuple[str, ...]) -> dict[str, str]:
    """Collect existing non-empty env vars that start with any prefix."""
    collected: dict[str, str] = {}
    for key, value in env.items():
        if value and key.startswith(prefixes):
            collected[key] = value
    return collected


def merge_env(*mappings: Mapping[str, str]) -> dict[str, str]:
    """Merge mappings in order; later values win."""
    merged: dict[str, str] = {}
    for mapping in mappings:
        merged.update(mapping)
    return merged
