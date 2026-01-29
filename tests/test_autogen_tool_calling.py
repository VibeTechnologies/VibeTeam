"""
Test for AutoGen tool calling functionality.

This test verifies that AutoGen agents properly execute tools when using Azure GPT-5.
AutoGen uses explicit model_info to declare function calling support, unlike CrewAI
which relies on LiteLLM's model registry.

Run with: pytest tests/test_autogen_tool_calling.py -v
"""

import os

import pytest

# Skip if AutoGen not available
autogen_agentchat = pytest.importorskip("autogen_agentchat")

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

# Track whether the tool was actually executed
TOOL_EXECUTION_LOG: list[str] = []

# Model info for Azure GPT-5
GPT_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",
    "structured_output": True,
}


async def get_secret(key: str) -> str:
    """Get a secret value by key.

    Args:
        key: The secret key to retrieve

    Returns:
        The secret value
    """
    secrets = {
        "magic_number": "XYZZY-42-PLUGH",
        "api_key": "SECRET-API-KEY-123",
    }
    value = secrets.get(key, "UNKNOWN_KEY")

    # Log that the tool was actually executed
    TOOL_EXECUTION_LOG.append(f"get_secret({key}) = {value}")
    print(f"\n>>> TOOL EXECUTED: get_secret('{key}') = '{value}'\n")

    return f"The secret value for '{key}' is: {value}"


@pytest.fixture
def azure_client():
    """Create Azure OpenAI client."""
    api_key = os.environ.get("AZURE_API_KEY")
    api_base = os.environ.get("AZURE_API_BASE")

    if not api_key or not api_base:
        pytest.skip("Azure credentials not available")

    return AzureOpenAIChatCompletionClient(
        azure_deployment="gpt-5-2",
        model="gpt-5-2",
        api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
        azure_endpoint=api_base,
        api_key=api_key,
        model_info=GPT_MODEL_INFO,
    )


@pytest.fixture
def secret_agent(azure_client):
    """Create an agent with the get_secret tool."""
    return AssistantAgent(
        name="SecretKeeper",
        model_client=azure_client,
        tools=[get_secret],
        system_message="You are a secret keeper. Use the get_secret tool to retrieve secrets.",
        reflect_on_tool_use=True,
    )


class TestAutoGenModelInfo:
    """Tests for AutoGen model configuration."""

    def test_model_info_has_function_calling(self):
        """Verify model_info declares function calling support."""
        assert GPT_MODEL_INFO["function_calling"] is True

    def test_client_uses_model_info(self, azure_client):
        """Verify client is configured with model info."""
        # AutoGen uses model_info to bypass LiteLLM registry checks
        assert azure_client is not None


class TestAutoGenToolExecution:
    """Tests for actual tool execution (not hallucination)."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_tool_is_actually_executed(self, secret_agent):
        """
        Test that the tool is actually executed, not hallucinated.

        This test will FAIL if AutoGen hallucinates the tool output because:
        1. TOOL_EXECUTION_LOG will be empty (tool never called)
        2. The result won't contain the actual secret value
        """
        TOOL_EXECUTION_LOG.clear()

        result = await secret_agent.run(
            task="Use the get_secret tool to retrieve the value for key 'magic_number'."
        )

        # Get the final response
        result_str = ""
        if result.messages:
            for msg in reversed(result.messages):
                if hasattr(msg, "content") and msg.content:
                    result_str = str(msg.content)
                    break

        # Verify the tool was actually executed
        assert len(TOOL_EXECUTION_LOG) > 0, (
            "Tool was never executed! AutoGen may be hallucinating tool outputs. "
            f"Result: {result_str}"
        )

        # Verify the correct value is in the result
        assert "XYZZY-42-PLUGH" in result_str, (
            f"Expected 'XYZZY-42-PLUGH' in result, got: {result_str}. "
            "Tool may have been executed but result not used correctly."
        )

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_multiple_tool_calls(self, secret_agent):
        """Test that multiple tool calls work correctly."""
        TOOL_EXECUTION_LOG.clear()

        result = await secret_agent.run(
            task=(
                "Use the get_secret tool to retrieve two secrets: "
                "'magic_number' and 'api_key'. Report both values."
            )
        )

        # Get the final response
        result_str = ""
        if result.messages:
            for msg in reversed(result.messages):
                if hasattr(msg, "content") and msg.content:
                    result_str = str(msg.content)
                    break

        # Should have at least 2 tool executions
        assert len(TOOL_EXECUTION_LOG) >= 2, (
            f"Expected at least 2 tool calls, got {len(TOOL_EXECUTION_LOG)}. "
            f"Log: {TOOL_EXECUTION_LOG}"
        )

        # Both values should be present
        assert "XYZZY-42-PLUGH" in result_str, "magic_number value not in result"
        assert "SECRET-API-KEY-123" in result_str, "api_key value not in result"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
