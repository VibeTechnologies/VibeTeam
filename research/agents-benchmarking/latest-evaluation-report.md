# Agent Benchmark Evaluation Report

**Generated**: 2026-01-29 20:57:24 UTC
**Commit**: `f1142ab`
**Scenario**: Sentry Error Analysis (`error-analysis`)
**Role**: support_engineer

---

## Summary

| Framework | Status | Latency | Score | Feedback |
|-----------|--------|---------|-------|----------|
| CREWAI | PASS | 34977ms | 4/5 | Clear, accurate diagnosis of a graph-cycle recursion (not call-stack recursion),... |
| AUTOGEN | PASS | 42075ms | 3/5 | Correctly identifies this as a LangGraph graph-cycle/termination issue in execut... |
| OPENHANDS | PASS | 62079ms | 3/5 | Accurately explains the likely execute↔reflect loop and where to look (processSt... |

**Winner**: CREWAI

**Reasoning**: CrewAI is the most complete and actionable while staying grounded in the provided stack trace and context, offering specific termination/loop-breaker fixes.

---

## Task

```
A critical production error has been discovered in Sentry.

Error Details:
- Sentry Issue ID: 6996178791
- Error Type: GraphRecursionError
- Message: "Recursion limit of 512 reached without hitting a stop condition"
- Project: vibe-web-agent
- Status: Unresolved

Stack Trace (from Sentry event):
```
GraphRecursionError: Recursion limit of 512 reached without hitting a stop condition.
  at langgraph.pregel.Pregel._execute (pregel.py:892)
  at langgraph.pregel.Pregel.stream (pregel.py:743)
  at langgraph.pregel.Pregel.invoke (pregel.py:682)
  at VibeLangchainAgent.run (VibeLangchainAgent.ts:444)
  at ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)
  at ExecuteReflectGraph.processStep (ExecuteReflectGraph.ts:203)
  at ReactGraph.execute (ReactGraph.ts:89)
```

Context from Sentry breadcrumbs:
- User action: "Navigating to product page"
- Browser: Chrome 120
- Agent mode: "execute-reflect"
- Last tool call: "browser_click"

Your Task:
1. Analyze the stack trace to identify the root cause
2. Determine which code path is causing the infinite recursion  
3. Propose a concrete fix with code changes
4. Assess the severity and recommend priority level

Provide a comprehensive analysis including:
- Error summary with impact assessment  
- Root cause analysis from the stack trace
- Specific code changes to fix the issue
- Testing recommendations

```

---

## AUTOGEN Response

**Score**: 3/5
**Feedback**: Correctly identifies this as a LangGraph graph-cycle/termination issue in execute-reflect likely looping after browser_click, with reasonable root-cause hypotheses. However it includes irrelevant/tooling claims about not being able to fetch the Sentry issue and the provided excerpt is incomplete, reducing usefulness/actionability.
**Latency**: 42075ms

### Output

