# VibeTeam Readiness Requirements

This document defines the requirements for VibeTeam to be **fully functional and operational**. Use this as a checklist before deploying to production or after infrastructure changes.

## Overview

VibeTeam must be able to:

1. **Respond to Slack mentions** (`@vibeteam`)
2. **Handle GitHub issues** (via `fix-me` label or `@openhands-agent`)
3. **Process support emails** (Gmail integration)
4. **Monitor Sentry errors** (Release Engineer)
5. **Analyze Langfuse traces** (Product Manager)
6. **Check endpoint health** (Reliability Engineer)

---

## Integration Requirements

### 1. Slack Integration

| Requirement | Status | Notes |
|-------------|--------|-------|
| Slack App created | [ ] | https://api.slack.com/apps |
| Bot User OAuth Token (`xoxb-...`) | [ ] | OAuth & Permissions page |
| Signing Secret | [ ] | Basic Information page |
| App installed to workspace | [ ] | Install to Workspace |
| Bot invited to channels | [ ] | `/invite @vibeteam` |
| Webhook server deployed | [ ] | K8s: `vibeteam` namespace |
| Event subscriptions configured | [ ] | `app_mention`, `message.im` |

**Required Secrets:**
```json
{
  "SLACK_BOT_TOKEN": "xoxb-...",
  "SLACK_SIGNING_SECRET": "...",
  "SLACK_APP_ID": "A0...",
  "SLACK_WORKSPACE_ID": "T0..."
}
```

**Verification:**
```bash
# Test webhook endpoint
curl -s https://team.vibebrowser.app/slack/events

# Check K8s deployment
kubectl get pods -n vibeteam -l app=slack-webhook-bot
```

---

### 2. GitHub Integration

| Requirement | Status | Notes |
|-------------|--------|-------|
| GitHub Token (PAT or App) | [ ] | `repo` scope required |
| OpenHands Resolver workflow | [ ] | `.github/workflows/openhands-resolver.yml` |
| `LLM_API_KEY` secret set | [ ] | In each target repo |
| `fix-me` label exists | [ ] | Create in each repo |
| Microagent config | [ ] | `.openhands/microagents/repo.md` |

**Required Secrets (GitHub Actions):**
- `LLM_API_KEY` - Azure OpenAI key
- `GITHUB_TOKEN` - Auto-provided or PAT

**Verification:**
```bash
# Test GitHub API access
gh api /repos/VibeTechnologies/VibeWebAgent/issues/322 --jq '.title'

# Check rate limit
gh api /rate_limit --jq '.rate'
```

**Target Repositories:**
- [ ] `VibeTechnologies/VibeWebAgent`
- [ ] `VibeTechnologies/vibe-mcp`
- [ ] `VibeTechnologies/VibeBrowserAppPage`
- [ ] `VibeTechnologies/VibeTeam`

---

### 3. Email (Gmail) Integration

| Requirement | Status | Notes |
|-------------|--------|-------|
| Google Cloud project | [ ] | With Gmail API enabled |
| OAuth credentials | [ ] | `gmail-credentials.json` |
| OAuth token | [ ] | `gmail-token.json` (after auth flow) |
| K8s secret created | [ ] | `gmail-oauth-secrets` |
| Support email configured | [ ] | Receives `[Docs Support]` emails |

**Required Files:**
```
.secrets/
├── gmail-credentials.json    # OAuth client credentials
└── gmail-token.json          # Authorized token
```

**Verification:**
```bash
# Test Gmail connector locally
python -c "
from vibeteam.connectors.gmail import GmailConnector
g = GmailConnector()
print('Authenticated:', g.service is not None)
"
```

---

### 4. Sentry Integration

| Requirement | Status | Notes |
|-------------|--------|-------|
| Sentry Auth Token | [ ] | Project access required |
| Projects configured | [ ] | `vibebrowserextension`, `vibe-api-gateway` |

