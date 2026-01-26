"""
Kubernetes Tool - OpenHands tool wrapper for K8s cluster operations.

Provides agent-callable functions for cluster validation and monitoring.
Uses in-cluster authentication via ServiceAccount token.
"""

import json
import os
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult


class KubernetesTool(BaseTool):
    """
    Tool for Kubernetes cluster operations.

    Provides read-only access to cluster resources for validation.
    Uses in-cluster authentication when running in K8s pods.
    """

    name = "kubernetes"
    description = "Query Kubernetes cluster for pods, deployments, services, and health status"

    def __init__(self):
        self._client = None
        self._initialized = False

    def _init_client(self):
        """Initialize Kubernetes client lazily."""
        if self._initialized:
            return

        try:
            from kubernetes import client, config

            # Try in-cluster config first (when running in K8s)
            try:
                config.load_incluster_config()
            except config.ConfigException:
                # Fall back to kubeconfig file
                kubeconfig = os.environ.get("KUBECONFIG", "~/.kube/config")
                config.load_kube_config(config_file=os.path.expanduser(kubeconfig))

            self._client = client
            self._initialized = True
        except ImportError:
            raise RuntimeError("kubernetes package not installed. Run: pip install kubernetes")

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
                                "get_pods",
                                "get_deployments",
                                "get_services",
                                "get_nodes",
                                "get_events",
                                "get_pod_logs",
                                "get_cluster_health",
                                "get_namespace_summary",
                            ],
                            "description": "The Kubernetes action to perform",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (default: all namespaces)",
                        },
                        "name": {
                            "type": "string",
                            "description": "Resource name (for get_pod_logs)",
                        },
                        "container": {
                            "type": "string",
                            "description": "Container name (for get_pod_logs)",
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Number of log lines to retrieve (default: 50)",
                        },
                        "label_selector": {
                            "type": "string",
                            "description": "Label selector (e.g., 'app=webhook')",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Kubernetes action."""
        action = kwargs.get("action")
        namespace = kwargs.get("namespace")
        label_selector = kwargs.get("label_selector")

        try:
            self._init_client()
            v1 = self._client.CoreV1Api()
            apps_v1 = self._client.AppsV1Api()

            if action == "get_pods":
                return await self._get_pods(v1, namespace, label_selector)

            elif action == "get_deployments":
                return await self._get_deployments(apps_v1, namespace, label_selector)

            elif action == "get_services":
                return await self._get_services(v1, namespace, label_selector)

            elif action == "get_nodes":
                return await self._get_nodes(v1)

            elif action == "get_events":
                return await self._get_events(v1, namespace)

            elif action == "get_pod_logs":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(
                        success=False, output="", error="name required for get_pod_logs"
                    )
                container = kwargs.get("container")
                tail_lines = kwargs.get("tail_lines", 50)
                return await self._get_pod_logs(
                    v1, namespace or "default", name, container, tail_lines
                )

            elif action == "get_cluster_health":
                return await self._get_cluster_health(v1, apps_v1)

            elif action == "get_namespace_summary":
                return await self._get_namespace_summary(v1, apps_v1, namespace)

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def _get_pods(self, v1, namespace: str | None, label_selector: str | None) -> ToolResult:
        """Get pods in namespace or all namespaces."""
        if namespace:
            pods = v1.list_namespaced_pod(namespace, label_selector=label_selector or "")
        else:
            pods = v1.list_pod_for_all_namespaces(label_selector=label_selector or "")

        pod_list = []
        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "ready": self._get_pod_ready_status(pod),
                "restarts": self._get_pod_restarts(pod),
                "age": self._get_age(pod.metadata.creation_timestamp),
            }
            pod_list.append(pod_info)

        return ToolResult(
            success=True,
            output=json.dumps(pod_list, indent=2, default=str),
            metadata={"count": len(pod_list)},
        )

    async def _get_deployments(
        self, apps_v1, namespace: str | None, label_selector: str | None
    ) -> ToolResult:
        """Get deployments in namespace or all namespaces."""
        if namespace:
            deployments = apps_v1.list_namespaced_deployment(
                namespace, label_selector=label_selector or ""
            )
        else:
            deployments = apps_v1.list_deployment_for_all_namespaces(
                label_selector=label_selector or ""
            )

        deployment_list = []
        for dep in deployments.items:
            dep_info = {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": f"{dep.status.ready_replicas or 0}/{dep.spec.replicas}",
                "available": dep.status.available_replicas or 0,
                "age": self._get_age(dep.metadata.creation_timestamp),
            }
            deployment_list.append(dep_info)

        return ToolResult(
            success=True,
            output=json.dumps(deployment_list, indent=2, default=str),
            metadata={"count": len(deployment_list)},
        )

    async def _get_services(
        self, v1, namespace: str | None, label_selector: str | None
    ) -> ToolResult:
        """Get services in namespace or all namespaces."""
        if namespace:
            services = v1.list_namespaced_service(namespace, label_selector=label_selector or "")
        else:
            services = v1.list_service_for_all_namespaces(label_selector=label_selector or "")

        service_list = []
        for svc in services.items:
            svc_info = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": [f"{p.port}/{p.protocol}" for p in (svc.spec.ports or [])],
            }
            service_list.append(svc_info)

        return ToolResult(
            success=True,
            output=json.dumps(service_list, indent=2, default=str),
            metadata={"count": len(service_list)},
        )

    async def _get_nodes(self, v1) -> ToolResult:
        """Get cluster nodes status."""
        nodes = v1.list_node()
        node_list = []
        for node in nodes.items:
            conditions = {c.type: c.status for c in node.status.conditions}
            node_info = {
                "name": node.metadata.name,
                "ready": conditions.get("Ready", "Unknown"),
                "version": node.status.node_info.kubelet_version,
                "os": node.status.node_info.os_image,
                "cpu": node.status.capacity.get("cpu"),
                "memory": node.status.capacity.get("memory"),
            }
            node_list.append(node_info)

        return ToolResult(
            success=True,
            output=json.dumps(node_list, indent=2, default=str),
            metadata={"count": len(node_list)},
        )

    async def _get_events(self, v1, namespace: str | None) -> ToolResult:
        """Get recent events (warnings)."""
        if namespace:
            events = v1.list_namespaced_event(namespace)
        else:
            events = v1.list_event_for_all_namespaces()

        # Filter to warnings and recent events
        event_list = []
        for event in sorted(
            events.items,
            key=lambda e: e.last_timestamp or e.metadata.creation_timestamp,
            reverse=True,
        )[:20]:
            if event.type == "Warning":
                event_info = {
                    "namespace": event.metadata.namespace,
                    "reason": event.reason,
                    "message": event.message[:200] if event.message else "",
                    "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                    "count": event.count,
                    "last_seen": self._get_age(
                        event.last_timestamp or event.metadata.creation_timestamp
                    ),
                }
                event_list.append(event_info)

        return ToolResult(
            success=True,
            output=json.dumps(event_list, indent=2, default=str),
            metadata={"count": len(event_list)},
        )

    async def _get_pod_logs(
        self, v1, namespace: str, name: str, container: str | None, tail_lines: int
    ) -> ToolResult:
        """Get logs from a pod."""
        try:
            logs = v1.read_namespaced_pod_log(
                name=name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
            )
            return ToolResult(
                success=True,
                output=logs,
                metadata={"pod": name, "namespace": namespace, "lines": tail_lines},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to get logs: {e}")

    async def _get_cluster_health(self, v1, apps_v1) -> ToolResult:
        """Get overall cluster health summary."""
        # Get nodes
        nodes = v1.list_node()
        nodes_ready = sum(
            1
            for n in nodes.items
            if any(c.type == "Ready" and c.status == "True" for c in n.status.conditions)
        )

        # Get all pods
        pods = v1.list_pod_for_all_namespaces()
        pods_running = sum(1 for p in pods.items if p.status.phase == "Running")
        pods_pending = sum(1 for p in pods.items if p.status.phase == "Pending")
        pods_failed = sum(1 for p in pods.items if p.status.phase == "Failed")

        # Get deployments
        deployments = apps_v1.list_deployment_for_all_namespaces()
        deployments_ready = sum(
            1 for d in deployments.items if (d.status.ready_replicas or 0) == d.spec.replicas
        )

        # Determine overall health
        overall = "Healthy"
        if pods_failed > 0 or pods_pending > 3:
            overall = "Degraded"
        if nodes_ready < len(nodes.items):
            overall = "Critical"

        health = {
            "overall": overall,
            "nodes": {"ready": nodes_ready, "total": len(nodes.items)},
            "pods": {"running": pods_running, "pending": pods_pending, "failed": pods_failed},
            "deployments": {"ready": deployments_ready, "total": len(deployments.items)},
        }

        return ToolResult(
            success=True,
            output=json.dumps(health, indent=2),
            metadata={"overall": overall},
        )

    async def _get_namespace_summary(self, v1, apps_v1, namespace: str | None) -> ToolResult:
        """Get summary of resources in a namespace."""
        if not namespace:
            # List all namespaces
            namespaces = v1.list_namespace()
            ns_list = [
                {"name": ns.metadata.name, "status": ns.status.phase} for ns in namespaces.items
            ]
            return ToolResult(
                success=True,
                output=json.dumps(ns_list, indent=2),
                metadata={"count": len(ns_list)},
            )

        # Get resources in namespace
        pods = v1.list_namespaced_pod(namespace)
        deployments = apps_v1.list_namespaced_deployment(namespace)
        services = v1.list_namespaced_service(namespace)

        summary = {
            "namespace": namespace,
            "pods": len(pods.items),
            "deployments": len(deployments.items),
            "services": len(services.items),
            "pod_status": {
                "Running": sum(1 for p in pods.items if p.status.phase == "Running"),
                "Pending": sum(1 for p in pods.items if p.status.phase == "Pending"),
                "Failed": sum(1 for p in pods.items if p.status.phase == "Failed"),
            },
        }

        return ToolResult(
            success=True,
            output=json.dumps(summary, indent=2),
            metadata={"namespace": namespace},
        )

    def _get_pod_ready_status(self, pod) -> str:
        """Get pod ready container count."""
        if not pod.status.container_statuses:
            return "0/0"
        ready = sum(1 for c in pod.status.container_statuses if c.ready)
        total = len(pod.status.container_statuses)
        return f"{ready}/{total}"

    def _get_pod_restarts(self, pod) -> int:
        """Get total pod restarts."""
        if not pod.status.container_statuses:
            return 0
        return sum(c.restart_count for c in pod.status.container_statuses)

    def _get_age(self, timestamp) -> str:
        """Get human-readable age from timestamp."""
        if not timestamp:
            return "Unknown"
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        delta = now - timestamp
        if delta.days > 0:
            return f"{delta.days}d"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h"
        minutes = delta.seconds // 60
        return f"{minutes}m"
