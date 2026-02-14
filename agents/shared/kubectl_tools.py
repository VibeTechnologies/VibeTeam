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
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default namespace for VibeTeam internal infrastructure
DEFAULT_NAMESPACE = "vibeteam"

# Production namespace for customer-facing services
PRODUCTION_NAMESPACE = "vibe"

# Key deployments to monitor per namespace
KEY_DEPLOYMENTS = [
    "vibeteam-gateway",
    "openhands-svc",
    "autogen-svc",
    "crewai-svc",
]

PRODUCTION_DEPLOYMENTS = [
    "user-portal",
    "stripe-service",
    "litellm",
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
    timeout: int = 10,
) -> KubectlResult:
    """Get recent logs from a deployment.

    Uses a shorter timeout (10s) since log fetching is non-critical
    and deployments that don't exist will hang until timeout.
    """
    return run_kubectl(
        [
            "logs",
            f"deployment/{deployment}",
            "-n",
            namespace,
            f"--tail={tail}",
            "--timestamps",
        ],
        timeout=timeout,
    )


def get_rollout_history(
    deployment: str,
    namespace: str = DEFAULT_NAMESPACE,
    timeout: int = 10,
) -> KubectlResult:
    """Get rollout history for a deployment.

    Uses a shorter timeout (10s) since rollout history is supplementary.
    """
    return run_kubectl(
        [
            "rollout",
            "history",
            f"deployment/{deployment}",
            "-n",
            namespace,
        ],
        timeout=timeout,
    )


def _extract_deployment_names(pods_output: str) -> set[str]:
    """
    Extract deployment names from 'kubectl get pods' output.

    Parses pod names like 'vibeteam-gateway-7f589ff7f9-7zvvp' to extract
    the deployment prefix (e.g., 'vibeteam-gateway'). Uses the convention
    that pod names are '{deployment}-{replicaset-hash}-{pod-hash}'.

    Returns a set of deployment name prefixes found in the pods output.
    """
    names: set[str] = set()
    for line in pods_output.strip().split("\n"):
        if not line or line.startswith("NAME"):
            continue
        pod_name = line.split()[0] if line.split() else ""
        # Pod name format: {deployment}-{rs-hash}-{pod-hash}
        # Remove the last two segments (pod-hash and rs-hash)
        parts = pod_name.rsplit("-", 2)
        if len(parts) >= 3:
            names.add(parts[0])
    return names


