"""
Tests for shared response extraction utility.

Verifies that extract_response_from_events correctly handles:
1. FinishAction events (via ActionEvent) - .message and .thought
2. MessageEvent with agent source - .llm_message.content blocks
3. Priority: FinishAction takes precedence over MessageEvent
4. Edge cases: empty events, no matching types
"""

from __future__ import annotations

from agents.openhands.utils import extract_response_from_events

# ---------------------------------------------------------------------------
# Lightweight mock objects that replicate OpenHands event structures
# ---------------------------------------------------------------------------


class MockFinishAction:
    """Mimics openhands FinishAction with message and thought fields."""

    def __init__(self, message: str = "", thought: str = ""):
        self.message = message
        self.thought = thought


class MockActionEvent:
    """Mimics openhands ActionEvent wrapping an action object.

    In the real OpenHands SDK, ActionEvent has a `thought` field at the event
    level (not on the action object itself). Actions like TerminalAction only
    have [command, is_input, timeout, reset] — no thought.  The LLM's
    reasoning is stored in ActionEvent.thought.
    """

    def __init__(self, action, thought: str = ""):
        self.action = action
        self.thought = thought

    # The extraction function checks type(event).__name__
    # so we need the class name to be "ActionEvent"


# Rename so __name__ == "ActionEvent"
MockActionEvent.__name__ = "ActionEvent"


class MockContentBlock:
    """Mimics an LLM content block with a text field."""

    def __init__(self, text: str = ""):
        self.text = text


class MockLLMMessage:
    """Mimics the llm_message object on MessageEvent."""

    def __init__(self, content: list[MockContentBlock] | None = None):
        self.content = content or []


class MockMessageEvent:
    """Mimics openhands MessageEvent with source and llm_message."""

    def __init__(self, source: str = "agent", llm_message: MockLLMMessage | None = None):
        self.source = source
        self.llm_message = llm_message


MockMessageEvent.__name__ = "MessageEvent"


class MockOtherEvent:
    """An event type that should be ignored by extraction."""

    pass


MockOtherEvent.__name__ = "ObservationEvent"


class MockCmdRunAction:
    """Mimics a non-finish action (like CmdRunAction) with a thought field."""

    def __init__(self, thought: str = ""):
        self.thought = thought


MockCmdRunAction.__name__ = "CmdRunAction"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFinishActionExtraction:
    """Test extraction from ActionEvent containing FinishAction."""

    def test_extracts_message_from_finish_action(self):
        action = MockFinishAction(message="Task completed successfully")
        action.__class__.__name__ = "FinishAction"
        event = MockActionEvent(action)

        result = extract_response_from_events([event])
        assert result == "Task completed successfully"

    def test_extracts_message_from_agent_finish_action(self):
        action = MockFinishAction(message="Done with analysis")
        action.__class__.__name__ = "AgentFinishAction"
        event = MockActionEvent(action)

        result = extract_response_from_events([event])
        assert result == "Done with analysis"

    def test_falls_back_to_thought_when_no_message(self):
        action = MockFinishAction(message="", thought="I have completed the investigation")
        action.__class__.__name__ = "FinishAction"
        event = MockActionEvent(action)

        result = extract_response_from_events([event])
        assert result == "I have completed the investigation"

    def test_message_takes_priority_over_thought(self):
        action = MockFinishAction(
            message="Final response",
            thought="Internal reasoning",
        )
        action.__class__.__name__ = "FinishAction"
        event = MockActionEvent(action)

        result = extract_response_from_events([event])
        assert result == "Final response"

    def test_skips_action_event_without_finish_action(self):
        """ActionEvent with a non-finish action should be skipped."""
        action = MockFinishAction(message="Not a finish")
        action.__class__.__name__ = "CmdRunAction"
        event = MockActionEvent(action)

        result = extract_response_from_events([event])
        assert result == ""


class TestMessageEventExtraction:
    """Test extraction from MessageEvent with agent source."""

    def test_extracts_text_from_agent_message(self):
        msg = MockLLMMessage(content=[MockContentBlock(text="Hello from agent")])
        event = MockMessageEvent(source="agent", llm_message=msg)

        result = extract_response_from_events([event])
        assert result == "Hello from agent"

    def test_ignores_non_agent_message(self):
        msg = MockLLMMessage(content=[MockContentBlock(text="User message")])
        event = MockMessageEvent(source="user", llm_message=msg)

        result = extract_response_from_events([event])
        assert result == ""

    def test_handles_multiple_content_blocks(self):
        """Should extract text from the first non-empty block."""
        msg = MockLLMMessage(
            content=[
                MockContentBlock(text=""),
                MockContentBlock(text="Second block text"),
                MockContentBlock(text="Third block text"),
            ]
        )
        event = MockMessageEvent(source="agent", llm_message=msg)

        result = extract_response_from_events([event])
        assert result == "Second block text"

    def test_handles_missing_llm_message(self):
        event = MockMessageEvent(source="agent", llm_message=None)

        result = extract_response_from_events([event])
        assert result == ""

    def test_handles_empty_content_list(self):
        msg = MockLLMMessage(content=[])
        event = MockMessageEvent(source="agent", llm_message=msg)

        result = extract_response_from_events([event])
        assert result == ""


