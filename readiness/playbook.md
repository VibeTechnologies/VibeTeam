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
for var in AZURE_API_KEY AZURE_API_BASE GITHUB_TOKEN SENTRY_AUTH_TOKEN LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  echo "$var: $([ -n "${!var}" ] && echo 'SET' || echo 'NOT SET')"
done
```

Required:
- `AZURE_API_KEY` - Azure OpenAI API key
- `AZURE_API_BASE` - Azure OpenAI endpoint
- `GITHUB_TOKEN` - GitHub personal access token

Optional:
- `SENTRY_AUTH_TOKEN` - Sentry API token (skip Sentry checks if not set)
- `LANGFUSE_PUBLIC_KEY` - Langfuse public key (skip Langfuse checks if not set)
- `LANGFUSE_SECRET_KEY` - Langfuse secret key

---

## 1. Infrastructure Health

### 1.1 API Production
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api.vibebrowser.app/health
```
**Expected:** 200 or 401 (auth required is OK), response < 2s
**Critical:** Yes - if down, LLM calls will fail

### 1.2 API Development
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api-dev.vibebrowser.app/health
```
**Expected:** 200 or 401, response < 2s
**Critical:** No - dev environment

### 1.3 User Portal
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://portal.vibebrowser.app
```
**Expected:** 200, response < 3s
**Critical:** Yes - user-facing

### 1.4 Documentation Site
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://docs.vibebrowser.app
```
**Expected:** 200, response < 3s
**Critical:** No

### 1.5 Langfuse Observability
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://langfuse.vibebrowser.app/api/public/health
```
**Expected:** 200, response < 3s
**Critical:** No - observability only

---

## 2. LLM Availability

### 2.1 Test Azure OpenAI
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

### 2.2 Evaluate Response Quality
- Is the response coherent?
- Did it follow the instruction (5 words)?
- Any error messages?

---

## 3. Kubernetes Cluster

### 3.1 Production Namespace
```bash
kubectl get pods -n vibe -o wide 2>&1
```
**Expected:** 
- All pods in `Running` state
- No `CrashLoopBackOff` or `Error` states
- READY column shows all containers ready (e.g., 1/1)

**Evaluate:**
- How many restarts? (< 5 is OK, > 10 is concerning)
- How long have pods been running? (AGE column)
- Any pods pending or failed?

### 3.2 Development Namespace
```bash
kubectl get pods -n vibe-dev -o wide 2>&1
```
**Expected:** Same as production
**Critical:** No - dev environment

### 3.3 Check for Recent Crashes
```bash
kubectl get events -n vibe --sort-by='.lastTimestamp' | tail -20
```
**Evaluate:**
- Any `Warning` events?
- OOMKilled events?
- Failed scheduling?

---

## 4. Error Monitoring (Sentry)

**Skip if SENTRY_AUTH_TOKEN is not set.**

### 4.1 Fetch Unresolved Issues
```bash
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibebrowserextension/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
  | jq 'if type == "array" then [.[] | {title: .title, count: .count, level: .level}] | sort_by(-.count) | .[:5] else {error: .detail} end'
```

### 4.2 Check vibe-api-gateway
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

## 5. LLM Observability (Langfuse)

**Skip if LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is not set.**

### 5.1 Check Recent Traces
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

## 6. GitHub Integration

### 6.1 Test API Access
```bash
gh api /repos/VibeTechnologies/VibeWebAgent/issues/322 --jq '.title'
```
**Expected:** Returns issue title
**Critical:** Yes - needed for customer requests tracking

### 6.2 Check Rate Limit
```bash
gh api /rate_limit --jq '.rate | "Used: \(.used)/\(.limit), Resets: \(.reset | strftime("%H:%M:%S"))"'
```
**Evaluate:** Is rate limit healthy? (< 80% used is fine)

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

## 8. VibeTeam Agent Outcomes

**This section verifies actual agent behavior, not just infrastructure.**

### 8.1 Check CronJob Status
```bash
kubectl get cronjobs -n vibeteam
```
**Expected:** All 4 CronJobs present and not suspended:
- `reliability-engineer` (*/5 * * * *)
- `product-manager` (0 */2 * * *)
- `support-engineer` (*/15 * * * *)
- `release-engineer` (0 9 * * *)

