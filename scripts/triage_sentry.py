#!/usr/bin/env python3
"""
Sentry Issue Triage - AI-powered error analysis and GitHub issue creation.

This script runs every 12 hours to:
1. Fetch unresolved Sentry issues
2. Analyze each issue to determine validity
3. For valid issues: Create GitHub issue and link to Sentry
4. For invalid issues: Add comment and resolve in Sentry

Usage:
    # Run triage (one-time)
    python scripts/triage_sentry.py
    
    # Dry run (don't create issues or resolve)
    python scripts/triage_sentry.py --dry-run
    
    # Run as daemon (every 12 hours)
    python scripts/triage_sentry.py --daemon
    
    # Custom interval (hours)
    python scripts/triage_sentry.py --daemon --interval 6

Environment Variables:
    SENTRY_AUTH_TOKEN - Sentry API auth token
    GITHUB_TOKEN - GitHub personal access token (for issue creation)
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add connectors directory to path
_connectors_path = Path(__file__).parent.parent / "vibeteam" / "connectors"
sys.path.insert(0, str(_connectors_path))

from sentry import SentryConnector, SentryIssue  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# GitHub repo for issue creation
GITHUB_REPO = "VibeTechnologies/VibeWebAgent"

# Issue classification rules
INVALID_PATTERNS = [
    # Network errors (usually transient)
    r"Failed to fetch",
    r"NetworkError",
    r"net::ERR_",
    r"ECONNREFUSED",
    r"ETIMEDOUT",
    r"Request timeout",
    
    # Browser-specific (not our bug)
    r"ResizeObserver loop",
    r"Script error\.",
    r"Blocked a frame with origin",
    
    # Third-party errors
    r"chrome-extension://(?!ajfjlohdpfgngdjfafhhcnpmijbbdgln)",  # Other extensions
    r"gtag",
    r"analytics",
    r"facebook\.com",
    r"google-analytics",
    
    # User actions (not bugs)
    r"AbortError",
    r"User denied",
    r"Permission denied",
]

# Patterns that indicate valid bugs
VALID_PATTERNS = [
    r"TypeError:",
    r"ReferenceError:",
    r"Cannot read propert",
    r"is not a function",
    r"undefined is not",
    r"null is not",
    r"Unhandled Promise",
    r"Maximum call stack",
    r"SyntaxError:",
]


@dataclass
class TriageResult:
    """Result of issue triage analysis."""
    
    issue: SentryIssue
    is_valid: bool
    reason: str
    severity: str  # critical, high, medium, low
    suggested_title: str
    suggested_labels: list[str]
    root_cause_hypothesis: str


class SentryTriager:
    """
    Triage Sentry issues and create GitHub issues for valid bugs.
    
    Flow:
    1. Fetch unresolved issues from Sentry
    2. For each issue:
       a. Get detailed stacktrace and context
       b. Analyze to determine if valid bug or noise
       c. If valid: Create GitHub issue, link to Sentry
       d. If invalid: Add comment, resolve/ignore
    """
    
    def __init__(
        self,
        sentry: SentryConnector,
        dry_run: bool = False,
        processed_file: Optional[Path] = None,
    ):
        self.sentry = sentry
        self.dry_run = dry_run
        self.processed_file = processed_file or Path(".secrets/sentry-processed.json")
        self.processed_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load previously processed issues
        self.processed_ids = self._load_processed()
        
        # Stats
        self.stats = {
            "fetched": 0,
            "analyzed": 0,
            "valid": 0,
            "invalid": 0,
            "skipped": 0,
            "errors": 0,
        }
    
    def _load_processed(self) -> set:
        """Load set of previously processed issue IDs."""
        if self.processed_file.exists():
            with open(self.processed_file) as f:
                data = json.load(f)
                return set(data.get("processed_ids", []))
        return set()
    
    def _save_processed(self, issue_id: str) -> None:
        """Add issue ID to processed set and save."""
        self.processed_ids.add(issue_id)
        with open(self.processed_file, "w") as f:
            json.dump({
                "processed_ids": list(self.processed_ids),
                "last_updated": datetime.now().isoformat(),
            }, f, indent=2)
    
    def triage_issues(self, hours: int = 12, limit: int = 20) -> dict:
        """
        Triage unresolved Sentry issues.
        
        Args:
            hours: Look at issues with activity in last N hours
            limit: Maximum issues to process
            
        Returns:
            Triage statistics
        """
        logger.info(f"Fetching unresolved issues from last {hours}h...")
        
        try:
            issues = self.sentry.fetch_unresolved_issues(hours=hours, limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch issues: {e}")
            return self.stats
        
        self.stats["fetched"] = len(issues)
        
        if not issues:
            logger.info("No unresolved issues found.")
            return self.stats
        
        logger.info(f"Found {len(issues)} unresolved issues.")
        
        for issue in issues:
            # Skip already processed
            if issue.id in self.processed_ids:
                logger.debug(f"Skipping already processed: {issue.short_id}")
                self.stats["skipped"] += 1
                continue
            
            try:
                self._process_issue(issue)
                self.stats["analyzed"] += 1
            except Exception as e:
                logger.error(f"Error processing {issue.short_id}: {e}")
                self.stats["errors"] += 1
        
        logger.info(f"Triage complete. Stats: {self.stats}")
        return self.stats
    
    def _process_issue(self, issue: SentryIssue) -> None:
        """Process a single Sentry issue."""
        logger.info(f"Analyzing: [{issue.project}] {issue.short_id}: {issue.title}")
        
        # Get detailed info
        try:
            details = self.sentry.get_issue_details(issue.id)
        except Exception as e:
            logger.warning(f"Could not get details for {issue.short_id}: {e}")
            details = {}
        
        # Analyze the issue
        result = self._analyze_issue(issue, details)
        
        if result.is_valid:
            logger.info(f"VALID BUG: {result.reason}")
            self._handle_valid_issue(issue, result, details)
            self.stats["valid"] += 1
        else:
            logger.info(f"INVALID/NOISE: {result.reason}")
            self._handle_invalid_issue(issue, result)
            self.stats["invalid"] += 1
        
        # Mark as processed
        if not self.dry_run:
            self._save_processed(issue.id)
    
    def _analyze_issue(self, issue: SentryIssue, details: dict) -> TriageResult:
        """
        Analyze issue to determine if it's a valid bug.
        
        TODO: Integrate with actual SoftwareEngineer MetaGPT role
        for more intelligent analysis.
        """
        title = issue.title
        culprit = issue.culprit
        
        # Get stacktrace if available
        stacktrace = ""
        latest_event = details.get("latestEvent", {})
        if latest_event:
            entries = latest_event.get("entries", [])
            for entry in entries:
                if entry.get("type") == "exception":
                    data = entry.get("data", {})
                    values = data.get("values", [])
                    for exc in values:
                        frames = exc.get("stacktrace", {}).get("frames", [])
                        for frame in frames[-5:]:  # Last 5 frames
                            stacktrace += f"{frame.get('filename', '?')}:{frame.get('lineno', '?')} in {frame.get('function', '?')}\n"
        
        # Check for invalid patterns (noise)
        for pattern in INVALID_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE) or re.search(pattern, culprit, re.IGNORECASE):
                return TriageResult(
                    issue=issue,
                    is_valid=False,
                    reason=f"Matches invalid pattern: {pattern}",
                    severity="low",
                    suggested_title="",
                    suggested_labels=[],
                    root_cause_hypothesis="Likely transient or third-party issue",
                )
        
        # Check for valid patterns (real bugs)
        for pattern in VALID_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE):
                severity = self._determine_severity(issue)
                labels = self._suggest_labels(issue, details)
                
                return TriageResult(
                    issue=issue,
                    is_valid=True,
                    reason=f"Matches valid bug pattern: {pattern}",
                    severity=severity,
                    suggested_title=self._generate_title(issue),
                    suggested_labels=labels,
                    root_cause_hypothesis=self._hypothesize_root_cause(issue, stacktrace),
                )
        
        # Default: Check frequency and user impact
        if issue.count > 50 or issue.user_count > 10:
            return TriageResult(
                issue=issue,
                is_valid=True,
                reason=f"High impact: {issue.count} occurrences, {issue.user_count} users",
                severity="high" if issue.user_count > 10 else "medium",
                suggested_title=self._generate_title(issue),
                suggested_labels=self._suggest_labels(issue, details),
                root_cause_hypothesis="Requires investigation - high frequency",
            )
        
        # Low frequency, no matching patterns - likely noise
        return TriageResult(
            issue=issue,
            is_valid=False,
            reason=f"Low impact ({issue.count} occurrences) and no bug patterns",
            severity="low",
            suggested_title="",
            suggested_labels=[],
            root_cause_hypothesis="Likely edge case or user environment issue",
        )
    
    def _determine_severity(self, issue: SentryIssue) -> str:
        """Determine issue severity based on impact."""
        if issue.user_count > 100 or issue.count > 1000:
            return "critical"
        elif issue.user_count > 10 or issue.count > 100:
            return "high"
        elif issue.user_count > 5 or issue.count > 20:
            return "medium"
        return "low"
    
    def _suggest_labels(self, issue: SentryIssue, details: dict) -> list[str]:
        """Suggest GitHub labels for the issue."""
        labels = ["bug", "sentry"]
        
        # Add project label
        if "extension" in issue.project:
            labels.append("extension")
        elif "api" in issue.project:
            labels.append("api")
        
        # Add severity
        severity = self._determine_severity(issue)
        if severity in ["critical", "high"]:
            labels.append(f"priority:{severity}")
        
        return labels
    
    def _generate_title(self, issue: SentryIssue) -> str:
        """Generate a GitHub issue title."""
        # Clean up the Sentry title
        title = issue.title
        
        # Remove stack trace details
        title = re.sub(r" at .*$", "", title)
        
        # Add project prefix
        project_prefix = "Extension" if "extension" in issue.project else "API"
        
        return f"[{project_prefix}] {title}"
    
    def _hypothesize_root_cause(self, issue: SentryIssue, stacktrace: str) -> str:
        """Generate a hypothesis about the root cause."""
        title = issue.title.lower()
        
        if "undefined" in title or "null" in title:
            return "Likely missing null check or undefined variable access"
        elif "not a function" in title:
            return "Method called on wrong object type or missing import"
        elif "maximum call stack" in title:
            return "Infinite recursion or circular dependency"
        elif "network" in title.lower():
            return "Network connectivity or API availability issue"
        
        return "Requires code investigation"
    
    def _handle_valid_issue(
        self,
        issue: SentryIssue,
        result: TriageResult,
        details: dict,
    ) -> None:
        """Create GitHub issue for valid bug."""
        # Build issue body
        body = f"""## Sentry Issue

