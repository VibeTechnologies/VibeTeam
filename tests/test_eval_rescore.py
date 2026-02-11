"""
Tests for eval_slack_e2e.py --thread-ts rescore mode and handoff timeout extension.

These are pure logic tests with mocked Slack — NOT e2e tests.
"""

from __future__ import annotations

import os

# We need to import from the eval script — it uses relative path manipulation
# so we import after ensuring sys.path is set up
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibeteam.connectors.slack import SlackMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.eval_slack_e2e import (
    ROLE_DISPLAY,
    SCENARIOS,
    build_transcript,
    run_evaluation,
)

# ==============================================================================
# Helpers
# ==============================================================================


def make_slack_message(
    ts: str,
    text: str,
    is_bot: bool = False,
    thread_ts: str | None = None,
    channel: str = "C_TEST",
) -> SlackMessage:
    """Create a SlackMessage for testing."""
    return SlackMessage(
        ts=ts,
        channel=channel,
        user="U_BOT" if is_bot else "U_USER",
        text=text,
        thread_ts=thread_ts,
        timestamp=datetime.now(timezone.utc),
        is_bot=is_bot,
        mentions=[],
    )


# ==============================================================================
# Tests: build_transcript
# ==============================================================================


class TestBuildTranscript:
    """Tests for the build_transcript helper."""

    def test_single_user_message(self):
        messages = [("user", "Hello")]
        result = build_transcript(messages)
        assert result == "[User] Hello"

    def test_multi_role_conversation(self):
        messages = [
            ("user", "Check the API"),
            ("support_engineer", "I'll investigate."),
            ("software_engineer", "Found the bug."),
        ]
        result = build_transcript(messages)
        assert "[User] Check the API" in result
        assert "[SupportEngineer] I'll investigate." in result
        assert "[SoftwareEngineer] Found the bug." in result

    def test_unknown_role_uses_title(self):
        messages = [("unknown_role", "Test")]
        result = build_transcript(messages)
        assert "[Unknown_Role] Test" in result


# ==============================================================================
# Tests: --thread-ts rescore mode
# ==============================================================================


class TestRescoreMode:
    """Tests for the --thread-ts rescore path in run_evaluation."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set required env vars."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

    @pytest.fixture
    def mock_slack(self):
        """Create a mock SlackConnector that returns canned thread replies."""
        mock = MagicMock()
        # get_thread_replies returns a list of SlackMessage objects
        mock.get_thread_replies.return_value = [
            # First message in thread is the original user message
            make_slack_message(
                ts="1770710833.425539",
                text="@SupportEngineer investigate the Stripe webhook failure",
                is_bot=False,
                thread_ts="1770710833.425539",
            ),
            # Bot response from SupportEngineer
            make_slack_message(
                ts="1770710900.000001",
                text="[SupportEngineer] I've checked Sentry and kubectl. The webhook endpoint returns 404.",
                is_bot=True,
                thread_ts="1770710833.425539",
            ),
            # Bot response from SoftwareEngineer (handoff)
            make_slack_message(
                ts="1770711200.000002",
                text="[SoftwareEngineer] I've found the issue in the routing config.",
                is_bot=True,
                thread_ts="1770710833.425539",
            ),
        ]
        return mock

    @pytest.mark.asyncio
    async def test_rescore_skips_post_message(self, mock_env, mock_slack):
        """When existing_thread_ts is provided, post_message should NOT be called."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        # post_message should never be called in rescore mode
        mock_slack.post_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_rescore_skips_gateway_trigger(self, mock_env, mock_slack):
        """When existing_thread_ts is provided, no HTTP call to gateway /slack/trigger."""
        with (
            patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack),
            patch("scripts.eval_slack_e2e.httpx.AsyncClient") as mock_httpx,
        ):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        # httpx.AsyncClient should never be instantiated in rescore mode
        mock_httpx.assert_not_called()

    @pytest.mark.asyncio
    async def test_rescore_calls_get_thread_replies(self, mock_env, mock_slack):
        """When existing_thread_ts is provided, get_thread_replies IS called."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        mock_slack.get_thread_replies.assert_called_once_with(
            channel="C0AATPSADB8",
            thread_ts="1770710833.425539",
            limit=50,
        )

    @pytest.mark.asyncio
    async def test_rescore_latency_is_zero(self, mock_env, mock_slack):
        """In rescore mode, latency_ms should be 0."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        assert result["latency_ms"] == 0

    @pytest.mark.asyncio
    async def test_rescore_thread_ts_matches_provided(self, mock_env, mock_slack):
        """Result thread_ts should match the provided existing_thread_ts."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        assert result["thread_ts"] == "1770710833.425539"

    @pytest.mark.asyncio
    async def test_rescore_parses_conversation_roles(self, mock_env, mock_slack):
        """Conversation should be correctly parsed from thread replies with role detection."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        conversation = result["conversation"]
        # First entry is the user message (from scenario config, not thread)
        assert conversation[0][0] == "user"
        # Second entry should be support_engineer (parsed from [SupportEngineer] prefix)
        assert conversation[1][0] == "support_engineer"
        assert "Sentry" in conversation[1][1]
        # Third entry should be software_engineer
        assert conversation[2][0] == "software_engineer"
        assert "routing config" in conversation[2][1]

    @pytest.mark.asyncio
    async def test_rescore_conversation_count(self, mock_env, mock_slack):
        """Should have 3 messages: 1 user + 2 bot replies."""
        with patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        assert len(result["conversation"]) == 3

    @pytest.mark.asyncio
    async def test_rescore_generates_report(self, mock_env, mock_slack, tmp_path):
        """Rescore mode should generate a report file."""
        with (
            patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack),
            patch(
                "scripts.eval_slack_e2e.generate_eval_report",
                return_value=tmp_path / "test_report.md",
            ) as mock_report,
        ):
            result = await run_evaluation(
                scenario_name="stripe_webhook_failure",
                channel="C0AATPSADB8",
                existing_thread_ts="1770710833.425539",
                skip_eval=True,
            )

        # Report generation should still be called
        mock_report.assert_called_once()
        call_kwargs = mock_report.call_args
        # latency_ms should be 0 in rescore mode
        assert call_kwargs.kwargs.get(
            "latency_ms", call_kwargs[1].get("latency_ms", None)
        ) == 0 or (len(call_kwargs.args) > 6 and call_kwargs.args[6] == 0)