### 8.2 Run Agent Verification Jobs
```bash
kubectl create job --from=cronjob/reliability-engineer test-sre -n vibeteam
kubectl create job --from=cronjob/product-manager test-pm -n vibeteam
kubectl create job --from=cronjob/support-engineer test-support -n vibeteam
kubectl create job --from=cronjob/release-engineer test-release -n vibeteam
# Wait 90 seconds for completion
sleep 90
kubectl get jobs -n vibeteam | grep "^test-"
```
**Expected:** All jobs show `Complete 1/1`

### 8.3 Verify Agent Logs
```bash
# Reliability Engineer - should show endpoint health
kubectl logs -n vibeteam $(kubectl get pods -n vibeteam -l job-name=test-sre -o jsonpath='{.items[0].metadata.name}')
```
**Expected:** "All X endpoints healthy"

```bash
# Product Manager - should connect to Langfuse
kubectl logs -n vibeteam $(kubectl get pods -n vibeteam -l job-name=test-pm -o jsonpath='{.items[0].metadata.name}')
```
**Expected:** "Found X conversations" (0 is OK if no recent activity)

```bash
# Support Engineer - should connect to Gmail
kubectl logs -n vibeteam $(kubectl get pods -n vibeteam -l job-name=test-support -o jsonpath='{.items[0].metadata.name}')
```
**Expected:** "Found X unread emails" (processes emails with `[Docs Support]` prefix)

```bash
# Release Engineer - should list merged PRs
kubectl logs -n vibeteam $(kubectl get pods -n vibeteam -l job-name=test-release -o jsonpath='{.items[0].metadata.name}')
```
**Expected:** "Found X recently merged PRs"

### 8.4 Clean Up Test Jobs
```bash
kubectl delete jobs test-sre test-pm test-support test-release -n vibeteam
```

### 8.5 Check Historical Outcomes

**GitHub Issues Created by Agents:**
```bash
gh issue list -R VibeTechnologies/VibeWebAgent --search "author:vibetechnologies" --limit 5
```

**Gmail Sent Responses:**
Check for emails sent with `[Docs Support]` responses in Gmail sent folder.

**Langfuse Traces:**
```bash
curl -s "https://langfuse.vibebrowser.app/api/public/traces?limit=5&name=support-chat" \
  -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" \
  | jq '.data | map({timestamp: .timestamp, name: .name})'
```

**Evaluate:**
- Are agents completing without errors?
- Are outcomes being produced (issues, emails, traces)?
- Any permission or authentication errors in logs?

**Critical:** Yes - agents must produce verifiable outcomes

---

## Final Assessment

Based on all checks, determine the overall status:

### GREEN - All Systems Go
All conditions met:
- [ ] All critical endpoints responding (API Prod, Portal)
- [ ] LLM responds correctly within timeout
- [ ] Kubernetes pods running without CrashLoopBackOff
- [ ] GitHub API accessible
- [ ] No high-frequency Sentry issues
- [ ] All 4 VibeTeam agents complete successfully
- [ ] Agent logs show expected outcomes (no auth errors)

### YELLOW - Degraded
One or more non-critical issues:
- [ ] Dev endpoints down (prod OK)
- [ ] Elevated latency (but functional)
- [ ] Some pod restarts (but stable now)
- [ ] Sentry has low-frequency issues
- [ ] Langfuse shows warnings
- [ ] Some agents find 0 items to process (OK if no activity)
- [ ] Agent job takes longer than expected but completes

### RED - Not Ready
Any critical failure:
- [ ] Production API down
- [ ] LLM not responding or timing out
- [ ] Pods in CrashLoopBackOff
- [ ] GitHub API inaccessible
- [ ] Multiple high-frequency Sentry errors
- [ ] Agent jobs failing (ImagePullBackOff, OOMKilled, auth errors)
- [ ] Langfuse or Gmail credentials invalid (401 errors in logs)

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
| API Prod | OK/WARN/FAIL | [details] |
| API Dev | OK/WARN/FAIL | [details] |
| Portal | OK/WARN/FAIL | [details] |
| Docs | OK/WARN/FAIL | [details] |
| Langfuse | OK/WARN/FAIL | [details] |
| LLM | OK/WARN/FAIL | [details] |
| K8s Prod | OK/WARN/FAIL | [details] |
| K8s Dev | OK/WARN/FAIL | [details] |
| Sentry | OK/WARN/FAIL | [details] |
| GitHub | OK/WARN/FAIL | [details] |
| Docs Chat | OK/WARN/FAIL | [details] |
| VibeTeam Agents | OK/WARN/FAIL | [details] |

## Issues Found
- [List any issues]

## Recommendations
- [List any recommended actions]
```
