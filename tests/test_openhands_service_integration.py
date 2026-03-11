"""
Integration test for OpenHands service running on localhost.

This starts the OpenHands service with Azure OpenAI credentials and checks that
all agent roles return a response via the HTTP API.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator

import httpx
import pytest


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_error = None

    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)

    raise RuntimeError(f"OpenHands service failed to start: {last_error}")


@pytest.fixture(scope="session")
def openhands_service_url(azure_credentials: dict[str, str]) -> Iterator[str]:
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.update(
        {
            "AZURE_API_KEY": azure_credentials["api_key"],
            "AZURE_API_BASE": azure_credentials["api_base"],
            "AZURE_API_VERSION": azure_credentials.get("api_version", "2024-08-01-preview"),
            # Default to gpt-4.1 locally; CI overrides to gpt-5-mini via env
            "AZURE_OPENAI_DEPLOYMENT": os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
            "PYTHONPATH": f"{os.getcwd()}:{env.get('PYTHONPATH', '')}",
        }
    )

    # Use a temporary SQLite database so the test doesn't need PostgreSQL
    db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_tmp.close()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_tmp.name}"

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "agent_service.openhands.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    log_file = os.path.join(os.path.dirname(__file__), ".openhands_test_server.log")
    log_fh = open(log_file, "w")

    process = subprocess.Popen(
        command,
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_health(base_url)
        yield base_url
    except Exception as err:
        log_fh.flush()
        with open(log_file) as f:
            output = f.read()
        if output:
            raise RuntimeError(f"OpenHands service output:\n{output}") from err
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log_fh.close()
        # Print server logs on test exit for debugging
        with open(log_file) as f:
            server_output = f.read()
        if server_output:
            print(f"\n=== OpenHands Server Logs ===\n{server_output}\n=== End Server Logs ===")
        # Clean up temp SQLite database
        try:
            os.unlink(db_tmp.name)
        except OSError:
            pass


ALL_ROLES = [
    "software_engineer",
    "release_engineer",
    "support_engineer",
    "product_manager",
    "marketing_manager",
]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ALL_ROLES)
async def test_openhands_agent_responds(openhands_service_url: str, role: str) -> None:
    """Verify a single agent role responds via the HTTP service."""
    # Payload mirrors what the Slack gateway sends (see vibeteam/gateway/server.py
    # call_agent_service) so the test exercises the same code-path.
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {
            "task": f"Reply with 'READY {role}' in one short sentence.",
            "role": role,
            "context_type": "slack",
            "context_id": f"C0TEST:{role}",
            "use_tools": True,
        }
        response = await client.post(f"{openhands_service_url}/run", json=payload)
        if response.status_code != 200:
            detail = response.text
            pytest.fail(f"Role '{role}' returned HTTP {response.status_code}: {detail}")
        data = response.json()

        agent_response = data.get("response", "")
        session_key = data.get("session_key", "")
        agents_used = data.get("agents_used", [])
        latency = data.get("metadata", {}).get("latency_ms", "?")

        # --- Print the actual agent response so it's visible in test output ---
        print(f"\n{'=' * 60}")
        print(f"  Agent: {role}")
        print(f"  Latency: {latency} ms")
        print(f"  Session: {session_key}")
        print(f"  Response: {agent_response}")
        print(f"{'=' * 60}")

        assert agent_response, f"No response from {role}"
        assert session_key.startswith(
            f"openhands:{role}:",
        ), f"Unexpected session key for {role}: {session_key}"
        assert role in agents_used, f"Role not in agents_used: {role}"
