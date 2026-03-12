# Testing and Evaluation Guide

This is the single canonical document for VibeTeam testing and evaluation.

## Scope

This guide consolidates:
- unit and integration test guidance
- E2E evaluation requirements
- scenario catalogs and expected outcomes
- scoring and troubleshooting

## Required Workflow

1. Run unit tests.
2. Run evals relevant to the change.
3. If an eval fails: fix code/config/team behavior, rerun eval, repeat until pass.
4. Report results with required conversation URLs.

## Required Reporting (Hard Rule)

Every eval update must include URLs:
- Slack evals: Slack thread URL (`https://slack.com/app_redirect?...`).
- GitHub evals: GitHub issue/discussion/PR URL(s).
- Cross-channel evals: both Slack and GitHub URLs.

## Environment Setup

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
```

## Rollout Safety for Evals

```bash
kubectl rollout pause deployment/vibeteam-gateway -n vibeteam
kubectl rollout pause deployment/openhands-svc -n vibeteam

# run evals

kubectl rollout resume deployment/vibeteam-gateway -n vibeteam
kubectl rollout resume deployment/openhands-svc -n vibeteam
```

## Core Commands

```bash
# Unit tests (all)
uv run python -m pytest tests/ -v

# Unit tests (single file)
uv run python -m pytest tests/test_task_routing.py -v

# Integration tests (live services required)
uv run python -m pytest tests/test_openhands_service_integration.py -v --run-integration -s

# List Slack eval scenarios
uv run python scripts/eval_slack_e2e.py --list-scenarios

# Slack eval examples
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0ALG01DLJV --timeout 600
uv run python scripts/eval_slack_e2e.py --scenario github_issue_pr_handoff_slack --channel C0ALG01DLJV --timeout 600

# GitHub webhook eval examples
uv run python scripts/eval_github_e2e.py --scenario github_issue_pr_handoff_github --repo VibeTechnologies/vibeteam-eval-hello-world --issue 3 --pr 1 --timeout 600
uv run python scripts/eval_github_e2e.py --scenario github_threads_all --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --timeout 600

