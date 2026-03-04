---
name: github-handoff-evals
description: Run VibeTeam GitHub/Slack handoff validation with unit tests, Slack evals, GitHub webhook evals, and permission checks. Use when validating multi-agent GitHub communication (issues, discussions, PR comments) or when asked to prove changes via tests/evals and record status.
---

# GitHub Handoff Evals

## Checklist
1. Export env once: `export $( < .env )`.
2. Requirement for cross-channel handoff evals: use native role mentions only
   (`@SoftwareEngineer`, `@SupportEngineer`) in trigger text. Do not use slash mentions.
3. Pause rollouts before any eval: `kubectl rollout pause deployment/vibeteam-gateway -n vibeteam` and `kubectl rollout pause deployment/openhands-svc -n vibeteam`.
4. Run unit tests with rerunfailures disabled: `.venv/bin/python -m pytest tests/ -v -p no:rerunfailures`.
5. Run a Slack eval:
   - Preferred: `.venv/bin/python scripts/eval_slack_e2e.py --scenario github_issue_pr_handoff_slack --channel C0AATPSADB8 --timeout 600`
   - Fallback: `.venv/bin/python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600`
6. Run GitHub webhook evals:
   - Matched issue+PR handoff (same semantics as Slack): `.venv/bin/python scripts/eval_github_e2e.py --scenario github_issue_pr_handoff_github --repo VibeTechnologies/vibeteam-eval-hello-world --issue 3 --pr 1 --timeout 600`
   - Full thread coverage (issue + discussion + PR): `.venv/bin/python scripts/eval_github_e2e.py --scenario github_threads_all --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --timeout 600`
7. Check GitHub App permissions (Discussions):
   - `.venv/bin/python scripts/check_github_app_permissions.py --require-discussions`
8. Resume rollouts after evals:
   - `kubectl rollout resume deployment/vibeteam-gateway -n vibeteam`
   - `kubectl rollout resume deployment/openhands-svc -n vibeteam`
9. Record results in the GitHub issue with links to eval reports under `results/eval_reports/`.

## Notes
- If `pytest` fails with `PermissionError` binding a socket, use `-p no:rerunfailures`.
- If `uv` cannot write cache, set `UV_CACHE_DIR=/tmp/uv-cache` or use `.venv/bin/python` directly.
- If GitHub evals fail with `Resource not accessible by integration`, update GitHub App Discussions permission and re-install the app on the eval repo.
- If network/DNS is blocked, capture the exact error and report it as a test/eval blocker.
