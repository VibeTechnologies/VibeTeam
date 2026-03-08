---
name: task-completition-evaluation
description: Final completion gate for VibeTeam tasks. Use at the end of implementation to verify diff quality, real testing, GitHub/Slack multi-agent communication evidence, and PR health before declaring done.
---

# Task Completition Evaluation

Use this skill only at the end of a task, after implementation is complete and before reporting completion.

## Required Inputs

- Task reference: GitHub issue/PR URL.
- Code evidence: `git diff`/patch and changed file list.
- Test evidence: command outputs and report files.
- Collaboration evidence: Slack thread URL(s), GitHub issue/PR/discussion URL(s), and eval report paths.

## Completion Checklist (All Required)

1. Review diff/patch.
   - Run `git status --short` and `git diff --stat`.
   - Inspect full diff for correctness, scope control, and accidental edits.
2. Reflect: cleanup.
   - Remove dead code, debug output, TODO placeholders, and temporary files.
   - Confirm no tests were weakened to force passing.
3. Reflect: optimality.
   - Verify the issue is solved in the simplest robust way.
   - Confirm docs and design alignment for behavior changes.
4. Run real tests (not mocked shortcuts).
   - Export environment first:
     - `export $( < ~/.env.d/codex.env )`
     - `export $( < .env )`
   - Run unit/integration tests relevant to the touched area.
   - If agent behavior/routing/tools/eval logic changed, run at least one Slack eval.
   - Fail the checklist if tests were skipped without explicit justification.
5. Run GitHub evaluation tests for agent collaboration.
   - Use `scripts/eval_github_e2e.py` scenarios relevant to the task.
   - Verify and report:
     - different GitHub App identities participated as different agents
     - correct existing `@githubapphandle` mentions were used
     - agents communicated/handoff occurred across thread(s)
6. Run Slack evaluation tests for agent collaboration.
   - Use `scripts/eval_slack_e2e.py` scenarios relevant to the task.
   - Verify and report:
     - different Slack app identities participated as different agents
     - correct existing `@slackapphandle` mentions were used
     - agents communicated/handoff occurred
     - Slack thread URL is included and manually reviewed against requirements
7. Create PR and verify checks.
   - Create a PR linked to the issue (`Fixes #<issue>`).
   - Confirm required GitHub checks pass before completion claim.

## Minimum Command Set

```bash
# Inspect changes
git status --short
git diff --stat
git diff

# Test/eval environment
export $( < ~/.env.d/codex.env )
export $( < .env )

# Example unit tests
uv run python -m pytest tests/ -v

# Example Slack eval
uv run python scripts/eval_slack_e2e.py --scenario github_issue_pr_handoff_slack --channel C0AATPSADB8 --timeout 600

# Example GitHub eval
uv run python scripts/eval_github_e2e.py --scenario github_issue_pr_handoff_github --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --actor-login OpenCodeEngineer --issue-role software_engineer --issue-assignee 'vibeteam-swe-bot-260301[bot]' --timeout 600
```

## Evidence Required In Final Report

- Docs referenced:
  - `docs/testing.md`
  - `docs/design.md`
  - `docs/requirements.md`
- Design decisions applied: decision, reason, impact.
- Test results: exact commands + pass/fail summary.
- Eval artifacts:
  - Slack thread URL(s) and transcript summary.
  - GitHub thread URL(s).
  - Report file paths in `results/eval_reports/`.
- Clear verdict: `COMPLETED` only when every checklist item is satisfied.
