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
