from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from vibeteam.gateway import server as gateway_server


def _http_status_error(status_code: int, detail: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://openhands-svc:8080/run")
    response = httpx.Response(status_code, request=request, text=detail)
    return httpx.HTTPStatusError(
        f"{status_code} error",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
async def test_call_agent_service_retries_transient_status_then_succeeds():
    client = Mock()
    success_response = Mock()
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {"response": "ok"}
    client.post = AsyncMock(
        side_effect=[
            _http_status_error(503, "The AI service is temporarily overloaded"),
            success_response,
        ]
    )

    with (
        patch("vibeteam.gateway.server.get_http_client", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await gateway_server.call_agent_service(
            task="test task",
            role="support_engineer",
            context_type="slack",
            context_id="C_TEST:ts_1",
        )

    assert result.get("response") == "ok"
    assert client.post.await_count == 2


@pytest.mark.asyncio
async def test_call_agent_service_returns_overload_error_after_retry_budget():
    client = Mock()
    client.post = AsyncMock(
        side_effect=[
            _http_status_error(503, "The AI service is temporarily overloaded"),
            _http_status_error(503, "The AI service is temporarily overloaded"),
            _http_status_error(503, "The AI service is temporarily overloaded"),
        ]
    )

    with (
        patch("vibeteam.gateway.server.get_http_client", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await gateway_server.call_agent_service(
            task="test task",
            role="support_engineer",
            context_type="slack",
            context_id="C_TEST:ts_1",
        )

    assert "temporarily overloaded" in result.get("error", "").lower()
    assert client.post.await_count == 3


@pytest.mark.asyncio
async def test_call_agent_service_async_retries_transient_status_then_accepts():
    client = Mock()
    accepted = Mock()
    accepted.raise_for_status.return_value = None
    accepted.json.return_value = {"job_id": "job-123", "status": "accepted"}
    client.post = AsyncMock(
        side_effect=[
            _http_status_error(429, "Too Many Requests"),
            accepted,
        ]
    )

    with (
        patch("vibeteam.gateway.server.get_http_client", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await gateway_server.call_agent_service_async(
            task="test task",
            role="release_engineer",
            context_type="slack",
            context_id="C_TEST:ts_1",
            callback_url="http://vibeteam-gateway:8080/callback/agent",
        )

    assert result.get("status") == "accepted"
    assert result.get("job_id") == "job-123"
    assert client.post.await_count == 2