**Required Environment Variable:**
```bash
SENTRY_AUTH_TOKEN=sntrys_...
```

**Verification:**
```bash
# Test Sentry API
curl -s "https://sentry.io/api/0/projects/vibetechnologies/vibebrowserextension/issues/?query=is:unresolved&statsPeriod=24h" \
  -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" | jq '.[0].title'
```

---

### 5. Langfuse Integration

| Requirement | Status | Notes |
|-------------|--------|-------|
| Langfuse instance running | [ ] | `langfuse.vibebrowser.app` |
| Public key | [ ] | `pk-lf-...` |
| Secret key | [ ] | `sk-lf-...` |
| Traces being recorded | [ ] | LLM calls logged |

**Required Environment Variables:**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://langfuse.vibebrowser.app
```

**Verification:**
```bash
# Test Langfuse health
curl -s https://langfuse.vibebrowser.app/api/public/health

# Check recent traces
curl -s "https://langfuse.vibebrowser.app/api/public/traces?limit=5" \
  -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | jq '.data | length'
```

---

### 6. Azure OpenAI (LLM)

| Requirement | Status | Notes |
|-------------|--------|-------|
| Azure OpenAI resource | [ ] | Deployed model |
| API key | [ ] | From Azure portal |
| Endpoint URL | [ ] | `.cognitiveservices.azure.com` |
| Model deployed | [ ] | `gpt-4.1` or `gpt-5-2` |

**Required Environment Variables:**
```bash
AZURE_API_KEY=...
AZURE_API_BASE=https://your-endpoint.cognitiveservices.azure.com/
AZURE_API_VERSION=2024-08-01-preview
```

**Verification:**
```bash
# Test LLM response
curl -s -X POST "${AZURE_API_BASE}openai/deployments/gpt-4.1/chat/completions?api-version=2024-08-01-preview" \
  -H "Content-Type: application/json" \
  -H "api-key: ${AZURE_API_KEY}" \
  -d '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":50}' \
  | jq -r '.choices[0].message.content'
```

---

### 7. Infrastructure Health Endpoints

| Endpoint | URL | Critical |
|----------|-----|----------|
| API Production | `https://api.vibebrowser.app/health` | Yes |
| API Development | `https://api-dev.vibebrowser.app/health` | No |
| User Portal | `https://portal.vibebrowser.app` | Yes |
| Documentation | `https://docs.vibebrowser.app` | No |
| Langfuse | `https://langfuse.vibebrowser.app/api/public/health` | No |
| OpenHands | `https://team.vibebrowser.app` | Yes |

---

## Kubernetes Requirements

### Namespace: `vibeteam`

| Resource | Type | Schedule | Purpose |
|----------|------|----------|---------|
| reliability-engineer | CronJob | `*/5 * * * *` | Health checks |
| support-engineer | CronJob | `*/15 * * * *` | Email processing |
| product-manager | CronJob | `0 */2 * * *` | Langfuse analysis |
| software-engineer | CronJob | `0 */4 * * *` | GitHub issues |
| release-engineer | CronJob | `0 9 * * *` | Release validation |
| slack-webhook-bot | Deployment | Always on | Slack integration |
| openhands | Deployment | Always on | Web UI |

### Required K8s Secrets

```bash
# 1. Container registry
kubectl create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-pat> \
  -n vibeteam

# 2. Core credentials
kubectl create secret generic vibeteam-secrets \
  --from-literal=AZURE_API_KEY=<key> \
  --from-literal=AZURE_API_BASE=<url> \
  --from-literal=GITHUB_TOKEN=<token> \
  --from-literal=LANGFUSE_PUBLIC_KEY=<key> \
  --from-literal=LANGFUSE_SECRET_KEY=<key> \
  --from-literal=SENTRY_AUTH_TOKEN=<token> \
  -n vibeteam

# 3. Gmail OAuth
kubectl create secret generic gmail-oauth-secrets \
  --from-file=gmail-credentials.json=.secrets/gmail-credentials.json \
  --from-file=gmail-token.json=.secrets/gmail-token.json \
  -n vibeteam

# 4. Slack
kubectl create secret generic slack-bot-secrets \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  -n vibeteam
```

