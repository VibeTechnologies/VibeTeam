---
name: vibeteam-readiness
description: Run VibeTeam system readiness checks - validates infrastructure, LLM, integrations (Slack, GitHub, Gmail, Sentry, Langfuse), and K8s agents
license: MIT
compatibility: opencode
metadata:
  audience: sre
  workflow: verification
---

# VibeTeam Readiness Check Skill

Execute this playbook to evaluate whether VibeTeam is fully operational.
Run each check, record results, and produce a GREEN/YELLOW/RED assessment.

## Instructions

1. Execute checks in order (pre-flight, infrastructure, LLM, integrations, K8s agents)
2. Record actual output for each check
3. Compare against expected criteria
4. Use judgment for ambiguous cases
5. Produce final assessment with reasoning

---

## Pre-Flight

Load environment variables first:

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
```

Verify required variables are set:

```bash
for var in AZURE_API_KEY AZURE_API_BASE GITHUB_TOKEN SENTRY_AUTH_TOKEN LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY SLACK_BOT_TOKEN; do
  echo "$var: $([ -n "${!var}" ] && echo 'SET' || echo 'NOT SET')"
done
```

**Required:**
- `AZURE_API_KEY` - Azure OpenAI API key
- `AZURE_API_BASE` - Azure OpenAI endpoint
- `GITHUB_TOKEN` - GitHub personal access token

**Optional:**
- `SENTRY_AUTH_TOKEN` - Sentry API token
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` - Langfuse keys
- `SLACK_BOT_TOKEN` - Slack bot token

---

## 1. Infrastructure Health

### 1.1 API Production (CRITICAL)
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api.vibebrowser.app/health
```
**Expected:** 200 or 401, response < 2s

### 1.2 API Development
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://api-dev.vibebrowser.app/health
```
**Expected:** 200 or 401, response < 2s

### 1.3 User Portal (CRITICAL)
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://portal.vibebrowser.app
```
**Expected:** 200, response < 3s

### 1.4 Documentation Site
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://docs.vibebrowser.app
```
**Expected:** 200, response < 3s

### 1.5 Langfuse Observability
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://langfuse.vibebrowser.app/api/public/health
```
**Expected:** 200, response < 3s

### 1.6 OpenHands Web UI (CRITICAL)
```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://team.vibebrowser.app
```
**Expected:** 200, response < 5s

---

## 2. LLM Availability (CRITICAL)

```bash
curl -s -X POST "${AZURE_API_BASE}openai/deployments/gpt-4.1-mini/chat/completions?api-version=2024-08-01-preview" \
  -H "Content-Type: application/json" \
  -H "api-key: ${AZURE_API_KEY}" \
  -d '{"messages":[{"role":"user","content":"Say hello in 5 words"}],"max_tokens":50}' \
  | jq -r '.choices[0].message.content // .error.message'
```

**Expected:** Coherent 5-word response
**Timeout:** Allow up to 120 seconds
**Evaluate:**
- Is the response coherent?
- Did it follow the instruction?
- Any error messages?

---

## 3. Slack Integration

### 3.1 Verify Slack Token Set
```bash
[ -n "$SLACK_BOT_TOKEN" ] && echo "SLACK_BOT_TOKEN is set" || echo "SLACK_BOT_TOKEN is NOT SET"
```

### 3.2 Test Slack API (if token set)
```bash
curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
  -H "Content-Type: application/json" \
  | jq '{ok: .ok, user: .user, team: .team}'
```
**Expected:** `"ok": true` with user and team info

### 3.3 Check Webhook Server (K8s)
```bash
kubectl get pods -n vibeteam -l app=slack-webhook-bot 2>/dev/null || echo "kubectl not available or namespace missing"
```
**Expected:** Pod in Running state

---

## 4. GitHub Integration (CRITICAL)

### 4.1 Test API Access
```bash
gh api /repos/VibeTechnologies/VibeWebAgent/issues/322 --jq '.title'
```
**Expected:** Returns issue title

### 4.2 Check Rate Limit
```bash
gh api /rate_limit --jq '.rate | "Used: \(.used)/\(.limit), Resets: \(.reset | strftime("%H:%M:%S"))"'
```
**Expected:** Less than 80% used

---

## 5. Gmail Integration

### 5.1 Check Credentials Files
```bash
ls -la .secrets/gmail-credentials.json .secrets/gmail-token.json 2>/dev/null || echo "Gmail credential files not found"
```

### 5.2 Check K8s Secret
```bash
kubectl get secret gmail-oauth-secrets -n vibeteam -o jsonpath='{.data}' 2>/dev/null | jq -r 'keys' || echo "Secret not found or kubectl unavailable"
```
**Expected:** Contains `gmail-credentials.json` and `gmail-token.json`

---

## 6. Sentry Integration

**Skip if SENTRY_AUTH_TOKEN is not set.**

### 6.1 Fetch Unresolved Issues
```bash
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibebrowserextension/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
  | jq 'if type == "array" then [.[] | {title: .title, count: .count, level: .level}] | sort_by(-.count) | .[:5] else {error: .detail} end'
