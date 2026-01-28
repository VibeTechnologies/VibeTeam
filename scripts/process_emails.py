#!/usr/bin/env python3
"""
Email Support Pipeline - Process incoming support emails with AI.

This script:
1. Fetches unread emails from support inbox
2. Analyzes each email using SupportEngineer role
3. Either responds directly or escalates to human
4. Validates security before sending
5. Marks processed emails as read

Usage:
    # First time: authenticate with Gmail
    python scripts/process_emails.py --authenticate

    # Process emails (one-time)
    python scripts/process_emails.py

    # Run as daemon (poll every N seconds)
    python scripts/process_emails.py --daemon --interval 60

    # Dry run (don't send responses)
    python scripts/process_emails.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add connectors directory to path (avoid metagpt dependency in main package)
_connectors_path = Path(__file__).parent.parent / "vibeteam" / "connectors"
sys.path.insert(0, str(_connectors_path))

from gmail import Email, GmailConnector  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Pattern for docs portal escalation emails
# Format: [Docs Support #TICKET-ID] New request from user@email.com
DOCS_SUPPORT_PATTERN = r"^\[Docs Support #[A-Z0-9-]+\]"


class EmailProcessor:
    """
    Process support emails using SupportEngineer role.

    Only processes emails that match the docs portal escalation format:
    Subject: [Docs Support #TICKET-ID] New request from user@email.com

    These are customer escalations from the chat widget at docs.vibebrowser.app.
    Other emails (npm notifications, security alerts, etc.) are ignored.

    Flow:
    1. Fetch unread emails
    2. Filter to only docs portal escalations
    3. For each email:
       a. Analyze with AnalyzeCustomerEmail
       b. If escalation needed: FlagForEscalation, send acknowledgment
       c. If can respond: WriteEmailResponse, ValidateResponseSecurity
       d. Send response (if not dry run)
       e. Mark as read
    """

    def __init__(
        self,
        gmail: GmailConnector,
        dry_run: bool = False,
        escalation_dir: Path | None = None,
    ):
        self.gmail = gmail
        self.dry_run = dry_run
        self.escalation_dir = escalation_dir or Path(".secrets/escalations")
        self.escalation_dir.mkdir(parents=True, exist_ok=True)

        # Stats
        self.stats = {
            "processed": 0,
            "responded": 0,
            "escalated": 0,
            "skipped": 0,
            "errors": 0,
        }

    async def process_emails(self, max_emails: int = 10) -> dict:
        """
        Process unread emails from inbox.

        Only processes emails matching the docs portal escalation format:
        [Docs Support #TICKET-ID] New request from user@email.com

        Args:
            max_emails: Maximum number of emails to process

        Returns:
            Processing statistics
        """
        logger.info(f"Fetching up to {max_emails} unread emails...")

        try:
            emails = self.gmail.fetch_unread_emails(max_results=max_emails)
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return self.stats

        if not emails:
            logger.info("No unread emails found.")
            return self.stats

        logger.info(f"Found {len(emails)} unread emails.")

        for email in emails:
            # Filter: only process docs portal escalations
            if not self._is_docs_portal_escalation(email):
                logger.debug(f"Skipping non-support email: {email.subject}")
                self.stats["skipped"] += 1
                continue

            try:
                await self._process_single_email(email)
                self.stats["processed"] += 1
            except Exception as e:
                logger.error(f"Error processing email {email.id}: {e}")
                self.stats["errors"] += 1

        logger.info(f"Processing complete. Stats: {self.stats}")
        return self.stats

    def _is_docs_portal_escalation(self, email: Email) -> bool:
        """
        Check if email is a docs portal escalation.

        Format: [Docs Support #TICKET-ID] New request from user@email.com
        Sent from: noreply@vibebrowser.app (Azure Communication Services)
        Reply-To: customer's email
        """
        return bool(re.match(DOCS_SUPPORT_PATTERN, email.subject))

    def _extract_ticket_info(self, email: Email) -> dict:
        """
        Extract ticket ID and customer email from docs portal escalation.

        Subject format: [Docs Support #TICKET-ID] New request from user@email.com
        Reply-To header contains customer email.
        """
        ticket_id = None
        customer_email = None

        # Extract ticket ID from subject
        match = re.search(r"\[Docs Support #([A-Z0-9-]+)\]", email.subject)
        if match:
            ticket_id = match.group(1)

        # Extract customer email from subject
        email_match = re.search(r"from\s+([^\s@]+@[^\s@]+\.[^\s@]+)", email.subject)
        if email_match:
            customer_email = email_match.group(1)

        return {
            "ticket_id": ticket_id,
            "customer_email": customer_email,
        }

    async def _process_single_email(self, email: Email) -> None:
        """Process a single docs portal escalation email."""
        # Extract ticket info
        ticket_info = self._extract_ticket_info(email)
        ticket_id = ticket_info.get("ticket_id", "UNKNOWN")
        customer_email = ticket_info.get("customer_email") or email.sender_email

        logger.info(f"Processing ticket #{ticket_id} from {customer_email}")

        # Step 1: Analyze email
        analysis = await self._analyze_email(email)

        # Add ticket info to analysis for handlers
        analysis["ticket_id"] = ticket_id
        analysis["customer_email"] = customer_email

        # Step 2: Check if escalation needed
        needs_escalation = self._check_escalation(analysis)

        if needs_escalation:
            # Escalate and send acknowledgment
            await self._handle_escalation(email, analysis)
            self.stats["escalated"] += 1
        else:
            # Generate and validate response
            await self._handle_response(email, analysis)
            self.stats["responded"] += 1

        # Step 3: Mark as read (unless dry run)
        if not self.dry_run:
            self.gmail.mark_as_read(email.id)
            logger.info(f"Marked as read: {email.id}")

    async def _analyze_email(self, email: Email) -> dict:
        """
        Analyze email using SupportEngineer.AnalyzeCustomerEmail action.

        For now, returns a mock analysis. In production, this would
        call the MetaGPT action.
        """
        # TODO: Integrate with actual SupportEngineer role
        # For now, simple heuristic analysis

        body_lower = email.body.lower()

        # Detect escalation triggers
        escalation_triggers = []

        if any(
            word in body_lower for word in ["refund", "charge", "billing", "payment"]
        ):
            escalation_triggers.append("BILLING")

        if any(
            word in body_lower
            for word in ["security", "vulnerability", "breach", "hack"]
        ):
            escalation_triggers.append("SECURITY")

        if any(
            word in body_lower
            for word in ["lawyer", "legal", "sue", "gdpr", "subpoena"]
        ):
            escalation_triggers.append("LEGAL")

        if any(
            word in body_lower
            for word in ["angry", "frustrated", "terrible", "worst", "lawsuit"]
        ):
            escalation_triggers.append("ANGRY_CUSTOMER")

        if any(
            word in body_lower
            for word in ["partnership", "enterprise", "sales", "business"]
        ):
            escalation_triggers.append("PARTNERSHIP")

        if any(
            word in body_lower for word in ["journalist", "press", "interview", "media"]
        ):
            escalation_triggers.append("PRESS")

        # Determine category
        category = "Question"
        if "bug" in body_lower or "error" in body_lower or "not working" in body_lower:
            category = "Bug Report"
        elif "feature" in body_lower or "would be nice" in body_lower:
            category = "Feature Request"
        elif any(word in body_lower for word in ["how to", "how do", "can i"]):
            category = "How-To Question"

        # Sentiment
        sentiment = "Neutral"
        if any(word in body_lower for word in ["thanks", "great", "love", "amazing"]):
            sentiment = "Positive"
        elif any(
            word in body_lower for word in ["frustrated", "annoyed", "disappointed"]
        ):
            sentiment = "Frustrated"
        elif any(
            word in body_lower for word in ["angry", "furious", "terrible", "worst"]
        ):
            sentiment = "Angry"

        return {
            "category": category,
            "sentiment": sentiment,
            "escalation_triggers": escalation_triggers,
            "needs_escalation": len(escalation_triggers) > 0,
            "key_issues": [email.subject],
            "suggested_docs": ["https://docs.vibebrowser.app"],
        }

    def _check_escalation(self, analysis: dict) -> bool:
        """Check if email needs human escalation."""
        return analysis.get("needs_escalation", False)

    async def _handle_escalation(self, email: Email, analysis: dict) -> None:
        """Handle email that needs human escalation to support team."""
        ticket_id = analysis.get("ticket_id", "UNKNOWN")
        customer_email = analysis.get("customer_email", email.sender_email)

        logger.warning(
            f"ESCALATING ticket #{ticket_id}: {analysis.get('escalation_triggers', [])}"
        )

        # Create escalation ticket for internal tracking
        ticket = {
            "timestamp": datetime.now().isoformat(),
            "ticket_id": ticket_id,
            "email_id": email.id,
            "thread_id": email.thread_id,
            "customer_email": customer_email,
            "subject": email.subject,
            "triggers": analysis.get("escalation_triggers", []),
            "sentiment": analysis.get("sentiment"),
            "body_preview": email.snippet,
        }

        # Save escalation ticket
        ticket_path = self.escalation_dir / f"{ticket_id}.json"
        with open(ticket_path, "w") as f:
            json.dump(ticket, f, indent=2)
        logger.info(f"Escalation ticket saved: {ticket_path}")

        # Send acknowledgment to customer
        if not self.dry_run:
            ack_body = f"""Hi,

Thank you for contacting VibeBrowser support (Ticket #{ticket_id}).

I've escalated your request to our specialized team who will follow up within 24-48 hours. We appreciate your patience.

If you have any additional information to add, please reply to this email.

Best regards,
VibeBrowser Support
support@vibebrowser.app
"""
            self.gmail.send_reply(
                thread_id=email.thread_id,
                to=customer_email,
                subject=f"Re: {email.subject}",
                body=ack_body,
            )
            logger.info(f"Sent escalation acknowledgment to {customer_email}")
        else:
            logger.info(
                f"[DRY RUN] Would send escalation acknowledgment to {customer_email}"
            )

    async def _handle_response(self, email: Email, analysis: dict) -> None:
        """Generate and send response to customer for non-escalation email."""
        ticket_id = analysis.get("ticket_id", "UNKNOWN")
        customer_email = analysis.get("customer_email", email.sender_email)

        # TODO: Use actual SupportEngineer.WriteEmailResponse action
        # For now, generate a template response

        response_body = f"""Hi,

Thank you for reaching out to VibeBrowser support (Ticket #{ticket_id}).

I understand you have a question. Here are some resources that may help:

- Documentation: https://docs.vibebrowser.app
- Portal: https://portal.vibebrowser.app
- Troubleshooting: https://docs.vibebrowser.app/troubleshooting

If you need further assistance, please reply to this email and I'll be happy to help.

Best regards,
VibeBrowser Support
support@vibebrowser.app
"""

        # Validate response (basic security check)
        validation = self._validate_response(response_body)

        if not validation["valid"]:
            logger.error(f"Response validation failed: {validation['issues']}")
            return

        # Send response to customer
        if not self.dry_run:
            self.gmail.send_reply(
                thread_id=email.thread_id,
                to=customer_email,
                subject=f"Re: {email.subject}",
                body=response_body,
            )
            logger.info(f"Sent response to {customer_email}")
        else:
            logger.info(f"[DRY RUN] Would send response to {customer_email}:")
            logger.info(response_body[:200] + "...")

    def _validate_response(self, response: str) -> dict:
        """Basic security validation of response."""
        issues = []
        response_lower = response.lower()

        # Check for internal URLs
        internal_patterns = [
            "api-dev.vibebrowser.app",
            "localhost",
            "127.0.0.1",
            "internal",
            "staging",
        ]
        for pattern in internal_patterns:
            if pattern in response_lower:
                issues.append(f"Contains internal URL pattern: {pattern}")

        # Check for potential secrets
        secret_patterns = ["api_key", "secret", "password", "token=", "bearer"]
        for pattern in secret_patterns:
            if pattern in response_lower:
                issues.append(f"May contain secret: {pattern}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }


async def main():
    parser = argparse.ArgumentParser(
        description="Process support emails with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Run OAuth authentication flow",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't send responses, just log what would be done",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon, polling for new emails",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Polling interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=10,
        help="Maximum emails to process per run (default: 10)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(".secrets/gmail-credentials.json"),
        help="Path to Gmail OAuth credentials",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=Path(".secrets/gmail-token.json"),
        help="Path to Gmail OAuth token",
    )

    args = parser.parse_args()

    # Initialize Gmail connector
    gmail = GmailConnector(
        credentials_path=args.credentials,
        token_path=args.token,
    )

    # Authentication mode
    if args.authenticate:
        logger.info("Running OAuth authentication flow...")
        gmail.authenticate(headless=False)
        logger.info("Authentication successful!")
        return

    # Authenticate (headless)
    try:
        gmail.authenticate(headless=True)
    except RuntimeError as e:
        logger.error(f"Authentication failed: {e}")
        logger.error("Run with --authenticate first to set up OAuth.")
        sys.exit(1)

    # Initialize processor
    processor = EmailProcessor(gmail=gmail, dry_run=args.dry_run)

    if args.daemon:
        logger.info(f"Starting daemon mode, polling every {args.interval}s...")
        while True:
            await processor.process_emails(max_emails=args.max_emails)
            logger.info(f"Sleeping {args.interval}s...")
            time.sleep(args.interval)
    else:
        await processor.process_emails(max_emails=args.max_emails)


if __name__ == "__main__":
    asyncio.run(main())
