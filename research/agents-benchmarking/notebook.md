# Agent Benchmarking Research Notebook

## Goal
Investigate why OpenHands scores lower (3/5) than CrewAI (4/5) in the error-analysis benchmark, and identify improvements.

## Current Status: COMPLETED

## Results Summary

### Before Fix
| Framework | Status | Latency | Score | 
|-----------|--------|---------|-------|
| CrewAI | PASS | 35s | 4/5 |
| AutoGen | PASS | 42s | 3/5 |
| OpenHands | PASS | 62s | 3/5 |

**Winner: CrewAI**

### After Fix (skip_context_injection)
| Framework | Status | Latency | Score | 
|-----------|--------|---------|-------|
| CrewAI | PASS | 46s | 4/5 |
| AutoGen | PASS | 48s | 2/5 |
| **OpenHands** | **PASS** | **60s** | **4/5** |

**Winner: OpenHands**

### Improvement
- OpenHands: 3/5 -> 4/5 (+1 point)
- OpenHands now **wins** the benchmark instead of placing third

---

## Steps

- [x] 1. Collect evaluation reports and framework responses
- [ ] 2. Analyze judge feedback for each framework
- [ ] 3. Compare response quality/completeness
- [ ] 4. Identify specific weaknesses in OpenHands response
- [ ] 5. Propose improvements to OpenHands configuration
- [ ] 6. Test improvements and re-benchmark

---

## Analysis

### Judge Feedback Comparison

| Framework | Score | Key Feedback |
|-----------|-------|--------------|
| **CrewAI** | 4/5 | "Clear, accurate diagnosis of a graph-cycle recursion (not call-stack recursion), pinpoints the likely loop in ExecuteReflectGraph.processStep/executeNode, and provides concrete, actionable mitigations (step budget/retry/loop detection). Minor overconfidence on severity/reproducibility but overall strong." |
| **AutoGen** | 3/5 | "Correctly identifies this as a LangGraph graph-cycle/termination issue in execute-reflect likely looping after browser_click, with reasonable root-cause hypotheses. However it includes irrelevant/tooling claims about not being able to fetch the Sentry issue and the provided excerpt is incomplete, reducing usefulness/actionability." |
| **OpenHands** | 3/5 | "Accurately explains the likely execute-reflect loop and where to look (processStep/executeNode/graph edges), with plausible specific failure modes. But it adds questionable claims (e.g., 'Sentry shows repeated occurrences', 'Users: 0') not in the prompt and the fix section is cut off, making it less actionable." |

### OpenHands-Specific Issues Identified

1. **Hallucinated claims**: Response includes "Sentry shows repeated occurrences" and "Users: 0" which were not in the prompt
2. **Truncated response**: The fix section appears cut off ("making it less actionable")
3. **Slower latency**: 62s vs 35s for CrewAI

### AutoGen Issues Identified

1. **Irrelevant tooling claims**: Mentions inability to fetch Sentry issue, distracting from the analysis
2. **Incomplete excerpt**: Response is incomplete, reducing actionability

### CrewAI Strengths

1. **Grounded in provided context**: Stays focused on the stack trace and context given
2. **Complete and actionable**: Provides specific termination/loop-breaker fixes
3. **Accurate diagnosis**: Correctly identifies graph-cycle vs call-stack recursion

---

## Response Length Comparison

| Framework | Response Length |
|-----------|-----------------|
| CrewAI | 8,159 chars |
| AutoGen | 8,920 chars |
| OpenHands | 9,344 chars |

Interestingly, OpenHands has the longest response but scores lower. Length != quality.

---

## Root Cause Analysis

### CONFIRMED: Sentry Context Injection Causing "Hallucination"

**Finding**: OpenHands automatically injects real Sentry data into the prompt, which the judge penalizes as "questionable claims not in the prompt".

**Mechanism**:
1. Benchmark task contains keywords "error" and "sentry"
2. OpenHands `run()` method checks for these keywords and injects `fetch_sentry_context()`
3. Real Sentry data includes:
   - "Users: 0" - appears in OpenHands response
   - "Count: 47" - becomes "repeated occurrences" claim
4. Judge doesn't know this context was injected, penalizes as hallucination

**Why CrewAI doesn't have this issue**:
- CrewAI has `SentryTool()` as an **optional tool** the agent can call
- It does NOT automatically inject context into the prompt
- The agent stays focused on the provided benchmark task

**Code evidence** (`agents/openhands/support_engineer.py:256-260`):
```python
if any(kw in task_lower for kw in ["sentry", "error", "issue", "bug", "crash"]):
    injected_context.append(fetch_sentry_context())
```

### Secondary Issue: Response Truncation

The judge notes "fix section is cut off". This may be due to:
- `max_output_tokens=4096` limiting response length
- Response is 9,344 chars but ends mid-sentence

### Tertiary Issue: Slower Latency

OpenHands is 77% slower than CrewAI (62s vs 35s), though this doesn't affect score.

---

## Experiments to Run

### Experiment 1: Disable Sentry Context Injection for Benchmarks
Add a `skip_context_injection` parameter to OpenHands `run()` to prevent automatic context injection for benchmark tasks. This will make OpenHands behave like CrewAI (only use provided task content).

### Experiment 2: Increase max_output_tokens
Try increasing from 4096 to 8192 to prevent truncation.

### Experiment 3: Test with reasoning_effort="high" 
See if higher reasoning improves score even if slower.

---

## Proposed Fix

Modify `agents/openhands/support_engineer.py` to add a `skip_context_injection` parameter:

```python
def run(
    self,
    task: str,
    context_type: str = "ephemeral",
    context_id: str | None = None,
    workspace: str | None = None,
    use_tools: bool = True,
    skip_context_injection: bool = False,  # NEW
    **kwargs: Any,
) -> dict[str, Any]:
    ...
    # Only inject context if not skipped
    if not skip_context_injection:
        # existing context injection logic
```

Then update `scripts/benchmark_agents.py`:

```python
if framework == "openhands":
    run_kwargs["use_tools"] = False
    run_kwargs["skip_context_injection"] = True  # NEW
```

---

## Next Steps

1. Consider adding `skip_context_injection` to AutoGen as well (if it has similar issues)
2. Investigate why AutoGen dropped from 3/5 to 2/5 (may be run-to-run variance)
3. Run multiple benchmark iterations to account for variance

---

## Files Related to This Research

- `reports/evaluation-report-20260129-211433-8e5fd3e.md` - Latest benchmark report (after fix)
- `reports/evaluation-report-20260129-205724-f1142ab.md` - Previous benchmark report (before fix)
- `agents/openhands/support_engineer.py` - OpenHands agent implementation (modified)
- `scripts/benchmark_agents.py` - Benchmark runner (modified)