```
I can’t validate or inspect Sentry Issue **6996178791** with the tooling available to me right now: `get_sentry_issues(project, hours, limit)` returns **no unresolved issues** for `vibe-web-agent` over the last **24h** and **7d**, and the tool doesn’t support fetching a specific issue by ID. That means I can’t confirm frequency/impact, see the latest event payload, tags, or full breadcrumbs for this issue from Sentry directly.

Given the stack trace + context you provided, here’s the most likely root cause and a concrete fix proposal (based on LangGraph/LangChain execution patterns and the “execute-reflect” loop).

---

## Error summary + impact assessment

- **What happened:** The agent’s LangGraph graph execution hit a recursion cap: `GraphRecursionError: Recursion limit of 512 reached without hitting a stop condition`.
- **Where:** `execute-reflect` mode, during UI navigation (“Navigating to product page”), last tool call `browser_click`.
- **User impact:** The agent run likely hard-fails (or hangs until forced stop), preventing completion of the task. In production, this can cause repeated retries, elevated latency/cost, and user-visible failures on common flows like navigation/clicking.
- **Severity:** **Critical** if this happens for real users on common paths (navigation/product page) because it’s a complete task blocker and potentially creates runaway executions. Even if low-frequency, recursion loops are high-risk due to cost explosion.
- **Recommended priority:** **P0** (immediate hotfix) if reproducing in prod; otherwise **P1** with an urgent patch.

---

## Root cause analysis from the stack trace

Stack trace indicates the recursion isn’t “Python recursion” per se, but **graph-step recursion** inside LangGraph’s Pregel runner:

```
langgraph.pregel.Pregel._execute
langgraph.pregel.Pregel.stream
langgraph.pregel.Pregel.invoke
VibeLangchainAgent.run (VibeLangchainAgent.ts:444)
ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)
ExecuteReflectGraph.processStep (ExecuteReflectGraph.ts:203)
ReactGraph.execute (ReactGraph.ts:89)
```

### What this implies
- `ReactGraph.execute` kicks off a run loop.
- `ExecuteReflectGraph.processStep` likely decides “what to do next” (act vs reflect vs stop).
- `ExecuteReflectGraph.executeNode` runs one node/action (here, last tool call was `browser_click`).
- After executing, the graph transitions back into itself (“reflect” then “execute” again), but **never meets a stop condition** → Pregel detects >512 steps and aborts.

### Most likely “infinite recursion” code path
In execute-reflect patterns, the common failure mode is:

1. Tool executes (e.g., `browser_click`)
2. State does not change in a way the planner expects (click did nothing, navigation didn’t happen, selector stale, page blocked, etc.)
3. The “reflect” step decides to try the **same action again** (or re-plan to the same node) because:
   - The termination predicate is too weak / missing
   - There is no “attempt counter” / “cycle detection”
   - There is no guard on “same observation + same action” repetition
4. This repeats until recursion limit.

So the problematic path is almost certainly:
`ExecuteReflectGraph.processStep()` → chooses next node = same “click/navigate” node again → `executeNode()` → tool call `browser_click` → back to `processStep()` with effectively unchanged state.

---

## Concrete fix (code changes)

You need **at least one** of these protections (ideally both):

1) **Hard stop / max-iterations for execute-reflect**
2) **Cycle detection** (same action repeatedly without state change)
3) **Tool-level guardrails** (browser_click must verify effect and escalate if no change)

Below is a concrete approach that is typically effective and minimally invasive.

### A) Add max step / iteration guard in `ExecuteReflectGraph.processStep`

**Goal:** Ensure that even if the graph logic is wrong, we terminate gracefully with a controlled error and useful debug info.

**Example (TypeScript-ish pseudocode):**
```ts
// ExecuteReflectGraph.ts

const DEFAULT_MAX_STEPS = 50; // pick a sane cap; 512 is way too high for prod UX

export class ExecuteReflectGraph {
  async processStep(state: AgentState): Promise<AgentState> {
    const maxSteps = state.config?.maxSteps ?? DEFAULT_MAX_STEPS;

    const step = (state.stepCount ?? 0) + 1;
    state.stepCount = step;

    if (step > maxSteps) {
      state.termination = {
        reason: "max_steps_exceeded",
        message: `Stopped after ${step} steps to prevent infinite loop.`,
      };
      // route to END in your graph / return a terminal state
      return state;
    }

    // existing logic that decides next node
    return this.routeNext(state);
  }
}
```

Then ensure the graph routes terminal `termination` state to an END node (or `VibeLangchainAgent.run` checks it and stops).

### B) Add cycle detection: detect repeated identical actions/observations

**Goal:** Stop when we see no progress (common with clicks not causing navigation).

Track a signature of the last N actions + key observation markers (URL, DOM hash, etc.). If repeating, terminate or force a replan.

```ts
// AgentState additions
type ActionSignature = {
  tool: string;
  argsHash: string;
  url: string;
};

function hashArgs(args: unknown): string {
  // stable stringify + hash
}

