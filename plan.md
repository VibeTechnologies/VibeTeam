# VibeTeam OpenHands Agent Fix

## Goal
Fix OpenHands agents so they properly investigate Slack-triggered support requests without:
1. Trying to use Slack tools directly (which fail without SLACK_BOT_TOKEN)
2. Listing all available roles instead of doing actual work
3. Creating handoff cascades that hit max depth

## Current Issue (Feb 5, 2026)

Gateway logs show agents responding with all four role mentions:
```
Detected handoff to: ['support_engineer', 'software_engineer', 'release_engineer', 'product_manager'] (depth 1/3)
```

This causes a handoff cascade where each agent just lists available roles instead of:
- Using Sentry tools to investigate the issue
- Providing specific findings (error counts, issue IDs, timestamps)
- Only handing off when genuinely needed

## Root Cause

The task template in `vibeteam/gateway/routes/slack.py` (line 254-259) tells agents:
```
2. Complete the task using available tools
3. Provide a clear, concise response
4. If you need another team member's help, mention them with @RoleName
```

Agents interpret this as "list the available roles" rather than "do the work first, then hand off if needed".

## Fix Strategy

Update the task template to be more explicit:

1. **Be specific about expected behavior**: Tell agents to investigate first
2. **Clarify handoffs**: Only hand off AFTER completing their own analysis
3. **Remove role listing instruction**: Don't encourage listing all roles

## Completed Tasks

### Phase 1: Standalone Tools ✅ (commit e822e20)
Made `agents/shared/` tools standalone (no vibeteam dependency)

### Phase 2: Context Injection ✅ (commit 3f99ad1)
- Enabled context injection for OpenHands in gateway
- Added "Communication is Handled By System" section to agent prompts

## Current Tasks

- [x] Fix task template in `vibeteam/gateway/routes/slack.py` ✅ (commit 0776cbe)
- [x] Add visual separators for injected context ✅ (commit d3548b0)
- [x] Commit and push changes ✅
- [x] Run E2E evaluation to verify ✅

## Results

**Evaluation Status: ✅ WORKING**