# GitHub App/assignee preflight (required before assignment-first evals)
uv run python scripts/check_github_app_permissions.py --repo VibeTechnologies/vibeteam-eval-hello-world --require-discussions --require-assignable-assignee
```

## Test Suite Map

### Core Gateway and Routing

| File | What It Tests |
|---|---|
| `test_task_routing.py` | Task template classification and thread reply behavior |
| `test_async_callback.py` | Async callbacks, Slack reactions, handoff chaining |
| `test_gateway_trigger.py` | `/slack/trigger` auth and routing |
| `test_role_resolver.py` | `@RoleName` and `/RoleName` parsing |
| `test_message_splitting.py` | Slack-safe response splitting |

### Agent Tools

| File | What It Tests |
|---|---|
| `test_slack_tools.py` | Slack send/react/thread operations |
| `test_sentry_tools.py` | Sentry issue/event tool operations |
| `test_kubectl_tools.py` | kubectl execution and parsing |

### Integrations

| File | What It Tests |
|---|---|
| `test_openhands_service_integration.py` | OpenHands `/run` integration |
| `test_webhook_integration.py` | GitHub webhook signature and routing |
| `test_sentry_integration.py` | Sentry webhook processing |
| `test_github_app_auth.py` | GitHub App JWT and installation token flow |
| `test_gmail_integration.py` | Gmail API connectivity |
| `test_gmail_processor.py` | Email triage/escalation pipeline |
| `test_langfuse_integration.py` | Langfuse tracing |
| `test_browser_integration.py` | Browser/CDP integration |

### Agent Response and Infra

| File | What It Tests |
|---|---|
| `test_response_extraction.py` | Agent response extraction |
| `test_extract_response.py` | Response extraction edge cases |
| `test_system_prompt.py` | Role-specific prompt generation |
| `test_module_paths.py` | Python module path integrity |
| `test_integration.py` | General integration smoke |
| `test_eval_rescore.py` | DeepEval report rescoring logic |

## E2E Evaluation Flow

1. Eval script posts to Slack or updates/creates a GitHub thread.
2. Slack evals call `POST /slack/trigger` with `SLACK_TRIGGER_SECRET`.
3. Gateway parses role mentions and routes to framework service.
4. Agent(s) execute and reply in the same thread.
5. Eval script polls until thread is stable.
6. DeepEval scores transcript metrics (unless `--skip-eval`), and report is written.

## Architecture (Consolidated)

- Driver scripts:
  - `scripts/eval_slack_e2e.py`
  - `scripts/eval_github_e2e.py`
- Routing:
  - `vibeteam-gateway` (`/slack/trigger`, GitHub webhook route)
  - role mention parser + framework routing
- Agent runtime:
  - `agent_service/openhands` (and other framework services)
- Artifacts:
  - Slack/GitHub thread links
  - `results/eval_reports/eval_<scenario>_<timestamp>.md`

## Operational Loop

1. Run scenario.
2. Verify thread activity.
3. Verify required post-checks.
4. Verify metric thresholds and overall pass.
5. If fail, fix and rerun until pass.

## Slack Scenario Catalog and Expected Outcomes

Slack scenarios are defined in `scripts/eval_slack_e2e.py` (`SCENARIOS`).

| Scenario ID | Expected Agent | Expected Outcome |
|---|---|---|
| `support_400_errors` | `support_engineer` | Investigate 400 errors with internal evidence and provide evidence-based resolution/handoff. |
| `support_notify_check` | `support_engineer` | Send notification only without unnecessary investigation flow. |
| `support_sentry_triage` | `support_engineer` | Check Sentry and answer whether action is required. |
| `support_sentry_to_pr` | `support_engineer` | Review Sentry and create PR/close issue when required. |
| `software_engineer_pr_attribution` | `software_engineer` | Create PR authored by role bot (GitHub App), not personal account. |
| `software_engineer_github_app_hello_world` | `software_engineer` | Create/reuse eval repo and open bot-authored PR there. |
| `github_issue_pr_handoff_slack` | `software_engineer` | Create issue+PR comments and ensure multi-bot participation in both threads. |
| `support_gmail_inbox` | `support_engineer` | Perform inbox triage and provide actionable next steps or explicit no-action state. |
| `chrome_cdp_smoke` | `marketing_manager` | Use CDP tools and return requested artifacts/facts. |
| `openclaw_chrome_cdp_smoke` | `product_manager` | Execute OpenClaw CDP smoke flow and report outputs. |
| `marketing_reddit_engagement` | `marketing_manager` | Produce community-fit soft-promo Reddit engagement outputs. |
| `marketing_hn_engagement` | `marketing_manager` | Produce HN-fit, non-spam engagement outputs. |
| `marketing_google_finance_news` | `marketing_manager` | Gather MSFT/NVDA news via CDP with source/timestamp context. |
| `github_issue` | `software_engineer` | Investigate referenced GitHub issue with concrete diagnosis and next actions. |
| `release_deploy` | `release_engineer` | Execute validated deployment workflow (disabled in scenario config by default). |
| `stripe_webhook_failure` | `support_engineer` | Investigate Stripe webhook failures with concrete remediation path. |
| `release_health_check` | `release_engineer` | Perform production health/readiness checks with evidence-based conclusion. |
| `release_k3s_configure_then_health` | `release_engineer` | Two-step flow: configure k3s access context first, then investigate `vibe` cluster health in the same thread. |

Implementation note for trigger-driven evals:
- `release_k3s_configure_then_health` runs through `/slack/trigger` and seeds a validated kubeconfig context via trigger payload (`kubeconfig_yaml`) so the agent receives thread-scoped cluster context without relying on bot-generated Slack file events.
- Real user flow remains Slack attachment-based (`/slack/events` with uploaded kubeconfig file), as documented in `docs/slack.md`.

Collaboration identity requirement (hard check for `github_issue_pr_handoff_slack`):
- Required Slack roles must respond (`software_engineer`, `support_engineer`).
- Each required role must post using its own role-scoped Slack app identity.
- The eval validates this via Slack `auth.test` user IDs for role tokens and fails when role identities are shared or mismatched.
- Report evidence must come from the generated `Conversation History` section and include role-attributed messages plus concrete GitHub/Slack URLs from that same run.
- Synthetic traces, placeholders, or hand-written “mock conversation” summaries do not satisfy this requirement.

## GitHub Webhook Scenario Catalog and Expected Outcomes

GitHub scenarios are defined in `scripts/eval_github_e2e.py` (`SCENARIOS`).

| Scenario ID | Expected Outcome |
|---|---|
| `github_issue_handoff` | Issue thread shows bot activity and assignment check passes for target assignee. |
| `github_issue_pr_handoff_github` | Issue and PR threads both pass bot activity checks; issue assignment check passes. |
| `github_discussion_handoff` | Discussion thread receives expected multi-bot handoff responses. |
| `github_pr_comment_handoff` | PR thread receives expected multi-bot handoff responses. |
| `github_threads_all` | Issue + discussion + PR sub-scenarios all pass in one run. |

## Assignment-Immediate Validation (No Eval Trigger Comment)

Use this mode to validate that assignment alone triggers immediate work without eval-authored trigger comment.

```bash
uv run python scripts/eval_github_e2e.py \
  --scenario github_issue_handoff \
  --repo VibeTechnologies/vibeteam-eval-hello-world \
  --issue <EXISTING_ISSUE_NUMBER> \
  --actor-login 'OpenCodeEngineer' \
  --issue-role software_engineer \
  --issue-assignee 'vibeteam-swe-bot-260301[bot]' \
  --timeout 600
