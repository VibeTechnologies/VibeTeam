from __future__ import annotations

from pathlib import Path

from scripts import eval_github_e2e


def test_run_issue_pr_handoff_uses_existing_issue(monkeypatch):
    issue_called = {"presence": False}

    def fake_issue_presence(owner, repo, token, issue_number, timeout):
        issue_called["presence"] = True
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/3",
            "bot_logins": ["vibeteam-software-engineer-bot[bot]"],
            "passed": True,
        }

    def fake_pr_presence(owner, repo, token, pr_number, timeout):
        return {
            "thread": "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1",
            "bot_logins": ["vibeteam-support-engineer-bot[bot]"],
            "passed": True,
        }

    monkeypatch.setattr(eval_github_e2e, "_run_issue_handoff_presence", fake_issue_presence)
    monkeypatch.setattr(eval_github_e2e, "_run_pr_handoff_presence", fake_pr_presence)

    result = eval_github_e2e._run_issue_pr_handoff(
        "VibeTechnologies",
        "vibeteam-eval-hello-world",
        "token",
        3,
        1,
        60,
    )

    assert issue_called["presence"] is True
    assert result["passed"] is True
    assert result["threads"]["issue"]["passed"] is True
    assert result["threads"]["pr"]["passed"] is True
    assert result["bot_logins"] == [
        "vibeteam-software-engineer-bot[bot]",
        "vibeteam-support-engineer-bot[bot]",
    ]


def test_write_report_with_thread_details(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    issue_url = "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/issues/3"
    pr_url = "https://github.com/VibeTechnologies/vibeteam-eval-hello-world/pull/1"
    results = {
        "thread": f"{issue_url} | {pr_url}",
        "passed": True,
        "bot_logins": ["vibeteam-software-engineer-bot[bot]"],
        "threads": {
            "issue": {
                "thread": issue_url,
                "passed": True,
                "bot_logins": ["bot-a"],
                "recent_bot_logins": ["bot-a"],
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
    assert "- Recent bot authors after trigger: bot-a" in report
