from __future__ import annotations

from scripts import check_github_app_permissions as checker


def test_resolve_role_assignee_prefers_role_specific_env(monkeypatch):
    monkeypatch.setenv("GITHUB_SOFTWARE_ENGINEER_BOT_ASSIGNEE", "agentgithubapphandle")
    monkeypatch.setenv("GITHUB_APP_BOT_USERNAME_SOFTWARE_ENGINEER", "fallback-app-handle")
    monkeypatch.setenv("GITHUB_BOT_USERNAME_SOFTWARE_ENGINEER", "fallback-gateway-handle")

    assert checker._resolve_role_assignee("software_engineer") == "agentgithubapphandle"


def test_resolve_role_assignee_fallback_order(monkeypatch):
    monkeypatch.delenv("GITHUB_SUPPORT_ENGINEER_BOT_ASSIGNEE", raising=False)
    monkeypatch.setenv("GITHUB_APP_BOT_USERNAME_SUPPORT_ENGINEER", "app-handle")
    monkeypatch.setenv("GITHUB_BOT_USERNAME_SUPPORT_ENGINEER", "gateway-handle")

    assert checker._resolve_role_assignee("support_engineer") == "app-handle"


def test_check_assignee_assignable_handles_204(monkeypatch):
    class Response:
        status_code = 204
        text = ""

        @staticmethod
        def json() -> dict:
            return {}

    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response())

    ok, status = checker._check_assignee_assignable(
        repo="VibeTechnologies/vibeteam-eval-hello-world",
        token="tok",
        assignee="agentgithubapphandle",
    )
    assert ok is True
    assert status == "assignable"


def test_check_assignee_assignable_handles_non_assignable(monkeypatch):
    class Response:
        status_code = 404
        text = "not found"

        @staticmethod
        def json() -> dict:
            return {"message": "Not Found"}

    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response())

    ok, status = checker._check_assignee_assignable(
        repo="VibeTechnologies/vibeteam-eval-hello-world",
        token="tok",
        assignee="vibeteam-swe-bot-260301[bot]",
    )
    assert ok is False
    assert "not assignable status=404" in status


def test_validate_installation_missing_id():
    ok, status = checker._validate_installation_for_repo(
        app_id="123",
        private_key="pem",
        installation_id=None,
        repo="VibeTechnologies/vibeteam-eval-hello-world",
    )
    assert ok is False
    assert "missing installation_id" in status


def test_validate_installation_id_not_found(monkeypatch):
    monkeypatch.setattr(
        checker,
        "list_installations",
        lambda app_id, private_key: [{"id": 111}, {"id": 222}],
    )

    ok, status = checker._validate_installation_for_repo(
        app_id="123",
        private_key="pem",
        installation_id="333",
        repo="VibeTechnologies/vibeteam-eval-hello-world",
    )
    assert ok is False
    assert "installation_id=333 not found" in status


def test_validate_installation_skip_repo_check(monkeypatch):
    monkeypatch.setattr(
        checker,
        "list_installations",
        lambda app_id, private_key: [{"id": 333}],
    )

    ok, status = checker._validate_installation_for_repo(
        app_id="123",
        private_key="pem",
        installation_id="333",
        repo=None,
    )
    assert ok is True
    assert status == "ok (repo check skipped)"


def test_validate_installation_repo_access_ok(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {}

    monkeypatch.setattr(
        checker,
        "list_installations",
        lambda app_id, private_key: [{"id": 333}],
    )
    monkeypatch.setattr(checker, "get_installation_token", lambda a, b, c: "tok")
    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response())

    ok, status = checker._validate_installation_for_repo(
        app_id="123",
        private_key="pem",
        installation_id="333",
        repo="VibeTechnologies/vibeteam-eval-hello-world",
    )
    assert ok is True
    assert status == "ok"


def test_validate_installation_repo_access_fails(monkeypatch):
    class Response:
        status_code = 404
        text = "not found"

        @staticmethod
        def json() -> dict:
            return {"message": "Not Found"}

    monkeypatch.setattr(
        checker,
        "list_installations",
        lambda app_id, private_key: [{"id": 333}],
    )
    monkeypatch.setattr(checker, "get_installation_token", lambda a, b, c: "tok")
    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response())

    ok, status = checker._validate_installation_for_repo(
        app_id="123",
        private_key="pem",
        installation_id="333",
        repo="VibeTechnologies/vibeteam-eval-hello-world",
    )
    assert ok is False
    assert "repo access status=404" in status
