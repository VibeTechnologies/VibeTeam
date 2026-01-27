import asyncio
import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from vibeteam.webhook.server import app, handle_sentry_webhook

# Mock data
MOCK_SENTRY_PAYLOAD = {
    "action": "created",
    "data": {
        "issue": {
            "id": "12345",
            "shortId": "WEB-123",
            "title": "TypeError: Cannot read property 'id' of undefined",
            "project": {"slug": "vibeteam"},
            "level": "error",
            "count": 100,
            "userCount": 20,
            "firstSeen": "2023-01-01T00:00:00Z",
            "lastSeen": "2023-01-01T01:00:00Z",
            "permalink": "https://sentry.io/organizations/vibeteam/issues/12345/",
            "culprit": "auth.py",
        }
    },
}


@pytest.mark.asyncio
async def test_handle_sentry_webhook_valid_bug():
    """Test routing a valid bug to the Release Engineer agent."""
    with (
        patch("vibeteam.webhook.server.verify_sentry_signature", return_value=True),
        patch("vibeteam.webhook.server.run_release_engineer_agent") as mock_run_agent,
    ):
        # Create a mock request
        mock_request = MagicMock()

        # Mock awaitable body()
        async def get_body():
            return json.dumps(MOCK_SENTRY_PAYLOAD).encode()

        mock_request.body = get_body

        # Call the handler
        response = await handle_sentry_webhook(
            request=mock_request, sentry_hook_signature="mock_signature"
        )

        # Verify response
        assert response["status"] == "accepted"
        assert response["classification"] == "VALID_BUG"

        # Verify agent was called
        mock_run_agent.assert_called_once()
        args = mock_run_agent.call_args[0]
        assert args[0]["shortId"] == "WEB-123"
        assert args[1] == "VALID_BUG"


@pytest.mark.asyncio
async def test_handle_sentry_webhook_noise():
    """Test filtering noise."""
    import copy

    noise_payload = copy.deepcopy(MOCK_SENTRY_PAYLOAD)
    noise_payload["data"]["issue"]["title"] = "NetworkError: Failed to fetch"
    noise_payload["data"]["issue"]["count"] = 1
    noise_payload["data"]["issue"]["userCount"] = 1

    with (
        patch("vibeteam.webhook.server.verify_sentry_signature", return_value=True),
        patch("vibeteam.webhook.server.run_release_engineer_agent") as mock_run_agent,
    ):
        # Create a mock request
        mock_request = MagicMock()

        # Mock awaitable body()
        async def get_body():
            return json.dumps(noise_payload).encode()

        mock_request.body = get_body

        # Call the handler
        response = await handle_sentry_webhook(
            request=mock_request, sentry_hook_signature="mock_signature"
        )

        # Verify response
        assert response["status"] == "skipped"
        assert response["reason"] == "noise"

        # Verify agent was NOT called
        mock_run_agent.assert_not_called()
