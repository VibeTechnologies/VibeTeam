from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import eval_github_e2e
from vibeteam.utils import github_app


def test_require_token_prefers_valid_env_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(eval_github_e2e, "_get_gh_cli_token", lambda user=None: None)
    monkeypatch.setattr(
        eval_github_e2e,
        "_is_token_usable",
        lambda token: token == "env-token",
    )

    token = eval_github_e2e._require_token()
    assert token == "env-token"


def test_require_token_prefers_specific_gh_user(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def fake_get_gh_cli_token(user=None):
        if user == "OpenCodeEngineer":
            return "preferred-gh-token"
        return None

    monkeypatch.setattr(eval_github_e2e, "_get_gh_cli_token", fake_get_gh_cli_token)
    monkeypatch.setattr(
        eval_github_e2e,
        "_is_token_usable",
        lambda token: token == "preferred-gh-token",
    )

    token = eval_github_e2e._require_token("OpenCodeEngineer")
    assert token == "preferred-gh-token"


def test_require_token_falls_back_to_role_app_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(eval_github_e2e, "_get_gh_cli_token", lambda user=None: None)
    monkeypatch.setattr(
        eval_github_e2e,
        "_is_token_usable",
        lambda token: token == "app-token",
    )
    monkeypatch.setattr(
        github_app,
        "get_installation_token_for_role",
        lambda role: "app-token" if role == "software_engineer" else None,
    )

    token = eval_github_e2e._require_token()
    assert token == "app-token"


def test_require_token_raises_without_usable_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(eval_github_e2e, "_get_gh_cli_token", lambda user=None: None)
    monkeypatch.setattr(eval_github_e2e, "_is_token_usable", lambda token: False)
    monkeypatch.setattr(github_app, "get_installation_token_for_role", lambda role: None)

    try:
        eval_github_e2e._require_token()
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "No usable GitHub token found" in str(exc)


def test_require_token_falls_back_to_gh_cli(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(eval_github_e2e, "_get_gh_cli_token", lambda user=None: "gh-cli-token")
    monkeypatch.setattr(
        eval_github_e2e,
        "_is_token_usable",
        lambda token: token == "gh-cli-token",
    )

    token = eval_github_e2e._require_token()
    assert token == "gh-cli-token"


def test_issue_trigger_comment_uses_role_mentions_only():
    trigger = eval_github_e2e._build_issue_trigger_comment()
    assert "@SoftwareEngineer" in trigger
    assert "@SupportEngineer" in trigger
    assert "-bot" not in trigger
    assert "[bot]" not in trigger


def test_pick_issue_assignee_prefers_explicit_assignee():
    bot_logins = {
        "vibeteam-support-bot-260301[bot]",
        "vibeteam-swe-bot-260301[bot]",
    }
    selected = eval_github_e2e._pick_issue_assignee(
        bot_logins,
        preferred_assignee="vibeteam-github-app[bot]",
    )
    assert selected == "vibeteam-github-app[bot]"


def test_pick_issue_assignee_prefers_software_bot():
    bot_logins = {
        "vibeteam-support-bot-260301[bot]",
        "vibeteam-swe-bot-260301[bot]",
    }
    selected = eval_github_e2e._pick_issue_assignee(bot_logins)
    assert selected == "vibeteam-swe-bot-260301[bot]"


def test_default_assignee_for_role_and_bot_validation(monkeypatch):
    monkeypatch.setitem(
        eval_github_e2e.ROLE_DEFAULT_ASSIGNEES,
        "software_engineer",
        "vibeteam-swe-bot-260301[bot]",
    )

    assert (
        eval_github_e2e._default_assignee_for_role("software_engineer")
        == "vibeteam-swe-bot-260301[bot]"
    )
    assert eval_github_e2e._is_bot_login("vibeteam-swe-bot-260301[bot]") is True
    assert eval_github_e2e._is_bot_login("OpenCodeEngineer") is False


def test_is_bot_login_accepts_explicit_bot_handle_allowlist():
    assert (
        eval_github_e2e._is_bot_login(
            "agentgithubapphandle",
            extra_allowed={"agentgithubapphandle"},
        )
        is True
    )


def test_allowed_assignees_for_role_uses_role_env_and_default(monkeypatch):
    monkeypatch.setitem(
        eval_github_e2e.ROLE_DEFAULT_ASSIGNEES,
        "software_engineer",
        "vibeteam-swe-bot-260301[bot]",
    )
    monkeypatch.setenv(
        "GITHUB_SOFTWARE_ENGINEER_BOT_ASSIGNEE",
        "vibeteam-swe-bot-260301[bot],vibeteam-swe-bot-alt[bot]",
    )

    allowed = eval_github_e2e._allowed_assignees_for_role("software_engineer")
    assert "vibeteam-swe-bot-260301[bot]" in allowed
    assert "vibeteam-swe-bot-alt[bot]" in allowed


def test_assignee_matches_issue_role_rejects_cross_role(monkeypatch):
    monkeypatch.setitem(
        eval_github_e2e.ROLE_DEFAULT_ASSIGNEES,
        "software_engineer",
        "vibeteam-swe-bot-260301[bot]",
    )
    monkeypatch.setitem(
        eval_github_e2e.ROLE_DEFAULT_ASSIGNEES,
        "support_engineer",
        "vibeteam-support-bot-260301[bot]",
    )

    assert (
        eval_github_e2e._assignee_matches_issue_role(
            "vibeteam-swe-bot-260301[bot]",
            "software_engineer",
        )
        is True
    )
    assert (
        eval_github_e2e._assignee_matches_issue_role(
            "vibeteam-support-bot-260301[bot]",
            "software_engineer",
        )
        is False
    )


def test_resolve_issue_assignee_prefers_explicit_value(monkeypatch):
    def fail_fetch_repo_assignees(owner, repo, token):
        raise AssertionError("repo assignees should not be fetched when explicit assignee is set")

    monkeypatch.setattr(eval_github_e2e, "_fetch_repo_assignees", fail_fetch_repo_assignees)

    selected = eval_github_e2e._resolve_issue_assignee(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        preferred_assignee="vibeteam-swe-bot-260301[bot]",
    )
    assert selected == "vibeteam-swe-bot-260301[bot]"


def test_resolve_issue_assignee_prefers_repo_bot_login(monkeypatch):
    def fake_fetch_repo_assignees(owner, repo, token):
        return ["octocat", "vibeteam-swe-bot-260301[bot]", "vibeteam-support-bot-260301[bot]"]

    monkeypatch.setattr(eval_github_e2e, "_fetch_repo_assignees", fake_fetch_repo_assignees)

    selected = eval_github_e2e._resolve_issue_assignee(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
    )
    assert selected == "vibeteam-swe-bot-260301[bot]"


def test_resolve_issue_assignee_uses_role_default_when_no_repo_bot(monkeypatch):
    def fake_fetch_repo_assignees(owner, repo, token):
        return ["octocat", "alice", "bob"]

    monkeypatch.setattr(eval_github_e2e, "_fetch_repo_assignees", fake_fetch_repo_assignees)

    selected = eval_github_e2e._resolve_issue_assignee(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
    )
    assert selected == "vibeteam-swe-bot-260301[bot]"


def test_evaluate_issue_assignment_uses_existing_assignee(monkeypatch):
    def fake_fetch_assignees(owner, repo, number, token):
        return ["vibeteam-swe-bot-260301[bot]"]

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
    )

    assert result["assignment_passed"] is True
    assert result["target_assignee"] == "vibeteam-swe-bot-260301[bot]"
    assert result["issue_assignees"] == ["vibeteam-swe-bot-260301[bot]"]


def test_evaluate_issue_assignment_fails_when_assignee_not_present(monkeypatch):
    def fake_fetch_assignees(owner, repo, number, token):
        return ["some-other-user"]

    def fake_assign_issue(owner, repo, token, issue_number, assignee):
        return {
            "assigned": False,
            "assigned_at": datetime.now(timezone.utc),
            "issue_assignees": ["some-other-user"],
            "error": "Failed to assign issue to target",
        }

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)
    monkeypatch.setattr(eval_github_e2e, "_assign_issue", fake_assign_issue)

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
    )

    assert result["assignment_passed"] is False
    assert result["target_assignee"] == "vibeteam-swe-bot-260301[bot]"
    assert "Failed to assign issue to target" in result["assignment_error"]


