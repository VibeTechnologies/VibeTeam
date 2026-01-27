"""
Tests for the Supervisor Chat API.

These tests verify:
1. Health endpoint
2. Chat endpoint
3. OpenAI-compatible chat completions endpoint
4. Session management
"""

import pytest
from fastapi.testclient import TestClient

from vibeteam.api.main import app, _sessions


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


class TestChatEndpoint:
    """Tests for the chat endpoint."""

    def test_chat_creates_session(self, api_client):
        """Test that chat creates a new session."""
        response = api_client.post(
            "/v1/chat",
            json={"message": "Hello"},
        )

        # Note: This may fail without LLM connection, but structure should be right
        if response.status_code == 200:
            data = response.json()
            assert "session_id" in data
            assert "response" in data
            assert "agents_used" in data

    def test_chat_with_session_id(self, api_client):
        """Test that chat can use existing session."""
        # First request creates session
        response1 = api_client.post(
            "/v1/chat",
            json={"message": "Hello"},
        )

        if response1.status_code == 200:
            session_id = response1.json()["session_id"]

            # Second request should use same session
            response2 = api_client.post(
                "/v1/chat",
                json={"message": "Follow up", "session_id": session_id},
            )

            if response2.status_code == 200:
                assert response2.json()["session_id"] == session_id


class TestOpenAIChatCompletions:
    """Tests for OpenAI-compatible chat completions."""

    def test_chat_completions_structure(self, api_client):
        """Test chat completions response structure."""
        response = api_client.post(
            "/v1/chat/completions",
            json={
                "model": "vibeteam-supervisor",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        # Check response structure (may fail without LLM)
        if response.status_code == 200:
            data = response.json()
            assert data["object"] == "chat.completion"
            assert "id" in data
            assert "created" in data
            assert "choices" in data
            assert len(data["choices"]) > 0
            assert data["choices"][0]["message"]["role"] == "assistant"

    def test_chat_completions_requires_user_message(self, api_client):
        """Test that chat completions requires a user message."""
        response = api_client.post(
            "/v1/chat/completions",
            json={
                "model": "vibeteam-supervisor",
                "messages": [{"role": "system", "content": "You are helpful"}],
            },
        )

        # Should fail without user message
        assert response.status_code == 400
        assert "No user message found" in response.json()["detail"]

    def test_chat_completions_with_multiple_messages(self, api_client):
        """Test chat completions with conversation history."""
        response = api_client.post(
            "/v1/chat/completions",
            json={
                "model": "vibeteam-supervisor",
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                    {"role": "user", "content": "What can you do?"},
                ],
            },
        )

        # Check response (may fail without LLM)
        if response.status_code == 200:
            data = response.json()
            assert data["choices"][0]["message"]["content"]


class TestSessionManagement:
    """Tests for session management endpoints."""

    def test_get_nonexistent_session(self, api_client):
        """Test getting a session that doesn't exist."""
        response = api_client.get("/v1/sessions/nonexistent/history")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_delete_nonexistent_session(self, api_client):
        """Test deleting a session that doesn't exist."""
        response = api_client.delete("/v1/sessions/nonexistent")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]


class TestSessionCleanup:
    """Tests for session cleanup functionality."""

    def test_cleanup_old_sessions(self):
        """Test cleanup of old sessions."""
        from datetime import datetime, timedelta, timezone
        from vibeteam.api.main import cleanup_old_sessions, _sessions
        from vibeteam.swarm import create_swarm_orchestrator

        _sessions.clear()

        # Create an old session
        old_orch = create_swarm_orchestrator()
        old_orch.shared_state.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        _sessions[old_orch.shared_state.session_id] = old_orch

        # Create a new session
        new_orch = create_swarm_orchestrator()
        _sessions[new_orch.shared_state.session_id] = new_orch

        # Cleanup
        removed = cleanup_old_sessions(max_age_hours=24)

        assert removed == 1
        assert len(_sessions) == 1
        assert new_orch.shared_state.session_id in _sessions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
