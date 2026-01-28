"""
Shared Gmail tool functions for all agent frameworks.

These functions wrap the GmailConnector and provide a consistent interface
that can be used by AutoGen (as FunctionTool), CrewAI (wrapped in BaseTool),
and OpenHands (for context injection).

All functions are async-compatible for AutoGen and can be called synchronously
for other frameworks.
"""

import os
from pathlib import Path


def _get_gmail_connector():
    """Get authenticated Gmail connector."""
    from vibeteam.connectors.gmail import GmailConnector

    creds_path = Path(os.environ.get("GMAIL_CREDENTIALS_PATH", ".secrets/gmail-credentials.json"))
    token_path = Path(os.environ.get("GMAIL_TOKEN_PATH", ".secrets/gmail-token.json"))

    connector = GmailConnector(
        credentials_path=creds_path,
        token_path=token_path,
    )

    # Try to authenticate (will use cached token if available)
    try:
        connector.authenticate(headless=True)
        return connector
    except Exception as e:
        return None, str(e)


async def list_emails(label: str = "INBOX", max_results: int = 10) -> str:
    """List emails from a Gmail label.

    Args:
        label: Gmail label (INBOX, SENT, SPAM, UNREAD, etc.)
        max_results: Maximum number of emails to return (default: 10)

    Returns:
        JSON list of email summaries or error message
    """
    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"Gmail authentication error: {result[1]}"

    connector = result

    try:
        # GmailConnector.fetch_unread_emails supports label_ids parameter
        if label.upper() == "UNREAD":
            emails = connector.fetch_unread_emails(max_results=max_results)
        elif label.upper() == "INBOX":
            emails = connector.fetch_unread_emails(max_results=max_results, label_ids=["INBOX"])
        else:
            # For other labels, use the label_ids parameter
            emails = connector.fetch_unread_emails(
                max_results=max_results, label_ids=[label.upper()]
            )

        if not emails:
            return f"No emails found in {label}"

        # Format for agent consumption
        result = f"=== Emails from {label} ({len(emails)} found) ===\n\n"
        for i, email in enumerate(emails, 1):
            result += f"{i}. **{email.subject}**\n"
            result += f"   From: {email.sender_name} <{email.sender_email}>\n"
            result += f"   Date: {email.date}\n"
            result += f"   Snippet: {email.snippet[:100]}...\n"
            result += f"   ID: {email.id} | Thread: {email.thread_id}\n\n"

        return result

    except Exception as e:
        return f"Error listing emails: {e}"


def fetch_unread_emails(max_results: int = 10) -> str:
    """Fetch unread emails from inbox (synchronous version).

    Args:
        max_results: Maximum number of emails to return

    Returns:
        Formatted string with email summaries
    """
    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"Gmail authentication error: {result[1]}"

    connector = result

    try:
        emails = connector.fetch_unread_emails(max_results=max_results)

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

    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"Gmail authentication error: {result[1]}"

    connector = result

    try:
        msg_id = connector.send_email(to=to, subject=subject, body=body)
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
    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"Gmail authentication error: {result[1]}"

    connector = result

    try:
        msg_id = connector.send_reply(
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
    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"Gmail authentication error: {result[1]}"

    connector = result

    try:
        connector.mark_as_read(message_id)
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
    result = _get_gmail_connector()
    if isinstance(result, tuple):
        return f"## Email Status\n\nGmail not configured: {result[1]}"

    connector = result

    try:
        emails = connector.fetch_unread_emails(max_results=max_results)

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
