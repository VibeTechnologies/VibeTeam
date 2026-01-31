"""
Tests for the Supervisor Chat API.

NOTE: The API is deprecated and now returns 501 for most endpoints.
These tests verify the deprecation behavior and remaining working endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from vibeteam.api.main import _sessions, app


@pytest.fixture
def api_client():
    """Create a test client for the API."""
    # Clear sessions before each test
    _sessions.clear()
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health endpoint."""

    def test_health_returns_ok(self, api_client):
        """Test health endpoint returns 200."""
        response = api_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "vibeteam-supervisor"
        assert "timestamp" in data

    def test_health_includes_version(self, api_client):
        """Test health endpoint includes version."""
        response = api_client.get("/health")
        data = response.json()

        assert "version" in data


class TestModelsEndpoint:
    """Tests for the models list endpoint."""

    def test_list_models(self, api_client):
        """Test listing available models."""
        response = api_client.get("/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "vibeteam-supervisor"
        assert data["data"][0]["owned_by"] == "vibeteam"


class TestDeprecatedEndpoints:
    """Tests for deprecated endpoints - should return 501."""

    def test_chat_returns_501(self, api_client):
        """Test that chat endpoint is deprecated."""
        response = api_client.post(
            "/v1/chat",
            json={"message": "Hello"},
        )

        assert response.status_code == 501
        assert "deprecated" in response.json()["detail"].lower()

    def test_chat_completions_returns_501(self, api_client):
        """Test that chat completions endpoint is deprecated."""
        response = api_client.post(
            "/v1/chat/completions",
            json={
                "model": "vibeteam-supervisor",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 501
        assert "deprecated" in response.json()["detail"].lower()

    def test_session_history_returns_501(self, api_client):
        """Test that session history endpoint is deprecated."""
        response = api_client.get("/v1/sessions/any-session/history")

        assert response.status_code == 501
        assert "deprecated" in response.json()["detail"].lower()

    def test_delete_session_returns_501(self, api_client):
        """Test that delete session endpoint is deprecated."""
        response = api_client.delete("/v1/sessions/any-session")

        assert response.status_code == 501
        assert "deprecated" in response.json()["detail"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
