"""
Custom LLM wrappers for CrewAI with Azure OpenAI.

This module provides LLM classes that work around issues with LiteLLM's
model registry not recognizing Azure GPT-5 models.
"""

try:
    from crewai.llm import LLM

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    LLM = object  # type: ignore


class AzureFunctionCallingLLM(LLM if CREWAI_AVAILABLE else object):  # type: ignore
    """
    Custom LLM wrapper that forces function calling support for Azure GPT-5.

    Problem:
        LiteLLM's model registry doesn't include 'gpt-5-2', causing
        `supports_function_calling()` to return False. This makes CrewAI fall
        back to ReAct-style prompting, where the model outputs:

            Thought: I need to call the tool
            Action: tool_name
            Action Input: {"key": "value"}
            Observation: <model continues and hallucinates the result>

        The model should stop at '\nObservation:' but GPT-5 ignores the stop
        sequence and hallucinates the tool output instead of letting CrewAI
        execute the actual tool.

    Solution:
        Override `supports_function_calling()` to return True, forcing CrewAI
        to use native function calling via LiteLLM's `tools` parameter.

    Usage:
        ```python
        llm = AzureFunctionCallingLLM(
            model="azure/gpt-5-2",
            provider="litellm",
            api_base=os.environ["AZURE_API_BASE"],
            api_key=os.environ["AZURE_API_KEY"],
        )
        agent = Agent(role="...", llm=llm, tools=[...])
        ```

    See: https://github.com/VibeTechnologies/VibeTeam/issues/39
    """

    def supports_function_calling(self) -> bool:
        """Force function calling mode for Azure GPT-5."""
        return True


__all__ = ["AzureFunctionCallingLLM", "CREWAI_AVAILABLE"]
