#!/usr/bin/env python3
"""
VibeTeam Readiness Check Script

Validates all infrastructure is operational before running VibeTeam agents.

Usage:
    python scripts/check_readiness.py           # Standard checks
    python scripts/check_readiness.py --quick   # Health endpoints only
    python scripts/check_readiness.py --full    # Everything including k8s, Sentry, Langfuse

Exit codes:
    0 = GREEN (all systems go)
    1 = YELLOW (degraded, non-critical issues)
    2 = RED (not ready, critical failures)
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

# Add connectors directory to path for direct imports (avoid metagpt dependency)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CONNECTORS_DIR = os.path.join(PROJECT_ROOT, "vibeteam", "connectors")
sys.path.insert(0, CONNECTORS_DIR)

# Import connectors directly
from health import HealthConnector

# Global quiet flag for JSON output mode
QUIET = False


@dataclass
class CheckResult:
    """Result of a single check."""

    name: str
    status: str  # OK, WARN, FAIL
    message: str
    details: str = ""
    critical: bool = False


@dataclass
class ReadinessReport:
    """Overall readiness report."""

    status: str = "GREEN"  # GREEN, YELLOW, RED
    checks: list[CheckResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    def add_check(self, check: CheckResult) -> None:
        """Add a check result and update overall status."""
        self.checks.append(check)

        if check.status == "FAIL":
            if check.critical:
                self.status = "RED"
                self.issues.append(f"[CRITICAL] {check.name}: {check.message}")
            elif self.status != "RED":
                self.status = "YELLOW"
                self.issues.append(f"{check.name}: {check.message}")
        elif check.status == "WARN":
            if self.status == "GREEN":
                self.status = "YELLOW"
            self.issues.append(f"{check.name}: {check.message}")


def print_header() -> None:
    """Print report header."""
    print("=" * 80)
    print("                       VIBETEAM READINESS CHECK")
    print("=" * 80)
    print()
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC]")
    print()


def print_section(title: str) -> None:
    """Print section header."""
    if QUIET:
        return
    print(f"\n{title}")
    print("-" * len(title))


def print_check(check: CheckResult) -> None:
    """Print a single check result."""
    if QUIET:
        return
    status_icon = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    icon = status_icon.get(check.status, "[???]")
    print(f"{icon} {check.name:<20} {check.message}")
    if check.details:
        for line in check.details.split("\n"):
            print(f"      {line}")


def print_footer(report: ReadinessReport) -> None:
    """Print report footer."""
    print()
    print("=" * 80)
    status_text = {
        "GREEN": "GREEN (All Systems Go)",
        "YELLOW": "YELLOW (Degraded)",
        "RED": "RED (Not Ready)",
    }
    print(f"STATUS: {status_text.get(report.status, report.status)}")
    print("=" * 80)

    if report.issues:
        print("\nIssues:")
        for issue in report.issues:
            print(f"  - {issue}")
    print()


# =============================================================================
# Check Functions
# =============================================================================


def check_health_endpoints(report: ReadinessReport) -> None:
    """Check all health endpoints using HealthConnector."""
    print_section("INFRASTRUCTURE HEALTH")

    connector = HealthConnector()
    health = connector.check_all()

    for check in health.checks:
        # Find endpoint config to get name and critical flag
        endpoint = next(
            (e for e in connector.endpoints if e["url"] == check.url),
            {"name": check.url, "critical": False},
        )
        name = endpoint.get("name", check.url)
        critical = endpoint.get("critical", False)

        # For API endpoints, 401 means server is up (just needs auth)
        is_api_endpoint = "api" in name.lower() or "api" in check.url.lower()
        if check.status == "healthy" or (is_api_endpoint and check.status_code == 401):
            result = CheckResult(
                name=name,
                status="OK",
                message=f"{check.url} ({check.latency_ms:.0f}ms)",
                critical=critical,
            )
        elif check.status == "degraded":
            result = CheckResult(
                name=name,
                status="WARN",
                message=f"{check.url} (status {check.status_code})",
                critical=critical,
            )
        else:  # down
            result = CheckResult(
                name=name,
                status="FAIL",
                message=f"{check.url} - {check.error or 'No response'}",
                critical=critical,
            )

        print_check(result)
        report.add_check(result)


def check_llm_availability(report: ReadinessReport) -> None:
    """Test LLM availability with a simple prompt."""
    print_section("LLM AVAILABILITY")

    # Check required env vars - support both naming conventions
    api_key = os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")
    api_base = os.environ.get("AZURE_API_BASE") or os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-2")
    model_name = f"azure/{deployment}"

    if not api_key or not api_base:
        result = CheckResult(
            name=model_name,
            status="WARN",
            message="AZURE_API_KEY or AZURE_API_BASE not set",
            critical=False,
        )
        print_check(result)
        report.add_check(result)
        return

    try:
        import litellm

        start = datetime.now(timezone.utc)
        response = litellm.completion(
            model=model_name,
            messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
            api_base=api_base,
            api_key=api_key,
            api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
            max_tokens=50,
            timeout=120,  # 120 second timeout for LLM
        )
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        tokens = response.usage.total_tokens if response.usage else 0

        result = CheckResult(
            name=model_name,
            status="OK",
            message=f"Response in {elapsed:.1f}s, {tokens} tokens",
            critical=True,
        )
    except Exception as e:
        result = CheckResult(
            name=model_name,
            status="FAIL",
            message=f"LLM error: {str(e)[:80]}",
            critical=True,
        )

    print_check(result)
    report.add_check(result)


def check_github_api(report: ReadinessReport) -> None:
    """Test GitHub API access."""
    print_section("GITHUB")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        result = CheckResult(
            name="GitHub API",
            status="WARN",
            message="GITHUB_TOKEN not set",
            critical=False,
        )
        print_check(result)
        report.add_check(result)
        return

    try:
        from github import GitHubConnector

        connector = GitHubConnector(token=token)
        issue = connector.get_issue(322)

        # Count requests in the table
        _, requests = connector.get_customer_requests_table()

        result = CheckResult(
            name="Issue #322",
            status="OK",
            message=f"Accessible, {len(requests)} customer requests",
            critical=False,
        )
    except Exception as e:
        result = CheckResult(
            name="GitHub API",
            status="FAIL",
            message=f"Error: {str(e)[:60]}",
            critical=True,
        )

    print_check(result)
    report.add_check(result)


def check_kubernetes(report: ReadinessReport, namespace: str = "vibe") -> None:
    """Check Kubernetes pod status."""
    print_section(f"KUBERNETES ({namespace} namespace)")

    try:
        # Check if kubectl is available
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            if "Unable to connect" in result.stderr or "connection refused" in result.stderr:
                check = CheckResult(
                    name="kubectl",
                    status="WARN",
                    message="Cannot connect to cluster (kubeconfig not set?)",
                    critical=False,
                )
            else:
                check = CheckResult(
                    name="kubectl",
                    status="WARN",
                    message=f"kubectl error: {result.stderr[:60]}",
                    critical=False,
                )
            print_check(check)
            report.add_check(check)
            return

        pods = json.loads(result.stdout)

        for pod in pods.get("items", []):
            name = pod["metadata"]["name"]
            short_name = name[:25] + "..." if len(name) > 25 else name

            # Get status
            phase = pod["status"].get("phase", "Unknown")
            container_statuses = pod["status"].get("containerStatuses", [])

            restarts = 0
            ready = True
            crash_loop = False

            for cs in container_statuses:
                restarts += cs.get("restartCount", 0)
                if not cs.get("ready", False):
                    ready = False
                waiting = cs.get("state", {}).get("waiting", {})
                if waiting.get("reason") == "CrashLoopBackOff":
                    crash_loop = True

            if crash_loop:
                check = CheckResult(
                    name=short_name,
                    status="FAIL",
                    message=f"CrashLoopBackOff ({restarts} restarts)",
                    critical=True,
                )
            elif not ready:
                check = CheckResult(
                    name=short_name,
                    status="WARN",
                    message=f"Not ready (phase: {phase})",
                    critical=False,
                )
            elif restarts > 5:
                check = CheckResult(
                    name=short_name,
                    status="WARN",
                    message=f"Running, {restarts} restarts",
                    critical=False,
                )
            else:
                check = CheckResult(
                    name=short_name,
                    status="OK",
                    message=f"Running, {restarts} restarts",
                    critical=False,
                )

            print_check(check)
            report.add_check(check)

    except subprocess.TimeoutExpired:
        check = CheckResult(
            name="kubectl",
            status="WARN",
            message="kubectl timed out",
            critical=False,
        )
        print_check(check)
        report.add_check(check)
    except FileNotFoundError:
        check = CheckResult(
            name="kubectl",
            status="WARN",
            message="kubectl not installed",
            critical=False,
        )
        print_check(check)
        report.add_check(check)
    except Exception as e:
        check = CheckResult(
            name="kubectl",
            status="WARN",
            message=f"Error: {str(e)[:60]}",
            critical=False,
        )
        print_check(check)
        report.add_check(check)


def check_sentry(report: ReadinessReport) -> None:
    """Check Sentry for unresolved issues."""
    print_section("SENTRY")

    token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not token:
        check = CheckResult(
            name="Sentry",
            status="WARN",
            message="SENTRY_AUTH_TOKEN not set (skipped)",
            critical=False,
        )
        print_check(check)
        report.add_check(check)
        return

    try:
        from sentry import SentryConnector

        connector = SentryConnector(auth_token=token)
        issues = connector.fetch_unresolved_issues(hours=24, limit=50)

        # Count by level
        error_count = sum(1 for i in issues if i.level == "error")
        warning_count = sum(1 for i in issues if i.level == "warning")
        high_frequency = [i for i in issues if i.count > 100]

        if high_frequency:
            check = CheckResult(
                name="Sentry",
                status="WARN",
                message=f"{len(high_frequency)} high-frequency issues (>100 events)",
                details="\n".join(f"{i.short_id}: {i.title[:40]}" for i in high_frequency[:3]),
                critical=False,
            )
        elif error_count > 10:
            check = CheckResult(
                name="Sentry",
                status="WARN",
                message=f"{error_count} errors, {warning_count} warnings (24h)",
                critical=False,
            )
        else:
            check = CheckResult(
                name="Sentry",
                status="OK",
                message=f"{error_count} errors, {warning_count} warnings (24h)",
                critical=False,
            )

    except Exception as e:
        check = CheckResult(
            name="Sentry",
            status="WARN",
            message=f"Error: {str(e)[:60]}",
            critical=False,
        )

    print_check(check)
    report.add_check(check)


def check_langfuse(report: ReadinessReport) -> None:
    """Check Langfuse for anomalies."""
    print_section("LANGFUSE")

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        check = CheckResult(
            name="Langfuse",
            status="WARN",
            message="LANGFUSE keys not set (skipped)",
            critical=False,
        )
        print_check(check)
        report.add_check(check)
        return

    try:
        from langfuse import LangfuseConnector

        connector = LangfuseConnector(public_key=public_key, secret_key=secret_key)

        # Health check first
        if not connector.health_check():
            check = CheckResult(
                name="Langfuse",
                status="WARN",
                message="Health endpoint not responding",
                critical=False,
            )
            print_check(check)
            report.add_check(check)
            return

        # Get stats and anomalies
        stats = connector.get_stats(hours=1)
        anomalies = connector.detect_anomalies(hours=1)

        if anomalies:
            critical_anomalies = [a for a in anomalies if a.severity == "critical"]
            if critical_anomalies:
                check = CheckResult(
                    name="Langfuse",
                    status="WARN",
                    message=f"{len(anomalies)} anomalies ({len(critical_anomalies)} critical)",
                    details="\n".join(f"{a.type}: {a.message[:50]}" for a in anomalies[:3]),
                    critical=False,
                )
            else:
                check = CheckResult(
                    name="Langfuse",
                    status="WARN",
                    message=f"{len(anomalies)} anomalies detected",
                    critical=False,
                )
        else:
            check = CheckResult(
                name="Langfuse",
                status="OK",
                message=f"{stats.total_traces} traces, {stats.error_rate:.1%} error rate (1h)",
                critical=False,
            )

    except Exception as e:
        check = CheckResult(
            name="Langfuse",
            status="WARN",
            message=f"Error: {str(e)[:60]}",
            critical=False,
        )

    print_check(check)
    report.add_check(check)


def check_docs_chat(report: ReadinessReport) -> None:
    """Test the docs chat API."""
    print_section("DOCS CHAT API")

    try:
        response = requests.post(
            "https://docs.vibebrowser.app/api/chat",
            json={"messages": [{"role": "user", "content": "What is VibeBrowser?"}]},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            content_len = len(data.get("content", ""))
            check = CheckResult(
                name="Docs Chat",
                status="OK",
                message=f"Response OK ({content_len} chars)",
                critical=False,
            )
        else:
            check = CheckResult(
                name="Docs Chat",
                status="WARN",
                message=f"Status {response.status_code}",
                critical=False,
            )

    except requests.exceptions.Timeout:
        check = CheckResult(
            name="Docs Chat",
            status="WARN",
            message="Request timed out (30s)",
            critical=False,
        )
    except Exception as e:
        check = CheckResult(
            name="Docs Chat",
            status="WARN",
            message=f"Error: {str(e)[:60]}",
            critical=False,
        )

    print_check(check)
    report.add_check(check)


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    """Run readiness checks and return exit code."""
    parser = argparse.ArgumentParser(description="VibeTeam Readiness Check")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick check: health endpoints only",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full check: include k8s, Sentry, Langfuse, docs chat",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )

    args = parser.parse_args()

    # Set global quiet flag for JSON mode
    global QUIET
    QUIET = args.json

    report = ReadinessReport()

    if not args.json:
        print_header()

    # Always run health checks
    check_health_endpoints(report)

    if not args.quick:
        # Standard checks
        check_llm_availability(report)
        check_github_api(report)

    if args.full:
        # Full checks
        check_kubernetes(report, "vibe")
        check_kubernetes(report, "vibe-dev")
        check_sentry(report)
        check_langfuse(report)
        check_docs_chat(report)

    if args.json:
        output = {
            "status": report.status,
            "timestamp": report.timestamp,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "critical": c.critical,
                }
                for c in report.checks
            ],
            "issues": report.issues,
        }
        print(json.dumps(output, indent=2))
    else:
        print_footer(report)

    # Return exit code based on status
    exit_codes = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    return exit_codes.get(report.status, 2)


if __name__ == "__main__":
    sys.exit(main())
