# VibeTeam Readiness Playbook

This playbook is for GenAI agents to follow when evaluating system readiness.
Execute each step, interpret results, and produce a final assessment.

## Instructions for AI Agent

1. Execute each check in order
2. Record the actual output
3. Compare against expected criteria
4. Use judgment for ambiguous cases
5. Produce a final GREEN/YELLOW/RED assessment with reasoning

---

## Pre-Flight

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
```

Check environment variables (prints SET or NOT SET):
```bash
for var in AZURE_API_KEY AZURE_API_BASE GITHUB_TOKEN SLACK_BOT_TOKEN SLACK_SIGNING_SECRET SENTRY_AUTH_TOKEN LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  echo "$var: $([ -n "${!var}" ] && echo 'SET' || echo 'NOT SET')"
done
```

Required:
- `AZURE_API_KEY` - Azure OpenAI API key
- `AZURE_API_BASE` - Azure OpenAI endpoint
- `GITHUB_TOKEN` - GitHub personal access token
- `SLACK_BOT_TOKEN` - Slack bot token (for agent messaging)
- `SLACK_SIGNING_SECRET` - Slack signing secret (for webhook verification)

Optional:
- `DISCORD_BOT_TOKEN` - Discord bot token
- `SENTRY_AUTH_TOKEN` - Sentry API token (skip Sentry checks if not set)
- `LANGFUSE_PUBLIC_KEY` - Langfuse public key (skip Langfuse checks if not set)
- `LANGFUSE_SECRET_KEY` - Langfuse secret key

---

## 1. VibeTeam Namespace (Critical)

This is where the VibeTeam agents run. **This is the most important check.**

### 1.1 Check All Pods
```bash
kubectl get pods -n vibeteam -o wide
```

**Expected pods (all should be Running 1/1):**
- `vibeteam-gateway-*` - Message router (Gateway)
- `openhands-svc-*` - OpenHands agent service
- `openhands-*` - OpenHands runtime
- `scheduler-svc-*` - Scheduler service
- `postgres-0` - Database
- `slack-agent-swe-*` - SoftwareEngineer Slack agent
- `slack-agent-pm-*` - ProductManager Slack agent
- `slack-agent-release-*` - ReleaseEngineer Slack agent
- `slack-agent-support-*` - SupportEngineer Slack agent

**Critical failures:**
- Any pod in `CrashLoopBackOff` or `Error` state
- Any pod with `0/1` READY status
- High restart counts (> 10)

### 1.2 Check for CrashLoopBackOff
```bash
kubectl get pods -n vibeteam | grep -E "CrashLoopBackOff|Error|ImagePullBackOff"
```
**Expected:** No output (no failing pods)
**Critical:** Yes - any output here means agents are broken

### 1.3 Check Recent Events
```bash
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -20
```
**Evaluate:**
- Any `Warning` events?
- OOMKilled events?
- Failed image pulls?
- Container crash reasons?

### 1.4 Check Failing Pod Logs
If any pods are failing, check their logs:
```bash
# Replace <pod-name> with actual failing pod
kubectl logs -n vibeteam <pod-name> --tail=50
```
**Look for:**
- Missing files or scripts
- Authentication errors
- Connection refused
- Import errors

---

## 2. VibeBrowser Infrastructure

### 2.1 API Production
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api.vibebrowser.app/health
```
**Expected:** 200 or 401 (auth required is OK), response < 2s
**Critical:** Yes - if down, API calls will fail

### 2.2 API Development
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api-dev.vibebrowser.app/health
```
**Expected:** 200 or 401, response < 2s
**Critical:** No - dev environment

### 2.3 User Portal
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://portal.vibebrowser.app
```
**Expected:** 200, response < 3s
**Critical:** Yes - user-facing

### 2.4 Documentation Site
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://docs.vibebrowser.app
```
**Expected:** 200, response < 3s
**Critical:** No

### 2.5 Langfuse Observability
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://langfuse.vibebrowser.app/api/public/health
```
**Expected:** 200, response < 3s
**Critical:** No - observability only

---

## 3. LLM Availability

### 3.1 Test Azure OpenAI
```bash
curl -s -X POST "${AZURE_API_BASE}openai/deployments/gpt-4.1/chat/completions?api-version=2024-08-01-preview" \
  -H "Content-Type: application/json" \
  -H "api-key: ${AZURE_API_KEY}" \
  -d '{"messages":[{"role":"user","content":"Say hello in 5 words"}],"max_tokens":50}' \
  | jq -r '.choices[0].message.content // .error.message'
```
**Note:** Using gpt-4.1 model deployed on Azure OpenAI.
**Expected:** A coherent 5-word response
**Timeout:** Allow up to 120 seconds for response
**Critical:** Yes - core functionality