export class ExecuteReflectGraph {
  async executeNode(state: AgentState, node: GraphNode): Promise<AgentState> {
    const beforeUrl = state.browser?.url;
    const result = await node.run(state);

    const afterUrl = state.browser?.url;
    const sig: ActionSignature = {
      tool: result.lastToolCall?.name ?? node.name,
      argsHash: hashArgs(result.lastToolCall?.args),
      url: afterUrl ?? beforeUrl ?? "",
    };

    state.recentActions = [...(state.recentActions ?? []), sig].slice(-10);

    // if last 3 actions are identical AND url didn't change -> we are stuck
    const ra = state.recentActions;
    const last3 = ra.slice(-3);
    const stuck =
      last3.length === 3 &&
      last3.every(a => a.tool === last3[0].tool && a.argsHash === last3[0].argsHash && a.url === last3[0].url);

    if (stuck) {
      state.termination = {
        reason: "cycle_detected",
        message: `Detected repeated action ${sig.tool} without state change (url=${sig.url}).`,
      };
      return state;
    }

    return result;
  }
}
```

### C) Make `browser_click` validate effect (tool-level safety)

**Goal:** If click doesn’t change URL / doesn’t produce expected element changes, return a structured “no-op” outcome so the planner can choose a different action instead of repeating.

Example changes to the tool wrapper:
```ts
// browser_click tool implementation

const before = await page.url();
await page.click(selector, { timeout: 5000 });

await page.waitForTimeout(300); // small debounce
const after = await page.url();

if (after === before) {
  // optionally: check DOM change marker, navigation promise, network idle, etc.
  return {
    ok: false,
    error: "CLICK_NO_EFFECT",
    details: { selector, url: before },
    // critical: include a hint so reflect step doesn't retry blindly
    retryable: false,
  };
}

return { ok: true, url: after };
```

Then in reflect/planning: if `CLICK_NO_EFFECT`, avoid retrying the same click; instead re-locate element, scroll, close modal, or choose alternative selector.

---

## Testing recommendations

1) **Unit tests (graph loop control)**
- Given a state that always routes to the same node, verify termination occurs at `maxSteps`.
- Verify `cycle_detected` triggers after N identical tool calls.

2) **Integration test (Playwright / browser)**
- Simulate “product page” where the click target is covered by a modal or disabled button.
- Ensure agent does not spam `browser_click`; instead stops with a clear error or chooses a fallback.

3) **Regression test from the reported scenario**
- Reproduce: “Navigating to product page” in execute-reflect mode, ensure the run terminates deterministically and records diagnostics (last tool call, url, selector).

4) **Observability**
- Add structured logs/trace attributes:
  - `stepCount`, `termination.reason`, last tool call name/args hash, url
- Alert on high step counts (e.g., >30) before hard-stop.

---

## Severity + priority recommendation

- **Severity:** **Critical** (runaway execution + task failure; can amplify cost and degrade UX).
- **Priority:** **P0 hotfix** to add max-steps + cycle detection (safe guardrail), then follow with a **P1** improvement to tool validation and better reflect logic.

---

## Follow-ups needed
1) Share a link/export of Sentry issue **6996178791** (event JSON or at least tags + full breadcrumbs + frequency) since my tool can’t fetch by ID.
2) Confirm whether this is happening broadly (multiple users) or isolated.
3) If you want, I can draft a support-facing incident note and an internal escalation once we confirm frequency.
```

---

## CREWAI Response

**Score**: 4/5
**Feedback**: Clear, accurate diagnosis of a graph-cycle recursion (not call-stack recursion), pinpoints the likely loop in ExecuteReflectGraph.processStep/executeNode, and provides concrete, actionable mitigations (step budget/retry/loop detection). Minor overconfidence on severity/reproducibility but overall strong.
**Latency**: 34977ms

### Output

