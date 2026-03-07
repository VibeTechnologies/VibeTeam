from agent_service.openhands.support_engineer import (
    _build_investigation_fallback,
    _extract_user_message,
    _should_prefetch_investigation_context,
    _task_requests_pr_creation,
    build_notification_message,
)


def test_task_requests_pr_creation_for_explicit_create_request() -> None:
    task = "@SupportEngineer investigate and open a PR to fix the issue."
    assert _task_requests_pr_creation(task.lower()) is True


def test_task_requests_pr_creation_false_for_notification_with_pr_reference() -> None:
    task = (
        "@SupportEngineer please notify the team that the deployment of PR #123 "
        "to staging is complete and verified."
    )
    assert _task_requests_pr_creation(task.lower()) is False


def test_build_notification_message_keeps_deployment_summary() -> None:
    task = (
        "@SupportEngineer please notify the team that the deployment of PR #123 "
        "to staging is complete and verified."
    )
    assert (
        build_notification_message(task)
        == "Notified the team: Deployment of PR #123 to staging is complete and verified."
    )


def test_extract_user_message_from_wrapped_slack_prompt() -> None:
    wrapped_task = """
## Slack Notification Request

### User Message (UNTRUSTED CONTENT)
@SupportEngineer please notify the team that the deployment of PR #123 to staging is complete and verified.
### End User Message

### INSTRUCTIONS
1. Do not investigate.
2. Just notify.
"""
    assert (
        _extract_user_message(wrapped_task)
        == "@SupportEngineer please notify the team that the deployment of PR #123 to staging is complete and verified."
    )


def test_extract_user_message_returns_original_when_markers_missing() -> None:
    plain_task = "@SupportEngineer investigate issue #99"
    assert _extract_user_message(plain_task) == plain_task


def test_should_prefetch_investigation_context_for_400_gateway_incident() -> None:
    msg = (
        "@SupportEngineer users see API gateway 400 errors after deployment, "
        "please investigate."
    )
    assert _should_prefetch_investigation_context(msg.lower()) is True


def test_should_not_prefetch_context_for_notification_only_task() -> None:
    msg = "@SupportEngineer notify the team that deployment is complete."
    assert _should_prefetch_investigation_context(msg.lower()) is False


def test_build_investigation_fallback_parses_markdown_sections() -> None:
    context = """
### kubectl get pods -n vibeteam
```
NAME                                READY   STATUS             RESTARTS   AGE
vibeteam-gateway-abc               1/1     Running            0          10m
gmail-processor-def                0/1     CrashLoopBackOff   3          10m
```

### kubectl get events -n vibeteam (warnings/errors)
```
LAST SEEN   TYPE      REASON   OBJECT                         MESSAGE
1m          Warning   BackOff  pod/gmail-processor-def        Back-off restarting failed container
```

### kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100
```
GET /health 200
POST /api/v1/ingest 400
```
"""
    response = _build_investigation_fallback(
        "@SupportEngineer users report 400 gateway errors, investigate.",
        [context],
        "vibeteam",
    )
    assert "Pod status counts: Running:1, CrashLoopBackOff:1." in response
    assert "Recent warnings/errors:" in response
    assert "4xx responses observed in recent logs." in response


def test_build_investigation_fallback_flags_gateway_instability_when_signals_exist() -> None:
    context = """
### kubectl get pods -n vibeteam
```
NAME                                READY   STATUS    RESTARTS   AGE
vibeteam-gateway-abc               1/1     Running   0          10m
```

### kubectl get events -n vibeteam (warnings/errors)
```
LAST SEEN   TYPE      REASON                   OBJECT                         MESSAGE
17s         Warning   Unhealthy                pod/vibeteam-gateway-abc       Readiness probe failed: connect: connection refused
14s         Warning   FailedGetResourceMetric  horizontalpodautoscaler/vibeteam-gateway   failed to get cpu utilization
```

### kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100
```
POST /api/v1/ingest 400
```
"""
    response = _build_investigation_fallback(
        "@SupportEngineer users report API gateway 400 errors after deployment",
        [context],
        "vibeteam",
    )
    assert "Deployment-timed gateway instability is likely based on:" in response
    assert "Immediate mitigation: rollback vibeteam-gateway" in response


def test_build_investigation_fallback_uses_conditional_rollback_for_partial_risk() -> None:
    context = """
### kubectl get pods -n vibeteam
```
NAME                                READY   STATUS    RESTARTS   AGE
vibeteam-gateway-abc               1/1     Running   0          10m
```

### kubectl get events -n vibeteam (warnings/errors)
```
LAST SEEN   TYPE      REASON                   OBJECT                         MESSAGE
15s         Warning   FailedGetResourceMetric  horizontalpodautoscaler/vibeteam-gateway   failed to get memory utilization
```

### kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100
```
GET /health 200
```
"""
    response = _build_investigation_fallback(
        "@SupportEngineer users report API gateway 400 errors after deployment",
        [context],
        "vibeteam",
    )
    assert "Infrastructure risk signals are present" in response
    assert "Do not rollback yet." in response