class TestEventPriority:
    """Test that FinishAction takes priority and reverse ordering works."""

    def test_finish_action_takes_priority_over_message_event(self):
        """When both exist, the most recent one wins (reverse iteration)."""
        # Earlier: MessageEvent, Later: FinishAction
        msg = MockLLMMessage(content=[MockContentBlock(text="Earlier message")])
        msg_event = MockMessageEvent(source="agent", llm_message=msg)

        action = MockFinishAction(message="Final answer from finish")
        action.__class__.__name__ = "FinishAction"
        action_event = MockActionEvent(action)

        # Events in chronological order: message first, then finish
        events = [msg_event, action_event]

        result = extract_response_from_events(events)
        # Reverse iteration: action_event is checked first
        assert result == "Final answer from finish"

    def test_most_recent_event_wins(self):
        """The most recent matching event (last in list) should be extracted."""
        msg1 = MockLLMMessage(content=[MockContentBlock(text="First response")])
        event1 = MockMessageEvent(source="agent", llm_message=msg1)

        msg2 = MockLLMMessage(content=[MockContentBlock(text="Second response")])
        event2 = MockMessageEvent(source="agent", llm_message=msg2)

        events = [event1, event2]

        result = extract_response_from_events(events)
        assert result == "Second response"

    def test_skips_non_matching_events(self):
        """Should skip unrelated events and find the matching one."""
        other1 = MockOtherEvent()
        other2 = MockOtherEvent()

        msg = MockLLMMessage(content=[MockContentBlock(text="Agent response")])
        agent_event = MockMessageEvent(source="agent", llm_message=msg)

        events = [other1, agent_event, other2]

        result = extract_response_from_events(events)
        assert result == "Agent response"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_events_returns_empty_string(self):
        result = extract_response_from_events([])
        assert result == ""

    def test_no_matching_events_returns_empty_string(self):
        events = [MockOtherEvent(), MockOtherEvent()]
        result = extract_response_from_events(events)
        assert result == ""

    def test_finish_action_with_empty_message_and_thought(self):
        """FinishAction with both empty message and thought should not match."""
        action = MockFinishAction(message="", thought="")
        action.__class__.__name__ = "FinishAction"
        event = MockActionEvent(action)

        # Should NOT match this action (both empty) and return ""
        result = extract_response_from_events([event])
        assert result == ""

    def test_finish_action_with_empty_then_message_event(self):
        """Empty FinishAction should be skipped, falling through to MessageEvent."""
        action = MockFinishAction(message="", thought="")
        action.__class__.__name__ = "FinishAction"
        action_event = MockActionEvent(action)

        msg = MockLLMMessage(content=[MockContentBlock(text="Fallback response")])
        msg_event = MockMessageEvent(source="agent", llm_message=msg)

        # Chronological: message first, then empty finish
        events = [msg_event, action_event]

        result = extract_response_from_events(events)
        # Reverse: action_event checked first but empty, then msg_event matches
        assert result == "Fallback response"


class TestActionThoughtFallback:
    """Test fallback extraction from non-finish ActionEvent.thought."""

    def test_extracts_thought_from_last_action_when_no_finish(self):
        """When agent hits max_iterations without finish(), use last ActionEvent's thought."""
        action = MockCmdRunAction()
        event = MockActionEvent(
            action, thought="I have analyzed the issue and found the root cause."
        )

        result = extract_response_from_events([event])
        assert result == "I have analyzed the issue and found the root cause."

    def test_skips_empty_thoughts(self):
        """Actions with empty thoughts should be skipped in fallback."""
        action_empty = MockCmdRunAction()
        event_empty = MockActionEvent(action_empty, thought="")

        action_with = MockCmdRunAction()
        event_with = MockActionEvent(action_with, thought="Found the bug in the login handler.")

        # Chronological: action_with first, then empty
        events = [event_with, event_empty]

        result = extract_response_from_events(events)
        # Reverse: empty skipped, then action_with matches
        assert result == "Found the bug in the login handler."

    def test_finish_action_takes_priority_over_thought_fallback(self):
        """FinishAction should still take priority even when other actions have thoughts."""
        cmd_action = MockCmdRunAction()
        cmd_event = MockActionEvent(cmd_action, thought="Internal tool reasoning")

        finish_action = MockFinishAction(message="Final answer")
        finish_action.__class__.__name__ = "FinishAction"
        finish_event = MockActionEvent(finish_action)

        events = [cmd_event, finish_event]

        result = extract_response_from_events(events)
        assert result == "Final answer"

    def test_message_event_takes_priority_over_thought_fallback(self):
        """MessageEvent should take priority over action thought fallback."""
        cmd_action = MockCmdRunAction()
        cmd_event = MockActionEvent(cmd_action, thought="Internal tool reasoning")

        msg = MockLLMMessage(content=[MockContentBlock(text="Agent message")])
        msg_event = MockMessageEvent(source="agent", llm_message=msg)

        events = [cmd_event, msg_event]

        result = extract_response_from_events(events)
        assert result == "Agent message"

    def test_thought_fallback_with_observation_events(self):
        """Simulates typical max_iterations scenario: alternating actions and observations."""
        other1 = MockOtherEvent()  # ObservationEvent
        action1 = MockCmdRunAction()
        event1 = MockActionEvent(action1, thought="Let me check the logs")

        other2 = MockOtherEvent()
        action2 = MockCmdRunAction()
        event2 = MockActionEvent(action2, thought="The issue is in the auth module, line 42.")

        events = [event1, other1, event2, other2]

        result = extract_response_from_events(events)
        # Should extract from the last ActionEvent (event2), skipping ObservationEvent
        assert result == "The issue is in the auth module, line 42."
