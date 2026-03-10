from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from vibeteam import agents_config


def test_get_agents_config_path_falls_back_when_cwd_missing():
    with patch("vibeteam.agents_config.Path.cwd", side_effect=FileNotFoundError(2, "missing")):
        config_path = agents_config._get_agents_config_path()

    assert config_path.is_absolute()
    assert str(config_path).endswith("agents/agents.yaml")


def test_resolve_framework_handles_missing_cwd_without_crashing():
    # Clear cache so this test always exercises config path resolution.
    agents_config._get_agents_map.cache_clear()
    with patch("vibeteam.agents_config.Path.cwd", side_effect=FileNotFoundError(2, "missing")):
        framework = agents_config.resolve_framework("support_engineer", None, "openhands")

    assert framework in {"openhands", "openclaw", "autogen", "crewai"}


def test_normalize_framework_name_maps_legacy_frameworks():
    assert agents_config.normalize_framework_name("autogen") == "openhands"
    assert agents_config.normalize_framework_name("crewai") == "openhands"
    assert agents_config.normalize_framework_name("openclaw") == "openclaw"


def test_resolve_framework_applies_alias_to_framework_override():
    framework = agents_config.resolve_framework(None, "crewai", "openclaw")
    assert framework == "openhands"


def test_secret_placeholders_are_loaded_from_agents_yaml(tmp_path: Path):
    config = tmp_path / "agents.yaml"
    config.write_text(
        """
agents:
  software_engineer:
    framework: openhands
    slack_handle: SoftwareEngineer
    credentials:
      github_app:
        app_id: "${GITHUB_APP_ID_SWE_CUSTOM}"
        installation_id: "${GITHUB_APP_INSTALLATION_ID_SWE_CUSTOM}"
        private_key: "${GITHUB_APP_PRIVATE_KEY_SWE_CUSTOM}"
      slack:
        bot_token: "${SLACK_BOT_TOKEN_SWE_CUSTOM}"
        assistant_token: "${SLACK_ASSISTANT_TOKEN_SWE_CUSTOM}"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    agents_config._get_agents_map.cache_clear()
    with patch.object(agents_config, "AGENTS_CONFIG_PATH", str(config)):
        placeholders = agents_config.get_role_secret_placeholders("software_engineer")
        suffixes = agents_config.get_role_secret_suffixes()
        env_vars = agents_config.list_role_secret_env_vars()
    agents_config._get_agents_map.cache_clear()

    assert placeholders["github.app_id"] == "GITHUB_APP_ID_SWE_CUSTOM"
    assert placeholders["github.installation_id"] == "GITHUB_APP_INSTALLATION_ID_SWE_CUSTOM"
    assert placeholders["github.private_key"] == "GITHUB_APP_PRIVATE_KEY_SWE_CUSTOM"
    # Missing placeholder falls back to conventional naming.
    assert placeholders["github.webhook_secret"] == "GITHUB_WEBHOOK_SECRET_SOFTWARE_ENGINEER"
    assert placeholders["slack.bot_token"] == "SLACK_BOT_TOKEN_SWE_CUSTOM"
    assert placeholders["slack.assistant_token"] == "SLACK_ASSISTANT_TOKEN_SWE_CUSTOM"
    assert placeholders["slack.signing_secret"] == "SLACK_SIGNING_SECRET_SOFTWARE_ENGINEER"
    assert suffixes["software_engineer"] == "SWE_CUSTOM"
    assert "GITHUB_APP_PRIVATE_KEY_SWE_CUSTOM" in env_vars
