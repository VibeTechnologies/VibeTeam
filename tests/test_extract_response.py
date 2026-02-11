"""
Tests for the shared extract_response_from_events utility.

Covers:
- FinishAction with message
- FinishAction with thought fallback
- AgentFinishAction
- MessageEvent with source=="agent"
- Empty events list
- Events with no matching types
- Priority: FinishAction over MessageEvent (when FinishAction is more recent)
- Mixed events where MessageEvent is more recent than FinishAction
"""

from __future__ import annotations

from agent_service.openhands.utils import extract_response_from_events

# ---------------------------------------------------------------------------
# Helper stubs - mimic OpenHands event types without importing them
# ---------------------------------------------------------------------------


class FakeContentBlock:
    """Mimic an LLM content block with a .text attribute."""

    def __init__(self, text: str = ""):
        self.text = text


class FakeLlmMessage:
    """Mimic an LLM message with a list of content blocks."""

    def __init__(self, content: list[FakeContentBlock] | None = None):
        self.content = content or []


class FakeMessageEvent:
    """Mimic openhands MessageEvent."""

    __name__ = "MessageEvent"

    def __init__(self, source: str, text: str = ""):
        self.source = source
        self.llm_message = FakeLlmMessage([FakeContentBlock(text)]) if text else None


# Give FakeMessageEvent the class name the code checks
FakeMessageEvent.__qualname__ = "MessageEvent"


class FakeFinishAction:
    """Mimic openhands FinishAction."""

    def __init__(self, message: str = "", thought: str = ""):
        self.message = message
        self.thought = thought


class FakeAgentFinishAction:
    """Mimic openhands AgentFinishAction."""

    def __init__(self, message: str = "", thought: str = ""):
        self.message = message
        self.thought = thought


class FakeActionEvent:
    """Mimic openhands ActionEvent wrapping an action.

    In the real SDK, ActionEvent has a `thought` field at the event level.
    Actions like TerminalAction don't have thought — it's on the event.
    """

    def __init__(self, action, thought: str = ""):
        self.action = action
        self.thought = thought


class FakeObservationEvent:
    """An event type that should be ignored by extraction."""

    def __init__(self):
        pass


