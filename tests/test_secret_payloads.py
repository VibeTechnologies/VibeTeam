from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from vibeteam.utils.secret_payloads import (
    flatten_github_role_payload,
    flatten_slack_role_payload,
    parse_json_payload,
)


def test_parse_json_payload_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_json_payload("{not-json}", source_name="TEST_JSON")

    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_json_payload('["array"]', source_name="TEST_JSON")


def test_flatten_github_role_payload_from_roles_object() -> None:
    payload = {
        "roles": {
            "software_engineer": {
                "app_id": 123,
                "installation_id": "456",
                "private_key": "line1\\nline2",
                "webhook_secret": "hook-secret",
                "bot_username": "vibeteam-swe-bot[bot]",
            },
            "support": {
                "appId": "777",
                "installationId": "888",
                "privateKey": "pem",
            },
        }
    }

    env = flatten_github_role_payload(payload)

    assert env["GITHUB_APP_ID_SOFTWARE_ENGINEER"] == "123"
    assert env["GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER"] == "456"
    assert env["GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER"] == "line1\\nline2"
    assert env["GITHUB_WEBHOOK_SECRET_SOFTWARE_ENGINEER"] == "hook-secret"
    assert env["GITHUB_APP_BOT_USERNAME_SOFTWARE_ENGINEER"] == "vibeteam-swe-bot[bot]"
    assert env["GITHUB_APP_ID_SUPPORT_ENGINEER"] == "777"
    assert env["GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER"] == "888"
    assert env["GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER"] == "pem"


def test_flatten_slack_role_payload_with_default_and_roles() -> None:
    payload = {
        "default": {
            "bot_token": "xoxb-default",
            "assistant_token": "xapp-default",
            "signing_secret": "sign-default",
            "trigger_secret": "trigger-default",
            "assistant_status_text": "thinking",
        },
        "product_manager": {
            "bot_token": "xoxb-pm",
            "assistant_token": "xapp-pm",
            "signing_secret": "sign-pm",
        },
    }

    env = flatten_slack_role_payload(payload)

    assert env["SLACK_BOT_TOKEN"] == "xoxb-default"
    assert env["SLACK_ASSISTANT_TOKEN"] == "xapp-default"
    assert env["SLACK_SIGNING_SECRET"] == "sign-default"
    assert env["SLACK_TRIGGER_SECRET"] == "trigger-default"
    assert env["SLACK_ASSISTANT_STATUS_TEXT"] == "thinking"
    assert env["SLACK_BOT_TOKEN_PRODUCT_MANAGER"] == "xoxb-pm"
    assert env["SLACK_ASSISTANT_TOKEN_PRODUCT_MANAGER"] == "xapp-pm"
    assert env["SLACK_SIGNING_SECRET_PRODUCT_MANAGER"] == "sign-pm"


def test_flatten_payloads_honor_custom_role_suffixes() -> None:
    github = flatten_github_role_payload(
        {"roles": {"support_engineer": {"app_id": "101"}}},
        role_suffixes={"support_engineer": "SUP_CUSTOM"},
    )
    slack = flatten_slack_role_payload(
        {"support_engineer": {"bot_token": "xoxb-custom"}},
        role_suffixes={"support_engineer": "SUP_CUSTOM"},
    )

    assert github["GITHUB_APP_ID_SUP_CUSTOM"] == "101"
    assert slack["SLACK_BOT_TOKEN_SUP_CUSTOM"] == "xoxb-custom"