```

### 6.2 Check vibe-api-gateway
```bash
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibe-api-gateway/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
  | jq 'if type == "array" then [.[] | {title: .title, count: .count, level: .level}] | sort_by(-.count) | .[:5] else {error: .detail} end'
```

**Evaluate:**
- Any issues with count > 100? (high frequency = problem)
- Any `fatal` or `error` level issues?

---

## 7. Langfuse Integration

**Skip if LANGFUSE keys not set.**

### 7.1 Check Recent Traces
```bash
curl -s "https://langfuse.vibebrowser.app/api/public/traces?limit=10" \
  -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" \
  | jq 'if .data then (.data | map({name: .name, latency: .latency, level: .level}) | .[:5]) else {error: .message} end'
```

**Evaluate:**
- Average latency (< 5s is good, > 15s is concerning)
- Any ERROR level traces?
- Are traces being recorded?

---

## 8. Kubernetes Agents

### 8.1 Check CronJob Status
```bash
kubectl get cronjobs -n vibeteam 2>/dev/null || echo "kubectl unavailable"
```

**Expected CronJobs:**
- `reliability-engineer` (*/5 * * * *)
- `product-manager` (0 */2 * * *)
- `support-engineer` (*/15 * * * *)
- `software-engineer` (0 */4 * * *)
- `release-engineer` (0 9 * * *)

### 8.2 Check Recent Job Runs
```bash
kubectl get jobs -n vibeteam --sort-by=.metadata.creationTimestamp 2>/dev/null | tail -10 || echo "kubectl unavailable"
```

### 8.3 Check Pod Health
```bash
kubectl get pods -n vibeteam 2>/dev/null || echo "kubectl unavailable"
```

**Evaluate:**
- All pods Running?
- Any CrashLoopBackOff?
- Restart count < 5?

---

## Final Assessment

Based on all checks, determine overall status:

### GREEN - All Systems Go
All conditions met:
- [ ] All critical endpoints responding (API Prod, Portal, OpenHands)
- [ ] LLM responds correctly within timeout
- [ ] Slack token valid and webhook server running
- [ ] GitHub API accessible
- [ ] Gmail credentials present (if support-engineer needed)
- [ ] No high-frequency Sentry issues
- [ ] K8s pods running without CrashLoopBackOff
- [ ] All CronJobs present and not suspended

### YELLOW - Degraded
One or more non-critical issues:
- [ ] Dev endpoints down (prod OK)
- [ ] Elevated latency (but functional)
- [ ] Some pod restarts (but stable now)
- [ ] Sentry has low-frequency issues
- [ ] Langfuse shows warnings
- [ ] Some optional integrations missing

### RED - Not Ready
Any critical failure:
- [ ] Production API down
- [ ] LLM not responding or timing out
- [ ] Slack webhook server not running
- [ ] Pods in CrashLoopBackOff
- [ ] GitHub API inaccessible
- [ ] Gmail credentials invalid (401 errors)
- [ ] Multiple high-frequency Sentry errors

---

## Report Template

Generate a report in this format:

```markdown
# VibeTeam Readiness Assessment - [DATE]

## Status: [GREEN/YELLOW/RED]

## Summary
[1-2 sentence overall assessment]

## Checks Performed

| Check | Status | Notes |
|-------|--------|-------|
| API Prod | OK/WARN/FAIL | [details] |
| API Dev | OK/WARN/FAIL | [details] |
| Portal | OK/WARN/FAIL | [details] |
| OpenHands UI | OK/WARN/FAIL | [details] |
| Docs | OK/WARN/FAIL | [details] |
| LLM | OK/WARN/FAIL | [details] |
| Slack | OK/WARN/FAIL | [details] |
| GitHub | OK/WARN/FAIL | [details] |
| Gmail | OK/WARN/FAIL | [details] |
| Sentry | OK/WARN/FAIL | [details] |
| Langfuse | OK/WARN/FAIL | [details] |
| K8s Agents | OK/WARN/FAIL | [details] |

## Issues Found
- [List any issues]

## Recommendations
- [List any recommended actions]
```