def test_evaluate_issue_assignment_assigns_when_missing(monkeypatch):
    called = {"assignee": None}

    def fake_fetch_assignees(owner, repo, number, token):
        return ["some-other-user"]

    def fake_assign_issue(owner, repo, token, issue_number, assignee):
        called["assignee"] = assignee
        return {
            "assigned": True,
            "assigned_at": datetime.now(timezone.utc),
            "issue_assignees": ["some-other-user", assignee],
            "error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)
    monkeypatch.setattr(eval_github_e2e, "_assign_issue", fake_assign_issue)

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
    )

    assert called["assignee"] == "vibeteam-swe-bot-260301[bot]"
    assert result["assignment_passed"] is True
    assert result["issue_assignees"] == [
        "some-other-user",
        "vibeteam-swe-bot-260301[bot]",
    ]


def test_evaluate_issue_assignment_force_reassigns_existing_assignee(monkeypatch):
    called = {"unassign": 0, "assign": 0}

    def fake_fetch_assignees(owner, repo, number, token):
        return ["vibeteam-swe-bot-260301[bot]"]

    def fake_unassign_issue(owner, repo, token, issue_number, assignee):
        called["unassign"] += 1
        return {
            "removed": True,
            "issue_assignees": [],
            "error": "",
        }

    def fake_assign_issue(owner, repo, token, issue_number, assignee):
        called["assign"] += 1
        return {
            "assigned": True,
            "assigned_at": datetime.now(timezone.utc),
            "issue_assignees": [assignee],
            "error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)
    monkeypatch.setattr(eval_github_e2e, "_unassign_issue", fake_unassign_issue)
    monkeypatch.setattr(eval_github_e2e, "_assign_issue", fake_assign_issue)

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
        force_reassign=True,
    )

    assert called["unassign"] == 1
    assert called["assign"] == 1
    assert result["assignment_passed"] is True