def test_render_k8s_role_secrets_script_merges_json_and_legacy(tmp_path: Path) -> None:
    vibeteam_env = tmp_path / "vibeteam.env"
    github_yaml = tmp_path / "github-role.yaml"

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_TOKEN": "gh-token",
            "SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "legacy-support-token",
            "SLACK_ROLE_SECRETS_JSON": (
                '{"support_engineer":{"bot_token":"json-support-token"},'
                '"default":{"signing_secret":"json-signing"}}'
            ),
            "GITHUB_APP_ID_SOFTWARE_ENGINEER": "legacy-app-id",
            "GITHUB_BOT_USERNAME_SOFTWARE_ENGINEER": "legacy-bot-user",
            "GITHUB_APP_ROLE_SECRETS_JSON": (
                '{"roles":{"software_engineer":{"app_id":"json-app-id",'
                '"installation_id":"101","private_key":"lineA\\\\nlineB",'
                '"webhook_secret":"json-hook"}}}'
            ),
        }
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/render_k8s_role_secrets.py",
            "--namespace",
            "vibeteam",
            "--vibeteam-env-output",
            str(vibeteam_env),
            "--github-role-yaml-output",
            str(github_yaml),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        env=env,
    )

    vibeteam_text = vibeteam_env.read_text(encoding="utf-8")
    github_text = github_yaml.read_text(encoding="utf-8")

    assert "GITHUB_TOKEN=gh-token" in vibeteam_text
    # JSON payload should override legacy role-scoped value.
    assert "SLACK_BOT_TOKEN_SUPPORT_ENGINEER=json-support-token" in vibeteam_text
    assert "SLACK_SIGNING_SECRET=json-signing" in vibeteam_text

    # JSON payload should override legacy app ID and include multiline private key.
    assert "GITHUB_APP_ID_SOFTWARE_ENGINEER: 'json-app-id'" in github_text
    assert "GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER: '101'" in github_text
    assert "GITHUB_WEBHOOK_SECRET_SOFTWARE_ENGINEER: 'json-hook'" in github_text
    assert "GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER: 'lineA\\nlineB'" in github_text
    # Legacy env aliases still flow through rendered role secret output.
    assert "GITHUB_BOT_USERNAME_SOFTWARE_ENGINEER: 'legacy-bot-user'" in github_text


def test_render_script_uses_agents_yaml_placeholders_for_role_suffixes(tmp_path: Path) -> None:
    vibeteam_env = tmp_path / "vibeteam.env"
    github_yaml = tmp_path / "github-role.yaml"
    custom_agents = tmp_path / "agents.yaml"
    custom_agents.write_text(
        """
agents:
  support_engineer:
    framework: openhands
    slack_handle: SupportEngineer
    credentials:
      github_app:
        app_id: "${GITHUB_APP_ID_SUP_CUSTOM}"
        installation_id: "${GITHUB_APP_INSTALLATION_ID_SUP_CUSTOM}"
        private_key: "${GITHUB_APP_PRIVATE_KEY_SUP_CUSTOM}"
        webhook_secret: "${GITHUB_WEBHOOK_SECRET_SUP_CUSTOM}"
      slack:
        bot_token: "${SLACK_BOT_TOKEN_SUP_CUSTOM}"
        assistant_token: "${SLACK_ASSISTANT_TOKEN_SUP_CUSTOM}"
        signing_secret: "${SLACK_SIGNING_SECRET_SUP_CUSTOM}"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "AGENTS_CONFIG_PATH": str(custom_agents),
            "SLACK_BOT_TOKEN_SUP_CUSTOM": "legacy-custom-token",
            "SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "legacy-standard-token",
            "SLACK_ROLE_SECRETS_JSON": '{"support_engineer":{"bot_token":"json-custom-token"}}',
            "GITHUB_APP_ID_SUP_CUSTOM": "legacy-app-id",
            "GITHUB_APP_ROLE_SECRETS_JSON": '{"roles":{"support_engineer":{"app_id":"json-app-id"}}}',
        }
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/render_k8s_role_secrets.py",
            "--namespace",
            "vibeteam",
            "--vibeteam-env-output",
            str(vibeteam_env),
            "--github-role-yaml-output",
            str(github_yaml),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        env=env,
    )

    vibeteam_text = vibeteam_env.read_text(encoding="utf-8")
    github_text = github_yaml.read_text(encoding="utf-8")

    assert "SLACK_BOT_TOKEN_SUP_CUSTOM=json-custom-token" in vibeteam_text
    assert "SLACK_BOT_TOKEN_SUPPORT_ENGINEER=legacy-standard-token" not in vibeteam_text
    assert "GITHUB_APP_ID_SUP_CUSTOM: 'json-app-id'" in github_text
