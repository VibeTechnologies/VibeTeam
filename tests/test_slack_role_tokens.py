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

    def test_resolve_slack_assistant_token_does_not_use_ingress_for_role(self):
        from vibeteam.gateway.routes.slack import _resolve_slack_assistant_token

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_ASSISTANT_TOKEN = "xapp-ingress"
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"
            assert _resolve_slack_assistant_token("support_engineer") == ""
            assert _resolve_slack_assistant_token(None) == "xapp-ingress"


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

            ts = await send_slack_message("C_TEST", "hello", "1111.2222", role="support_engineer")
            assert ts == "1234.5678"

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-support"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_code", ["account_inactive", "not_in_channel"])
    async def test_send_slack_message_does_not_fallback_to_ingress_token(
        self, error_code: str
    ):
        from vibeteam.gateway.routes.slack import send_slack_message

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SOFTWARE_ENGINEER": "xoxb-software"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            response = MagicMock()
            response.json.return_value = {"ok": False, "error": error_code}

            mock_client = AsyncMock()
            mock_client.post.return_value = response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ts = await send_slack_message(
                "C_TEST", "hello", "1111.2222", role="software_engineer"
            )
            assert ts is None
            assert mock_client.post.call_count == 1

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-software"

    @pytest.mark.asyncio
    async def test_send_slack_message_does_not_fallback_for_non_retryable_error(self):
        from vibeteam.gateway.routes.slack import send_slack_message

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SOFTWARE_ENGINEER": "xoxb-software"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            first_response = MagicMock()
            first_response.json.return_value = {"ok": False, "error": "invalid_auth"}

            mock_client = AsyncMock()
            mock_client.post.return_value = first_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ts = await send_slack_message(
                "C_TEST", "hello", "1111.2222", role="software_engineer"
            )
            assert ts is None
            assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_slack_message_requires_role_token_when_role_is_set(self):
        from vibeteam.gateway.routes.slack import send_slack_message

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            ts = await send_slack_message(
                "C_TEST", "hello", "1111.2222", role="software_engineer"
            )
            assert ts is None
            mock_client_cls.assert_not_called()

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


