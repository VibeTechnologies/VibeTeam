"""
Gmail Tool - OpenHands tool wrapper for Gmail connector.

Provides agent-callable functions for Gmail operations.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.gmail import GmailConnector


class GmailTool(BaseTool):
    """
    Tool for interacting with Gmail.

    Wraps the GmailConnector for use by VibeTeam agents.
    """

    name = "gmail"
    description = "Read and send Gmail emails"

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
    ):
        self.connector = GmailConnector(
            credentials_path=credentials_path,
            token_path=token_path,
        )
        self._authenticated = False

    def _ensure_authenticated(self) -> bool:
        """Ensure we're authenticated before operations."""
        if not self._authenticated:
            try:
                self.connector.authenticate(headless=True)
                self._authenticated = True
            except Exception:
                return False
        return True

    def get_schema(self) -> dict:
        """Return OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "fetch_unread",
                                "send_reply",
                                "send_email",
                                "mark_as_read",
                                "get_thread",
                            ],
                            "description": "The Gmail action to perform",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum emails to fetch (default: 10)",
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Gmail message ID",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID",
                        },
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject",
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body text",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Gmail action."""
        action = kwargs.get("action")

        if not self._ensure_authenticated():
            return ToolResult(
                success=False,
                output="",
                error="Not authenticated. Run Gmail authentication first.",
            )

        try:
            if action == "fetch_unread":
                max_results = kwargs.get("max_results", 10)
                emails = self.connector.fetch_unread_emails(max_results=max_results)
                output = json.dumps([asdict(e) for e in emails], indent=2)
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"count": len(emails)},
                )

            elif action == "send_reply":
                thread_id = kwargs.get("thread_id")
                to = kwargs.get("to")
                subject = kwargs.get("subject")
                body = kwargs.get("body")
                if not all([thread_id, to, subject, body]):
                    return ToolResult(
                        success=False,
                        output="",
                        error="thread_id, to, subject, and body required",
                    )
                msg_id = self.connector.send_reply(
                    thread_id=thread_id,
                    to=to,
                    subject=subject,
                    body=body,
                )
                return ToolResult(
                    success=True,
                    output=f"Reply sent, message ID: {msg_id}",
                    metadata={"message_id": msg_id},
                )

            elif action == "send_email":
                to = kwargs.get("to")
                subject = kwargs.get("subject")
                body = kwargs.get("body")
                if not all([to, subject, body]):
                    return ToolResult(
                        success=False,
                        output="",
                        error="to, subject, and body required",
                    )
                msg_id = self.connector.send_email(to=to, subject=subject, body=body)
                return ToolResult(
                    success=True,
                    output=f"Email sent, message ID: {msg_id}",
                    metadata={"message_id": msg_id},
                )

            elif action == "mark_as_read":
                message_id = kwargs.get("message_id")
                if not message_id:
                    return ToolResult(success=False, output="", error="message_id required")
                self.connector.mark_as_read(message_id)
                return ToolResult(success=True, output=f"Message {message_id} marked as read")

            elif action == "get_thread":
                thread_id = kwargs.get("thread_id")
                if not thread_id:
                    return ToolResult(success=False, output="", error="thread_id required")
                emails = self.connector.get_thread(thread_id)
                output = json.dumps([asdict(e) for e in emails], indent=2)
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"count": len(emails)},
                )

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
