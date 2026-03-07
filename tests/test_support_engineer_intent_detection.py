from agent_service.openhands.support_engineer import (
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
