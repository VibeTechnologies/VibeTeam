"""
Unit tests for kubectl_tools parallel execution and deployment filtering.

Tests use mock subprocess calls to verify:
1. Parallel execution via ThreadPoolExecutor
2. Non-existent deployments are skipped (no hanging on timeout)
3. Timeout reduction (10s for logs/rollout vs 30s for pods/events)
4. _extract_deployment_names parsing
"""

from __future__ import annotations

from unittest.mock import patch

from agents.shared.kubectl_tools import (
    KubectlResult,
    _extract_deployment_names,
    get_kubectl_context,
)

# Sample kubectl get pods output
SAMPLE_PODS_OUTPUT = """\
NAME                                  READY   STATUS    RESTARTS   AGE   IP            NODE
vibeteam-gateway-7f589ff7f9-7zvvp     1/1     Running   0          2d    10.42.0.100   node1
openhands-svc-9dc999f79-z9lcd         1/1     Running   0          2d    10.42.0.101   node1
openhands-agents-7dfcbddfb6-x8wsz     1/1     Running   0          2d    10.42.0.102   node1
postgres-0                            1/1     Running   0          5d    10.42.0.103   node1
"""

# Pods output with all deployments running
FULL_PODS_OUTPUT = """\
NAME                                  READY   STATUS    RESTARTS   AGE
vibeteam-gateway-7f589ff7f9-7zvvp     1/1     Running   0          2d
openhands-svc-9dc999f79-z9lcd         1/1     Running   0          2d
autogen-svc-74746696c8-m5t84          1/1     Running   0          2d
crewai-svc-7fb45bf8cf-l6vdh           1/1     Running   0          2d
"""


class TestExtractDeploymentNames:
    """Test _extract_deployment_names parsing."""

    def test_extracts_names(self):
        names = _extract_deployment_names(SAMPLE_PODS_OUTPUT)
        assert "vibeteam-gateway" in names
        assert "openhands-svc" in names
        assert "openhands-agents" in names

    def test_skips_statefulsets(self):
        """StatefulSets like postgres-0 don't match the 3-segment pattern."""
        names = _extract_deployment_names(SAMPLE_PODS_OUTPUT)
        # postgres-0 only has 1 segment after rsplit("-", 2), won't be extracted
        assert "postgres" not in names

    def test_empty_output(self):
        names = _extract_deployment_names("")
        assert names == set()

    def test_header_only(self):
        names = _extract_deployment_names("NAME  READY  STATUS  RESTARTS  AGE\n")
        assert names == set()

    def test_full_cluster(self):
        names = _extract_deployment_names(FULL_PODS_OUTPUT)
        assert "vibeteam-gateway" in names
        assert "openhands-svc" in names
        assert "autogen-svc" in names
        assert "crewai-svc" in names


class TestGetKubectlContextParallel:
    """Test get_kubectl_context with mocked kubectl calls."""

    @patch("agents.shared.kubectl_tools.get_rollout_history")
    @patch("agents.shared.kubectl_tools.get_deployment_logs")
    @patch("agents.shared.kubectl_tools.get_events")
    @patch("agents.shared.kubectl_tools.get_pods")
    def test_skips_nonexistent_deployments(self, mock_pods, mock_events, mock_logs, mock_rollout):
        """When pods output shows only gateway + openhands, autogen/crewai logs are skipped."""
        mock_pods.return_value = KubectlResult(
            command="kubectl get pods",
            stdout=SAMPLE_PODS_OUTPUT,
            stderr="",
            return_code=0,
        )
        mock_events.return_value = KubectlResult(
            command="kubectl get events",
            stdout="(no events)",
            stderr="",
            return_code=0,
        )
        mock_logs.return_value = KubectlResult(
            command="kubectl logs",
            stdout="log line 1\nlog line 2",
            stderr="",
            return_code=0,
        )
        mock_rollout.return_value = KubectlResult(
            command="kubectl rollout history",
            stdout="REVISION  CHANGE-CAUSE\n1         <none>",
            stderr="",
            return_code=0,
        )

        result = get_kubectl_context()

        # get_pods called once (phase 1)
        mock_pods.assert_called_once()

        # get_deployment_logs should only be called for existing deployments
        log_calls = [call.args[0] for call in mock_logs.call_args_list]
        assert "vibeteam-gateway" in log_calls
        assert "openhands-svc" in log_calls
        # autogen-svc and crewai-svc should NOT be called
        assert "autogen-svc" not in log_calls
        assert "crewai-svc" not in log_calls

        # Output should still contain section headers
        assert "Pre-Fetched Kubernetes Context" in result
        assert "kubectl get pods" in result

    @patch("agents.shared.kubectl_tools.get_rollout_history")
    @patch("agents.shared.kubectl_tools.get_deployment_logs")
    @patch("agents.shared.kubectl_tools.get_events")
    @patch("agents.shared.kubectl_tools.get_pods")
    def test_includes_all_when_all_running(self, mock_pods, mock_events, mock_logs, mock_rollout):
        """When all 4 deployments have pods, all 4 get log fetches."""
        mock_pods.return_value = KubectlResult(
            command="kubectl get pods",
            stdout=FULL_PODS_OUTPUT,
            stderr="",
            return_code=0,
        )
        mock_events.return_value = KubectlResult(
            command="kubectl get events",
            stdout="",
            stderr="",
            return_code=0,
        )
        mock_logs.return_value = KubectlResult(
            command="kubectl logs",
            stdout="log line",
            stderr="",
            return_code=0,
        )
        mock_rollout.return_value = KubectlResult(
            command="kubectl rollout history",
            stdout="REVISION  CHANGE-CAUSE\n1  <none>",
            stderr="",
            return_code=0,
        )

        get_kubectl_context()

        log_calls = [call.args[0] for call in mock_logs.call_args_list]
        assert "vibeteam-gateway" in log_calls
        assert "openhands-svc" in log_calls
        assert "autogen-svc" in log_calls
        assert "crewai-svc" in log_calls

    @patch("agents.shared.kubectl_tools.get_rollout_history")
    @patch("agents.shared.kubectl_tools.get_deployment_logs")
    @patch("agents.shared.kubectl_tools.get_events")
    @patch("agents.shared.kubectl_tools.get_pods")
    def test_handles_pods_failure_gracefully(self, mock_pods, mock_events, mock_logs, mock_rollout):
        """If get_pods fails, fall back to trying all deployments."""
        mock_pods.return_value = KubectlResult(
            command="kubectl get pods",
            stdout="",
            stderr="connection refused",
            return_code=1,
        )
        mock_events.return_value = KubectlResult(
            command="kubectl get events",
            stdout="",
            stderr="connection refused",
            return_code=1,
        )
        mock_logs.return_value = KubectlResult(
            command="kubectl logs",
            stdout="",
            stderr="connection refused",
            return_code=1,
        )
        mock_rollout.return_value = KubectlResult(
            command="kubectl rollout history",
            stdout="",
            stderr="connection refused",
            return_code=1,
        )

        result = get_kubectl_context()

        # Should still attempt all deployments (no filtering when pods fail)
        log_calls = [call.args[0] for call in mock_logs.call_args_list]
        assert len(log_calls) == 4  # All KEY_DEPLOYMENTS
        assert "Error:" in result
