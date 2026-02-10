"""
Tests for the async agent callback architecture.

Tests the complete async flow:
1. Slack event -> gateway adds eyes reaction -> submits /run/async
2. Agent completes -> POSTs to /callback/agent
3. Gateway removes spinner, posts response, adds checkmark
4. Handoffs in callback submit new async jobs
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from vibeteam.gateway.routes.slack import (
    _build_task_prompt,
    classify_task_template,
)


@pytest.fixture
def test_client():
    """Create test client for the gateway server."""
    from vibeteam.gateway.server import app

    return TestClient(app)


# ==============================================================================
# Tests for _build_task_prompt
# ==============================================================================


class TestBuildTaskPrompt:
    """Test that _build_task_prompt returns correct templates."""

    def test_deployment_prompt_contains_kubectl_set_image(self):
        prompt = _build_task_prompt(
            role="release_engineer",
            user_message="@ReleaseEngineer deploy v2.0 to staging",
            user_id="U123",
            channel="C456",
            thread_ts="1234.5678",
        )
        assert "kubectl set image" in prompt
        assert "CRITICAL SAFETY RULE" in prompt
        assert "FORBIDDEN" in prompt

    def test_deployment_prompt_includes_context(self):
        prompt = _build_task_prompt(
            role="release_engineer",
            user_message="deploy the latest",
            user_id="U_USER",
            channel="C_CHAN",
            thread_ts="ts_123",
        )
        assert "U_USER" in prompt
        assert "C_CHAN" in prompt
        assert "ts_123" in prompt

    def test_notification_prompt(self):
        prompt = _build_task_prompt(
            role="support_engineer",
            user_message="notify the customer the fix is deployed",
            user_id="U123",
            channel="C456",
            thread_ts=None,
        )
        assert "Notification Request" in prompt
        assert "new thread" in prompt
        assert "kubectl" not in prompt.lower() or "You do NOT need to run kubectl" in prompt

    def test_investigation_prompt_contains_kubectl_instructions(self):
        prompt = _build_task_prompt(
            role="support_engineer",
            user_message="customers are seeing 500 errors",
            user_id="U123",
            channel="C456",
            thread_ts="ts_456",
        )
        assert "kubectl get pods" in prompt
        assert "MANDATORY" in prompt
        assert "curl" in prompt

    def test_investigation_prompt_none_thread_ts(self):
        prompt = _build_task_prompt(
            role="support_engineer",
            user_message="what's happening?",
            user_id="U123",
            channel="C456",
            thread_ts=None,
        )
        assert "new thread" in prompt

    def test_deployment_takes_priority_over_notification(self):
        """Deploy + notify = deployment for release_engineer."""
        template = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer deploy to staging and notify the team",
        )
        assert template == "deployment"

    def test_investigation_trumps_all(self):
        """Investigation keywords override both deployment and notification."""
        template = classify_task_template(
            "release_engineer",
            "@ReleaseEngineer deploy failed, investigate the error",
        )
        assert template == "investigation"


# ==============================================================================
# Tests for remove_reaction helper
# ==============================================================================


class TestRemoveReaction:
    """Test the remove_reaction Slack API helper."""

    @pytest.mark.asyncio
    async def test_remove_reaction_success(self):
        from vibeteam.gateway.routes.slack import remove_reaction

        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await remove_reaction("C123", "1234.5678", "eyes")
                assert result is True

                # Verify the API call
                mock_client.post.assert_called_once()
                call_kwargs = mock_client.post.call_args
                assert call_kwargs[0][0] == "https://slack.com/api/reactions.remove"
                body = call_kwargs[1]["json"]
                assert body["channel"] == "C123"
                assert body["timestamp"] == "1234.5678"
                assert body["name"] == "eyes"

    @pytest.mark.asyncio
    async def test_remove_reaction_no_token(self):
        from vibeteam.gateway.routes.slack import remove_reaction

        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_BOT_TOKEN = ""
            result = await remove_reaction("C123", "1234.5678", "eyes")
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_reaction_no_reaction_is_not_error(self):
        """Removing a reaction that doesn't exist returns True (no-op)."""
        from vibeteam.gateway.routes.slack import remove_reaction

        with patch("vibeteam.gateway.routes.slack.config") as mock_config:
            mock_config.SLACK_BOT_TOKEN = "xoxb-test"

            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": False, "error": "no_reaction"}

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await remove_reaction("C123", "1234.5678", "eyes")
                assert result is True  # no_reaction is treated as success