def test_evaluate_issue_assignment_validates_expected_assignment_actor(monkeypatch):
    def fake_fetch_assignees(owner, repo, number, token):
        return ["vibeteam-swe-bot-260301[bot]"]

    def fake_fetch_assignment_events(owner, repo, token, issue_number, target_assignee, since):
        return [
            {
                "event": "assigned",
                "assignee": {"login": target_assignee},
                "actor": {"login": "OpenCodeEngineer"},
                "created_at": "2026-03-06T00:00:00Z",
            }
        ]

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)
    monkeypatch.setattr(
        eval_github_e2e,
        "_fetch_issue_assignment_events",
        fake_fetch_assignment_events,
    )

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
        expected_actor_login="OpenCodeEngineer",
    )

    assert result["assignment_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["assignment_event_actors"] == ["OpenCodeEngineer"]
    assert result["assignment_actor_passed"] is True
    assert result["assignment_actor_error"] == ""


def test_evaluate_issue_assignment_fails_on_actor_mismatch(monkeypatch):
    def fake_fetch_assignees(owner, repo, number, token):
        return ["vibeteam-swe-bot-260301[bot]"]

    def fake_fetch_assignment_events(owner, repo, token, issue_number, target_assignee, since):
        return [
            {
                "event": "assigned",
                "assignee": {"login": target_assignee},
                "actor": {"login": "dzianisv"},
                "created_at": "2026-03-06T00:00:00Z",
            }
        ]

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_assignees", fake_fetch_assignees)
    monkeypatch.setattr(
        eval_github_e2e,
        "_fetch_issue_assignment_events",
        fake_fetch_assignment_events,
    )

    result = eval_github_e2e._evaluate_issue_assignment(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        bot_logins={"vibeteam-swe-bot-260301[bot]"},
        expected_actor_login="OpenCodeEngineer",
    )

    assert result["assignment_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["assignment_event_actors"] == ["dzianisv"]
    assert result["assignment_actor_passed"] is False
    assert "Assignment event actor mismatch" in result["assignment_actor_error"]


def test_wait_for_assignee_activity_requires_target_bot_login():
    now = datetime.now(timezone.utc)
    recent_ts = (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    comments = [
        {
            "created_at": recent_ts,
            "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
        }
    ]

    result = eval_github_e2e._wait_for_assignee_activity(
        fetch_comments=lambda: comments,
        since=now,
        target_assignee="OpenCodeEngineer",
        timeout=1,
        poll_interval=0,
    )

    assert result == set()


def test_run_issue_handoff_presence_requires_assignment(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_create_issue_comment(owner, repo, token, number, body):
        return now

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-support-bot-260301[bot]", "type": "Bot"},
            },
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            },
        ]

    def fake_wait_for_bot_authors(fetch_comments, since, min_bots, timeout, poll_interval=10):
        return {"vibeteam-support-bot-260301[bot]"}

    def fake_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": [],
            "assignment_passed": False,
            "assignment_error": "assignment failed",
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue_comment", fake_create_issue_comment)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_bot_authors", fake_wait_for_bot_authors)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_assignment)

    result = eval_github_e2e._run_issue_handoff_presence(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        timeout=60,
    )

    assert result["passed"] is False
    assert result["assignment_passed"] is False
    assert result["target_assignee"] == "vibeteam-swe-bot-260301[bot]"


