"""
E2E tests for agent microservices.

Tests health endpoints and basic task execution via kubectl port-forward.
"""

import subprocess
import time

import httpx
import pytest


def port_forward(service: str, local_port: int, remote_port: int = 8080) -> subprocess.Popen:
    """Start kubectl port-forward and return the process."""
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{service}",
            f"{local_port}:{remote_port}",
            "-n",
            "vibeteam",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    return proc


class TestAgentServices:
    """Test agent microservices are deployed and responding."""

    def test_postgres_running(self):
        """Verify PostgreSQL is running."""
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "-n",
                "vibeteam",
                "postgres-0",
                "--",
                "pg_isready",
                "-U",
                "vibeteam",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"PostgreSQL not ready: {result.stderr}"

    def test_autogen_health(self):
        """Test AutoGen service health endpoint."""
        proc = port_forward("autogen-svc", 18080)
        try:
            time.sleep(2)
            response = httpx.get("http://localhost:18080/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["framework"] == "autogen"
        finally:
            proc.terminate()

    def test_crewai_health(self):
        """Test CrewAI service health endpoint."""
        proc = port_forward("crewai-svc", 18081)
        try:
            time.sleep(2)
            response = httpx.get("http://localhost:18081/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["framework"] == "crewai"
        finally:
            proc.terminate()

    def test_scheduler_health(self):
        """Test Scheduler service health endpoint."""
        proc = port_forward("scheduler-svc", 18082)
        try:
            time.sleep(2)
            response = httpx.get("http://localhost:18082/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["scheduler_running"] is True
        finally:
            proc.terminate()

    def test_scheduler_list_tasks(self):
        """Test scheduler can list tasks."""
        proc = port_forward("scheduler-svc", 18083)
        try:
            time.sleep(2)
            response = httpx.get("http://localhost:18083/tasks", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert "tasks" in data
            assert "count" in data
        finally:
            proc.terminate()


class TestAgentExecution:
    """Test actual agent task execution."""

    @pytest.mark.slow
    def test_autogen_run_simple_task(self):
        """Test AutoGen can execute a simple task."""
        proc = port_forward("autogen-svc", 18084)
        try:
            time.sleep(2)
            response = httpx.post(
                "http://localhost:18084/run",
                json={
                    "task": "What is 2 + 2? Reply with just the number.",
                    "context_type": "test",
                    "context_id": "e2e-test",
                },
                timeout=60,
            )
            assert response.status_code == 200
            data = response.json()
            assert "response" in data
            assert "session_id" in data
        finally:
            proc.terminate()

    @pytest.mark.slow
    def test_scheduler_schedule_task(self):
        """Test scheduling a future task."""
        proc = port_forward("scheduler-svc", 18085)
        try:
            time.sleep(2)
            response = httpx.post(
                "http://localhost:18085/tasks",
                json={
                    "task": "Test task from e2e",
                    "delay_minutes": 60,
                    "agent_service": "autogen-svc",
                    "context_type": "test",
                },
                timeout=10,
            )
            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "scheduled"

            # Clean up - cancel the task
            job_id = data["job_id"]
            httpx.delete(f"http://localhost:18085/tasks/{job_id}", timeout=10)
        finally:
            proc.terminate()


class TestGateway:
    """Test the VibeTeam Gateway service."""

    def test_gateway_health(self):
        """Test Gateway health endpoint with downstream service status."""
        proc = port_forward("vibeteam-gateway", 18090)
        try:
            time.sleep(2)
            response = httpx.get("http://localhost:18090/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "vibeteam-gateway"
            assert "services" in data
            # Gateway should report downstream service status
            assert "autogen-svc" in data["services"]
            assert "crewai-svc" in data["services"]
            assert "scheduler-svc" in data["services"]
        finally:
            proc.terminate()

    def test_gateway_api_run(self):
        """Test Gateway API run endpoint routes to agent service."""
        proc = port_forward("vibeteam-gateway", 18091)
        try:
            time.sleep(2)
            response = httpx.post(
                "http://localhost:18091/api/run",
                json={
                    "task": "What is 2 + 2? Reply with just the number.",
                    "context_type": "test",
                    "context_id": "gateway-e2e",
                },
                timeout=120,
            )
            assert response.status_code == 200
            data = response.json()
            assert "response" in data
            assert "session_id" in data
            assert data["framework"] in ["autogen", "crewai"]
        finally:
            proc.terminate()

    def test_gateway_api_sessions(self):
        """Test Gateway API can list sessions."""
        proc = port_forward("vibeteam-gateway", 18092)
        try:
            time.sleep(2)
            response = httpx.get(
                "http://localhost:18092/api/sessions",
                timeout=30,
            )
            assert response.status_code == 200
            data = response.json()
            assert "sessions" in data
            assert "count" in data
        finally:
            proc.terminate()

    def test_gateway_api_tasks(self):
        """Test Gateway API can list scheduled tasks."""
        proc = port_forward("vibeteam-gateway", 18093)
        try:
            time.sleep(2)
            response = httpx.get(
                "http://localhost:18093/api/tasks",
                timeout=30,
            )
            assert response.status_code == 200
            data = response.json()
            assert "tasks" in data
            assert "count" in data
        finally:
            proc.terminate()

    def test_gateway_github_webhook_ignored(self):
        """Test Gateway handles unknown GitHub events gracefully."""
        proc = port_forward("vibeteam-gateway", 18094)
        try:
            time.sleep(2)
            response = httpx.post(
                "http://localhost:18094/webhook",
                json={"action": "unknown", "repository": {"full_name": "test/repo"}},
                headers={
                    "X-GitHub-Event": "ping",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ignored"
        finally:
            proc.terminate()

    def test_gateway_slack_url_verification(self):
        """Test Gateway responds to Slack URL verification challenge."""
        proc = port_forward("vibeteam-gateway", 18095)
        try:
            time.sleep(2)
            response = httpx.post(
                "http://localhost:18095/slack/events",
                json={
                    "type": "url_verification",
                    "challenge": "test-challenge-123",
                },
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["challenge"] == "test-challenge-123"
        finally:
            proc.terminate()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
