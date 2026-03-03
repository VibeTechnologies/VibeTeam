# VibeTeam Test Suite

## Overview

The test suite contains **660+ tests** covering unit, integration, and E2E evaluation flows. All tests live in the `tests/` directory and run with `pytest`.

```bash
export $( < .env) && .venv/bin/python -m pytest tests/ -v
```

## Test Files

### Core Gateway & Routing

| File | What It Tests |
|------|---------------|
| `test_task_routing.py` | Task template classification (`investigation`, `feature_request`, `conversational`), including thread reply behavior. Contains `TestConversationalTemplate` with 10 tests for thread follow-up handling. |
| `test_async_callback.py` | Async agent callback flow, Slack reaction lifecycle (`thinking_face` → checkmark/X/hourglass), handoff chaining. |
| `test_gateway_trigger.py` | `/slack/trigger` endpoint authentication and routing. |
| `test_role_resolver.py` | `@RoleName` and `/RoleName` mention parsing and normalization. |
| `test_message_splitting.py` | Splitting long agent responses to fit Slack's 4000-char limit. |

### Agent Tools

| File | What It Tests |
|------|---------------|
| `test_slack_tools.py` | Slack tool functions (send message, react, thread operations). |
| `test_sentry_tools.py` | Sentry API integration tools (issue lookup, event details). |
| `test_kubectl_tools.py` | kubectl command execution and output parsing. |

### Integrations

| File | What It Tests |
|------|---------------|
| `test_openhands_service_integration.py` | OpenHands agent service `/run` endpoint (requires `--run-integration`). |
| `test_webhook_integration.py` | GitHub webhook signature verification and event routing. |
| `test_sentry_integration.py` | Sentry webhook processing and alert routing. |
| `test_github_app_auth.py` | GitHub App JWT generation and installation token exchange. |
| `test_gmail_integration.py` | Gmail API connection and message retrieval. |
| `test_gmail_processor.py` | Email pipeline: escalation detection, ticket extraction, docs portal filtering. |
| `test_langfuse_integration.py` | Langfuse tracing integration. |
| `test_browser_integration.py` | Browser/Chrome DevTools MCP integration. |

### Agent Response

| File | What It Tests |
|------|---------------|
| `test_response_extraction.py` | Extracting agent responses from OpenHands session output. |
| `test_extract_response.py` | Additional response extraction edge cases. |
| `test_system_prompt.py` | System prompt generation for different agent roles. |

### Infrastructure

| File | What It Tests |
|------|---------------|
| `test_module_paths.py` | Python import paths resolve correctly across the package. |
| `test_integration.py` | General integration smoke tests. |
| `test_eval_rescore.py` | DeepEval rescoring logic for evaluation reports. |

## Running Tests

```bash
# All tests
export $( < .env) && .venv/bin/python -m pytest tests/ -v

# Specific file
.venv/bin/python -m pytest tests/test_task_routing.py -v

# Integration tests (require live services)
.venv/bin/python -m pytest tests/test_openhands_service_integration.py -v --run-integration -s

# E2E evaluation (posts to real Slack)
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
uv run python scripts/eval_slack_e2e.py --scenario software_engineer_pr_attribution --channel C0AATPSADB8 --timeout 600
uv run python scripts/eval_slack_e2e.py --scenario software_engineer_github_app_hello_world --channel C0AATPSADB8 --timeout 600
uv run python scripts/eval_slack_e2e.py --scenario github_issue_pr_handoff_slack --channel C0AATPSADB8 --timeout 600

`github_issue_pr_handoff_slack` validates cross-agent handoff comments across issue and PR threads in the eval repo.

# GitHub webhook evaluation (issues/discussions/PR comments)
uv run python scripts/eval_github_e2e.py --scenario github_threads_all --repo VibeTechnologies/vibeteam-eval-hello-world --pr 1 --timeout 600
```

`eval_github_e2e.py` also respects:
`GITHUB_TEST_REPO` (default `VibeTechnologies/vibeteam-eval-hello-world`) and
`GITHUB_TEST_PR` (default `1`).

Discussion handoffs require GitHub App Discussions read/write permission on the eval repo.
If the app was updated, re-install or approve the new permissions before rerunning the eval.

## Test Categories

### Worth Covering (High Value)

- **Pure logic/unit tests**: mention parsing, task template classification, response extraction
- **Mocked connector tests**: validate polling loops, bot message skipping, thread replies
- **Routing/handoff tests**: role fan-out, subscription management
- **DB migration tests**: schema creation with ephemeral database
- **Sentry triage logic**: pattern matching, severity classification
- **Email pipeline logic**: escalation detection, ticket extraction

### Not Worth Mocking (Use E2E Instead)

- Full daemon loops with real Slack/Discord (high flake rate)
- Signal handling and logging output (brittle assertions)
- DeepEval scoring correctness (third-party behavior)
- Real Gmail/Sentry/GitHub network tests in CI (too flaky)
