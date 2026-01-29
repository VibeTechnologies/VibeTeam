# Plan: Fix OpenHands 0/5 Benchmark Failure

## Goal
Fix the OpenHands agent so it scores competitively (3-5/5) in benchmarks instead of timing out.

## Status: COMPLETED

OpenHands now scores **4/5** in benchmarks, matching CrewAI's performance.

## Final Benchmark Results

| Framework | Status | Latency | Score |
|-----------|--------|---------|-------|
| CREWAI | PASS | 49s | 4/5 |
| OPENHANDS | PASS | 164s | 4/5 |
| AUTOGEN | PASS | 39s | 2/5 |

**Winner: CREWAI** (tie-breaker on latency)

## Root Cause Analysis

Two issues were identified and fixed:

1. **Tools causing exploration loop** (FIXED): OpenHands agent had `TerminalTool` and `FileEditorTool` enabled, causing filesystem exploration instead of direct analysis. Added `use_tools=False` parameter.

2. **Response extraction bug** (FIXED): The code was checking for `AgentFinishAction` event type, but OpenHands wraps the action in an `ActionEvent` with action type `FinishAction`. Fixed to properly extract `ActionEvent.action.message` for `FinishAction` type.

## Steps

- [x] 1. Investigate OpenHands timeout - identified tools cause agentic exploration loop
- [x] 2. Review OpenHands agent implementation in `agents/openhands/support_engineer.py`
- [x] 3. Identify how to disable or limit tools for benchmark tasks
- [x] 4. Implement fix - add `use_tools` parameter to OpenHands agent
- [x] 5. Update benchmark to pass `use_tools=False` for OpenHands
- [x] 6. Fix response extraction for FinishAction (was checking wrong event type)
- [x] 7. Test OpenHands - scored 4/5
- [x] 8. Verify score improved to 3+/5 (achieved 4/5)
- [x] 9. Run full benchmark with all 3 frameworks
- [x] 10. Commit fix

## Files Modified

### `agents/openhands/support_engineer.py`
- Added `use_tools: bool = True` parameter to `_create_agent()`, `run()`, and `run_async()`
- When `use_tools=False`, agent is created without TerminalTool/FileEditorTool
- Fixed response extraction to check `ActionEvent` containing `FinishAction` or `AgentFinishAction`
- Response is now extracted from `action.message` attribute

### `scripts/benchmark_agents.py`
- Pass `use_tools=False` for OpenHands framework in `run_agent()`

## Key Learnings

1. OpenHands SDK wraps actions in events: `ActionEvent.action` contains the actual action object
2. The finish tool produces a `FinishAction` (not `AgentFinishAction`) with the response in `.message`
3. OpenHands always includes `ThinkTool` and `FinishTool` even when custom tools are empty
4. For analytical tasks without file/terminal needs, disabling exploration tools significantly improves performance

---

# Session 2: Fix Sentry Tool and Report Format (2026-01-29)

## Goal
1. Fix Sentry tool not receiving `SENTRY_AUTH_TOKEN` environment variable
2. Update benchmark report to show feedback in summary table instead of response length

## Status: COMPLETED

## Latest Benchmark Results

| Framework | Status | Latency | Score | Feedback |
|-----------|--------|---------|-------|----------|
| CREWAI | PASS | 61463ms | 4/5 | Clear, accurate interpretation of the stack trace... |
| AUTOGEN | PASS | 39001ms | 3/5 | Correctly identifies the core issue... |
| OPENHANDS | FAIL | 181196ms | 0/5 | No response content (LLM empty response issue) |

**Winner: CREWAI**

## Root Cause Analysis

**Sentry Tool Issue**: The benchmark script didn't use `python-dotenv` to load `.env` file. Running `source .env` in bash only sets shell variables, not Python's `os.environ`. Added `load_dotenv()` before config initialization.

**OpenHands New Issue**: Different from the previous fix - now producing empty LLM responses and getting stuck. This appears to be a model/API issue, not a code bug.

## Steps

- [x] 1. Investigate why Sentry tool returns "SENTRY_AUTH_TOKEN not configured"
- [x] 2. Found: `source .env` doesn't export to Python subprocess
- [x] 3. Add `from dotenv import load_dotenv; load_dotenv()` to benchmark script
- [x] 4. Update report format to include feedback column (truncated to 80 chars)
- [x] 5. Run benchmark to verify fixes
- [x] 6. Commit changes: `117b230`

## Files Modified

### `scripts/benchmark_agents.py`
- Added `from dotenv import load_dotenv` import
- Added `load_dotenv()` call before `BenchmarkConfig` class
- Changed summary table from "Response Length" to "Feedback" column
- Truncate feedback to 80 chars and escape pipe characters

## Open Issue

**OpenHands empty response**: ~~The agent produces empty LLM responses and gets stuck. This is flagged for separate investigation - likely a model configuration or API issue with Azure OpenAI when used through OpenHands SDK.~~ **RESOLVED** in Session 3.

---

# Session 3: Fix OpenHands Empty Response Issue (2026-01-29)

## Goal
Fix the OpenHands agent empty LLM response issue that caused 0/5 benchmark score.

## Status: COMPLETED

## Latest Benchmark Results

| Framework | Status | Latency | Score | Feedback |
|-----------|--------|---------|-------|----------|
| CREWAI | PASS | 34977ms | 4/5 | Clear, accurate diagnosis of a graph-cycle recursion... |
| AUTOGEN | PASS | 42075ms | 3/5 | Correctly identifies this as a LangGraph issue... |
| OPENHANDS | PASS | 62079ms | 3/5 | Accurately explains the likely execute-reflect loop... |