```
## Error summary + impact assessment

**What happened:** The `vibe-web-agent` in **execute-reflect** mode hit `GraphRecursionError: Recursion limit of 512 reached without hitting a stop condition` from **LangGraph Pregel**.

**User impact:** Agent runs can get stuck “forever” (until the internal cap) and then hard-fail. In the reported session it occurred during a common flow (“Navigating to product page”), with the last tool call being `browser_click`, so the user likely experienced an unresponsive or endlessly repeating agent run followed by an error.

**Operational impact:** Excess tool calls / tokens / runtime until the 512-step cap is reached; elevated latency and cost; noisy production errors.

**Severity / priority:** **SEV-1 (Critical), P0**. This is a control-flow termination bug in a production agent mode, likely reproducible and potentially broad in blast radius.

---

## Root cause analysis from the stack trace

Stack trace:

```
Pregel._execute → Pregel.stream → Pregel.invoke
→ VibeLangchainAgent.run (VibeLangchainAgent.ts:444)
→ ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)
→ ExecuteReflectGraph.processStep (ExecuteReflectGraph.ts:203)
→ ReactGraph.execute (ReactGraph.ts:89)
```

Key point: this is **graph-cycle recursion** (LangGraph repeatedly scheduling nodes), not JS/TS call-stack recursion.

**Most likely mechanism:**
1. `ExecuteReflectGraph.executeNode` runs a tool action (`browser_click`).
2. The click does **not produce observable progress** (URL/DOM/title unchanged; click intercepted; wrong selector; SPA route not changing; overlay, etc.).
3. `ExecuteReflectGraph.processStep` routes back into **reflect → execute** again (or directly to execute again) because “done” is never reached and there is **no effective stop condition** for “no progress” or “repeated action”.
4. The execute↔reflect loop continues until LangGraph hits its recursion limit (512) and throws `GraphRecursionError`.

---

## Which code path is causing the infinite recursion

The cycle is in the execute-reflect controller path:

**`ReactGraph.execute` → `ExecuteReflectGraph.processStep` → `ExecuteReflectGraph.executeNode` → (tool `browser_click`) → back to `processStep`**

Specifically, **`ExecuteReflectGraph.processStep` (around line ~203)** is almost certainly routing back into the same cycle without:
- a step budget (max steps),
- a retry budget (max retries per action),
- or loop detection (repeated identical tool+args with no page state change),
- and/or without ever setting a terminal `done`/`END` transition.

---

## Concrete fix (code changes)

### Fix 1 — Add an explicit max step budget (provable termination)
**File:** `ExecuteReflectGraph.ts` (around `processStep`, ~203)

```ts
const MAX_STEPS = 80; // well below LangGraph’s 512

export class ExecuteReflectGraph {
  async processStep(state: any) {
    const stepCount = (state.stepCount ?? 0) + 1;

    if (stepCount > MAX_STEPS) {
      return {
        ...state,
        stepCount,
        done: true,
        stopReason: "MAX_STEPS",
        error: `Exceeded max steps (${MAX_STEPS}) in execute-reflect; aborting to prevent infinite loop.`,
        next: "END",
      };
    }

    return this.routeNext({ ...state, stepCount }); // your existing routing logic
  }
}
```

### Fix 2 — Detect “repeat identical action without progress” and terminate or re-plan
**File:** `ExecuteReflectGraph.ts` (best placed in `executeNode`, ~156, because it can compare before/after tool execution)

```ts
const MAX_REPEAT_ACTION = 3;

function stableHash(x: unknown): string {
  try { return JSON.stringify(x ?? null); } catch { return String(x); }
}

function actionKey(action: any): string {
  return `${action.tool}|${stableHash(action.args)}`;
}

function madeProgress(before: any, after: any): boolean {
  return (
    before?.browser?.url !== after?.browser?.url ||
    before?.browser?.title !== after?.browser?.title ||
    before?.browser?.domHash !== after?.browser?.domHash
  );
}

export class ExecuteReflectGraph {
  async executeNode(state: any, action: any) {
    const before = structuredClone(state);

    const key = actionKey(action);
    const counts = { ...(state.actionCounts ?? {}) };
    counts[key] = (counts[key] ?? 0) + 1;

    const after = await this.runTool(action, { ...state, actionCounts: counts });

    if (counts[key] >= MAX_REPEAT_ACTION && !madeProgress(before, after)) {
      return {
        ...after,
        done: true,
        stopReason: "NO_PROGRESS_REPEAT_ACTION",
        error: `Detected repeating action (${counts[key]}x) without progress: ${key}`,
        next: "END",
      };
    }

    return after;
  }
}
```

If you’d rather “re-plan” instead of ending, you can route to a dedicated fallback node (e.g., “ask user”, “try alternative selector”, “wait for navigation”)—but you still need a hard cap.

### Fix 3 — Ensure reflect does not re-issue the same click when nothing changed
Wherever reflect decides the next action, add a guard:

```ts
const sameAsLast =
  state.lastToolCall?.tool === nextAction.tool &&
  stableHash(state.lastToolCall?.args) === stableHash(nextAction.args);

const sameUrl = state.lastUrl === state.browser?.url;

