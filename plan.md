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

Sample output from evaluation (2026-02-05T22:10):
- SupportEngineer analyzed Sentry data, found no 400-related issues
- Handed off to ReleaseEngineer for deployment investigation
- ReleaseEngineer confirmed analysis, handed off to SoftwareEngineer
- SoftwareEngineer provided config/code review recommendations

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