```

Expected outcome:
- no new eval-authored trigger comment on the issue
- assignment to configured role bot handle is verified
- bot activity appears after assignment event processing
- for existing issues already assigned to target bot, eval forces a reassignment (remove+add) to emit a fresh `issues.assigned` event

Fallback mode (for repos where GitHub App bot assignees are not assignable via API):
- eval keeps the role-bot assignee target unchanged and records assignment failure
- eval posts a native role-mention trigger comment
- pass requires bot responses from required role bots after that trigger (no placeholder-only pass)

Task-to-agent rule (hard requirement):
- Different tasks must be assigned to different role bot handles.
- Code-writing task -> SoftwareEngineer bot assignee.
- Support task -> SupportEngineer bot assignee.
- Release/deploy task -> ReleaseEngineer bot assignee.
- Product triage task -> ProductManager bot assignee.
- Marketing task -> MarketingManager bot assignee.

Role-to-assignee defaults used by `scripts/eval_github_e2e.py`:

| `--issue-role` | Default assignee env (fallback chain) |
|---|---|
| `software_engineer` | `GITHUB_SOFTWARE_ENGINEER_BOT_ASSIGNEE` -> `GITHUB_APP_BOT_USERNAME_SOFTWARE_ENGINEER` -> `vibeteam-swe-bot-260301[bot]` |
| `support_engineer` | `GITHUB_SUPPORT_ENGINEER_BOT_ASSIGNEE` -> `GITHUB_APP_BOT_USERNAME_SUPPORT_ENGINEER` -> `vibeteam-support-bot-260301[bot]` |
| `release_engineer` | `GITHUB_RELEASE_ENGINEER_BOT_ASSIGNEE` -> `GITHUB_APP_BOT_USERNAME_RELEASE_ENGINEER` -> `vibeteam-release-bot-260301[bot]` |
| `product_manager` | `GITHUB_PRODUCT_MANAGER_BOT_ASSIGNEE` -> `GITHUB_APP_BOT_USERNAME_PRODUCT_MANAGER` -> `vibeteam-pm-bot-260301[bot]` |
| `marketing_manager` | `GITHUB_MARKETING_MANAGER_BOT_ASSIGNEE` -> `GITHUB_APP_BOT_USERNAME_MARKETING_MANAGER` -> `vibeteam-mktg-bot-260301[bot]` |

Role-specific assignment eval examples:

```bash
# Support assignment scenario (existing issue)
uv run python scripts/eval_github_e2e.py \
  --scenario github_issue_handoff \
  --repo VibeTechnologies/vibeteam-eval-hello-world \
  --issue <EXISTING_ISSUE_NUMBER> \
  --actor-login 'OpenCodeEngineer' \
  --issue-role support_engineer \
  --issue-assignee 'vibeteam-support-bot-260301[bot]' \
  --timeout 600
