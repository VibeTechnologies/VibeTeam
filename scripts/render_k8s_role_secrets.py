#!/usr/bin/env python3
"""Render deploy-time secret files from legacy env vars and JSON payload secrets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from vibeteam.agents_config import get_role_secret_suffixes, list_role_secret_env_vars
from vibeteam.utils.secret_payloads import (
    collect_prefixed_env,
    flatten_github_role_payload,
    flatten_slack_role_payload,
    merge_env,
    parse_json_payload,
)

VIBETEAM_BASE_KEYS = (
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_API_VERSION",
    "LITELLM_MASTER_KEY",
    "GITHUB_TOKEN",
    "GITHUB_WEBHOOK_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_ASSISTANT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_TRIGGER_SECRET",
    "SLACK_ASSISTANT_STATUS_TEXT",
    "SENTRY_AUTH_TOKEN",
    "SENTRY_CLIENT_SECRET",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "DATABASE_URL",
    "CALLBACK_SECRET",
)


def _render_env_file(data: dict[str, str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in sorted(data.items()):
        normalized = value.replace("\r\n", "\\n").replace("\n", "\\n")
        lines.append(f"{key}={normalized}")
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _render_secret_yaml(name: str, namespace: str, data: dict[str, str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {namespace}",
        "type: Opaque",
        "stringData:",
    ]
    for key in sorted(data):
        value = data[key]
        if "\n" in value:
            lines.append(f"  {key}: |-")
            for line in value.splitlines():
                lines.append(f"    {line}")
            if value.endswith("\n"):
                lines.append("    ")
        else:
            quoted = value.replace("'", "''")
            lines.append(f"  {key}: '{quoted}'")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate deploy-time files for vibeteam-secrets (.env format) and "
            "github-app-role-secrets (YAML) from legacy env vars and JSON secret payloads."
        )
    )
    parser.add_argument(
        "--namespace",
        default="vibeteam",
        help="Kubernetes namespace used in generated YAML (default: vibeteam)",
    )
    parser.add_argument(
        "--vibeteam-env-output",
        required=True,
        help="Path to write vibeteam-secrets env file",
    )
    parser.add_argument(
        "--github-role-yaml-output",
        required=True,
        help="Path to write github-app-role-secrets YAML manifest",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    role_scoped_env_keys = list_role_secret_env_vars()
    role_suffixes = get_role_secret_suffixes()
    for suffix in role_suffixes.values():
        role_scoped_env_keys.add(f"GITHUB_BOT_USERNAME_{suffix}")

    base_vibeteam = {
        key: env[key]
        for key in VIBETEAM_BASE_KEYS
        if key in env and env[key] != ""
    }
    if role_scoped_env_keys:
        legacy_slack = {
            key: env[key]
            for key in role_scoped_env_keys
            if key.startswith(("SLACK_BOT_TOKEN_", "SLACK_ASSISTANT_TOKEN_", "SLACK_SIGNING_SECRET_"))
            and key in env
            and env[key] != ""
        }
    else:
        legacy_slack = collect_prefixed_env(
            env,
            (
                "SLACK_BOT_TOKEN_",
                "SLACK_ASSISTANT_TOKEN_",
                "SLACK_SIGNING_SECRET_",
            ),
        )
    slack_payload = parse_json_payload(
        env.get("SLACK_ROLE_SECRETS_JSON"),
        source_name="SLACK_ROLE_SECRETS_JSON",
    )
    json_slack = flatten_slack_role_payload(slack_payload, role_suffixes=role_suffixes)
    vibeteam_env = merge_env(base_vibeteam, legacy_slack, json_slack)

    if role_scoped_env_keys:
        legacy_github = {
            key: env[key]
            for key in role_scoped_env_keys
            if key.startswith(
                (
                    "GITHUB_APP_ID_",
                    "GITHUB_APP_INSTALLATION_ID_",
                    "GITHUB_APP_PRIVATE_KEY_",
                    "GITHUB_WEBHOOK_SECRET_",
                    "GITHUB_BOT_USERNAME_",
                    "GITHUB_APP_BOT_USERNAME_",
                )
            )
            and key in env
            and env[key] != ""
        }
    else:
        legacy_github = collect_prefixed_env(
            env,
            (
                "GITHUB_APP_ID_",
                "GITHUB_APP_INSTALLATION_ID_",
                "GITHUB_APP_PRIVATE_KEY_",
                "GITHUB_WEBHOOK_SECRET_",
                "GITHUB_BOT_USERNAME_",
                "GITHUB_APP_BOT_USERNAME_",
            ),
        )
    github_payload = parse_json_payload(
        env.get("GITHUB_APP_ROLE_SECRETS_JSON"),
        source_name="GITHUB_APP_ROLE_SECRETS_JSON",
    )
    json_github = flatten_github_role_payload(github_payload, role_suffixes=role_suffixes)
    github_role_data = merge_env(legacy_github, json_github)

    _render_env_file(vibeteam_env, Path(args.vibeteam_env_output))
    _render_secret_yaml(
        "github-app-role-secrets",
        args.namespace,
        github_role_data,
        Path(args.github_role_yaml_output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