---

## Pre-Deployment Checklist

### Local Development

- [ ] `.env` file contains all required variables
- [ ] `.secrets/` directory has credential files
- [ ] `pip install -e .` completes successfully
- [ ] `vibeteam status` runs without errors
- [ ] `python readiness/check.py` returns GREEN

### Kubernetes Deployment

- [ ] All secrets created in `vibeteam` namespace
- [ ] Docker image pushed to `ghcr.io/vibetechnologies/vibeteam`
- [ ] All CronJobs created and not suspended
- [ ] Ingress configured for `team.vibebrowser.app`
- [ ] SSL certificate valid

---

## Verification Commands

### Quick Health Check

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python readiness/check.py --quick
```

### Full System Check

```bash
python readiness/check.py --full
```

### Agent Smoke Test

```bash
# Test each agent
vibeteam run "Check API health" --agent sre
vibeteam run "Check for new emails" --agent support
vibeteam run "Check Langfuse for issues" --agent pm
vibeteam run "List open issues" --agent swe
vibeteam run "Check latest release" --agent release
```

### Kubernetes Verification

```bash
# Check all resources
kubectl get all -n vibeteam

# View CronJob schedules
kubectl get cronjobs -n vibeteam

# Check recent job runs
kubectl get jobs -n vibeteam --sort-by=.metadata.creationTimestamp | tail -10

# View logs
kubectl logs -n vibeteam -l app=slack-webhook-bot --tail=50
```

---

## Troubleshooting

### Slack Not Responding

1. Check webhook server logs: `kubectl logs -n vibeteam -l app=slack-webhook-bot`
2. Verify bot token: Is `SLACK_BOT_TOKEN` set correctly?
3. Check Slack Event Subscriptions: Is URL verified?
4. Ensure bot is invited to the channel

### Emails Not Processing

1. Check Gmail credentials: `kubectl get secret gmail-oauth-secrets -n vibeteam`
2. Token may be expired: Re-run OAuth flow
3. Check support-engineer logs: `kubectl logs -n vibeteam -l app=support-engineer`

### GitHub Integration Failing

1. Verify `LLM_API_KEY` secret in target repo
2. Check workflow run in Actions tab
3. Ensure `fix-me` label exists
4. Review OpenHands resolver logs

### LLM Timeout

1. Azure OpenAI may be overloaded
2. Check deployment quota in Azure portal
3. Verify model name matches deployment name

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_API_KEY` | Yes | Azure OpenAI API key |
| `AZURE_API_BASE` | Yes | Azure OpenAI endpoint |
| `AZURE_API_VERSION` | Yes | API version (e.g., `2024-08-01-preview`) |
| `GITHUB_TOKEN` | Yes | GitHub PAT with `repo` scope |
| `LANGFUSE_PUBLIC_KEY` | Opt | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Opt | Langfuse secret key |
| `LANGFUSE_BASE_URL` | Opt | Langfuse endpoint |
| `SENTRY_AUTH_TOKEN` | Opt | Sentry API token |
| `SLACK_BOT_TOKEN` | Opt | Slack bot OAuth token |
| `SLACK_SIGNING_SECRET` | Opt | Slack request verification |
| `GMAIL_CREDENTIALS_PATH` | Opt | Path to Gmail OAuth credentials |
| `GMAIL_TOKEN_PATH` | Opt | Path to Gmail OAuth token |

---

## Related Documentation

- [Readiness Playbook](../readiness/playbook.md) - Detailed verification steps
- [OpenHands Integration](openhands-integration.md) - Interactive agent setup
- [Slack App Setup](slack-app-setup.md) - Slack bot configuration
- [Support Engineer](support-engineer.md) - Email processing flow