def test_run_issue_handoff_requires_assignee_activity_for_pass(monkeypatch):
    now = datetime.now(timezone.utc)
    called = {"waited_for": None}

    def fake_create_issue(owner, repo, token):
        return (
            109,
            "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/109",
            now,
            "OpenCodeEngineer",
        )

    def fail_create_issue_comment(*args, **kwargs):
        raise AssertionError("assignment-first issue handoff must not post trigger comments")

    def fake_wait_for_bot_authors(fetch_comments, since, min_bots, timeout, poll_interval=10):
        return {"vibeteam-support-bot-260301[bot]"}

    def fake_wait_for_assignee_activity(fetch_comments, since, target_assignee, timeout, poll_interval=10):
        called["waited_for"] = target_assignee
        return set()

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-support-bot-260301[bot]", "type": "Bot"},
            },
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            }
        ]

    def fake_evaluate_issue_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue", fake_create_issue)
    monkeypatch.setattr(eval_github_e2e, "_create_issue_comment", fail_create_issue_comment)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_bot_authors", fake_wait_for_bot_authors)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_assignee_activity", fake_wait_for_assignee_activity)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_evaluate_issue_assignment)

    result = eval_github_e2e._run_issue_handoff(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        timeout=60,
        issue_assignee="vibeteam-swe-bot-260301[bot]",
    )

    assert called["waited_for"] == "vibeteam-swe-bot-260301[bot]"
    assert result["assignment_passed"] is True
    assert result["creator_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["passed"] is False


def test_run_issue_handoff_passes_with_assignment_and_assignee_activity(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_create_issue(owner, repo, token):
        return (
            110,
            "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/110",
            now,
            "OpenCodeEngineer",
        )

    def fail_create_issue_comment(*args, **kwargs):
        raise AssertionError("assignment-first issue handoff must not post trigger comments")

    def fake_wait_for_bot_authors(fetch_comments, since, min_bots, timeout, poll_interval=10):
        return {"vibeteam-support-bot-260301[bot]"}

    def fake_wait_for_assignee_activity(fetch_comments, since, target_assignee, timeout, poll_interval=10):
        return {target_assignee}

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-support-bot-260301[bot]", "type": "Bot"},
            },
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            },
        ]

    def fake_evaluate_issue_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue", fake_create_issue)
    monkeypatch.setattr(eval_github_e2e, "_create_issue_comment", fail_create_issue_comment)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_bot_authors", fake_wait_for_bot_authors)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_assignee_activity", fake_wait_for_assignee_activity)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_evaluate_issue_assignment)

    result = eval_github_e2e._run_issue_handoff(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        timeout=60,
        issue_assignee="vibeteam-swe-bot-260301[bot]",
    )

    assert result["assignment_passed"] is True
    assert result["creator_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["passed"] is True


def test_run_issue_handoff_presence_passes_with_assignment_and_recent_activity(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_create_issue_comment(owner, repo, token, number, body):
        return now

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-support-bot-260301[bot]", "type": "Bot"},
            }
        ]

    def fake_wait_for_bot_authors(fetch_comments, since, min_bots, timeout, poll_interval=10):
        return {"vibeteam-support-bot-260301[bot]"}

    def fake_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue_comment", fake_create_issue_comment)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_bot_authors", fake_wait_for_bot_authors)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_assignment)

    result = eval_github_e2e._run_issue_handoff_presence(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        timeout=60,
        post_trigger_comment=True,
    )

    assert result["assignment_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["passed"] is True


def test_run_issue_handoff_existing_skips_trigger_comment_by_default(monkeypatch):
    called = {"waited_for": None}

    def fail_create_issue_comment(*args, **kwargs):
        raise AssertionError("trigger comment should not be posted for existing issue by default")

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-support-bot-260301[bot]", "type": "Bot"},
            },
            {
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            },
        ]

    def fake_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
        }

    def fake_wait_for_assignee_activity(
        fetch_comments, since, target_assignee, timeout, poll_interval=10
    ):
        called["waited_for"] = target_assignee
        return {target_assignee}

    monkeypatch.setattr(eval_github_e2e, "_create_issue_comment", fail_create_issue_comment)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_assignment)
    monkeypatch.setattr(
        eval_github_e2e,
        "_wait_for_assignee_activity",
        fake_wait_for_assignee_activity,
    )

    result = eval_github_e2e._run_issue_handoff_existing(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        timeout=60,
    )

    assert called["waited_for"] == "vibeteam-swe-bot-260301[bot]"
    assert result["passed"] is True
    assert result["assignment_passed"] is True
    assert result["assignment_event_seen"] is True