The agents now properly:
1. Analyze injected Sentry data with specific issue IDs
2. Provide detailed findings (issue ID, count, timestamps, correlation analysis)
3. Make appropriate handoffs with specific context (not listing all roles)
4. Follow the expected response format
5. **Make evidence-based decisions** (don't recommend rollback without evidence)
6. **Complete handoffs** (target agent responds and takes action)

### Phase 3: Evidence-Based Evaluation (2026-02-07)

Added new evaluation metrics to all scenarios:
- **EvidenceBasedDecision**: Penalizes agents that recommend drastic actions (rollback) without evidence
- **HandoffCompletion**: Penalizes incomplete handoffs where target agent never responds

Latest evaluation results:
- `support_400_errors`: InvestigationQuality 0.90, EvidenceBasedDecision 1.00, HandoffCompletion 0.90
- `stripe_webhook_failure`: InvestigationQuality 0.90, EvidenceBasedDecision 0.90, HandoffCompletion 0.90

Key improvements:
- Agents now correctly report "no action needed" when investigation shows healthy infrastructure
- Agents ask for customer details (request IDs, timestamps) instead of speculating
- Handoffs include specific context for the target agent

### Phase 4: Message Splitting & Endpoint Testing (2026-02-07)

**Issue 1: Message Truncation Breaking Handoffs**
- Problem: Responses > 3000 chars were truncated, cutting off handoff mentions (@ReleaseEngineer)
- Fix: Split long messages into multiple Slack messages instead of truncating
- File: `vibeteam/gateway/routes/slack.py` (lines 320-362)

**Issue 2: Agents Not Testing Actual Endpoints**
- Problem: Agent checked pods/logs but never ran `curl` to test the reported broken endpoint
- The endpoint returns 404 - but agent concluded "infrastructure healthy"
- Fix: Added STEP 3 to instructions requiring curl testing for webhook/API issues
- File: `vibeteam/gateway/routes/slack.py` (lines 268-277, 295-296)

**Issue 3: f-string Bug with curl format**
- Problem: `{http_code}` in curl format string was interpreted as Python variable, causing NameError
- Fix: Escaped curly braces to `{{http_code}}`
- Commit: `1022a33`

Tasks:
- [x] Replace truncation with message splitting
- [x] Add curl endpoint testing requirement to agent instructions
- [x] Update REQUIRED OUTPUT to include endpoint test findings
- [x] Fix f-string escape for curl format
- [x] Deploy and run stripe_webhook_failure evaluation to verify ✅

**Evaluation Results (2026-02-08):**
```
Scenario: stripe_webhook_failure
Status: ✅ PASSED
- InvestigationQuality: 1.00
- TaskCompletion: 0.90
- EvidenceBasedDecision: 0.90
- HandoffCompletion: 0.90
```

Agent now correctly:
1. Tests the endpoint with curl → finds HTTP 404
2. Identifies root cause: "route does not exist or is not registered"
3. Recommends CODE FIX (not rollback)
4. Hands off to @SoftwareEngineer

### Phase 5: Handoff Investigation & Response Time Analysis (2026-02-08)

**Handoff Verification:**
- Investigated the `stripe_webhook_failure` scenario handoff to @SoftwareEngineer
- Gateway logs confirmed: `Executing handoff to software_engineer...` at 02:26:26
- SoftwareEngineer responded in Slack at 02:36:38 (10 minutes later)
- The handoff completed successfully - eval timed out but agents worked correctly

**Response Time Analysis:**
- Single agent response: ~2.4 minutes (142891ms) for `support_400_errors`
- Multi-tool investigation: ~10 minutes (605150ms) for `stripe_webhook_failure`

**Why responses take 2-10 minutes:**
1. **OpenHands agentic loop**: Multiple LLM → tool → LLM cycles
2. **Tool execution**: Each kubectl/curl command requires network calls
3. **Azure OpenAI latency**: Model inference time per LLM call
4. **Thinking budget**: `reasoning_effort="medium"` still allows extended thinking

**This is expected behavior** for agentic systems that investigate autonomously. The trade-off is:
- Faster (no tools): Direct LLM response in seconds, but no real investigation
- Slower (with tools): 2-10 min, but provides actual diagnostic data

**Recommendations:**
- Keep 600s eval timeout for multi-agent handoff scenarios
- Consider streaming responses for better UX (show progress as agent works)
- The current ~2.4 min for simple investigations is acceptable

Tasks:
- [x] Refactor split_long_message as standalone function (commit 8908778)
- [x] Add unit tests for message splitting (9 tests, all passing)
- [x] Verify handoff completion via Slack thread inspection
- [x] Analyze response time characteristics
- [x] Document findings in plan.md

### Phase 6: Kubectl Pre-Injection & Latency Optimization (2026-02-08)

**Problem:** Agent response times were ~2.4 minutes (142s) due to sequential kubectl calls during investigation.

**Solution:** Pre-fetch kubectl data in the gateway before calling the agent, similar to Sentry context injection.

**Implementation:**

1. **New file: `agents/shared/kubectl_tools.py`** (commit c85a75f)
   - `get_pods()` - Fetches pod status from vibeteam namespace
   - `get_events()` - Fetches recent events with warnings
   - `get_deployment_logs()` - Gets container logs for deployments
   - `get_rollout_history()` - Gets deployment revision history
   - `get_kubectl_context()` - Main function that batches all the above

2. **Modified: `agents/openhands/support_engineer.py`** (commit c85a75f)
   - Added `fetch_kubectl_context()` wrapper function
   - Injected kubectl context alongside Sentry for infrastructure issues
   - Added interpretation guide explaining probe failures during updates are normal

3. **Modified: `scripts/eval_slack_e2e.py`** (commit pending)
   - Reduced stability wait from 120s fixed to **adaptive**: 15s (no handoff) / 60s (with handoff)
   - This better reflects actual agent response time

**Results:**

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Actual agent call | ~60s (multiple kubectl) | ~12-16s | **4x faster** |
| Eval measured latency | ~142s | ~32s | **4.5x faster** |
| Investigation quality | 0.90 | 0.90 | Maintained |

**Key insight:** The 142s eval latency was mostly eval overhead (120s stability wait), not actual agent slowness. With kubectl pre-injection AND adaptive stability wait:
- Agent responds in **12-16 seconds**
- Eval reports **~32 seconds** total

**Remaining recommendations:**
- Consider caching kubectl data for rapid sequential requests
- Consider pre-fetching in parallel with Sentry data
- Could reduce stability wait to 10s for scenarios without handoffs

### Phase 7: Expanding Kubectl Pre-Injection to All Agents (2026-02-08)

**Goal:** Standardize response times by applying kubectl pre-injection to `ReleaseEngineer` and `SoftwareEngineer`.

**Implementation:**
- Modified `agents/openhands/release_engineer.py`:
  - Always injects kubectl context (since their role is infra-centric)
  - Updated prompt to prioritize pre-fetched data
- Modified `agents/openhands/software_engineer.py`:
  - Conditionally injects kubectl context based on keywords (pod, deployment, error, webhook, etc.)
  - Updated prompt to mention pre-fetched data availability

**Verification:**
- Will run `stripe_webhook_failure` scenario to verify `SoftwareEngineer` speedup (previously ~54s)
- **Result:** `SoftwareEngineer` response time dropped to **~12s** (4.5x faster)
- Eval passed with perfect scores (InvestigationQuality 1.0, TaskCompletion 1.0)

### Phase 8: Preventing Self-Handoffs (2026-02-08)

**Problem:** Agents were sometimes handing off tasks to themselves (e.g., SoftwareEngineer tagging @SoftwareEngineer), creating unnecessary loops.

**Implementation:**
1. **Updated Evaluation Metrics:**
   - Modified `scripts/eval_slack_e2e.py` to strictly penalize self-handoffs (score 0.0-0.2).
   - Added specific checks for "tagging own role".

2. **Updated Agent Prompts:**
   - Modified `SoftwareEngineer`, `ReleaseEngineer`, `SupportEngineer`, `ProductManager`, and `MarketingManager` contexts.
   - Added `CRITICAL: Agent Identity and Handoffs` section:
     - "You are the **Role**."
     - "DO NOT tag @Role in your response."
     - "If you have completed the task, simply state that. Do not tag yourself."

**Verification:**
- Will monitor next evaluations for absence of self-handoffs.

### Phase 9: CLI Output Redirection for Stability (2026-02-09)

**Problem:** `github_issue` scenario was timing out (600s). The OpenHands agent would hang when running `gh issue view` or `gh issue list` directly in the terminal, likely due to TTY/buffer handling issues with large output or interactive prompts.

**Implementation:**
1. **Debugged:** Created `fix/github-issue-debug` branch and traced execution.
2. **Fixed:** Updated `agents/openhands/software_engineer.py` system prompt.
   - Added strict instruction: **"ALWAYS redirect output to a file"** for CLI tools like `gh`.
   - Pattern: `gh issue list ... > issue_list.txt` then `cat issue_list.txt`.
3. **Deployed:** Merged to `master` and redeployed.

**Verification:**
- `github_issue` scenario now passes in ~68s (down from timeout).
- Agent correctly retrieves issue details and proposes a fix plan.

### Phase 10: Fix GitHub Issue Investigation (2026-02-09)

**Problem:** Agent was failing `github_issue` scenario due to:
1. `bash: rg: command not found` (trying to use ripgrep which is not installed).
2. `Authentication failed` when cloning repo (skipping `gh auth setup-git`).
3. `fatal: unable to auto-detect email address` (missing git config).

**Fixes:**
1. **Enforce Grep:** Updated system prompt to explicitly say "`rg` is NOT available. USE GREP."
2. **Enforce Auth:** Updated system prompt to mandate `gh auth setup-git` before cloning.
3. **Verified:** Agent now successfully clones repo, searches with grep, and attempts to fix code.

**Status:**
- [x] Fix `rg` issue
- [x] Fix `gh auth` issue
- [x] Fix `git config` (email/name) identity
- [x] Verify fix with E2E evaluation (Environment updated, agent active)

## Fix Details (2026-02-08)

To fix the `Author identity unknown` git error:
1.  Updated `agents/openhands/software_engineer.py` to include `git config` commands in the "Setup" prompt.
2.  Applied `k8s/overlays/dev` to enable `git-sync` sidecar, ensuring code changes are reflected in the running pods without rebuilding images.
3.  Verified the pod has the updated code.

### Phase 11: Fix SoftwareEngineer Empty Response Issue (2026-02-08)

**Problem:** In the `stripe_webhook_failure` scenario, the SoftwareEngineer was:
1. Getting handed off the task from SupportEngineer
2. Investigating the code correctly
3. Getting stuck in a loop viewing the same file sections repeatedly
4. OpenHands stuck detector terminated the loop, resulting in **empty response**

**Root Causes:**
1. Agent wasn't mandated to **implement** fixes - it was just analyzing and recommending
2. Agent got stuck in "view file" loop without making progress
3. No guidance on what to do when stuck

**Fixes Applied:**
1. **Added "CRITICAL: You Must IMPLEMENT Fixes" section** - Mandates actual code fixes, not just analysis
2. **Added "AVOID LOOPS" guidance** - Tells agent to stop if viewing same file section twice
3. **Added "Always Provide a Response" requirement** - Even if incomplete, provide findings
4. **Clarified handoff criteria** - Only hand off for infra changes to @ReleaseEngineer

**Commits:**
- `bc90f4d`: fix(agent): require SoftwareEngineer to implement fixes, not just analyze
- `047ec28`: fix(agent): prevent SoftwareEngineer from getting stuck in loops

**Results:**
- Previous run: HandoffCompletion 0.30 (FAILED - empty response)
- Current run: All metrics PASSED
  - InvestigationQuality: 1.00
  - TaskCompletion: 1.00
  - EvidenceBasedDecision: 0.90
  - HandoffCompletion: 0.90

**Agent now correctly:**
1. Investigates the code (found webhook route in `stripe-service/server.js`)
2. Diagnoses root cause (ingress routing issue, not code bug)
3. Hands off to @ReleaseEngineer for infrastructure fix
4. Provides a detailed response with findings



## Files to Modify

### `vibeteam/gateway/routes/slack.py` (line 242-262)

**Current template:**
```python
task = f"""## Slack Request

A user has requested help via Slack.

### User Message
{user_message}

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_ts or "new thread"}

### Instructions
1. Analyze what the user is asking for
2. Complete the task using available tools
3. Provide a clear, concise response
4. If you need another team member's help, mention them with @RoleName
   (e.g., @ReleaseEngineer, @SoftwareEngineer, @SupportEngineer)
```

**Fixed template:**
```python
task = f"""## Slack Request

A user has requested help via Slack.

### User Message
{user_message}

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_ts or "new thread"}

### Instructions
1. Analyze the user's request
2. Use the tools available to you (Sentry, Langfuse, GitHub, etc.) to investigate
3. Provide a response with SPECIFIC findings (issue IDs, error counts, timestamps, URLs)
4. DO NOT use Slack or messaging tools - your response is automatically posted
5. DO NOT list available team roles - only @mention a specific role if you genuinely need their help AFTER you've done your own investigation

### Expected Output Format
Your response should include:
- Summary of what you found
- Specific data points (error counts, issue IDs, affected users, etc.)
- Recommended next steps
- If needed: A single @RoleName handoff with specific context about what they need to do
```

## Useful Commands

```bash
# Check gateway logs
kubectl logs -n vibeteam deployment/vibeteam-gateway -f

# Run E2E evaluation
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8

# Redeploy gateway after changes
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/vibetechnologies/vibeteam:$IMAGE_TAG .
docker push ghcr.io/vibetechnologies/vibeteam:$IMAGE_TAG
kubectl set image deployment/vibeteam-gateway -n vibeteam gateway=ghcr.io/vibetechnologies/vibeteam:$IMAGE_TAG
kubectl rollout status deployment/vibeteam-gateway -n vibeteam
```

## Success Criteria

After fix, agents should:
1. NOT list all available roles in their response
2. Use Sentry/Langfuse tools to investigate the issue
3. Provide specific findings with data points
4. Only hand off to ONE specific role when genuinely needed
5. E2E evaluation should pass without handoff cascades