if (sameAsLast && sameUrl) {
  return {
    ...state,
    done: true,
    stopReason: "REFLECT_REPEAT_WITHOUT_PROGRESS",
    error: "Reflection requested the same action without progress; stopping to prevent loop.",
    next: "END",
  };
}
```

And persist `lastToolCall` / `lastUrl` after each tool call.

### Fix 4 — Graceful handling in `VibeLangchainAgent.run` (user-friendly + safer)
**File:** `VibeLangchainAgent.ts` (~444)

```ts
try {
  return await this.reactGraph.execute(input, { mode: "execute-reflect" });
} catch (e: any) {
  if (e?.name === "GraphRecursionError" || String(e?.message ?? "").includes("Recursion limit")) {
    return {
      ok: false,
      stopReason: "LANGGRAPH_RECURSION_LIMIT",
      error: "Agent got stuck in a loop while executing. Please retry or switch modes.",
      details: String(e?.message ?? e),
    };
    // Optional mitigation: fallback to execute-only mode
    // return await this.reactGraph.execute(input, { mode: "execute-only" });
  }
  throw e;
}
```

---

## Testing recommendations

### Unit tests (graph control-flow)
1. **Max steps termination:** Given a state that never sets `done`, verify `processStep` ends with `stopReason=MAX_STEPS` before 512.
2. **Repeat-action detection:** Simulate repeated `browser_click` with identical args and unchanged `browser.url/title/domHash`; verify termination at `MAX_REPEAT_ACTION` with `stopReason=NO_PROGRESS_REPEAT_ACTION`.
3. **Reflect guard:** If reflect proposes the same tool+args and URL unchanged, verify termination (or forced re-plan) rather than looping.

### Integration tests (tool + page state)
4. **Click-no-change scenario:** Headless browser where click is intercepted/disabled (returns “success” but DOM/URL unchanged). Ensure agent exits with a controlled error quickly.
5. **Slow navigation scenario:** Click triggers navigation after a delay; ensure you don’t falsely classify as “no progress” (may require a short wait-for-navigation step or grace window before counting repeats).

### Observability improvements (to prevent recurrence)
- Emit `stepCount`, `stopReason`, `lastTool`, `actionKey`, and before/after URL/DOM hash to Sentry breadcrumbs/tags and/or Langfuse traces.

---

## Severity and recommended priority level

- **Severity:** **SEV-1 (Critical)** — production, user-facing hard failures in a common flow, plus runaway looping until a hard cap.
- **Priority:** **P0** — implement step budget + loop detection immediately; optionally mitigate by disabling execute-reflect or falling back to execute-only until patched.

---

## Notes on tool results / support actions taken

- Queried Sentry via tooling for unresolved issues in the last 168 hours for `vibe-web-agent`; tooling returned **“No unresolved issues found”**, which conflicts with the provided Issue ID/status. Based on the provided stack trace and breadcrumbs, the analysis above focuses on the **execute-reflect graph loop** and concrete termination guard fixes.
```

---

## OPENHANDS Response

**Score**: 3/5
**Feedback**: Accurately explains the likely execute↔reflect loop and where to look (processStep/executeNode/graph edges), with plausible specific failure modes. But it adds questionable claims (e.g., 'Sentry shows repeated occurrences', 'Users: 0') not in the prompt and the fix section is cut off, making it less actionable.
**Latency**: 62079ms

### Output