def get_kubectl_context(
    namespace: str = DEFAULT_NAMESPACE,
    deployments: list[str] | None = None,
    log_tail: int = 50,
) -> str:
    """
    Fetch comprehensive kubectl context for agent injection.

    Two-phase approach for minimal latency:
    1. Fetch pods first to discover which deployments actually exist
    2. Fetch events, logs, and rollout history in parallel (only for existing deployments)

    Previously: 7 sequential calls x 30s timeout = up to 210s worst case.
    Now: ~1s (pods) + ~10s (parallel logs/events) = ~11s worst case.

    Non-existent deployments (e.g., autogen-svc, crewai-svc when not running)
    are automatically skipped, avoiding hanging until timeout.

    Args:
        namespace: Kubernetes namespace
        deployments: List of deployments to get logs for (default: KEY_DEPLOYMENTS)
        log_tail: Number of log lines to fetch per deployment

    Returns:
        Formatted string with kubectl context
    """
    if deployments is None:
        deployments = KEY_DEPLOYMENTS

    t0 = time.monotonic()

    # Phase 1: Fetch pods first (fast, ~1s) to discover which deployments exist.
    # This avoids wasting time on kubectl logs for non-existent deployments
    # (which hang until the full timeout).
    pods_result = get_pods(namespace)

    # Filter deployments to only those that have running pods
    if pods_result.success and pods_result.stdout.strip():
        active_deployments = _extract_deployment_names(pods_result.stdout)
        filtered = [d for d in deployments if d in active_deployments]
        skipped = set(deployments) - set(filtered)
        if skipped:
            logger.info(f"Skipping kubectl logs for non-existent deployments: {skipped}")
        deployments = filtered

    # Phase 2: Fetch events, logs, and rollout history in parallel
    futures: dict = {}
    with ThreadPoolExecutor(max_workers=1 + len(deployments)) as pool:
        futures["events"] = pool.submit(get_events, namespace)
        for dep in deployments:
            futures[f"logs:{dep}"] = pool.submit(get_deployment_logs, dep, namespace, log_tail)
        # Only fetch rollout history for vibeteam namespace (where gateway runs)
        if namespace == DEFAULT_NAMESPACE:
            futures["rollout:vibeteam-gateway"] = pool.submit(
                get_rollout_history, "vibeteam-gateway", namespace
            )

        # Collect results
        results: dict[str, KubectlResult] = {}
        for key, fut in futures.items():
            try:
                results[key] = fut.result(timeout=15)
            except Exception as e:
                results[key] = KubectlResult(command=key, stdout="", stderr=str(e), return_code=-1)

    # Store pods result alongside the parallel results
    results["pods"] = pods_result

    elapsed = time.monotonic() - t0
    logger.info(
        f"[TIMING] kubectl context fetched in {elapsed:.1f}s ({len(deployments)} deployments)"
    )

    # Format output
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

    # Pods
    pods_result = results["pods"]
    sections.append(f"### kubectl get pods -n {namespace}")
    sections.append("```")
    if pods_result.success:
        sections.append(pods_result.stdout.strip() or "(no pods found)")
    else:
        sections.append(f"Error: {pods_result.stderr}")
    sections.append("```")
    sections.append("")

    # Events
    events_result = results["events"]
    sections.append(f"### kubectl get events -n {namespace} (warnings/errors)")
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

    # Deployment logs
    for deployment in deployments:
        logs_result = results[f"logs:{deployment}"]
        sections.append(
            f"### kubectl logs deployment/{deployment} -n {namespace} --tail={log_tail}"
        )
        sections.append("```")
        if logs_result.success:
            log_lines = logs_result.stdout.strip().split("\n")
            if len(log_lines) > log_tail:
                log_lines = log_lines[-log_tail:]
            sections.append("\n".join(log_lines) or "(no logs)")
        else:
            sections.append(f"Error: {logs_result.stderr}")
        sections.append("```")
        sections.append("")

    # Rollout history (only for vibeteam namespace where gateway runs)
    if namespace == DEFAULT_NAMESPACE:
        history_result = results.get("rollout:vibeteam-gateway")
        if history_result:
            sections.append("### kubectl rollout history deployment/vibeteam-gateway")
            sections.append("```")
            if history_result.success:
                sections.append(history_result.stdout.strip() or "(no history)")
            else:
                sections.append(f"Error: {history_result.stderr}")
            sections.append("```")

    return "\n".join(sections)


def get_multi_namespace_context(log_tail: int = 50) -> str:
    """
    Fetch kubectl context for both production (vibe) and internal (vibeteam) namespaces.

    This gives agents visibility into customer-facing services AND internal
    agent infrastructure in a single pre-injection, eliminating the namespace
    knowledge gap where agents only saw vibeteam data.

    Args:
        log_tail: Number of log lines to fetch per deployment

    Returns:
        Formatted string with kubectl context for both namespaces
    """
    # Fetch both namespaces
    vibeteam_context = get_kubectl_context(
        namespace=DEFAULT_NAMESPACE,
        deployments=KEY_DEPLOYMENTS,
        log_tail=log_tail,
    )
    production_context = get_kubectl_context(
        namespace=PRODUCTION_NAMESPACE,
        deployments=PRODUCTION_DEPLOYMENTS,
        log_tail=log_tail,
    )

    # Combine with clear separation
    return vibeteam_context + "\n\n---\n\n" + production_context


# Convenience function matching other tools' patterns
def get_k8s_context(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Alias for get_kubectl_context for consistency with other tools."""
    return get_kubectl_context(namespace=namespace)
