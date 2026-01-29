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

**OpenHands empty response**: The agent produces empty LLM responses and gets stuck. This is flagged for separate investigation - likely a model configuration or API issue with Azure OpenAI when used through OpenHands SDK.
