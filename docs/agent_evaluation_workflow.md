# Agent Evaluation Workflow

This is a short overview of the evaluation loop. The canonical architecture and scenario details live in [eval-architecture.md](eval-architecture.md).

## Loop Overview

1. Run `scripts/eval_slack_e2e.py` to post a scenario to Slack.
2. The script calls `POST /slack/trigger` with `Authorization: Bearer $SLACK_TRIGGER_SECRET`.
3. Agents respond in the thread and the eval script collects replies.
4. DeepEval scores the thread transcript and writes a report to `results/eval_reports/`.

## Key Notes

- Role mentions are parsed via `agents/shared/role_resolver.py` and accept `@RoleName` or `/RoleName`.
- The judge model is configured in `scripts/eval_slack_e2e.py` (default `gpt-5.2`).
- Metrics and thresholds are scenario-specific and defined in `scripts/eval_slack_e2e.py` (`SCENARIOS`). Reports list the per-metric thresholds used for that run.
- See [design.md](design.md) for system architecture.

## Run a Scenario

```bash
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
uv run python scripts/eval_slack_e2e.py --scenario software_engineer_pr_attribution --channel C0AATPSADB8 --timeout 600
```