def test_run_issue_handoff_existing_uses_actor_login_for_assignment_event_check(monkeypatch):
    captured = {"expected_actor": None}

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            }
        ]

    def fake_assignment(
        owner,
        repo,
        token,
        issue_number,
        bot_logins,
        preferred_assignee,
        issue_role,
        wait_seconds=0,
        poll_interval=5,
        force_reassign=False,
        assignment_started_at=None,
        expected_actor_login=None,
    ):
        captured["expected_actor"] = expected_actor_login
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
            "assignment_event_actors": ["OpenCodeEngineer"],
            "assignment_actor_passed": True,
            "assignment_actor_error": "",
        }

    def fake_wait_for_assignee_activity(
        fetch_comments, since, target_assignee, timeout, poll_interval=10
    ):
        return {target_assignee}

    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_assignment)
    monkeypatch.setattr(
        eval_github_e2e,
        "_wait_for_assignee_activity",
        fake_wait_for_assignee_activity,
    )

    result = eval_github_e2e._run_issue_handoff_existing(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        issue_number=92,
        timeout=60,
        actor_login="OpenCodeEngineer",
    )

    assert captured["expected_actor"] == "OpenCodeEngineer"
    assert result["assignment_actor_passed"] is True
    assert result["passed"] is True


def test_run_issue_pr_handoff_uses_existing_issue_and_passes_assignee(monkeypatch):
    issue_called = {"presence": False, "assignee": None}

    def fake_issue_presence(
        owner,
        repo,
        token,
        issue_number,
        timeout,
        issue_assignee,
        issue_role,
        post_trigger_comment,
        actor_login="n/a",
    ):
        issue_called["presence"] = True
        issue_called["assignee"] = issue_assignee
        assert issue_role == "software_engineer"
        assert post_trigger_comment is False
        assert actor_login == "OpenCodeEngineer"
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/92",
            "bot_logins": ["vibeteam-swe-bot-260301[bot]"],
            "recent_bot_logins": ["vibeteam-swe-bot-260301[bot]"],
            "target_assignee": issue_assignee,
            "issue_assignees": [issue_assignee],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
            "assignment_event_actors": ["OpenCodeEngineer"],
            "assignment_actor_passed": True,
            "assignment_actor_error": "",
            "actor_login": "OpenCodeEngineer",
            "issue_creator": "n/a",
            "creator_passed": True,
            "creator_error": "",
            "passed": True,
        }

    def fake_pr_presence(owner, repo, token, pr_number, timeout):
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1",
            "bot_logins": ["vibeteam-support-bot-260301[bot]"],
            "recent_bot_logins": ["vibeteam-support-bot-260301[bot]"],
            "passed": True,
        }

    monkeypatch.setattr(eval_github_e2e, "_run_issue_handoff_presence", fake_issue_presence)
    monkeypatch.setattr(eval_github_e2e, "_run_pr_handoff_presence", fake_pr_presence)

    assignee = "vibeteam-swe-bot-260301[bot]"
    result = eval_github_e2e._run_issue_pr_handoff(
        "VibeTechnologies",
        "vibeteam-eval-hello-world",
        "token",
        92,
        1,
        60,
        assignee,
    )

    assert issue_called["presence"] is True
    assert issue_called["assignee"] == assignee
    assert result["passed"] is True
    assert result["threads"]["issue"]["assignment_passed"] is True
    assert result["threads"]["pr"]["passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["creator_passed"] is True
    assert result["bot_logins"] == [
        "vibeteam-support-bot-260301[bot]",
        "vibeteam-swe-bot-260301[bot]",
    ]


def test_run_issue_handoff_fails_when_creator_mismatch(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_create_issue(owner, repo, token):
        return (
            111,
            "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/111",
            now,
            "dzianisv",
        )

    def fake_wait_for_assignee_activity(fetch_comments, since, target_assignee, timeout, poll_interval=10):
        return {target_assignee}

    def fake_fetch_issue_comments(owner, repo, number, token, since=None):
        return [
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "user": {"login": "vibeteam-swe-bot-260301[bot]", "type": "Bot"},
            }
        ]

    def fake_evaluate_issue_assignment(*args, **kwargs):
        return {
            "target_assignee": "vibeteam-swe-bot-260301[bot]",
            "issue_assignees": ["vibeteam-swe-bot-260301[bot]"],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue", fake_create_issue)
    monkeypatch.setattr(eval_github_e2e, "_wait_for_assignee_activity", fake_wait_for_assignee_activity)
    monkeypatch.setattr(eval_github_e2e, "_fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(eval_github_e2e, "_evaluate_issue_assignment", fake_evaluate_issue_assignment)

    result = eval_github_e2e._run_issue_handoff(
        owner="VibeTechnologies",
        repo="vibeteam-eval-hello-world",
        token="token",
        timeout=60,
        issue_assignee="vibeteam-swe-bot-260301[bot]",
        actor_login="OpenCodeEngineer",
    )

    assert result["creator_passed"] is False
    assert "Issue creator mismatch" in result["creator_error"]
    assert result["assignment_passed"] is True
    assert result["assignment_event_seen"] is True
    assert result["passed"] is False


def test_run_issue_pr_handoff_new_issue_enforces_creator(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_create_issue(owner, repo, token):
        return (
            112,
            "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/112",
            now,
            "OpenCodeEngineer",
        )

    def fake_issue_presence(
        owner,
        repo,
        token,
        issue_number,
        timeout,
        issue_assignee,
        issue_role,
        post_trigger_comment,
        actor_login="n/a",
    ):
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/112",
            "bot_logins": ["vibeteam-swe-bot-260301[bot]"],
            "recent_bot_logins": ["vibeteam-swe-bot-260301[bot]"],
            "target_assignee": issue_assignee,
            "issue_assignees": [issue_assignee],
            "assignment_passed": True,
            "assignment_error": "",
            "assignment_event_seen": True,
            "assignment_event_count": 1,
            "assignment_event_error": "",
            "actor_login": actor_login,
            "issue_creator": "n/a",
            "creator_passed": True,
            "creator_error": "",
            "passed": True,
        }

    def fake_pr_presence(owner, repo, token, pr_number, timeout):
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1",
            "bot_logins": ["vibeteam-support-bot-260301[bot]"],
            "recent_bot_logins": ["vibeteam-support-bot-260301[bot]"],
            "passed": True,
        }

    monkeypatch.setattr(eval_github_e2e, "_create_issue", fake_create_issue)
    monkeypatch.setattr(eval_github_e2e, "_run_issue_handoff_presence", fake_issue_presence)
    monkeypatch.setattr(eval_github_e2e, "_run_pr_handoff_presence", fake_pr_presence)

    result = eval_github_e2e._run_issue_pr_handoff(
        "VibeTechnologies",
        "vibeteam-eval-hello-world",
        "token",
        0,
        1,
        60,
        "vibeteam-swe-bot-260301[bot]",
        "software_engineer",
        False,
        "OpenCodeEngineer",
    )

    assert result["creator_passed"] is True
    assert result["issue_creator"] == "OpenCodeEngineer"
    assert result["assignment_event_seen"] is True
    assert result["passed"] is True


def test_write_report_with_thread_details_and_assignment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    issue_url = "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/92"
    pr_url = "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1"
    assignee = "vibeteam-swe-bot-260301[bot]"
    results = {
        "thread": f"{issue_url} | {pr_url}",
        "passed": True,
        "bot_logins": ["vibeteam-swe-bot-260301[bot]"],
        "threads": {
            "issue": {
                "thread": issue_url,
                "passed": True,
                "bot_logins": ["bot-a"],
                "recent_bot_logins": ["bot-a"],
                "target_assignee": assignee,
                "issue_assignees": [assignee],
                "assignment_passed": True,
                "assignment_error": "",
                "assignment_event_seen": True,
                "assignment_event_count": 1,
                "assignment_event_error": "",
                "assignment_event_actors": ["OpenCodeEngineer"],
                "assignment_actor_passed": True,
                "assignment_actor_error": "",
                "actor_login": "OpenCodeEngineer",
                "issue_creator": "OpenCodeEngineer",
                "creator_passed": True,
                "creator_error": "",
            },
            "pr": {
                "thread": pr_url,
                "passed": False,
                "bot_logins": ["bot-b"],
                "recent_bot_logins": [],
            },
        },
    }

    report_path = eval_github_e2e._write_report("github_issue_pr_handoff_github", results)
    report = Path(report_path).read_text(encoding="utf-8")
    assert "## Conversation Links" in report
    assert f"- GitHub: {issue_url}" in report
    assert f"- GitHub: {pr_url}" in report
    assert "## Thread Details" in report
    assert "### ISSUE" in report
    assert "### PR" in report
    assert f"- Thread: {issue_url}" in report
    assert f"- Thread: {pr_url}" in report
    assert "- Recent bot authors after assignment/trigger: bot-a" in report
    assert "- Issue assigned: ✅" in report
    assert f"- Target assignee: {assignee}" in report
    assert "- Assignment event observed: ✅" in report
    assert "- Assignment event count: 1" in report
    assert "- Assignment event actors: OpenCodeEngineer" in report
    assert "- Assignment actor check: ✅" in report
    assert "- Issue creator check: ✅" in report
    assert "- Expected actor: OpenCodeEngineer" in report
    assert "- Issue creator: OpenCodeEngineer" in report