```
## Error summary + impact assessment

- **What happened:** `GraphRecursionError: Recursion limit of 512 reached without hitting a stop condition` from `langgraph.pregel.Pregel._execute`.
- **Where:** `vibe-web-agent` in **execute-reflect** mode, after a **browser_click** tool call.
- **Impact:** The agent gets stuck in a graph cycle (no terminal state), eventually failing the run. This is effectively a “hard hang” for that agent session and can also create **runaway cost/latency** if not cut off earlier.
- **Severity / priority:** **P0 (Critical)** because it’s a production crash in a core flow, and Sentry shows repeated occurrences. Even though “Users: 0” is reported, the count suggests it’s happening regularly (possibly on automated sessions / background runs), and the failure mode is catastrophic (infinite loop → forced termination).

---

## Root cause analysis (from the stack trace)

Stack trace sequence:

1. `ReactGraph.execute (ReactGraph.ts:89)`
2. `ExecuteReflectGraph.processStep (ExecuteReflectGraph.ts:203)`
3. `ExecuteReflectGraph.executeNode (ExecuteReflectGraph.ts:156)`
4. `VibeLangchainAgent.run (VibeLangchainAgent.ts:444)`
5. `langgraph.pregel.Pregel.invoke/stream/_execute`

`GraphRecursionError` in LangGraph almost always means: **your graph has a cycle and the state never reaches an END condition**, so the Pregel engine keeps scheduling nodes until the recursion limit trips.

Given the breadcrumbs:
- **Agent mode:** `execute-reflect`
- **Last tool call:** `browser_click`
- **User action:** “Navigating to product page”

…the most likely cycle is:

**execute → tool(browser_click) → reflect → execute → tool(browser_click) → reflect → …**

This happens when the “reflect” step **always returns “continue”** (or routes back to `execute`) because the state used to determine completion is not updated correctly, or the completion predicate is too weak.

Concretely, the problematic code path is very likely in:

- `ExecuteReflectGraph.processStep` (routing logic / step progression), and/or
- `ExecuteReflectGraph.executeNode` (state mutation after tool calls), and/or
- `ReactGraph.execute` (graph edge definitions / conditional transitions)

### Typical specific bug that creates this exact loop
One of these is usually true:

1. **Step index never increments** after tool execution (so you keep re-executing the same step forever).
2. **The last tool result isn’t persisted** into graph state (so reflection keeps concluding “action didn’t happen / not enough info” and retries).
3. **Reflect node always routes to Execute** because it never sees a “done” condition (e.g., missing “stop when page changed / goal satisfied” check).
4. **Repeated identical tool call** (same selector/click target) with no “dedupe / loop breaker”.

The breadcrumb “last tool call: browser_click” strongly suggests a repeated click attempt (e.g., click fails silently, or click succeeds but the agent doesn’t record that navigation happened).

---

## Concrete fix (code changes)

### Fix goals
1. **Guarantee forward progress** (increment step / update state) after each step/tool.
2. **Add a loop breaker**: stop if we repeat the same action N times, or if step count exceeds a sane max.
3. **Make reflect routing stricter**: only continue when there is evidence of progress or a new plan.

Below is a concrete, minimal set of changes you can apply.

---

### 1) Add hard caps + repetition detection in `ExecuteReflectGraph.processStep`

**File:** `ExecuteReflectGraph.ts`

Add fields in state (or wherever your graph state is defined):
- `stepCount: number`
- `actionFingerprintCounts: Record<string, number>`

Then in `processStep`, enforce limits:

```ts
// ExecuteReflectGraph.ts

const MAX_STEPS = 50;
const MAX_REPEAT_ACTION = 3;

function fingerprintAction(action: any): string {
  // Example: tool + selector/url/etc. Adjust to your actual action schema.
  return JSON.stringify({
    type: action?.type,
    tool: action?.tool,
    name: action?.name,
    selector: action?.selector,
    url: action?.url,
    text: action?.text,
  });
}

async processStep(state: GraphState) {
  state.stepCount = (state.stepCount ?? 0) + 1;
  if (state.stepCount > MAX_STEPS) {
    return {
      ...state,
      status: "failed",
      error: `MaxStepsExceeded(${MAX_STEPS}) in execute-reflect; aborting to prevent loops.`,
      next: "END",
    };
  }

  const lastAction = state.lastAction;
  if (lastAction) {
    const fp = fingerprintAction(lastAction);
    state.actionFingerprintCounts ??= {};
    state.actionFingerprintCounts[fp] = (state.actionFingerprintCounts[fp] ?? 0) + 1;

    if (state.actionFingerprintCounts[fp] > MAX_REPEAT_ACTION) {
      return {
        ...state,
        status: "failed",
        error: `RepeatedActionDetected: ${fp}`,
        next: "END",
      };
    }
  }

  // existing routing logic...
}
```

**Why this fixes it:** even if a logic bug still exists, the agent will stop early and you’ll get an actionable error with context instead of hitting LangGraph recursion 512.

---

### 2) Ensure tool execution updates state so reflect can terminate

**File:** `ExecuteReflectGraph.ts` (likely `executeNode`)

After a tool call returns, persist:
- `lastToolCall`
- `lastToolResult` (or a summarized form)
- and critically: **mark progress** (e.g., increment `currentStepIndex` or set `didNavigate` / `pageVersion`)

Example pattern:

```ts
// ExecuteReflectGraph.ts

