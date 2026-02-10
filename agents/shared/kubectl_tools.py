"""
Shared kubectl tool functions for all agent frameworks.

Pre-fetches Kubernetes cluster state for context injection.
This eliminates the need for agents to run kubectl commands,
significantly reducing response time.

Requirements:
    - kubectl must be installed and configured
    - KUBECONFIG environment variable or ~/.kube/config must be set
"""

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default namespace for VibeTeam
DEFAULT_NAMESPACE = "vibeteam"

# Key deployments to monitor
KEY_DEPLOYMENTS = [
    "vibeteam-gateway",
    "openhands-svc",
    "autogen-svc",
    "crewai-svc",
]


@dataclass
class KubectlResult:
    """Result from a kubectl command."""

    command: str
    stdout: str
    stderr: str
    return_code: int

    @property
    def success(self) -> bool:
        return self.return_code == 0


def run_kubectl(args: list[str], timeout: int = 30) -> KubectlResult:
    """
    Run a kubectl command and return the result.

    Args:
        args: Command arguments (e.g., ["get", "pods", "-n", "vibeteam"])
        timeout: Command timeout in seconds

    Returns:
        KubectlResult with stdout, stderr, and return code
    """
    cmd = ["kubectl"] + args
    cmd_str = " ".join(cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return KubectlResult(
            command=cmd_str,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return KubectlResult(
            command=cmd_str,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            return_code=-1,
        )
    except FileNotFoundError:
        return KubectlResult(
            command=cmd_str,
            stdout="",
            stderr="kubectl not found in PATH",
            return_code=-1,
        )
    except Exception as e:
        return KubectlResult(
            command=cmd_str,
            stdout="",
            stderr=str(e),
            return_code=-1,
        )


def get_pods(namespace: str = DEFAULT_NAMESPACE) -> KubectlResult:
    """Get pod status in namespace."""
    return run_kubectl(["get", "pods", "-n", namespace, "-o", "wide"])


def get_events(namespace: str = DEFAULT_NAMESPACE, limit: int = 20) -> KubectlResult:
    """Get recent events in namespace."""
    return run_kubectl(
        [
            "get",
            "events",
            "-n",
            namespace,
            "--sort-by=.lastTimestamp",
            "--field-selector=type!=Normal",  # Only warning/error events
        ]
    )


def get_deployment_logs(
    deployment: str,
    namespace: str = DEFAULT_NAMESPACE,
    tail: int = 50,
) -> KubectlResult:
    """Get recent logs from a deployment."""
    return run_kubectl(
        [
            "logs",
            f"deployment/{deployment}",
            "-n",
            namespace,
            f"--tail={tail}",
            "--timestamps",
        ]
    )


def get_rollout_history(
    deployment: str,
    namespace: str = DEFAULT_NAMESPACE,
) -> KubectlResult:
    """Get rollout history for a deployment."""
    return run_kubectl(
        [
            "rollout",
            "history",
            f"deployment/{deployment}",
            "-n",
            namespace,
        ]
    )


def get_kubectl_context(
    namespace: str = DEFAULT_NAMESPACE,
    deployments: list[str] | None = None,
    log_tail: int = 50,
) -> str:
    """
    Fetch comprehensive kubectl context for agent injection.

    This pre-fetches common kubectl data to reduce agent response time.
    The agent no longer needs to run these commands individually.

    Args:
        namespace: Kubernetes namespace
        deployments: List of deployments to get logs for (default: KEY_DEPLOYMENTS)
        log_tail: Number of log lines to fetch per deployment

    Returns:
        Formatted string with kubectl context
    """
    if deployments is None:
        deployments = KEY_DEPLOYMENTS

    sections = []
    sections.append("## Pre-Fetched Kubernetes Context")
    sections.append("")
    sections.append("The following kubectl data has been pre-fetched for your investigation.")
    sections.append(
        "You do NOT need to run these commands again - the data is current as of this request."
    )
    sections.append("")
    sections.append("**INTERPRETATION GUIDE:**")
    sections.append("- Probe failures during rolling updates are NORMAL and self-resolve")
    sections.append(
        "- Check if pods show 'Running' with no restarts - that means they're HEALTHY NOW"
    )
    sections.append(
        "- Old events (>5 min ago) with currently running pods = RECOVERED, not ongoing issue"
    )
    sections.append("- Focus on: CrashLoopBackOff, OOMKilled, or errors in actual logs")
    sections.append("")

    # Get pods
    pods_result = get_pods(namespace)
    sections.append("### kubectl get pods -n vibeteam")
    sections.append("```")
    if pods_result.success:
        sections.append(pods_result.stdout.strip() or "(no pods found)")
    else:
        sections.append(f"Error: {pods_result.stderr}")
    sections.append("```")
    sections.append("")

    # Get events (warnings/errors only)
    events_result = get_events(namespace)
    sections.append("### kubectl get events -n vibeteam (warnings/errors)")
    sections.append("```")
    if events_result.success:
        events_output = events_result.stdout.strip()
        if events_output:
            sections.append(events_output)
        else:
            sections.append("(no warning/error events found)")
    else:
        sections.append(f"Error: {events_result.stderr}")
    sections.append("```")
    sections.append("")

    # Get logs for key deployments
    for deployment in deployments:
        logs_result = get_deployment_logs(deployment, namespace, log_tail)
        sections.append(f"### kubectl logs deployment/{deployment} -n vibeteam --tail={log_tail}")
        sections.append("```")
        if logs_result.success:
            # Truncate very long logs
            log_lines = logs_result.stdout.strip().split("\n")
            if len(log_lines) > log_tail:
                log_lines = log_lines[-log_tail:]
            sections.append("\n".join(log_lines) or "(no logs)")
        else:
            sections.append(f"Error: {logs_result.stderr}")
        sections.append("```")
        sections.append("")

    # Get rollout history for gateway
    history_result = get_rollout_history("vibeteam-gateway", namespace)
    sections.append("### kubectl rollout history deployment/vibeteam-gateway")
    sections.append("```")
    if history_result.success:
        sections.append(history_result.stdout.strip() or "(no history)")
    else:
        sections.append(f"Error: {history_result.stderr}")
    sections.append("```")

    return "\n".join(sections)


# Convenience function matching other tools' patterns
def get_k8s_context(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Alias for get_kubectl_context for consistency with other tools."""
    return get_kubectl_context(namespace=namespace)