**Winner: CREWAI**

## Root Cause Analysis

Two issues were causing OpenHands to fail:

### Issue 1: Numbered Lists in Task (Partial cause)

OpenHands interprets numbered lists (`1. 2. 3.`) as action steps to execute rather than questions to answer. When tools are disabled with `use_tools=False`, the agent tries to use tools that don't exist, producing empty responses.

**Evidence**: 
- Task with `1. Analyze...` = empty response loop
- Task with `- Analyze...` = works correctly

**Fix**: Added `convert_numbered_lists_to_bullets()` function that transforms numbered lists to bullet points when `use_tools=False`.

### Issue 2: Excessive Reasoning Overhead (Main cause)

OpenHands defaults to `reasoning_effort='high'` and `extended_thinking_budget=200000`. This causes very long processing times (>180s) for complex tasks with injected Sentry context.

**Evidence**:
- Simple tasks: ~50-70s
- Complex benchmark task with high reasoning: >180s (timeout)
- Complex benchmark task with medium reasoning: ~62s

**Fix**: Set `reasoning_effort='medium'` and `extended_thinking_budget=10000` in the LLM configuration.

## Steps

- [x] 1. Investigate empty response pattern
- [x] 2. Identify numbered list interpretation issue
- [x] 3. Add convert_numbered_lists_to_bullets() function
- [x] 4. Update SUPPORT_ENGINEER_CONTEXT to use bullets instead of numbers
- [x] 5. Identify reasoning overhead issue causing timeouts
- [x] 6. Reduce reasoning_effort and extended_thinking_budget
- [x] 7. Test with exact benchmark task - SUCCESS (62s, 7069 chars)
- [x] 8. Run full benchmark - all frameworks pass

## Files Modified

### `agents/openhands/support_engineer.py`
- Added `import re` for regex operations
- Added `convert_numbered_lists_to_bullets(text: str) -> str` helper function
- Updated `SUPPORT_ENGINEER_CONTEXT` to use bullet points instead of numbered lists
- Applied conversion to full_task when `use_tools=False` 
- Added `reasoning_effort='medium'` and `extended_thinking_budget=10000` to LLM config

## Key Learnings

1. OpenHands treats numbered lists as imperative action steps, not questions to answer
2. OpenHands' default reasoning settings (`high`, 200k budget) are too slow for benchmarks
3. Reducing reasoning overhead improves response time without significantly impacting quality (3/5 vs potential 4/5)
4. The `use_tools=False` fix from Session 1 was necessary but not sufficient

---

# Session 4: Fix CI and Plan Long-Term Goal (2026-01-29)

## Goal
1. Fix CI test failures on PR #43
2. Plan next steps for long-term goal: autonomous AI team for 24/7 SaaS operations

## Status: IN PROGRESS

## CI Fix

**Problem**: PR #43 tests failing with `ImportError: cannot import name 'AgentType' from 'vibeteam'`

**Root Cause**: The `SlackConnector` imports `slack-sdk` but it wasn't in the `pyproject.toml` dependencies. The exception was silently caught in `vibeteam/__init__.py` as an `ImportError`, causing agent exports to be skipped.

**Fix**: Added `slack-sdk>=3.21.0` to dependencies in `pyproject.toml`.

**Commit**: `02ddbf6`

**Result**: CI now passes (lint: pass, test: pass)

---

## Long-Term Goal: Autonomous AI Team for 24/7 SaaS Operations

### What's Been Completed (70-80%)

| Category | Status | Details |
|----------|--------|---------|
| **Multi-Framework Agents** | ✅ Complete | AutoGen, CrewAI, OpenHands - all 5 agent types |
| **Gateway Service** | ✅ Complete | Webhook routing to agent services |
| **PostgreSQL Sessions** | ✅ Complete | Conversation persistence |
| **APScheduler Service** | ✅ Complete | Dynamic task scheduling |
| **K8s Deployment** | ✅ Complete | Full manifests with Kustomize |
| **Agent Benchmarking** | ✅ Complete | LLM-as-judge evaluation |
| **Connectors** | ✅ Partial | GitHub, Sentry, Langfuse, Gmail, Health, Slack |

### What's Still Needed (20-30%)

| Priority | Feature | Gap |
|----------|---------|-----|
| **HIGH** | Slack Agent Integration | Agents can't communicate via Slack autonomously |
| **HIGH** | Integration Verification | Several integrations partially configured |
| **MEDIUM** | Benchmark CI/CD | No nightly quality regression checks |
| **MEDIUM** | Documentation KB | Agents lack org knowledge/runbooks |

### Recommended Next Steps

1. **Merge PR #43** - Slack connector and agent improvements now passing CI
2. **Test Slack @mention workflow** - Verify agents can respond to Slack mentions
3. **Deploy Slack polling agents to K8s** - Each agent as independent pod
4. **Run full readiness check** - `python readiness/check.py --full`
5. **Set up nightly benchmarks** - Detect quality regressions

### Open Issues

- **Issue #40**: Slack-based autonomous agent communication
- **Issue #24**: Documentation Knowledge Base
- **Issue #44**: DeepEval integration for robust benchmarking
- **Issue #31**: Multi-agent system product requirements

---

## Tasks

- [x] 1. Push 8 local commits to update PR #43
- [x] 2. Debug CI failure (ImportError for AgentType)
- [x] 3. Root cause: missing slack-sdk dependency
- [x] 4. Fix: add slack-sdk>=3.21.0 to pyproject.toml
- [x] 5. Verify CI passes
- [ ] 6. Merge PR #43
- [ ] 7. Test Slack @mention workflow
- [ ] 8. Deploy Slack agents to K8s
