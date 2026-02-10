from __future__ import annotations

"""
Shared tool functions for all agent frameworks.

These functions wrap the vibeteam connectors and provide a consistent
interface that can be used by AutoGen, CrewAI, and OpenHands agents.

Usage:
    # AutoGen - use directly as FunctionTool
    from agents.shared.gmail_tools import list_emails, send_email
    agent = AssistantAgent(tools=[list_emails, send_email, ...])

    # CrewAI - wrap in BaseTool
    from agents.shared.gmail_tools import fetch_unread_emails
    class EmailSearchTool(BaseTool):
        def _run(self, query): return fetch_unread_emails(query)

    # OpenHands - use for context injection
    from agents.shared.gmail_tools import get_email_context
    context = get_email_context()
"""

from agents.shared.browser_tools import (
    analyze_competitor_page,
    analyze_competitor_page_sync,
    extract_links,
    extract_links_sync,
    fetch_webpage,
    fetch_webpage_sync,
    get_browser_context,
    take_screenshot,
    take_screenshot_sync,
    web_search,
    web_search_sync,
)
from agents.shared.calendar_tools import (
    create_calendar_event,
    get_calendar_context,
    list_calendar_events,
)
from agents.shared.docs_tools import (
    get_doc_content,
    get_docs_context,
    list_docs,
    rebuild_index,
    search_docs,
    search_docs_sync,
)
from agents.shared.gmail_tools import (
    fetch_unread_emails,
    get_email_context,
    list_emails,
    mark_email_as_read,
    send_email,
    send_email_reply,
)
from agents.shared.handoff import HANDOFF_PROMPT
from agents.shared.langfuse_tools import (
    get_langfuse_context,
    get_langfuse_stats,
    get_langfuse_traces,
)
from agents.shared.role_resolver import (
    ROLE_DISPLAY_NAMES,
    ROLE_MENTION_MAP,
    ROLE_PATTERN,
    AgentRole,
    get_display_name,
    parse_first_role_mention,
    parse_role_mentions,
)
from agents.shared.slack_tools import (
    clear_slack_context,
    get_slack_context,
    get_slack_context_for_injection,
    get_slack_handoff_instructions,
    is_slack_context_set,
    mention_agent,
    mention_agent_sync,
    post_slack_message,
    post_slack_message_sync,
    read_slack_channel,
    read_slack_channel_sync,
    read_slack_thread,
    read_slack_thread_sync,
    send_message,
    send_message_sync,
    set_slack_context,
)

__all__ = [
    # Gmail
    "list_emails",
    "fetch_unread_emails",
    "send_email",
    "send_email_reply",
    "mark_email_as_read",
    "get_email_context",
    # Calendar
    "list_calendar_events",
    "create_calendar_event",
    "get_calendar_context",
    # Langfuse
    "get_langfuse_traces",
    "get_langfuse_stats",
    "detect_langfuse_anomalies",
    "get_langfuse_context",
    # Browser
    "fetch_webpage",
    "fetch_webpage_sync",
    "web_search",
    "web_search_sync",
    "take_screenshot",
    "take_screenshot_sync",
    "extract_links",
    "extract_links_sync",
    "get_browser_context",
    "analyze_competitor_page",
    "analyze_competitor_page_sync",
    # Documentation Search
    "search_docs",
    "search_docs_sync",
    "list_docs",
    "get_doc_content",
    "get_docs_context",
    "rebuild_index",
    # Slack
    "send_message",
    "send_message_sync",
    "post_slack_message",
    "post_slack_message_sync",
    "mention_agent",
    "mention_agent_sync",
    "read_slack_channel",
    "read_slack_channel_sync",
    "read_slack_thread",
    "read_slack_thread_sync",
    "set_slack_context",
    "get_slack_context",
    "clear_slack_context",
    "is_slack_context_set",
    "get_slack_context_for_injection",
    "get_slack_handoff_instructions",
    # Handoff
    "HANDOFF_PROMPT",
    # Role resolution
    "AgentRole",
    "ROLE_MENTION_MAP",
    "ROLE_DISPLAY_NAMES",
    "ROLE_PATTERN",
    "parse_role_mentions",
    "parse_first_role_mention",
    "get_display_name",
]
