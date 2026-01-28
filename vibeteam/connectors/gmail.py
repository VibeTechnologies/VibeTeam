"""
Gmail Connector - OAuth2 integration for Gmail API.

Provides functionality to:
- Authenticate with Gmail using OAuth2
- Fetch unread emails from inbox
- Send email replies
- Mark emails as read

Designed for headless operation with refresh token support.
"""

import base64
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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


class GmailConnector:
    """
    Gmail API connector with OAuth2 authentication.

    Usage:
        connector = GmailConnector()
        connector.authenticate()  # First time: opens browser for OAuth

        # Fetch unread emails
        emails = connector.fetch_unread_emails(max_results=10)

        # Reply to an email
        connector.send_reply(
            thread_id=email.thread_id,
            to=email.sender_email,
            subject=f"Re: {email.subject}",
            body="Thank you for reaching out..."
        )

        # Mark as read
        connector.mark_as_read(email.id)
    """

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
    ):
        """
        Initialize Gmail connector.

        Args:
            credentials_path: Path to OAuth client credentials JSON
            token_path: Path to store/load OAuth tokens
        """
        self.credentials_path = credentials_path or DEFAULT_CREDENTIALS_PATH
        self.token_path = token_path or DEFAULT_TOKEN_PATH
        self.creds: Any = None
        self.service: Any = None

    def authenticate(self, headless: bool = False) -> bool:
        """
        Authenticate with Gmail API.

        First checks for existing valid token.
        If no valid token, initiates OAuth flow.

        Args:
            headless: If True, raise error instead of opening browser

        Returns:
            True if authentication successful

        Raises:
            FileNotFoundError: If credentials file not found
            RuntimeError: If headless=True and no valid token
        """
        # Check for existing token
        if self.token_path.exists():
            self.creds = Credentials.from_authorized_user_file(
                str(self.token_path), SCOPES
            )

        # If no valid credentials, authenticate
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                # Refresh expired token
                self.creds.refresh(Request())
            else:
                # Need new authentication
                if headless:
                    raise RuntimeError(
                        "No valid token found. Run authentication interactively first."
                    )

                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Credentials file not found: {self.credentials_path}"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            # Save token for future use
            self._save_token()

        # Build Gmail service
        self.service = build("gmail", "v1", credentials=self.creds)
        return True

    def _save_token(self) -> None:
        """Save credentials token to file."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w") as token:
            token.write(self.creds.to_json())

    def _ensure_authenticated(self) -> None:
        """Ensure we have a valid authenticated service."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

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

        except HttpError as error:
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

        except HttpError:
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
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                            "utf-8"
                        )
                        break
                elif part["mimeType"] == "text/html" and not body:
                    if part["body"].get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                            "utf-8"
                        )
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

        except HttpError as error:
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

        except HttpError as error:
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

        except HttpError as error:
            raise RuntimeError(f"Failed to mark as read: {error}") from error

    def add_label(self, message_id: str, label: str) -> bool:
        """
        Add label to email.

        Args:
            message_id: Gmail message ID
            label: Label to add (e.g., "STARRED", custom label ID)

        Returns:
            True if successful
        """
        self._ensure_authenticated()

        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label]},
            ).execute()

            return True

        except HttpError as error:
            raise RuntimeError(f"Failed to add label: {error}") from error

    def get_thread(self, thread_id: str) -> list[Email]:
        """
        Get all emails in a thread.

        Args:
            thread_id: Gmail thread ID

        Returns:
            List of Email objects in the thread
        """
        self._ensure_authenticated()

        try:
            thread = (
                self.service.users()
                .threads()
                .get(
                    userId="me",
                    id=thread_id,
                    format="full",
                )
                .execute()
            )

            emails = []
            for msg in thread.get("messages", []):
                email = self._parse_message(msg)
                if email:
                    emails.append(email)

            return emails

        except HttpError as error:
            raise RuntimeError(f"Failed to get thread: {error}") from error

    def _parse_message(self, msg: dict) -> Email | None:
        """Parse a message dict into an Email object."""
        try:
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            body = self._extract_body(msg["payload"])

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
        except Exception:
            return None


def authenticate_cli() -> None:
    """CLI helper to run initial OAuth authentication."""
    import argparse

    parser = argparse.ArgumentParser(description="Gmail OAuth Authentication")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS_PATH,
        help="Path to OAuth credentials JSON",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help="Path to save OAuth token",
    )

    args = parser.parse_args()

    connector = GmailConnector(
        credentials_path=args.credentials,
        token_path=args.token,
    )

    print("Authenticating with Gmail...")
    print(f"Credentials: {args.credentials}")
    print(f"Token will be saved to: {args.token}")

    connector.authenticate(headless=False)
    print("Authentication successful!")
    print(f"Token saved to: {args.token}")


if __name__ == "__main__":
    authenticate_cli()