### 3.2 Evaluate Response Quality
- Is the response coherent?
- Did it follow the instruction (5 words)?
- Any error messages?

---

## 4. GitHub Integration

### 4.1 Test API Access
```bash
gh api /repos/VibeTechnologies/VibeWebAgent/issues/322 --jq '.title'
```
**Expected:** Returns issue title
**Critical:** Yes - needed for customer requests tracking

### 4.2 Check Rate Limit
```bash
gh api /rate_limit --jq '.rate | "Used: \(.used)/\(.limit), Resets: \(.reset | strftime("%H:%M:%S"))"'
```
**Evaluate:** Is rate limit healthy? (< 80% used is fine)

---

## 5. Error Monitoring (Sentry)

**Skip if SENTRY_AUTH_TOKEN is not set.**

### 5.1 Fetch Unresolved Issues
```bash
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibebrowserextension/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
  | jq 'if type == "array" then [.[] | {title: .title, count: .count, level: .level}] | sort_by(-.count) | .[:5] else {error: .detail} end'
```

### 5.2 Check vibe-api-gateway
```bash
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibe-api-gateway/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
  | jq 'if type == "array" then [.[] | {title: .title, count: .count, level: .level}] | sort_by(-.count) | .[:5] else {error: .detail} end'
```

**Evaluate:**
- Any issues with count > 100? (high frequency = problem)
- Any `fatal` or `error` level issues?
- Are issues new or recurring?

**Critical:** No, but high-frequency errors should be flagged

---

## 6. LLM Observability (Langfuse)

**Skip if LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is not set.**

### 6.1 Check Recent Traces
```bash
curl -s "https://langfuse.vibebrowser.app/api/public/traces?limit=10" \
  -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" \
  | jq 'if .data then (.data | map({name: .name, latency: .latency, level: .level}) | .[:5]) else {error: .message} end'
```

**Evaluate:**
- Average latency (< 5s is good, > 15s is concerning)
- Any ERROR level traces?
- Are traces being recorded? (empty = problem)

---

## 7. Documentation Chat

### 7.1 Test Chat API
```bash
curl -s -X POST "https://docs.vibebrowser.app/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is VibeBrowser?"}]}' \
  | jq -r '.content[:200]'
```
**Expected:** Coherent response about VibeBrowser
**Critical:** No

---

## Final Assessment

Based on all checks, determine the overall status:

### GREEN - All Systems Go
All conditions met:
- [ ] All vibeteam namespace pods Running (no CrashLoopBackOff)
- [ ] All critical endpoints responding (API Prod, Portal)
- [ ] LLM responds correctly within timeout
- [ ] GitHub API accessible
- [ ] Slack agent pods healthy
- [ ] No high-frequency Sentry issues

### YELLOW - Degraded
One or more non-critical issues:
- [ ] Dev endpoints down (prod OK)
- [ ] Elevated latency (but functional)
- [ ] Some pod restarts (but stable now)
- [ ] Sentry has low-frequency issues
- [ ] Langfuse shows warnings
- [ ] Optional integrations unavailable

### RED - Not Ready
Any critical failure:
- [ ] vibeteam pods in CrashLoopBackOff or Error
- [ ] Slack agents not running
- [ ] Production API down
- [ ] LLM not responding or timing out
- [ ] GitHub API inaccessible
- [ ] Gateway or Agent Services down
- [ ] Postgres not running

---

## Report Template

```markdown
# Readiness Assessment - [DATE]

## Status: [GREEN/YELLOW/RED]

## Summary
[1-2 sentence overall assessment]

## Checks Performed

| Check | Status | Notes |
|-------|--------|-------|
| vibeteam namespace | OK/WARN/FAIL | [pod status details] |
| Slack agents | OK/WARN/FAIL | [which agents running/failing] |
| Gateway | OK/WARN/FAIL | [details] |
| Postgres | OK/WARN/FAIL | [details] |
| API Prod | OK/WARN/FAIL | [details] |
| API Dev | OK/WARN/FAIL | [details] |
| Portal | OK/WARN/FAIL | [details] |
| Docs | OK/WARN/FAIL | [details] |
| LLM | OK/WARN/FAIL | [details] |
| GitHub | OK/WARN/FAIL | [details] |
| Sentry | OK/WARN/FAIL | [details] |
| Langfuse | OK/WARN/FAIL | [details] |

## Issues Found
- [List any issues]

## Recommendations
- [List any recommended actions]
```