```

Notes:
- `--actor-login` is the account creating and assigning issues during eval (for this repo: `OpenCodeEngineer`).
- `--issue-assignee` must be a bot app handle. Handles with `-bot`/`[bot]` pass automatically; explicit configured bot handles also pass.
- Reports now include `Assignment fallback mode` and `Assignment fallback reason` when assignment cannot be applied to the role bot.
- Role-assignee compatibility is enforced by the eval runner. If `--issue-role` and
  `--issue-assignee` do not match the configured role mapping, eval exits immediately with
  `Issue assignee does not match required role mapping`.
- If bot assignment fails on fresh issues, treat it as GitHub/repo operational misconfiguration and fix assignability;
  do not replace assignee with a human account.
- See `docs/github.md` for the true-fix checklist.
- If `/repos/{owner}/{repo}/assignees/{handle}` returns `404`, that handle is not assignable in this repo.
- GitHub App `[bot]` identities may fail assignability checks; use a repo-assignable role identity and map it via
  `GITHUB_<ROLE>_BOT_ASSIGNEE` / `GITHUB_ASSIGNMENT_BOT_LOGINS` when required by repo policy.

## Scoring Rubric

| Score Range | Meaning |
|---|---|
| `0.0-0.2` | complete failure / no meaningful progress |
| `0.2-0.4` | minimal progress |
| `0.4-0.6` | partial success |
| `0.6-0.8` | good, actionable result |
| `0.8-1.0` | strong, complete outcome |

## Metrics and Thresholds

- Thresholds are scenario-specific in `scripts/eval_slack_e2e.py` (`SCENARIOS`).
- A scenario passes only when required metrics and required post-checks pass.
- Common metric families:
  - `InvestigationQuality`, `EvidenceBasedDecision`, `TaskCompletion`
  - `HandoffCompletion`, `ResponseEfficiency`
  - domain-specific metrics such as `SentryUsage`, `GmailUsage`, `IssueAnalysis`, `ChromeDevToolsUsage`
- If DeepEval is unavailable, reports are written without metric scores.

## Common Failure Modes

| Symptom | Likely Cause | Action |
|---|---|---|
| No agent response | Restart/routing issue | Pause rollouts; inspect gateway and agent logs |
| 401/403 in eval checks | Wrong token exported | Re-export env and verify GitHub/Azure tokens |
| Waiting indefinitely | Agent processing stalled | Verify webhook acceptance and service logs |
| Discussion permission errors | App permission/install approval missing | Update app permissions and reinstall |
| Handoff missing | Mention/routing gap | Validate mention format and routing logs |

## Coverage Guidance

### Worth Covering (High Value)

- pure logic/unit tests
- mocked connector tests
- routing/handoff tests
- migration tests
- Sentry/Gmail triage logic

### Avoid Over-Mocking (Prefer E2E)

- full daemon loops with real external services in CI
- brittle signal/logging assertions
- third-party model score correctness assertions

## Reports

- Reports are saved to `results/eval_reports/`.
- Include report path plus required Slack/GitHub URLs in every update.
