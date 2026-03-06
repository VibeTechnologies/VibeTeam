from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts import eval_github_e2e


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