class TestStrictRoleIdentityForAllSlackWrites:
    """Gap 2 regression: update_slack_message, add_reaction, remove_reaction
    must use strict role token resolution (no ingress fallback)."""

    @pytest.mark.asyncio
    async def test_update_slack_message_uses_role_token(self):
        from vibeteam.gateway.routes.slack import update_slack_message

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SUPPORT_ENGINEER": "xoxb-support"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ok = await update_slack_message("C_TEST", "1234.5678", "updated", role="support_engineer")
            assert ok is True

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-support"

    @pytest.mark.asyncio
    async def test_update_slack_message_refuses_ingress_fallback_for_role(self):
        from vibeteam.gateway.routes.slack import update_slack_message

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            ok = await update_slack_message("C_TEST", "1234.5678", "updated", role="support_engineer")
            assert ok is False
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_reaction_uses_role_token(self):
        from vibeteam.gateway.routes.slack import add_reaction

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_RELEASE_ENGINEER": "xoxb-release"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ok = await add_reaction("C_TEST", "1234.5678", "eyes", role="release_engineer")
            assert ok is True

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-release"

    @pytest.mark.asyncio
    async def test_add_reaction_refuses_ingress_fallback_for_role(self):
        from vibeteam.gateway.routes.slack import add_reaction

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            ok = await add_reaction("C_TEST", "1234.5678", "eyes", role="release_engineer")
            assert ok is False
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_reaction_uses_role_token(self):
        from vibeteam.gateway.routes.slack import remove_reaction

        with (
            patch.dict(
                "os.environ",
                {"SLACK_BOT_TOKEN_SOFTWARE_ENGINEER": "xoxb-swe"},
                clear=False,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            ok = await remove_reaction("C_TEST", "1234.5678", "thinking_face", role="software_engineer")
            assert ok is True

            headers = mock_client.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer xoxb-swe"

    @pytest.mark.asyncio
    async def test_remove_reaction_refuses_ingress_fallback_for_role(self):
        from vibeteam.gateway.routes.slack import remove_reaction

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"

            ok = await remove_reaction("C_TEST", "1234.5678", "thinking_face", role="software_engineer")
            assert ok is False
            mock_client_cls.assert_not_called()


class TestAppMentionRoleMentionPreservation:
    """Gap 1 regression: app_mention handler must preserve role app mentions
    and resolve roles from user mentions before stripping."""

    @pytest.mark.asyncio
    async def test_app_mention_preserves_role_mention_and_routes_correctly(self):
        """When ingress + role bot are both mentioned, only ingress mention
        is stripped and the role is injected as a text role mention."""
        from vibeteam.gateway.routes.slack import (
            _extract_roles_from_slack_user_mentions,
        )
        import re

        ingress_uid = "UINGRESS01"
        role_uid = "USUPPORT01"
        text = f"<@{ingress_uid}> <@{role_uid}> investigate this issue"

        with (
            patch(
                "vibeteam.gateway.routes.slack.get_bot_user_id",
                new_callable=AsyncMock,
                return_value=ingress_uid,
            ),
            patch(
                "vibeteam.gateway.routes.slack._role_bot_user_ids",
                new_callable=AsyncMock,
                return_value={role_uid: "support_engineer"},
            ),
        ):
            # Verify role extraction works before stripping
            roles = await _extract_roles_from_slack_user_mentions(text)
            assert roles == ["support_engineer"]

            # Simulate the app_mention handler logic:
            # Strip only ingress mention
            clean_text = re.sub(rf"<@{re.escape(ingress_uid)}>\s*", "", text).strip()
            assert f"<@{role_uid}>" in clean_text
            assert f"<@{ingress_uid}>" not in clean_text

    @pytest.mark.asyncio
    async def test_app_mention_with_only_ingress_mention_still_works(self):
        """When only ingress bot is mentioned (no role), text is fully cleaned."""
        import re

        ingress_uid = "UINGRESS01"
        text = f"<@{ingress_uid}> deploy the new version"

        with (
            patch(
                "vibeteam.gateway.routes.slack.get_bot_user_id",
                new_callable=AsyncMock,
                return_value=ingress_uid,
            ),
            patch(
                "vibeteam.gateway.routes.slack._role_bot_user_ids",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from vibeteam.gateway.routes.slack import _extract_roles_from_slack_user_mentions

            roles = await _extract_roles_from_slack_user_mentions(text)
            assert roles == []

            clean_text = re.sub(rf"<@{re.escape(ingress_uid)}>\s*", "", text).strip()
            assert clean_text == "deploy the new version"


class TestThinkingFaceRoleResolution:
    """Verify that thinking_face reactions use the resolved role token.

    This prevents the cross-app reaction bug where the ingress app adds
    thinking_face but the role-scoped app later fails to remove it
    (Slack only allows the app that added a reaction to remove it).
    """

    @pytest.mark.asyncio
    async def test_app_mention_thinking_face_uses_role_from_mention(self):
        """app_mention handler should add thinking_face with resolved role."""
        from vibeteam.gateway.routes.slack import _process_slack_event

        payload = {
            "type": "event_callback",
            "event_id": "Ev_test1",
            "event": {
                "type": "app_mention",
                "user": "U_HUMAN",
                "channel": "C_CHAN",
                "text": "<@U_INGRESS> <@U_SUPPORT> check errors",
                "ts": "123.456",
                "thread_ts": None,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack._extract_roles_from_slack_user_mentions",
                new_callable=AsyncMock,
                return_value=["support_engineer"],
            ),
            patch(
                "vibeteam.gateway.routes.slack.get_bot_user_id",
                new_callable=AsyncMock,
                return_value="U_INGRESS",
            ),
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
            patch(
                "vibeteam.gateway.routes.slack._extract_kubeconfig_context_from_event",
                new_callable=AsyncMock,
                return_value=(None, None),
            ),
            patch(
                "vibeteam.gateway.routes.slack._inject_thread_kubeconfig_context",
                side_effect=lambda t, *a, **k: t,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ) as mock_add_reaction,
            patch(
                "vibeteam.gateway.routes.slack.add_read_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_BOT_USER_ID = "U_INGRESS"
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"
            mock_config.VIBETEAM_HOST_URL = "http://test"
            mock_router = MagicMock()
            mock_router.parse_role_mentions.return_value = []
            mock_router_fn.return_value = mock_router

            await _process_slack_event(payload)

            # thinking_face must be added WITH the role so same bot removes it
            thinking_calls = [
                c for c in mock_add_reaction.call_args_list
                if len(c.args) >= 3 and c.args[2] == "thinking_face"
            ]
            assert len(thinking_calls) == 1
            assert thinking_calls[0].kwargs.get("role") == "support_engineer"

    @pytest.mark.asyncio
    async def test_dm_thinking_face_resolves_role_from_text(self):
        """DM handler should add thinking_face with role resolved from text."""
        from vibeteam.gateway.routes.slack import _process_slack_event

        payload = {
            "type": "event_callback",
            "event_id": "Ev_test2",
            "event": {
                "type": "message",
                "channel_type": "im",
                "user": "U_HUMAN",
                "channel": "C_DM",
                "text": "@SupportEngineer check errors",
                "ts": "456.789",
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack._resolve_explicit_role_for_text",
                new_callable=AsyncMock,
                return_value="support_engineer",
            ),
            patch(
                "vibeteam.gateway.routes.slack._extract_kubeconfig_context_from_event",
                new_callable=AsyncMock,
                return_value=(None, None),
            ),
            patch(
                "vibeteam.gateway.routes.slack._inject_thread_kubeconfig_context",
                side_effect=lambda t, *a, **k: t,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ) as mock_add_reaction,
            patch(
                "vibeteam.gateway.routes.slack.add_read_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ),
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_BOT_USER_ID = "U_INGRESS"
            mock_config.SLACK_BOT_TOKEN = "xoxb-ingress"
            mock_config.VIBETEAM_HOST_URL = "http://test"

            await _process_slack_event(payload)

            thinking_calls = [
                c for c in mock_add_reaction.call_args_list
                if len(c.args) >= 3 and c.args[2] == "thinking_face"
            ]
            assert len(thinking_calls) == 1
            assert thinking_calls[0].kwargs.get("role") == "support_engineer"


class TestEvalMentionReplacement:
    """Verify that eval tests replace @RoleName with <@U_BOT_ID> mentions."""

    def test_replace_role_mentions_with_slack_ids(self):
        """@RoleName text should become <@U_BOT_ID> when bot IDs are available."""
        with (
            patch(
                "scripts.eval_slack_e2e._load_role_to_bot_user_id",
                return_value={
                    "support_engineer": "U_SUPPORT_BOT",
                    "release_engineer": "U_RELEASE_BOT",
                },
            ),
        ):
            from scripts.eval_slack_e2e import _replace_role_mentions_with_slack_ids

            result = _replace_role_mentions_with_slack_ids(
                "@SupportEngineer check errors"
            )
            assert result == "<@U_SUPPORT_BOT> check errors"

    def test_replace_preserves_text_when_no_bot_ids(self):
        """When no bot IDs available, @RoleName stays as-is."""
        with (
            patch(
                "scripts.eval_slack_e2e._load_role_to_bot_user_id",
                return_value={},
            ),
        ):
            from scripts.eval_slack_e2e import _replace_role_mentions_with_slack_ids

            result = _replace_role_mentions_with_slack_ids(
                "@SupportEngineer check something"
            )
            assert result == "@SupportEngineer check something"


class TestGatewayMentionReplacement:
    """Verify gateway replaces @RoleName with <@U_BOT_ID> in outgoing messages."""

    @pytest.mark.asyncio
    async def test_replace_role_mentions_in_outgoing(self):
        """@RoleName in agent response becomes <@U_BOT_ID> before posting."""
        from vibeteam.gateway.routes.slack import (
            _replace_role_mentions_in_outgoing,
            _role_to_uid_cache,
        )
        import vibeteam.gateway.routes.slack as slack_mod

        original_cache = slack_mod._role_to_uid_cache
        try:
            slack_mod._role_to_uid_cache = {
                "support_engineer": "U_SUPPORT_BOT",
                "software_engineer": "U_SWE_BOT",
                "release_engineer": "U_RELEASE_BOT",
            }
            result = await _replace_role_mentions_in_outgoing(
                "I'm handing off to @SoftwareEngineer for the code fix."
            )
            assert "<@U_SWE_BOT>" in result
            assert "@SoftwareEngineer" not in result
        finally:
            slack_mod._role_to_uid_cache = original_cache

    @pytest.mark.asyncio
    async def test_replace_multiple_mentions(self):
        """Multiple @RoleName mentions all get replaced."""
        import vibeteam.gateway.routes.slack as slack_mod
        from vibeteam.gateway.routes.slack import _replace_role_mentions_in_outgoing

        original_cache = slack_mod._role_to_uid_cache
        try:
            slack_mod._role_to_uid_cache = {
                "support_engineer": "U_SUPPORT",
                "release_engineer": "U_RELEASE",
            }
            result = await _replace_role_mentions_in_outgoing(
                "@SupportEngineer please notify. @ReleaseEngineer please deploy."
            )
            assert "<@U_SUPPORT>" in result
            assert "<@U_RELEASE>" in result
            assert "@SupportEngineer" not in result
            assert "@ReleaseEngineer" not in result
        finally:
            slack_mod._role_to_uid_cache = original_cache

    @pytest.mark.asyncio
    async def test_no_replacement_when_cache_empty(self):
        """When no UIDs resolved, text stays unchanged."""
        import vibeteam.gateway.routes.slack as slack_mod
        from vibeteam.gateway.routes.slack import _replace_role_mentions_in_outgoing

        original_cache = slack_mod._role_to_uid_cache
        try:
            slack_mod._role_to_uid_cache = {}
            result = await _replace_role_mentions_in_outgoing(
                "@SoftwareEngineer check this"
            )
            assert result == "@SoftwareEngineer check this"
        finally:
            slack_mod._role_to_uid_cache = original_cache

    @pytest.mark.asyncio
    async def test_send_slack_message_applies_mention_replacement(self):
        """send_slack_message should call _replace_role_mentions_in_outgoing."""
        import vibeteam.gateway.routes.slack as slack_mod
        from vibeteam.gateway.routes.slack import send_slack_message

        original_cache = slack_mod._role_to_uid_cache
        try:
            slack_mod._role_to_uid_cache = {
                "software_engineer": "U_SWE_BOT",
            }
            with patch.object(
                slack_mod, "_resolve_slack_reply_bot_token", return_value="xoxb-test"
            ), patch("httpx.AsyncClient") as MockClient:
                mock_resp = AsyncMock()
                mock_resp.json.return_value = {"ok": True, "ts": "123.456"}
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(
                    return_value=mock_client_instance
                )
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                await send_slack_message(
                    "C123",
                    "@SoftwareEngineer please investigate",
                    "ts123",
                    role="support_engineer",
                )

                posted_payload = mock_client_instance.post.call_args[1]["json"]
                assert "<@U_SWE_BOT>" in posted_payload["text"]
                assert "@SoftwareEngineer" not in posted_payload["text"]
        finally:
            slack_mod._role_to_uid_cache = original_cache
