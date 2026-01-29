"""
Test for CrewAI tool calling fix (Issue #39).

This test verifies that CrewAI agents properly execute tools instead of
hallucinating their outputs when using Azure GPT-5.

Run with: pytest tests/test_crewai_tool_calling.py -v
"""

import os

import pytest

# Skip if CrewAI not available
crewai = pytest.importorskip("crewai")

from crewai import Agent, Crew, Process, Task
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from agents.crewai.llm import AzureFunctionCallingLLM

# Track whether the tool was actually executed
TOOL_EXECUTION_LOG: list[str] = []


class GetSecretInput(BaseModel):
    """Input schema for get_secret tool."""

    key: str = Field(..., description="The secret key to retrieve")


class GetSecretTool(BaseTool):
    """Tool that retrieves a secret value."""

    name: str = "get_secret"
    description: str = "Get a secret value by key. Returns the secret value."
    args_schema: type[BaseModel] = GetSecretInput

    def _run(self, key: str) -> str:
        """Execute the tool - this MUST be called for the test to pass."""
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
def azure_llm():
    """Create Azure LLM with function calling support."""
    api_key = os.environ.get("AZURE_API_KEY")
    api_base = os.environ.get("AZURE_API_BASE")

    if not api_key or not api_base:
        pytest.skip("Azure credentials not available")

    return AzureFunctionCallingLLM(
        model="azure/gpt-5-2",
        provider="litellm",
        api_base=api_base,
        api_key=api_key,
        api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
    )


@pytest.fixture
def secret_agent(azure_llm):
    """Create an agent with the GetSecretTool."""
    return Agent(
        role="Secret Keeper",
        goal="Retrieve secrets using the get_secret tool.",
        backstory="You are a secret keeper who retrieves secrets. Always use the get_secret tool to retrieve secrets.",
        tools=[GetSecretTool()],
        llm=azure_llm,
        verbose=True,
    )


class TestAzureFunctionCallingLLM:
    """Tests for the AzureFunctionCallingLLM wrapper."""

    def test_supports_function_calling_returns_true(self, azure_llm):
        """Verify the wrapper forces function calling support."""
        assert azure_llm.supports_function_calling() is True

    def test_standard_llm_returns_false(self):
        """Verify the standard LLM returns False for gpt-5-2."""
        from crewai.llm import LLM

        api_key = os.environ.get("AZURE_API_KEY")
        api_base = os.environ.get("AZURE_API_BASE")

        if not api_key or not api_base:
            pytest.skip("Azure credentials not available")

        llm = LLM(
            model="azure/gpt-5-2",
            provider="litellm",
            api_base=api_base,
            api_key=api_key,
        )
        # This should return False because gpt-5-2 isn't in LiteLLM's registry
        assert llm.supports_function_calling() is False


class TestCrewAIToolExecution:
    """Tests for actual tool execution (not hallucination)."""

    @pytest.mark.slow
    def test_tool_is_actually_executed(self, secret_agent):
        """
        Test that the tool is actually executed, not hallucinated.

        This test will FAIL if CrewAI hallucinates the tool output because:
        1. TOOL_EXECUTION_LOG will be empty (tool never called)
        2. The result won't contain the actual secret value
        """
        TOOL_EXECUTION_LOG.clear()

        task = Task(
            description="Use the get_secret tool to retrieve the value for key 'magic_number'.",
            agent=secret_agent,
            expected_output="The secret value for magic_number",
        )

        crew = Crew(
            agents=[secret_agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff()
        result_str = str(result)

        # Verify the tool was actually executed
        assert (
            len(TOOL_EXECUTION_LOG) > 0
        ), f"Tool was never executed! CrewAI is hallucinating tool outputs. Result: {result_str}"

        # Verify the correct value is in the result
        assert "XYZZY-42-PLUGH" in result_str, (
            f"Expected 'XYZZY-42-PLUGH' in result, got: {result_str}. "
            "Tool may have been executed but result not used correctly."
        )

    @pytest.mark.slow
    def test_multiple_tool_calls(self, secret_agent):
        """Test that multiple tool calls work correctly."""
        TOOL_EXECUTION_LOG.clear()

        task = Task(
            description=(
                "Use the get_secret tool to retrieve two secrets: "
                "'magic_number' and 'api_key'. Report both values."
            ),
            agent=secret_agent,
            expected_output="Both secret values",
        )

        crew = Crew(
            agents=[secret_agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff()
        result_str = str(result)

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