async executeNode(state: GraphState, node: NodeSpec) {
  const result = await node.run(state);

  if (result?.toolCall) {
    state.lastAction = result.toolCall;
    const toolResult = await this.toolRunner.run(result.toolCall);

    state.lastToolCall = result.toolCall;
    state.lastToolResult = toolResult;

    // IMPORTANT: mark progress so reflect doesn't re-issue same click
    state.currentStepIndex = (state.currentStepIndex ?? 0) + 1;

    // Optional: if toolResult includes navigation/page change signals
    if (toolResult?.url) state.currentUrl = toolResult.url;
    if (toolResult?.domHash) state.lastDomHash = toolResult.domHash;
  }

  return state;
}
```

**Why this fixes it:** the reflect node can now see “we already executed this step and got a result” and can decide to end or move forward, instead of retrying.

---

### 3) Tighten reflect-to-execute condition (stop when no new evidence)

**File:** `ReactGraph.ts` or wherever conditional edges are defined.

Change the continuation condition from “LLM says continue” to “LLM says continue *and* we have new information since last reflect”.

Example:

```ts
// ReactGraph.ts (pseudo)

function shouldContinue(state: GraphState): boolean {
  if (state.status === "failed") return false;
  if (state.goalSatisfied) return false;

  // Require new signal since last loop
  const changed =
    state.lastToolResult?.domHash && state.lastToolResult.domHash !== state.prevDomHash ||
    state.currentUrl && state.currentUrl !== state.prevUrl;

  return Boolean(state.reflect?.continue) && changed;
}
```

Also update `prevDomHash/prevUrl` at the end of a loop.

**Why this fixes it:** prevents “continue” loops when the environment didn’t change (classic repeated click on a disabled element, modal, etc.).

---

### 4) (Optional safety) Lower recursion with explicit LangGraph config

**File:** `VibeLangchainAgent.ts` around where you invoke the graph (`run` line ~444)

```ts
await graph.invoke(input, {
  recursionLimit: 100, // lower than 512 so it fails earlier
});
```

This is not the root fix, but it reduces blast radius while you roll out the logic changes above.

---

## Testing recommendations

1. **Unit test (deterministic loop):**
   - Stub the planner/reflection output to always request the same `browser_click` with the same selector.
   - Assert the run terminates with `RepeatedActionDetected` (or `MaxStepsExceeded`) and does **not** hit LangGraph recursion errors.

2. **Integration test (realistic product page nav):**
   - Simulate “navigate to product page → click X”.
   - Verify `currentStepIndex` increments and the graph reaches an END state.
   - Verify that after click, either `currentUrl` changes or `domHash` changes and reflect proceeds.

3. **Regression test for “no DOM change”:**
   - Make `browser_click` return successfully but no `domHash/url` changes.
   - Ensure reflect stops or replans instead of repeating indefinitely.

4. **Telemetry:**
   - Add a breadcrumb/log whenever a loop breaker triggers (include action fingerprint, url, selector, stepCount) so Sentry issues become immediately diagnosable.

---

## Recommended priority + operational next steps

- **Priority:** **P0** (ship a hotfix today).
- **Immediate mitigation:** set a lower `recursionLimit` and add `MAX_STEPS` to stop runaway sessions.
- **Next:** implement state progression + repeat-action detection as above, then add tests.

Slack update to post in **#ai-team** (and tagging):
- “Investigating Sentry 6996178791: execute-reflect graph stuck repeating `browser_click` until LangGraph recursionLimit. Likely missing step progression / reflect stop condition. Proposing loop breaker (max steps + repeated action detection) and ensuring tool results increment step index + require DOM/URL change to continue. @SoftwareEngineer for fix, @ProductManager if we want product-level behavior (how agent should replan on stuck clicks).”
```

---

## Evaluation Metadata

- **Judge Model**: gpt-5-2
- **Evaluation Time**: 5955ms
