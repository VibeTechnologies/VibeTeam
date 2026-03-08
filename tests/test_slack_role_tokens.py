"""Tests for role-scoped Slack token resolution and usage in gateway Slack helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRoleScopedTokenResolution:
    def test_resolve_slack_bot_token_prefers_role_scoped(self):
        from vibeteam.gateway.routes.slack import _resolve_slack_bot_token

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "xoxb-support"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"
            assert _resolve_slack_bot_token("support_engineer") == "xoxb-support"

    def test_resolve_slack_bot_token_supports_camel_case_and_prefixed_handles(self):
        from vibeteam.gateway.routes.slack import _resolve_slack_bot_token

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SOFTWARE_ENGINEER": "xoxb-swe"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"
            assert _resolve_slack_bot_token("SoftwareEngineer") == "xoxb-swe"
            assert _resolve_slack_bot_token("@SoftwareEngineer") == "xoxb-swe"
            assert _resolve_slack_bot_token("software-engineer") == "xoxb-swe"

    def test_resolve_slack_bot_token_falls_back_to_default(self):
        from vibeteam.gateway.routes.slack import _resolve_slack_bot_token

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"
            assert _resolve_slack_bot_token("support_engineer") == "xoxb-default"

    def test_resolve_slack_assistant_token_fallback_chain(self):
        from vibeteam.gateway.routes.slack import _resolve_slack_assistant_token

        with (
            patch.dict(
                "os.environ",
                {
                    "SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "xoxb-support",
                },
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_ASSISTANT_TOKEN = ""
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"
            assert _resolve_slack_assistant_token("support_engineer") == "xoxb-support"


class TestRoleScopedApiCalls:
    @pytest.mark.asyncio
    async def test_send_slack_message_uses_role_token(self):
        from vibeteam.gateway.routes.slack import send_slack_message

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "xoxb-support"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True, "ts": "1234.5678"}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ts = await send_slack_message(
                "C_TEST", "hello", "1111.2222", role="support_engineer"
            )
            assert ts == "1234.5678"

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-support"

    @pytest.mark.asyncio
    async def test_set_thread_status_uses_role_assistant_token(self):
        from vibeteam.gateway.routes.slack import set_thread_status

        with (
            patch.dict(
                "os.environ",
                {"SLACK_ASSISTANT_TOKEN_SUPPORT_ENGINEER": "xapp-support"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_ASSISTANT_TOKEN = "xapp-default"
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ok = await set_thread_status(
                "C_TEST", "1111.2222", "is thinking...", role="support_engineer"
            )
            assert ok is True

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xapp-support"


class TestThreadParticipationAcrossRoleBots:
    @pytest.mark.asyncio
    async def test_bot_participated_checks_multiple_role_tokens(self):
        from vibeteam.gateway.routes.slack import bot_participated_in_thread

        with (
            patch.dict(
                "os.environ",
                {
                    "SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "xoxb-support",
                    "SLACK_BOT_TOKEN_RELEASE_ENGINEER": "xoxb-release",
                },
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch(
                "vibeteam.gateway.routes.slack.get_bot_user_id",
                new_callable=AsyncMock,
                side_effect=["U_DEFAULT", "U_SUPPORT", "U_RELEASE"],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-default"

            first_resp = MagicMock()
            first_resp.json.return_value = {"ok": False, "error": "not_in_channel"}
            second_resp = MagicMock()
            second_resp.json.return_value = {
                "ok": True,
                "messages": [{"user": "U_SUPPORT", "text": "I investigated"}],
            }

            mock_client = AsyncMock()
            mock_client.get.side_effect = [first_resp, second_resp]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await bot_participated_in_thread("C_TEST", "1111.2222") is True
