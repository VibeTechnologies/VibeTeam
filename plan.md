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
