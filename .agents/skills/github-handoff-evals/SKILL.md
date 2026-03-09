---
name: github-handoff-evals
description: Run VibeTeam GitHub/Slack handoff validation with unit tests, Slack evals, GitHub webhook evals, and permission checks. Use when validating multi-agent GitHub communication (issues, discussions, PR comments) or when asked to prove changes via tests/evals and record status.
---

# GitHub Handoff Evals

## Checklist
1. Export env once:
   - `export $( < ~/.env.d/codex.env )`
   - `export $( < .env )`
2. Requirement for cross-channel handoff evals: use native role mentions only
   (`@SoftwareEngineer`, `@SupportEngineer`) in trigger text. Do not use slash mentions.
3. Pause rollouts before any eval:
   - `kubectl rollout pause deployment/vibeteam-gateway -n vibeteam`
   - `kubectl rollout pause deployment/openhands-svc -n vibeteam`
4. Run unit tests with rerunfailures disabled:
   - `.venv/bin/python -m pytest tests/ -v -p no:rerunfailures`
5. Run at least one Slack eval:
   - Preferred: `.venv/bin/python scripts/eval_slack_e2e.py --scenario github_issue_pr_handoff_slack --channel C0AATPSADB8 --timeout 600`
   - Fallback: `.venv/bin/python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600`
6. Run GitHub webhook evals (assignment-first, role-bot required):
   - Code-writing task (SoftwareEngineer bot assignee):
     - `.venv/bin/python scripts/eval_github_e2e.py --scenario github_issue_handoff --repo VibeTechnologies/vibeteam-eval-hello-world --actor-login OpenCodeEngineer --issue-role software_engineer --issue-assignee 'vibeteam-swe-bot-260301[bot]' --timeout 600`
   - Support task (SupportEngineer bot assignee):
     - `.venv/bin/python scripts/eval_github_e2e.py --scenario github_issue_handoff --repo VibeTechnologies/vibeteam-eval-hello-world --actor-login OpenCodeEngineer --issue-role support_engineer --issue-assignee 'vibeteam-support-bot-260301[bot]' --timeout 600`
   - Matched issue+PR handoff:
     - `.venv/bin/python scripts/eval_github_e2e.py --scenario github_issue_pr_handoff_github --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --actor-login OpenCodeEngineer --issue-role software_engineer --issue-assignee 'vibeteam-swe-bot-260301[bot]' --timeout 600`
   - Full thread coverage (issue + discussion + PR):
     - `.venv/bin/python scripts/eval_github_e2e.py --scenario github_threads_all --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --actor-login OpenCodeEngineer --issue-role software_engineer --issue-assignee 'vibeteam-swe-bot-260301[bot]' --timeout 600`
7. Verify assignability and role app permissions:
   - `.venv/bin/python scripts/check_github_app_permissions.py --repo VibeTechnologies/vibeteam-eval-hello-world --require-discussions --require-assignable-assignee`
   - `gh api repos/VibeTechnologies/vibeteam-eval-hello-world/assignees --jq '.[].login'`
   - `gh api graphql -f query='query { repository(owner:"VibeTechnologies", name:"vibeteam-eval-hello-world") { assignableUsers(first:100) { nodes { login } } } }' --jq '.data.repository.assignableUsers.nodes[].login'`
8. Resume rollouts after evals:
   - `kubectl rollout resume deployment/vibeteam-gateway -n vibeteam`
   - `kubectl rollout resume deployment/openhands-svc -n vibeteam`
9. Record results in the GitHub issue and include links:
   - Slack thread URL(s): `https://slack.com/app_redirect?...`
   - GitHub issue/discussion/PR URL(s)
   - report file path(s) in `results/eval_reports/`
   - transcript excerpt copied from report `Conversation History` (real messages from each required role)
   - For `github_issue_pr_handoff_slack`, confirm report includes:
     - `Slack required roles responded` ✅
     - `Slack distinct role app identities` ✅ (role tokens resolve to different bot user IDs)

## Hard Rules
- Different tasks must map to different role assignees:
  - code-writing -> software bot
  - support -> support bot
  - release -> release bot
  - product -> product bot
  - marketing -> marketing bot
- Never pass eval by switching assignment to a human assignee.
- If role bot is not assignable in GitHub API, use eval fallback mode only:
  - keep role-bot assignee target unchanged
  - require explicit `Assignment fallback mode` in report
  - require bot responses in-thread after native role-mention trigger

## Notes
- If `pytest` fails with `PermissionError` binding a socket, use `-p no:rerunfailures`.
- If `uv` cannot write cache, set `UV_CACHE_DIR=/tmp/uv-cache` or use `.venv/bin/python` directly.
- If GitHub evals fail with `Resource not accessible by integration`, update GitHub App Discussions permission and re-install the app on the eval repo.
- If eval exits with `Issue assignee does not match required role mapping`, align `--issue-role` and `--issue-assignee` or update role-assignee env mapping.
- If network/DNS is blocked, capture the exact error and report it as a test/eval blocker.
