"""
OpenCode client for VibeTeam agents.

Uses `opencode run` CLI with JSON output format for agent communication.
Supports session persistence via --session flag.
"""

import json
import subprocess
from dataclasses import dataclass


@dataclass
class OpenCodeResponse:
    """Response from an OpenCode run."""

    text: str
    session_id: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0
    finish_reason: str = "stop"


@dataclass
class OpenCodeClientConfig:
    """Configuration for OpenCode client."""

    opencode_path: str = "opencode"
    timeout: int = 120  # seconds
    format: str = "json"


class OpenCodeClient:
    """
    Client for running OpenCode agents.

    Uses the opencode CLI to run prompts and parse NDJSON responses.

    Example usage:
        client = OpenCodeClient()
        response = client.run("What is 2+2?")
        print(response.text)  # "4"

    With session persistence:
        response1 = client.run("My name is Alice", session_id="user123")
        response2 = client.run("What is my name?", session_id="user123")
        # response2.text will contain "Alice"
    """

    def __init__(self, config: OpenCodeClientConfig | None = None):
        self.config = config or OpenCodeClientConfig()
        self._validate_opencode()

    def _validate_opencode(self) -> None:
        """Check that opencode CLI is available."""
        try:
            result = subprocess.run(
                [self.config.opencode_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError(f"opencode --version failed: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                f"opencode not found at {self.config.opencode_path}. "
                "Install with: npm install -g @anthropic/opencode"
            ) from None

    def run(
        self,
        prompt: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        timeout: int | None = None,
    ) -> OpenCodeResponse:
        """
        Run a prompt through opencode.

        Args:
            prompt: The user message to send
            session_id: Optional session ID for conversation persistence
            system_prompt: Optional system prompt (prepended to user message)
            timeout: Optional timeout in seconds (overrides config)

        Returns:
            OpenCodeResponse with the agent's response
        """
        # Build the command
        cmd = [
            self.config.opencode_path,
            "run",
            "--format",
            self.config.format,
        ]

        # Add session if provided
        if session_id:
            cmd.extend(["--session", session_id])

        # Build the full prompt
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd.append(full_prompt)

        # Run the command
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.config.timeout,
            )
        except subprocess.TimeoutExpired:
            return OpenCodeResponse(
                text="Error: OpenCode request timed out",
                session_id=session_id or "",
                finish_reason="timeout",
            )

        # Parse NDJSON response
        return self._parse_ndjson_response(result.stdout, session_id)

    def _parse_ndjson_response(
        self, output: str, default_session_id: str | None = None
    ) -> OpenCodeResponse:
        """
        Parse NDJSON output from opencode run.

        Expected format:
            {"type":"step_start",...}
            {"type":"text","part":{"text":"response"},...}
            {"type":"step_finish","part":{"reason":"stop","tokens":{...}},...}
        """
        text_parts: list[str] = []
        session_id = default_session_id or ""
        tokens_input = 0
        tokens_output = 0
        cost = 0.0
        finish_reason = "stop"

        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "step_start":
                session_id = event.get("sessionID", session_id)

            elif event_type == "text":
                part = event.get("part", {})
                if text := part.get("text"):
                    text_parts.append(text)

            elif event_type == "step_finish":
                part = event.get("part", {})
                finish_reason = part.get("reason", "stop")
                cost = part.get("cost", 0.0)
                tokens = part.get("tokens", {})
                tokens_input = tokens.get("input", 0)
                tokens_output = tokens.get("output", 0)

        return OpenCodeResponse(
            text="".join(text_parts),
            session_id=session_id,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost=cost,
            finish_reason=finish_reason,
        )

    async def run_async(
        self,
        prompt: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        timeout: int | None = None,
    ) -> OpenCodeResponse:
        """Async version of run using asyncio subprocess."""
        import asyncio

        # Build the command
        cmd = [
            self.config.opencode_path,
            "run",
            "--format",
            self.config.format,
        ]

        if session_id:
            cmd.extend(["--session", session_id])

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd.append(full_prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self.config.timeout,
            )
            output = stdout.decode("utf-8")
        except asyncio.TimeoutError:
            return OpenCodeResponse(
                text="Error: OpenCode request timed out",
                session_id=session_id or "",
                finish_reason="timeout",
            )

        return self._parse_ndjson_response(output, session_id)


def create_client(config: OpenCodeClientConfig | None = None) -> OpenCodeClient:
    """Factory function to create OpenCode client."""
    return OpenCodeClient(config)
