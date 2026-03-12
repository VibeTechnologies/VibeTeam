# Handoff for Opus 4.6: Slack/GitHub Per-Agent Identity Alignment

## Scope
This handoff documents the gaps missed in the previous patch attempt.
Goal: enforce per-agent Slack/GitHub app identities end-to-end and align docs with real behavior.

## Current Workspace State
- Branch: `master`
- Base SHA when work started: `5ec0bca495e4c18dcbf6748ceed9779fb3f644a4`
- Current uncommitted diff includes edits in:
  - `vibeteam/gateway/routes/slack.py`
  - `vibeteam/gateway/routes/github.py`
  - `vibeteam/utils/github_app.py`
  - `tests/test_slack_role_tokens.py`
  - `tests/test_github_role_token_strict.py` (new)
  - `docs/slack.md`, `docs/requirements.md`, `docs/webhook-routing.md`

## What Was Fixed Already
1. Removed Slack reply fallback to ingress token in `send_slack_message()`.
   - File: `vibeteam/gateway/routes/slack.py`
   - Behavior changed: role replies no longer retry with `SLACK_BOT_TOKEN` when role token fails.
2. Added/updated unit tests for strict Slack reply behavior.
   - File: `tests/test_slack_role_tokens.py`
3. Tightened GitHub role token resolution utility to avoid role -> global fallback.
   - File: `vibeteam/utils/github_app.py`
4. Added strict GitHub role-token tests.
   - File: `tests/test_github_role_token_strict.py`

## Critical Gaps Missed

### Gap 1 (P0): `app_mention` path strips role app mentions before routing
- Evidence:
  - `vibeteam/gateway/routes/slack.py:2522` removes all `<@U...>` mentions from text.
  - This includes role app mentions like `<@U_SUPPORT_BOT>`.
- Impact:
  - Message like `<@VIBETEAM_INGRESS> <@SUPPORT_BOT> investigate` loses the role mention.
  - Router then falls back to keyword routing and can invoke the wrong role.
  - This directly conflicts with per-agent Slack app handle usage.
- Required fix:
  - Keep role mentions while removing only ingress mention, or resolve role from user mentions before stripping.
  - Add explicit test for app_mention containing ingress + role user mention.

### Gap 2 (P0): Strict role identity applies only to `chat.postMessage`, not full Slack action surface
- Evidence:
  - `update_slack_message()` uses `_resolve_slack_bot_token(role)` with global fallback at `slack.py:926`.
  - `add_reaction()` uses `_resolve_slack_bot_token(role)` at `slack.py:982`.
  - `remove_reaction()` uses `_resolve_slack_bot_token(role)` at `slack.py:1093`.
  - `_resolve_slack_bot_token()` itself still falls back to global token (`slack.py:735-737`).
- Impact:
  - Role workflows can still produce ingress-attributed reactions/updates.
  - Identity consistency remains partial and can hide role token misconfiguration.
- Required fix:
  - Introduce strict role-token resolver for all role-attributed Slack writes (message, reactions, updates, status).
  - Fail loudly for missing role token in role-attributed paths.

### Gap 3 (P0): GitHub per-role strictness is incomplete in runtime/connectors
- Evidence:
  - `vibeteam/connectors/github.py:160-169` falls back to global app credentials and PAT (`GITHUB_TOKEN`).
  - `agent_service/openhands/server.py:82-84` sets role token only if available, otherwise leaves existing global `GITHUB_TOKEN` in place.
  - Same pattern exists in `agent_service/autogen/server.py`, `agent_service/crewai/server.py`, `agent_service/openclaw/server.py`.
  - `agent_service/shared/integration_checks.py:13-19,55-57` still treats global PAT/default app as sufficient.
- Impact:
  - Role execution can silently use non-role credentials, breaking per-agent GitHub attribution.
- Required fix:
  - In role context, clear/override global token unless matching role token exists.
  - Enforce role-scoped GitHub App creds for role-routed webhook/agent actions.
  - Update startup validation to require role-scoped creds for configured roles.

### Gap 4 (P0): Slack eval flow bypasses real webhook ingress path
- Evidence:
  - `scripts/eval_slack_e2e.py:2800-2805` strips role mentions before posting to Slack.
  - `scripts/eval_slack_e2e.py:2810-2879` then triggers `/slack/trigger` directly.
- Impact:
  - Evals can pass even if real Slack event routing is broken in `app_mention`/`message.channels` flows.
  - This explains false confidence when production conversations fail.
- Required fix:
  - Add webhook-native eval mode that posts real role mentions and waits for `/slack/events` processing without `/slack/trigger`.
  - Keep `/slack/trigger` mode as separate diagnostic path, not primary acceptance gate.

### Gap 5 (P1): Docs still describe `@VibeTeam` as primary trigger despite direct role-handle policy
- Evidence:
  - `docs/slack.md:148` says app_mention `@VibeTeam` is primary entry point.
  - `docs/slack.md:155,169,307,348,350,361` repeatedly instructs `@VibeTeam` usage.
  - `docs/webhook-routing.md:11` still states `@VibeTeam` activates thread.
- Impact:
  - Operator/user guidance is inconsistent with requested behavior (direct per-agent handles).
- Required fix:
  - Update docs to make direct role app mentions first-class path.
  - Keep ingress app as transport receiver implementation detail, not user-facing invocation requirement.

### Gap 6 (P2): Legacy script/docs still describe deprecated prefix-based behavior
- Evidence:
  - `scripts/run_slack_bot.py:8-23` documents `@VibeTeam` and `[Role]` response prefixes.
  - `scripts/eval_slack_e2e.py:2726-2771,3095-3100` still has legacy `[Role]` prefix fallback parsing.
- Impact:
  - Legacy patterns remain in tooling and can hide identity/routing regressions.
- Required fix:
  - Mark legacy script as deprecated or update it.
  - Remove legacy-prefix fallback from eval assertions once migration window is closed.

## Test/Eval Status (Truth)
- Completed:
  - `uv run python -m pytest tests/test_slack_role_tokens.py tests/test_github_role_token_strict.py -v`
  - Result: `15 passed`.
- Not completed:
  - Full `uv run python -m pytest tests -v` (run was interrupted).
  - `uv run python -m pytest tests -v --run-integration` not executed after this patch.
  - Live Slack eval on current deployment not executed after this patch.

## Required Next Actions for Opus 4.6
1. Fix P0 gaps 1-4 before any merge.
2. Add regression tests:
   - `app_mention` with ingress + role user mention.
   - Strict role identity for reactions and updates.
   - Runtime context test proving no global token fallback in role execution.
   - Eval-mode test covering webhook-native path.
3. Run required validation:
   - `uv run python -m pytest tests -v`
   - `uv run python -m pytest tests -v --run-integration`
   - At least one webhook-native Slack eval in `#vibe-team` channel.
4. Confirm Slack thread responses are posted by role app user IDs (not ingress user ID).
5. Update docs (`docs/slack.md`, `docs/webhook-routing.md`, `docs/requirements.md`, `docs/testing.md`) to match final behavior.

## Acceptance Criteria
- No role-attributed Slack write uses ingress token fallback.
- No role-attributed GitHub action uses global PAT/default app fallback.
- Webhook-native eval passes in `#vibe-team` with role app identity evidence.
- Docs and implementation describe the same invocation model and identity guarantees.
