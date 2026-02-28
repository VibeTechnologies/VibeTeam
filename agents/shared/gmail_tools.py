"""
Standalone Gmail tools for OpenHands and other agent frameworks.

This module provides Gmail functionality WITHOUT depending on vibeteam package.
It uses google-api-python-client directly, making it suitable for containerized
deployments where only the agents/ directory is available.

Required environment variables:
- GMAIL_CREDENTIALS_PATH: Path to OAuth client credentials JSON (default: .secrets/gmail-credentials.json)
- GMAIL_TOKEN_PATH: Path to OAuth token file (default: .secrets/gmail-token.json)

Required packages:
- google-api-python-client
- google-auth-oauthlib
- google-auth-httplib2
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Default paths
DEFAULT_CREDENTIALS_PATH = Path(".secrets/gmail-credentials.json")
DEFAULT_TOKEN_PATH = Path(".secrets/gmail-token.json")


@dataclass
class Email:
    """Represents an email message."""

    id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    recipient: str
    date: str
    body: str
    snippet: str
    labels: list[str]

    @property
    def sender_name(self) -> str:
        """Extract sender name from full sender string."""
        if "<" in self.sender:
            return self.sender.split("<")[0].strip().strip('"')
        return self.sender


class GmailClient:
    """
    Standalone Gmail API client using google-api-python-client directly.

    This is a self-contained implementation that doesn't depend on vibeteam.

    Usage:
        client = GmailClient()  # Uses env vars for paths

        # Fetch unread emails
        emails = client.fetch_unread_emails(max_results=10)

        # Reply to an email
        client.send_reply(
            thread_id=email.thread_id,
            to=email.sender_email,
            subject=f"Re: {email.subject}",
            body="Thank you for reaching out..."
        )

        # Mark as read
        client.mark_as_read(email.id)
    """

    def __init__(
        self,
        credentials_path: Path | str | None = None,
        token_path: Path | str | None = None,
    ):
        """
        Initialize Gmail client.

        Args:
            credentials_path: Path to OAuth client credentials JSON
            token_path: Path to store/load OAuth tokens
        """
        self.credentials_path = Path(
            credentials_path or os.environ.get("GMAIL_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_PATH)
        )
        self.token_path = Path(token_path or os.environ.get("GMAIL_TOKEN_PATH", DEFAULT_TOKEN_PATH))
        self.creds: Any = None
        self.service: Any = None

        # Import required Google libs (fail fast if not available)
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            self.Request = Request
            self.Credentials = Credentials
            self.build = build
            self.HttpError = HttpError
        except ImportError as e:
            raise ImportError(
                "Google API libraries required. Install with: "
                "pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            ) from e

    def authenticate(self, headless: bool = True) -> bool:
        """
        Authenticate with Gmail API.

        Args:
            headless: If True, raise error instead of opening browser

        Returns:
            True if authentication successful

        Raises:
            RuntimeError: If headless=True and no valid token
        """
        # Check for existing token
        if self.token_path.exists():
            self.creds = self.Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        # If no valid credentials, try to refresh or fail
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                # Refresh expired token
                self.creds.refresh(self.Request())
                try:
                    self._save_token()
                except OSError as e:
                    logger.warning(
                        "Failed to write Gmail token to %s: %s",
                        self.token_path,
                        e,
                    )
            else:
                if headless:
                    raise RuntimeError(
                        "No valid Gmail token found. Run authentication interactively first."
                    )
                # Would need google_auth_oauthlib for interactive flow
                raise RuntimeError(
                    "Interactive Gmail authentication not supported in standalone mode. "
                    "Use vibeteam CLI to authenticate: python -m vibeteam.connectors.gmail"
                )

        # Build Gmail service
        self.service = self.build("gmail", "v1", credentials=self.creds)
        return True

    def _save_token(self) -> None:
        """Save credentials token to file."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w") as token:
            token.write(self.creds.to_json())

    def _ensure_authenticated(self) -> None:
        """Ensure we have a valid authenticated service."""
        if not self.service:
            self.authenticate()

    def fetch_unread_emails(
        self,
        max_results: int = 10,
        label_ids: list[str] | None = None,
    ) -> list[Email]:
        """
        Fetch unread emails from inbox.

        Args:
            max_results: Maximum number of emails to fetch
            label_ids: Filter by labels (default: INBOX, UNREAD)

        Returns:
            List of Email objects
        """
        self._ensure_authenticated()

        if label_ids is None:
            label_ids = ["INBOX", "UNREAD"]

        try:
            results = (
                self.service.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=label_ids,
                    maxResults=max_results,
                )
                .execute()
            )

            messages = results.get("messages", [])
            emails = []

            for msg in messages:
                email = self._get_email_details(msg["id"])
                if email:
                    emails.append(email)

            return emails

        except self.HttpError as error:
            raise RuntimeError(f"Gmail API error: {error}") from error

    def _get_email_details(self, message_id: str) -> Email | None:
        """Fetch full email details by ID."""
        try:
            msg = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="full",
                )
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

            # Extract body
            body = self._extract_body(msg["payload"])

            # Parse sender
            sender_full = headers.get("From", "")
            sender_email = sender_full
            if "<" in sender_full and ">" in sender_full:
                sender_email = sender_full.split("<")[1].split(">")[0]

            return Email(
                id=msg["id"],
                thread_id=msg["threadId"],
                subject=headers.get("Subject", "(No Subject)"),
                sender=sender_full,
                sender_email=sender_email,
                recipient=headers.get("To", ""),
                date=headers.get("Date", ""),
                body=body,
                snippet=msg.get("snippet", ""),
                labels=msg.get("labelIds", []),
            )

        except self.HttpError:
            return None

    def _extract_body(self, payload: dict) -> str:
        """Extract email body from payload, preferring plain text."""
        body = ""

        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    if part["body"].get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
                elif part["mimeType"] == "text/html" and not body:
                    if part["body"].get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                elif "parts" in part:
                    # Nested multipart
                    body = self._extract_body(part)
                    if body:
                        break

        return body

    def send_reply(
        self,
        thread_id: str,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        """
        Send email reply within a thread.

        Args:
            thread_id: Gmail thread ID
            to: Recipient email address
            subject: Email subject (typically "Re: ...")
            body: Email body text
            in_reply_to: Message-ID header for threading

        Returns:
            Sent message ID
        """
        self._ensure_authenticated()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        message["from"] = "me"

        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        try:
            sent = (
                self.service.users()
                .messages()
                .send(
                    userId="me",
                    body={"raw": raw, "threadId": thread_id},
                )
                .execute()
            )

            return sent["id"]

        except self.HttpError as error:
            raise RuntimeError(f"Failed to send email: {error}") from error

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> str:
        """
        Send new email (not a reply).

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body text

        Returns:
            Sent message ID
        """
        self._ensure_authenticated()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        message["from"] = "me"

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        try:
            sent = (
                self.service.users()
                .messages()
                .send(
                    userId="me",
                    body={"raw": raw},
                )
                .execute()
            )

            return sent["id"]

        except self.HttpError as error:
            raise RuntimeError(f"Failed to send email: {error}") from error

    def mark_as_read(self, message_id: str) -> bool:
        """
        Mark email as read (remove UNREAD label).

        Args:
            message_id: Gmail message ID

        Returns:
            True if successful
        """
        self._ensure_authenticated()

        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

            return True

        except self.HttpError as error:
            raise RuntimeError(f"Failed to mark as read: {error}") from error


# ==============================================================================
# High-level functions for agents
# ==============================================================================


def _get_gmail_client() -> GmailClient | tuple[None, str]:
    """Get or create Gmail client."""
    try:
        client = GmailClient()
        client.authenticate(headless=True)
        return client
    except ImportError as e:
        return None, f"Gmail libraries not installed: {e}"
    except RuntimeError as e:
        return None, str(e)
    except FileNotFoundError as e:
        return None, f"Gmail token not found: {e}"
    except Exception as e:
        return None, f"Gmail error: {e}"


async def list_emails(label: str = "INBOX", max_results: int = 10) -> str:
    """List emails from a Gmail label.

    Args:
        label: Gmail label (INBOX, SENT, SPAM, UNREAD, etc.)
        max_results: Maximum number of emails to return (default: 10)

    Returns:
        JSON list of email summaries or error message
    """
    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"Gmail error: {result[1]}"

    client = result

    try:
        # Handle different labels
        if label.upper() == "UNREAD":
            emails = client.fetch_unread_emails(max_results=max_results)
        elif label.upper() == "INBOX":
            emails = client.fetch_unread_emails(max_results=max_results, label_ids=["INBOX"])
        else:
            # For other labels, use the label_ids parameter
            emails = client.fetch_unread_emails(max_results=max_results, label_ids=[label.upper()])

        if not emails:
            return f"No emails found in {label}"

        # Format for agent consumption
        output = f"=== Emails from {label} ({len(emails)} found) ===\n\n"
        for i, email in enumerate(emails, 1):
            output += f"{i}. **{email.subject}**\n"
            output += f"   From: {email.sender_name} <{email.sender_email}>\n"
            output += f"   Date: {email.date}\n"
            output += f"   Snippet: {email.snippet[:100]}...\n"
            output += f"   ID: {email.id} | Thread: {email.thread_id}\n\n"

        return output

    except Exception as e:
        return f"Error listing emails: {e}"


def fetch_unread_emails(max_results: int = 10) -> str:
    """Fetch unread emails from inbox (synchronous version).

    Args:
        max_results: Maximum number of emails to return

    Returns:
        Formatted string with email summaries
    """
    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"Gmail error: {result[1]}"

    client = result

    try:
        emails = client.fetch_unread_emails(max_results=max_results)

        if not emails:
            return "No unread emails found."

        output = f"Found {len(emails)} unread emails:\n\n"
        for i, email in enumerate(emails, 1):
            output += f"{i}. **{email.subject}**\n"
            output += f"   From: {email.sender_name} <{email.sender_email}>\n"
            output += f"   Date: {email.date}\n"
            output += f"   Preview: {email.snippet[:150]}...\n"
            output += f"   [ID: {email.id}]\n\n"

        return output

    except Exception as e:
        return f"Error fetching emails: {e}"


async def send_email(to: str, subject: str, body: str) -> str:
    """Send a new email via Gmail.

    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body content (plain text)

    Returns:
        Success message with message ID or error
    """
    # Validate email format
    if "@" not in to:
        return "Error: Invalid email address format"

    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"Gmail error: {result[1]}"

    client = result

    try:
        msg_id = client.send_email(to=to, subject=subject, body=body)
        return f"Email sent successfully!\nTo: {to}\nSubject: {subject}\nMessage ID: {msg_id}"
    except Exception as e:
        return f"Error sending email: {e}"


async def send_email_reply(thread_id: str, to: str, subject: str, body: str) -> str:
    """Send a reply to an existing email thread.

    Args:
        thread_id: Gmail thread ID to reply to
        to: Recipient email address
        subject: Email subject (should start with "Re: ")
        body: Reply body content

    Returns:
        Success message with message ID or error
    """
    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"Gmail error: {result[1]}"

    client = result

    try:
        msg_id = client.send_reply(
            thread_id=thread_id,
            to=to,
            subject=subject,
            body=body,
        )
        return f"Reply sent successfully!\nThread: {thread_id}\nTo: {to}\nMessage ID: {msg_id}"
    except Exception as e:
        return f"Error sending reply: {e}"


async def mark_email_as_read(message_id: str) -> str:
    """Mark an email as read.

    Args:
        message_id: Gmail message ID

    Returns:
        Success or error message
    """
    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"Gmail error: {result[1]}"

    client = result

    try:
        client.mark_as_read(message_id)
        return f"Email {message_id} marked as read."
    except Exception as e:
        return f"Error marking email as read: {e}"


def get_email_context(max_results: int = 5) -> str:
    """Get email context for injection into agent prompts.

    This is designed for OpenHands-style context injection where we
    provide current state to the agent upfront.

    Args:
        max_results: Maximum emails to include in context

    Returns:
        Formatted context string for agent prompts
    """
    result = _get_gmail_client()
    if isinstance(result, tuple):
        return f"## Email Status\n\nGmail not configured: {result[1]}"

    client = result

    try:
        emails = client.fetch_unread_emails(max_results=max_results)

        if not emails:
            return "## Email Status\n\nNo unread emails in inbox."

        context = f"## Current Unread Emails ({len(emails)})\n\n"
        for email in emails:
            context += f"### {email.subject}\n"
            context += f"- **From**: {email.sender_name} <{email.sender_email}>\n"
            context += f"- **Date**: {email.date}\n"
            context += f"- **Preview**: {email.snippet[:200]}...\n"
            context += f"- **ID**: {email.id} | **Thread**: {email.thread_id}\n\n"

        return context

    except Exception as e:
        return f"## Email Status\n\nError loading emails: {e}"
