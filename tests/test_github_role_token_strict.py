"""Tests for strict per-role GitHub App token resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_get_installation_token_for_role_does_not_fallback_to_default_for_role() -> None:
    from vibeteam.utils import github_app

    with (
        patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID": "default-app",
                "GITHUB_APP_PRIVATE_KEY": "default-key",
                "GITHUB_APP_INSTALLATION_ID": "default-installation",
            },
            clear=True,
        ),
        patch(
            "vibeteam.utils.github_app.get_installation_token",
            return_value="ghs-default-token",
        ) as mock_get_installation_token,
    ):
        token = github_app.get_installation_token_for_role("software_engineer")
        assert token is None
        mock_get_installation_token.assert_not_called()


def test_get_installation_token_for_role_uses_default_for_default_role_marker() -> None:
    from vibeteam.utils import github_app

    with (
        patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID": "default-app",
                "GITHUB_APP_PRIVATE_KEY": "default-key",
                "GITHUB_APP_INSTALLATION_ID": "default-installation",
            },
            clear=True,
        ),
        patch(
            "vibeteam.utils.github_app.get_installation_token",
            return_value="ghs-default-token",
        ) as mock_get_installation_token,
    ):
        token = github_app.get_installation_token_for_role("__default__")
        assert token == "ghs-default-token"
        mock_get_installation_token.assert_called_once_with(
            "default-app",
            "default-key",
            "default-installation",
        )


@pytest.mark.asyncio
async def test_gateway_get_installation_token_role_does_not_use_default_config_fallback() -> None:
    from vibeteam.gateway.routes import github as github_module

    with (
        patch("vibeteam.gateway.routes.github.config") as mock_config,
        patch(
            "vibeteam.utils.github_app.get_installation_token_for_role",
            return_value=None,
        ) as mock_get_token_for_role,
    ):
        mock_config.GITHUB_APP_ID = "default-app"
        mock_config.GITHUB_APP_PRIVATE_KEY = "default-key"
        mock_config.GITHUB_APP_INSTALLATION_ID = "default-installation"

        token = await github_module.get_installation_token("software_engineer")
        assert token is None
        mock_get_token_for_role.assert_called_once_with("software_engineer")


class TestGitHubConnectorRoleFallback:
    """Gap 3 regression: GitHubConnector must not fall back to global creds when role is set."""

    def test_connector_uses_role_app_credentials(self):
        from vibeteam.connectors.github import GitHubConnector

        with patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID": "global-app",
                "GITHUB_APP_PRIVATE_KEY": "global-key",
                "GITHUB_APP_INSTALLATION_ID": "global-install",
                "GITHUB_TOKEN": "ghp-global",
            },
            clear=True,
        ), patch(
            "vibeteam.utils.github_app.get_role_app_credentials",
            return_value=("role-app", "role-key", "role-install"),
        ):
            conn = GitHubConnector(owner="owner", repo="repo", agent_role="support_engineer")
            assert conn.app_id == "role-app"
            assert conn.private_key == "role-key"
            assert conn.installation_id == "role-install"
            assert conn.token is None  # Must not fall back to global PAT

    def test_connector_does_not_fallback_to_global_when_role_creds_missing(self):
        from vibeteam.connectors.github import GitHubConnector

        with patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID": "global-app",
                "GITHUB_APP_PRIVATE_KEY": "global-key",
                "GITHUB_APP_INSTALLATION_ID": "global-install",
                "GITHUB_TOKEN": "ghp-global",
            },
            clear=True,
        ), patch(
            "vibeteam.utils.github_app.get_role_app_credentials",
            return_value=(None, None, None),
        ):
            # When role is set but role credentials are missing, the connector
            # must NOT silently fall back to global credentials. It should raise
            # because no valid auth is available for this role.
            with pytest.raises(ValueError, match="GitHub authentication required"):
                GitHubConnector(owner="owner", repo="repo", agent_role="support_engineer")

    def test_connector_uses_global_when_no_role(self):
        from vibeteam.connectors.github import GitHubConnector

        with patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID": "global-app",
                "GITHUB_APP_PRIVATE_KEY": "global-key",
                "GITHUB_APP_INSTALLATION_ID": "global-install",
            },
            clear=True,
        ):
            conn = GitHubConnector(owner="owner", repo="repo")
            assert conn.app_id == "global-app"
            assert conn.private_key == "global-key"
            assert conn.installation_id == "global-install"


class TestGitHubTokenContextClearing:
    """Gap 3 regression: _github_token_context must clear GITHUB_TOKEN when role
    is set but no role-scoped token exists."""

    def test_github_token_cleared_when_role_has_no_token(self):
        import os

        from agent_service.openhands.server import _github_token_context

        with patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "ghp-global", "GH_TOKEN": "ghp-global"},
            clear=True,
        ), patch(
            "vibeteam.utils.github_app.get_installation_token_for_role",
            return_value=None,
        ):
            with _github_token_context(role="support_engineer"):
                assert os.environ.get("GITHUB_TOKEN") is None
                assert os.environ.get("GH_TOKEN") is None
            # Restored after context exit
            assert os.environ.get("GITHUB_TOKEN") == "ghp-global"
            assert os.environ.get("GH_TOKEN") == "ghp-global"

    def test_github_token_set_when_role_has_token(self):
        import os

        from agent_service.openhands.server import _github_token_context

        with patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "ghp-global", "GH_TOKEN": "ghp-global"},
            clear=True,
        ), patch(
            "vibeteam.utils.github_app.get_installation_token_for_role",
            return_value="ghs-role-token",
        ):
            with _github_token_context(role="support_engineer"):
                assert os.environ.get("GITHUB_TOKEN") == "ghs-role-token"
                assert os.environ.get("GH_TOKEN") == "ghs-role-token"

    def test_github_token_unchanged_when_no_role(self):
        import os

        from agent_service.openhands.server import _github_token_context

        with patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "ghp-global", "GH_TOKEN": "ghp-global"},
            clear=True,
        ):
            with _github_token_context(role=None):
                assert os.environ.get("GITHUB_TOKEN") == "ghp-global"
                assert os.environ.get("GH_TOKEN") == "ghp-global"


class TestIntegrationChecksRoleCreds:
    """Gap 3 regression: startup validation warns about incomplete role credentials."""

    def test_warns_incomplete_role_github_creds(self):
        import logging

        from agent_service.shared.integration_checks import _warn_incomplete_role_github_creds

        with patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID_SUPPORT_ENGINEER": "app-id",
                # Missing GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER
                # Missing GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER
            },
            clear=True,
        ):
            with patch(
                "agent_service.shared.integration_checks.logger"
            ) as mock_logger:
                _warn_incomplete_role_github_creds()
                mock_logger.warning.assert_called_once()
                args = mock_logger.warning.call_args[0]
                assert "SUPPORT_ENGINEER" in args[1]
                assert "GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER" in args[2]

    def test_no_warning_when_complete(self):
        from agent_service.shared.integration_checks import _warn_incomplete_role_github_creds

        with patch.dict(
            "os.environ",
            {
                "GITHUB_APP_ID_SUPPORT_ENGINEER": "app-id",
                "GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER": "key",
                "GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER": "install",
            },
            clear=True,
        ):
            with patch(
                "agent_service.shared.integration_checks.logger"
            ) as mock_logger:
                _warn_incomplete_role_github_creds()
                mock_logger.warning.assert_not_called()