**Sentry Link:** {issue.permalink}
**Project:** {issue.project}
**First Seen:** {issue.first_seen}
**Occurrences:** {issue.count}
**Users Affected:** {issue.user_count}

## Error

```
{issue.title}
```

**Culprit:** `{issue.culprit}`

## Root Cause Hypothesis

{result.root_cause_hypothesis}

## Severity

**{result.severity.upper()}** - {result.reason}

---
*This issue was automatically created by Sentry Triage Bot.*
"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create GitHub issue:")
            logger.info(f"  Title: {result.suggested_title}")
            logger.info(f"  Labels: {result.suggested_labels}")
            logger.info(f"  Sentry: {issue.permalink}")
        else:
            # Create GitHub issue using gh CLI
            try:
                labels_arg = ",".join(result.suggested_labels)
                cmd = [
                    "gh", "issue", "create",
                    "--repo", GITHUB_REPO,
                    "--title", result.suggested_title,
                    "--body", body,
                    "--label", labels_arg,
                ]
                
                result_output = subprocess.run(cmd, capture_output=True, text=True)
                
                if result_output.returncode == 0:
                    gh_url = result_output.stdout.strip()
                    logger.info(f"Created GitHub issue: {gh_url}")
                    
                    # Add comment to Sentry linking to GitHub
                    gh_issue_num = gh_url.split("/")[-1]
                    self.sentry.add_comment(
                        issue.id,
                        f"GitHub issue created: {gh_url}\n\nThis issue is being tracked and will be fixed."
                    )
                else:
                    logger.error(f"Failed to create GitHub issue: {result_output.stderr}")
                    
            except Exception as e:
                logger.error(f"Error creating GitHub issue: {e}")
    
    def _handle_invalid_issue(self, issue: SentryIssue, result: TriageResult) -> None:
        """Resolve invalid issue in Sentry with comment."""
        comment = f"""## Auto-Triage: Resolved as Noise

**Reason:** {result.reason}

**Analysis:** {result.root_cause_hypothesis}

This issue has been automatically resolved by the Sentry Triage Bot.
If you believe this is a real bug, please reopen and add the `needs-investigation` tag.

---
*Automated by Sentry Triage Bot*
"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would resolve Sentry issue {issue.short_id}")
            logger.info(f"  Reason: {result.reason}")
        else:
            try:
                # Add comment explaining resolution
                self.sentry.add_comment(issue.id, comment)
                
                # Ignore for 30 days (in case it recurs frequently)
                self.sentry.ignore_issue(issue.id, ignore_duration=43200)  # 30 days in minutes
                
                logger.info(f"Resolved Sentry issue: {issue.short_id}")
                
            except Exception as e:
                logger.error(f"Error resolving issue: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Triage Sentry issues and create GitHub issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create issues or resolve, just analyze",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon, triaging every N hours",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=12,
        help="Triage interval in hours (default: 12)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=12,
        help="Look at issues from last N hours (default: 12)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum issues to process (default: 20)",
    )
    
    args = parser.parse_args()
    
    # Initialize Sentry connector
    try:
        sentry = SentryConnector()
    except ValueError as e:
        logger.error(f"Error: {e}")
        logger.error("Set SENTRY_AUTH_TOKEN environment variable.")
        sys.exit(1)
    
    # Initialize triager
    triager = SentryTriager(sentry=sentry, dry_run=args.dry_run)
    
    if args.daemon:
        interval_seconds = args.interval * 3600
        logger.info(f"Starting daemon mode, triaging every {args.interval}h...")
        
        while True:
            triager.triage_issues(hours=args.hours, limit=args.limit)
            logger.info(f"Sleeping {args.interval}h until next triage...")
            time.sleep(interval_seconds)
    else:
        triager.triage_issues(hours=args.hours, limit=args.limit)


if __name__ == "__main__":
    main()
