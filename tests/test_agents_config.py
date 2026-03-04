from __future__ import annotations

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