# ==============================================================================
# Tests for /callback/agent endpoint
# ==============================================================================


class TestCallbackEndpoint:
    """Test the POST /callback/agent endpoint."""

    def test_callback_success_posts_to_slack(self, test_client):
        """Successful agent callback posts response to Slack thread."""
        payload = {
            "job_id": "job-123",
            "status": "completed",
            "response": "I investigated the issue and found no errors.",
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "support_engineer",
                "display_name": "SupportEngineer",
                "max_handoff_depth": 3,
                "current_depth": 0,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_add,
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
        ):
            mock_router = mock_router_fn.return_value
            mock_router.parse_role_mentions.return_value = []

            response = test_client.post("/callback/agent", json=payload)

            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "ok"
            assert result["outcome"] == "response_posted"

            # Verify spinner removed
            mock_remove.assert_called_once_with("C_TEST", "ts_1234", "arrows_counterclockwise")

            # Verify checkmark added
            mock_add.assert_called_once_with("C_TEST", "ts_1234", "white_check_mark")

            # Verify message posted to thread
            mock_send.assert_called_once()
            sent_text = mock_send.call_args[0][1]
            assert "[SupportEngineer]" in sent_text
            assert "I investigated the issue" in sent_text

    def test_callback_failure_posts_error(self, test_client):
        """Failed agent callback posts error and adds X reaction."""
        payload = {
            "job_id": "job-456",
            "status": "failed",
            "error": "Agent crashed",
            "response": "",
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "release_engineer",
                "display_name": "ReleaseEngineer",
                "max_handoff_depth": 3,
                "current_depth": 0,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_add,
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            response = test_client.post("/callback/agent", json=payload)

            assert response.status_code == 200
            result = response.json()
            assert result["outcome"] == "error_posted"

            # Verify X reaction (not checkmark)
            mock_add.assert_called_once_with("C_TEST", "ts_1234", "x")

            # Verify error message sent
            sent_text = mock_send.call_args[0][1]
            assert "error" in sent_text.lower()
            assert "Agent crashed" in sent_text

    def test_callback_missing_channel_returns_error(self, test_client):
        """Callback without channel in metadata returns error."""
        payload = {
            "job_id": "job-789",
            "status": "completed",
            "response": "Done.",
            "callback_metadata": {},  # No channel
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ),
        ):
            response = test_client.post("/callback/agent", json=payload)
            assert response.status_code == 200
            assert response.json()["status"] == "error"

    def test_callback_invalid_json_returns_400(self, test_client):
        """Callback with invalid JSON body returns 400."""
        response = test_client.post(
            "/callback/agent",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_callback_handoff_submits_new_agent(self, test_client):
        """Callback with @RoleName in response triggers handoff."""
        payload = {
            "job_id": "job-handoff",
            "status": "completed",
            "response": "I found issues. @ReleaseEngineer please rollback the deployment.",
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "support_engineer",
                "display_name": "SupportEngineer",
                "max_handoff_depth": 3,
                "current_depth": 0,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_submit,
        ):
            mock_router = mock_router_fn.return_value
            mock_router.parse_role_mentions.return_value = ["release_engineer"]

            response = test_client.post("/callback/agent", json=payload)

            assert response.status_code == 200
            assert response.json()["outcome"] == "response_posted"

            # Verify handoff submitted
            mock_submit.assert_called_once()
            call_kwargs = mock_submit.call_args[1]
            assert call_kwargs["role"] == "release_engineer"
            assert call_kwargs["current_depth"] == 1
            assert "Handoff from SupportEngineer" in call_kwargs["user_message"]

    def test_callback_self_handoff_skipped(self, test_client):
        """Agent mentioning its own role should not trigger a handoff."""
        payload = {
            "job_id": "job-self",
            "status": "completed",
            "response": "@SupportEngineer I'll continue investigating.",
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "support_engineer",
                "display_name": "SupportEngineer",
                "max_handoff_depth": 3,
                "current_depth": 0,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_submit,
        ):
            mock_router = mock_router_fn.return_value
            mock_router.parse_role_mentions.return_value = ["support_engineer"]

            response = test_client.post("/callback/agent", json=payload)

            assert response.status_code == 200
            # Self-handoff should be skipped, so _submit_agent_async should NOT be called
            mock_submit.assert_not_called()

    def test_callback_max_depth_prevents_handoff(self, test_client):
        """Handoffs are not submitted when max depth is reached."""
        payload = {
            "job_id": "job-deep",
            "status": "completed",
            "response": "@ReleaseEngineer please help",
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "support_engineer",
                "display_name": "SupportEngineer",
                "max_handoff_depth": 3,
                "current_depth": 3,  # Already at max
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_submit,
        ):
            mock_router = mock_router_fn.return_value
            mock_router.parse_role_mentions.return_value = ["release_engineer"]

            response = test_client.post("/callback/agent", json=payload)

            assert response.status_code == 200
            # At max depth — should not submit further handoffs
            mock_submit.assert_not_called()

    def test_callback_long_response_split(self, test_client):
        """Long agent responses should be split into multiple Slack messages."""
        long_response = "A" * 4000  # Exceeds 2900 char split threshold

        payload = {
            "job_id": "job-long",
            "status": "completed",
            "response": long_response,
            "callback_metadata": {
                "channel": "C_TEST",
                "thread_ts": "ts_1234",
                "message_ts": "ts_1234",
                "user_id": "U_USER",
                "role": "support_engineer",
                "display_name": "SupportEngineer",
                "max_handoff_depth": 3,
                "current_depth": 0,
            },
        }

        with (
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch(
                "vibeteam.gateway.routes.slack.get_message_router",
            ) as mock_router_fn,
        ):
            mock_router = mock_router_fn.return_value
            mock_router.parse_role_mentions.return_value = []

            response = test_client.post("/callback/agent", json=payload)
            assert response.status_code == 200

            # Multiple messages should be sent
            assert mock_send.call_count >= 2

            # First message should have role prefix
            first_text = mock_send.call_args_list[0][0][1]
            assert "[SupportEngineer]" in first_text

            # Second message should have continuation prefix
            second_text = mock_send.call_args_list[1][0][1]
            assert "(cont.)" in second_text


# ==============================================================================
# Tests for _submit_agent_async
# ==============================================================================


class TestSubmitAgentAsync:
    """Test the _submit_agent_async function."""

    @pytest.mark.asyncio
    async def test_submit_success(self):
        from vibeteam.gateway.routes.slack import _submit_agent_async

        with (
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_add,
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(
                "vibeteam.gateway.routes.slack.call_agent_service_async",
                new_callable=AsyncMock,
                return_value={"job_id": "test-job-123", "status": "accepted"},
            ) as mock_call,
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.GATEWAY_URL = "http://vibeteam-gateway:8080"

            await _submit_agent_async(
                role="support_engineer",
                display_name="SupportEngineer",
                user_message="check the errors",
                channel="C_TEST",
                thread_ts="ts_1234",
                message_ts="msg_ts_1234",
                user_id="U_USER",
            )

            # Verify reaction lifecycle: add spinner, remove eyes
            mock_add.assert_called_once_with("C_TEST", "msg_ts_1234", "arrows_counterclockwise")
            mock_remove.assert_called_once_with("C_TEST", "msg_ts_1234", "eyes")

            # Verify async service was called with callback URL
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert call_kwargs["role"] == "support_engineer"
            assert "callback/agent" in call_kwargs["callback_url"]
            assert call_kwargs["callback_metadata"]["channel"] == "C_TEST"

    @pytest.mark.asyncio
    async def test_submit_failure_adds_x_reaction(self):
        from vibeteam.gateway.routes.slack import _submit_agent_async

        with (
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_add,
            patch(
                "vibeteam.gateway.routes.slack.remove_reaction",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.call_agent_service_async",
                new_callable=AsyncMock,
                return_value={"error": "Connection refused"},
            ),
            patch(
                "vibeteam.gateway.routes.slack.send_slack_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.GATEWAY_URL = "http://vibeteam-gateway:8080"

            await _submit_agent_async(
                role="support_engineer",
                display_name="SupportEngineer",
                user_message="check the errors",
                channel="C_TEST",
                thread_ts="ts_1234",
                message_ts="msg_ts_1234",
                user_id="U_USER",
            )

            # Should remove spinner and add X on failure
            add_calls = [call[0] for call in mock_add.call_args_list]
            assert ("C_TEST", "msg_ts_1234", "arrows_counterclockwise") in add_calls
            assert ("C_TEST", "msg_ts_1234", "x") in add_calls

            # Should send error message to Slack
            mock_send.assert_called_once()
            sent_text = mock_send.call_args[0][1]
            assert "couldn't reach" in sent_text.lower() or "error" in sent_text.lower()


# ==============================================================================
# Tests for Slack event handlers passing message_ts
# ==============================================================================


class TestSlackEventsPassMessageTs:
    """Verify that handle_slack_events passes message_ts to run_agent_for_slack."""

    def _make_slack_event(
        self,
        event_type: str,
        text: str = "help me",
        channel_type: str | None = None,
        is_bot: bool = False,
    ) -> dict[str, Any]:
        """Build a minimal Slack event payload."""
        event: dict[str, Any] = {
            "type": event_type,
            "text": text,
            "user": "U_TEST",
            "channel": "C_TEST",
            "ts": "1234567890.123456",
            "thread_ts": "1234567890.000000",
        }
        if channel_type:
            event["channel_type"] = channel_type
        if is_bot:
            event["bot_id"] = "B_BOT"
        return {
            "type": "event_callback",
            "event": event,
        }

    def test_app_mention_passes_message_ts(self, test_client):
        """app_mention handler passes message_ts to run_agent_for_slack."""
        payload = self._make_slack_event("app_mention", text="<@BOT123> help me")

        with (
            patch(
                "vibeteam.gateway.routes.slack.verify_slack_signature",
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            response = test_client.post(
                "/slack/events",
                json=payload,
                headers={
                    "X-Slack-Request-Timestamp": "123",
                    "X-Slack-Signature": "v0=test",
                },
            )

            assert response.status_code == 200
            assert response.json()["event"] == "app_mention"

            # Verify message_ts was passed
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # message_ts should be passed as keyword argument
            assert call_kwargs.kwargs.get("message_ts") == "1234567890.123456"

    def test_dm_passes_message_ts(self, test_client):
        """message.im handler passes message_ts to run_agent_for_slack."""
        payload = self._make_slack_event("message", channel_type="im")

        with (
            patch(
                "vibeteam.gateway.routes.slack.verify_slack_signature",
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            response = test_client.post(
                "/slack/events",
                json=payload,
                headers={
                    "X-Slack-Request-Timestamp": "123",
                    "X-Slack-Signature": "v0=test",
                },
            )

            assert response.status_code == 200
            assert response.json()["event"] == "message.im"

            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs.get("message_ts") == "1234567890.123456"

    def test_bot_message_with_role_mention_passes_message_ts(self, test_client):
        """Bot message with role mention passes message_ts."""
        payload = self._make_slack_event(
            "message", text="@SupportEngineer please investigate", is_bot=True
        )

        with (
            patch(
                "vibeteam.gateway.routes.slack.verify_slack_signature",
                return_value=True,
            ),
            patch(
                "vibeteam.gateway.routes.slack.add_reaction",
                new_callable=AsyncMock,
            ),
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            response = test_client.post(
                "/slack/events",
                json=payload,
                headers={
                    "X-Slack-Request-Timestamp": "123",
                    "X-Slack-Signature": "v0=test",
                },
            )

            assert response.status_code == 200
            assert response.json()["event"] == "message.bot_with_role_mention"

            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs.get("message_ts") == "1234567890.123456"


# ==============================================================================
# Tests for /slack/trigger sync behavior
# ==============================================================================


class TestSlackTriggerSyncPath:
    """/slack/trigger should use sync path (use_async=False)."""

    def test_trigger_uses_sync_path(self, test_client):
        """Trigger endpoint passes use_async=False to run_agent_for_slack."""
        with (
            patch(
                "vibeteam.gateway.routes.slack.run_agent_for_slack",
                new_callable=AsyncMock,
            ) as mock_run,
            patch("vibeteam.gateway.routes.slack.config") as mock_config,
        ):
            mock_config.SLACK_TRIGGER_SECRET = ""  # No auth for test

            response = test_client.post(
                "/slack/trigger",
                json={
                    "channel": "C_TEST",
                    "thread_ts": "ts_1234",
                    "text": "@SupportEngineer investigate the issue",
                    "user_id": "eval_script",
                },
            )

            assert response.status_code == 200
            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs.get("use_async") is False


# ==============================================================================
# Tests for run_agent_for_slack async/sync routing
# ==============================================================================


class TestRunAgentForSlackRouting:
    """Test that run_agent_for_slack correctly routes to async or sync path."""

    @pytest.mark.asyncio
    async def test_async_path_used_by_default(self):
        from vibeteam.gateway.routes.slack import run_agent_for_slack

        with (
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_async,
            patch(
                "vibeteam.gateway.routes.slack._run_agent_and_respond",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            await run_agent_for_slack(
                user_message="help me",
                channel="C_TEST",
                thread_ts="ts_1234",
                user_id="U_USER",
                message_ts="msg_1234",
                use_async=True,
            )

            mock_async.assert_called_once()
            mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_path_used_when_use_async_false(self):
        from vibeteam.gateway.routes.slack import run_agent_for_slack

        with (
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_async,
            patch(
                "vibeteam.gateway.routes.slack._run_agent_and_respond",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            await run_agent_for_slack(
                user_message="@SupportEngineer help",
                channel="C_TEST",
                thread_ts="ts_1234",
                user_id="U_USER",
                message_ts="msg_1234",
                use_async=False,
            )

            mock_sync.assert_called_once()
            mock_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_fallback_when_no_message_ts(self):
        """Without message_ts, even with use_async=True, falls back to sync."""
        from vibeteam.gateway.routes.slack import run_agent_for_slack

        with (
            patch(
                "vibeteam.gateway.routes.slack._submit_agent_async",
                new_callable=AsyncMock,
            ) as mock_async,
            patch(
                "vibeteam.gateway.routes.slack._run_agent_and_respond",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            await run_agent_for_slack(
                user_message="help me",
                channel="C_TEST",
                thread_ts=None,
                user_id="U_USER",
                message_ts=None,  # No message_ts
                use_async=True,
            )

            # Without message_ts, effective_message_ts is "" which is falsy
            # So it should fall back to sync
            mock_sync.assert_called_once()
            mock_async.assert_not_called()


# ==============================================================================
# Tests for openhands /run/async endpoint
# ==============================================================================


try:
    import sqlalchemy  # noqa: F401

    _has_sqlalchemy = True
except ImportError:
    _has_sqlalchemy = False


@pytest.mark.skipif(not _has_sqlalchemy, reason="sqlalchemy not installed")
class TestOpenHandsRunAsync:
    """Test the openhands-svc /run/async endpoint."""

    def test_run_async_returns_job_id(self):
        """POST /run/async should return a job_id immediately."""
        from agents.openhands.server import app as agent_app

        client = TestClient(agent_app)

        with patch(
            "agents.openhands.server._execute_and_callback",
            new_callable=AsyncMock,
        ):
            response = client.post(
                "/run/async",
                json={
                    "task": "test task",
                    "role": "support_engineer",
                    "context_type": "slack",
                    "context_id": "C123:ts_456",
                    "callback_url": "http://gateway:8080/callback/agent",
                    "callback_metadata": {"channel": "C123"},
                },
            )

            assert response.status_code == 200
            result = response.json()
            assert "job_id" in result
            assert result["status"] == "accepted"

    def test_run_async_requires_callback_url(self):
        """POST /run/async should require callback_url."""
        from agents.openhands.server import app as agent_app

        client = TestClient(agent_app)

        response = client.post(
            "/run/async",
            json={
                "task": "test task",
                "role": "support_engineer",
                # No callback_url — should fail validation
            },
        )

        assert response.status_code == 422  # Pydantic validation error