# Patch __name__ at the class level so type().__name__ works
FakeMessageEvent.__name__ = "MessageEvent"
FakeActionEvent.__name__ = "ActionEvent"
FakeFinishAction.__name__ = "FinishAction"
FakeAgentFinishAction.__name__ = "AgentFinishAction"
FakeObservationEvent.__name__ = "ObservationEvent"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractResponseFromEvents:
    """Test the shared extract_response_from_events function."""

    def test_empty_events_returns_empty_string(self):
        assert extract_response_from_events([]) == ""

    def test_finish_action_with_message(self):
        action = FakeFinishAction(message="Task completed successfully.")
        event = FakeActionEvent(action)
        result = extract_response_from_events([event])
        assert result == "Task completed successfully."

    def test_finish_action_thought_fallback(self):
        """When message is empty, fall back to thought."""
        action = FakeFinishAction(message="", thought="I finished the investigation.")
        event = FakeActionEvent(action)
        result = extract_response_from_events([event])
        assert result == "I finished the investigation."

    def test_agent_finish_action_with_message(self):
        action = FakeAgentFinishAction(message="Deployment completed.")
        event = FakeActionEvent(action)
        result = extract_response_from_events([event])
        assert result == "Deployment completed."

    def test_agent_finish_action_thought_fallback(self):
        action = FakeAgentFinishAction(message="", thought="Done with analysis.")
        event = FakeActionEvent(action)
        result = extract_response_from_events([event])
        assert result == "Done with analysis."

    def test_message_event_agent_source(self):
        event = FakeMessageEvent(source="agent", text="Here is my response.")
        result = extract_response_from_events([event])
        assert result == "Here is my response."

    def test_message_event_user_source_ignored(self):
        """MessageEvents from 'user' should be skipped."""
        event = FakeMessageEvent(source="user", text="This is user input.")
        result = extract_response_from_events([event])
        assert result == ""

    def test_message_event_no_llm_message(self):
        """MessageEvent without llm_message should be skipped."""
        event = FakeMessageEvent(source="agent")
        event.llm_message = None
        result = extract_response_from_events([event])
        assert result == ""

    def test_message_event_empty_content(self):
        """MessageEvent with empty content list should be skipped."""
        event = FakeMessageEvent(source="agent")
        event.llm_message = FakeLlmMessage(content=[])
        result = extract_response_from_events([event])
        assert result == ""

    def test_message_event_content_block_no_text(self):
        """Content block with empty text should be skipped."""
        event = FakeMessageEvent(source="agent")
        event.llm_message = FakeLlmMessage(content=[FakeContentBlock(text="")])
        result = extract_response_from_events([event])
        assert result == ""

    def test_finish_action_takes_priority_when_last(self):
        """When FinishAction is the last event, it is returned (reverse iteration)."""
        msg_event = FakeMessageEvent(source="agent", text="Earlier message.")
        action = FakeFinishAction(message="Final answer from finish.")
        action_event = FakeActionEvent(action)

        # FinishAction is last (most recent) - reverse iteration finds it first
        events = [msg_event, action_event]
        result = extract_response_from_events(events)
        assert result == "Final answer from finish."

    def test_message_event_takes_priority_when_last(self):
        """When MessageEvent is the last event, it is returned."""
        action = FakeFinishAction(message="Finish response.")
        action_event = FakeActionEvent(action)
        msg_event = FakeMessageEvent(source="agent", text="Latest agent message.")

        # MessageEvent is last (most recent) - reverse iteration finds it first
        events = [action_event, msg_event]
        result = extract_response_from_events(events)
        assert result == "Latest agent message."

    def test_non_finish_action_event_ignored(self):
        """ActionEvent wrapping a non-Finish action should be skipped."""

        class FakeBrowseAction:
            pass

        FakeBrowseAction.__name__ = "BrowseAction"

        action = FakeBrowseAction()
        event = FakeActionEvent(action)
        result = extract_response_from_events([event])
        assert result == ""

    def test_observation_event_ignored(self):
        """ObservationEvent should be skipped entirely."""
        event = FakeObservationEvent()
        result = extract_response_from_events([event])
        assert result == ""

    def test_action_event_without_action_attribute(self):
        """ActionEvent with action=None should be skipped."""
        event = FakeActionEvent(action=None)
        result = extract_response_from_events([event])
        assert result == ""

    def test_multiple_agent_messages_returns_last(self):
        """With multiple agent MessageEvents, the most recent one wins."""
        msg1 = FakeMessageEvent(source="agent", text="First response.")
        msg2 = FakeMessageEvent(source="agent", text="Second response.")
        msg3 = FakeMessageEvent(source="agent", text="Third response.")

        result = extract_response_from_events([msg1, msg2, msg3])
        assert result == "Third response."

    def test_mixed_events_realistic_sequence(self):
        """Realistic sequence: user msg, observation, agent msg, finish."""
        user_msg = FakeMessageEvent(source="user", text="Please investigate.")
        obs = FakeObservationEvent()
        agent_msg = FakeMessageEvent(source="agent", text="Intermediate analysis.")
        action = FakeFinishAction(message="Investigation complete. Found root cause.")
        finish_event = FakeActionEvent(action)

        events = [user_msg, obs, agent_msg, finish_event]
        result = extract_response_from_events(events)
        assert result == "Investigation complete. Found root cause."

    def test_finish_action_empty_message_and_thought(self):
        """FinishAction with both empty message and thought should fall through."""
        action = FakeFinishAction(message="", thought="")
        finish_event = FakeActionEvent(action)
        agent_msg = FakeMessageEvent(source="agent", text="Fallback message.")

        events = [agent_msg, finish_event]
        result = extract_response_from_events(events)
        # FinishAction is checked first (last event) but both are empty,
        # so it should fall through to the MessageEvent
        assert result == "Fallback message."

    def test_multiple_content_blocks_returns_first_non_empty(self):
        """When content has multiple blocks, the first non-empty text is returned."""
        event = FakeMessageEvent(source="agent")
        event.llm_message = FakeLlmMessage(
            content=[
                FakeContentBlock(text=""),
                FakeContentBlock(text="The actual response."),
                FakeContentBlock(text="Another block."),
            ]
        )
        result = extract_response_from_events([event])
        assert result == "The actual response."