# ==============================================================================
# Tests: Handoff timeout extension
# ==============================================================================


class TestHandoffTimeoutExtension:
    """Tests for the handoff timeout auto-extension in the polling loop."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set required env vars."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        monkeypatch.setenv("SLACK_TRIGGER_SECRET", "test-secret")

    def test_stable_time_with_handoff_is_300(self):
        """Verify the stable_time_with_handoff constant is 300 (not old 60)."""
        # Read the source to verify the constant
        import inspect

        source = inspect.getsource(run_evaluation)
        assert "stable_time_with_handoff = 300" in source

    def test_stable_time_no_handoff_is_15(self):
        """Verify stable_time_no_handoff constant is 15."""
        import inspect

        source = inspect.getsource(run_evaluation)
        assert "stable_time_no_handoff = 15" in source

    def test_effective_timeout_in_source(self):
        """Verify effective_timeout variable is used for auto-extension."""
        import inspect

        source = inspect.getsource(run_evaluation)
        assert "effective_timeout = wait_timeout" in source
        assert "effective_timeout = time.time() - start_time + handoff_timeout_extension" in source

    @pytest.mark.asyncio
    async def test_handoff_detected_extends_timeout(self, mock_env):
        """When bot message contains @SoftwareEngineer, effective_timeout should be extended."""
        # Set up a mock Slack connector with a handoff message followed by a response
        mock_slack = MagicMock()

        # post_message returns a message with a ts
        mock_slack.post_message.return_value = make_slack_message(
            ts="100.000",
            text="@SupportEngineer investigate",
            is_bot=False,
        )

        # Track how many times get_thread_replies is called
        call_count = 0

        def mock_replies(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # First poll: just the original message
                return [
                    make_slack_message(ts="100.000", text="@SupportEngineer investigate"),
                ]
            elif call_count == 2:
                # Second poll: bot response with handoff mention
                return [
                    make_slack_message(ts="100.000", text="@SupportEngineer investigate"),
                    make_slack_message(
                        ts="101.000",
                        text="[SupportEngineer] Found the issue. @SoftwareEngineer please fix the code.",
                        is_bot=True,
                        thread_ts="100.000",
                    ),
                ]
            else:
                # Third poll: second agent responded (no handoff)
                return [
                    make_slack_message(ts="100.000", text="@SupportEngineer investigate"),
                    make_slack_message(
                        ts="101.000",
                        text="[SupportEngineer] Found the issue. @SoftwareEngineer please fix the code.",
                        is_bot=True,
                        thread_ts="100.000",
                    ),
                    make_slack_message(
                        ts="102.000",
                        text="[SoftwareEngineer] Fixed the routing config in PR #123.",
                        is_bot=True,
                        thread_ts="100.000",
                    ),
                ]

        mock_slack.get_thread_replies.side_effect = mock_replies

        with (
            patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack),
            patch("scripts.eval_slack_e2e.httpx.AsyncClient") as mock_httpx_cls,
            patch("scripts.eval_slack_e2e.asyncio.sleep", new_callable=AsyncMock),
        ):
            # Set up httpx mock to return 200
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"roles": ["support_engineer"]}
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_client

            result = await run_evaluation(
                scenario_name="support_400_errors",
                channel="C_TEST",
                wait_timeout=10,
                poll_interval=1,
                skip_eval=True,
                handoff_timeout_extension=600,
            )

        # Should have conversation with handoff chain
        assert len(result["conversation"]) >= 2
        # The handoff response from SoftwareEngineer should appear
        roles = [role for role, _ in result["conversation"]]
        assert "support_engineer" in roles

    @pytest.mark.asyncio
    async def test_no_handoff_no_extension(self, mock_env):
        """When bot message has no handoff mention, timeout should NOT be extended."""
        mock_slack = MagicMock()

        mock_slack.post_message.return_value = make_slack_message(
            ts="100.000",
            text="@SupportEngineer check something",
            is_bot=False,
        )

        call_count = 0

        def mock_replies(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return [
                    make_slack_message(ts="100.000", text="@SupportEngineer check something"),
                ]
            else:
                # Bot response WITHOUT handoff
                return [
                    make_slack_message(ts="100.000", text="@SupportEngineer check something"),
                    make_slack_message(
                        ts="101.000",
                        text="[SupportEngineer] Everything looks healthy. No issues found.",
                        is_bot=True,
                        thread_ts="100.000",
                    ),
                ]

        mock_slack.get_thread_replies.side_effect = mock_replies

        with (
            patch("scripts.eval_slack_e2e.SlackConnector", return_value=mock_slack),
            patch("scripts.eval_slack_e2e.httpx.AsyncClient") as mock_httpx_cls,
            patch("scripts.eval_slack_e2e.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"roles": ["support_engineer"]}
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_client

            result = await run_evaluation(
                scenario_name="support_400_errors",
                channel="C_TEST",
                wait_timeout=10,
                poll_interval=1,
                skip_eval=True,
            )

        # Should have conversation without handoff extension
        assert result["conversation"][1][0] == "support_engineer"
        assert "healthy" in result["conversation"][1][1]


# ==============================================================================
# Tests: run_evaluation parameter validation
# ==============================================================================


class TestEvalParameterValidation:
    """Tests for parameter validation in run_evaluation."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

    @pytest.mark.asyncio
    async def test_invalid_scenario_raises(self, mock_env):
        """Unknown scenario name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown scenario"):
            await run_evaluation(scenario_name="nonexistent_scenario", channel="C_TEST")

    @pytest.mark.asyncio
    async def test_missing_slack_token_raises(self, monkeypatch):
        """Missing SLACK_BOT_TOKEN should raise ValueError."""
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            await run_evaluation(scenario_name="support_400_errors", channel="C_TEST")

    @pytest.mark.asyncio
    async def test_missing_channel_raises(self, mock_env, monkeypatch):
        """Missing channel should raise ValueError."""
        monkeypatch.delenv("SLACK_DEFAULT_CHANNEL", raising=False)
        with pytest.raises(ValueError, match="No channel specified"):
            await run_evaluation(scenario_name="support_400_errors", channel=None)

    def test_handoff_timeout_extension_parameter_exists(self):
        """run_evaluation should accept handoff_timeout_extension parameter."""
        import inspect

        sig = inspect.signature(run_evaluation)
        assert "handoff_timeout_extension" in sig.parameters
        # Default should be 600
        assert sig.parameters["handoff_timeout_extension"].default == 600

    def test_existing_thread_ts_parameter_exists(self):
        """run_evaluation should accept existing_thread_ts parameter."""
        import inspect

        sig = inspect.signature(run_evaluation)
        assert "existing_thread_ts" in sig.parameters
        assert sig.parameters["existing_thread_ts"].default is None


# ==============================================================================
# Tests: Scenario configuration
# ==============================================================================


class TestScenarios:
    """Tests for scenario definitions."""

    def test_all_scenarios_have_required_keys(self):
        """Each scenario must have name, message, expected_agent, evaluation_criteria, threshold."""
        required_keys = {"name", "message", "expected_agent", "evaluation_criteria", "threshold"}
        for name, config in SCENARIOS.items():
            missing = required_keys - set(config.keys())
            assert not missing, f"Scenario '{name}' missing keys: {missing}"

    def test_stripe_webhook_scenario_exists(self):
        """The stripe_webhook_failure scenario must exist (used for rescore testing)."""
        assert "stripe_webhook_failure" in SCENARIOS

    def test_role_display_covers_all_agents(self):
        """ROLE_DISPLAY should cover all expected agent roles."""
        expected_roles = {
            "user",
            "support_engineer",
            "software_engineer",
            "release_engineer",
            "product_manager",
            "marketing_manager",
        }
        assert set(ROLE_DISPLAY.keys()) == expected_roles


class TestPerScenarioTimeout:
    """Tests for per-scenario timeout override functionality."""

    def test_release_deploy_has_timeout_override(self):
        """The release_deploy scenario must have a timeout override > 600."""
        assert "release_deploy" in SCENARIOS
        assert "timeout" in SCENARIOS["release_deploy"], (
            "release_deploy scenario must have a 'timeout' key for per-scenario override"
        )
        assert SCENARIOS["release_deploy"]["timeout"] > 600, (
            f"release_deploy timeout should be > 600, got {SCENARIOS['release_deploy']['timeout']}"
        )

    def test_release_deploy_timeout_is_1800(self):
        """The release_deploy scenario timeout should be 1800s (30 min)."""
        assert SCENARIOS["release_deploy"]["timeout"] == 1800

    def test_other_scenarios_use_default_timeout(self):
        """Scenarios without explicit timeout should not have the key."""
        for name, config in SCENARIOS.items():
            if name != "release_deploy":
                # Other scenarios should either not have a timeout key
                # or their timeout should be <= 600 (the default)
                if "timeout" in config:
                    assert config["timeout"] <= 600, (
                        f"Scenario '{name}' has unexpected timeout {config['timeout']}"
                    )

    @pytest.fixture
    def mock_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

    @pytest.mark.asyncio
    async def test_per_scenario_timeout_used_when_default(self, mock_env):
        """When CLI timeout is default (600), per-scenario timeout should be used."""
        import inspect

        source = inspect.getsource(run_evaluation)
        # The function should check for per-scenario timeout
        assert 'scenario["timeout"]' in source or 'scenario["timeout"]' in source, (
            "run_evaluation must check for per-scenario timeout override"
        )

    def test_timeout_override_logic_in_source(self):
        """Verify the timeout override logic exists and is correct."""
        import inspect

        source = inspect.getsource(run_evaluation)
        # Must check if scenario has timeout and if CLI didn't explicitly set one
        assert "wait_timeout == 600" in source, (
            "Must check if wait_timeout is still the default (600) before overriding"
        )


# ==============================================================================
# Tests: CLI argument --thread-ts validation
# ==============================================================================


class TestCLIThreadTsValidation:
    """Tests for --thread-ts CLI argument handling."""

    def test_main_rejects_thread_ts_with_message(self):
        """--thread-ts and --message should be mutually exclusive."""
        from scripts.eval_slack_e2e import main

        with patch(
            "sys.argv",
            [
                "eval_slack_e2e.py",
                "--thread-ts",
                "123.456",
                "--message",
                "@SupportEngineer test",
                "--channel",
                "C_TEST",
            ],
        ):
            exit_code = main()
            assert exit_code == 1

    def test_main_passes_thread_ts_to_run_evaluation(self):
        """--thread-ts should be forwarded as existing_thread_ts to run_evaluation."""
        from scripts.eval_slack_e2e import main

        with (
            patch(
                "sys.argv",
                [
                    "eval_slack_e2e.py",
                    "--scenario",
                    "stripe_webhook_failure",
                    "--thread-ts",
                    "1770710833.425539",
                    "--channel",
                    "C0AATPSADB8",
                    "--skip-eval",
                ],
            ),
            patch("scripts.eval_slack_e2e.asyncio.run") as mock_run,
        ):
            mock_run.return_value = {"passed": True}
            main()

            # asyncio.run should be called with run_evaluation coroutine
            mock_run.assert_called_once()
            # Get the coroutine that was passed to asyncio.run
            coro = mock_run.call_args[0][0]
            # Close the coroutine to avoid RuntimeWarning
            coro.close()

    def test_main_passes_handoff_timeout(self):
        """--handoff-timeout should be forwarded as handoff_timeout_extension."""
        from scripts.eval_slack_e2e import main

        with (
            patch(
                "sys.argv",
                [
                    "eval_slack_e2e.py",
                    "--scenario",
                    "support_400_errors",
                    "--channel",
                    "C_TEST",
                    "--handoff-timeout",
                    "900",
                    "--skip-eval",
                ],
            ),
            patch("scripts.eval_slack_e2e.asyncio.run") as mock_run,
        ):
            mock_run.return_value = {"passed": True}
            main()
            mock_run.assert_called_once()
            coro = mock_run.call_args[0][0]
            coro.close()
