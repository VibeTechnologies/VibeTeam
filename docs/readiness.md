# VibeTeam Readiness Guide

VibeTeam is designed to be a fully operational team replacement. This guide ensures the system is reliable and ready for production use.

## Quick Readiness Check

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python scripts/check_readiness.py
```

## What Gets Checked

### 1. Infrastructure Health

| Endpoint | Purpose | Critical |
|----------|---------|----------|
| `api.vibebrowser.app/health` | LiteLLM API (prod) | Yes |
| `api-dev.vibebrowser.app/health` | LiteLLM API (dev) | No |
| `portal.vibebrowser.app` | User Portal | Yes |
| `docs.vibebrowser.app` | Documentation | No |
| `langfuse.vibebrowser.app/api/public/health` | LLM Observability | No |

### 2. LLM Availability

| Model | Deployment | Account |
|-------|------------|---------|
| gpt-5-2 | Azure OpenAI | info-mjnxtt51-eastus2 |
| gpt-5.1 | Azure OpenAI | info-mjnxtt51-eastus2 |
| grok-4 | Azure OpenAI | info-mjnxtt51-eastus2 |
| DeepSeek-R1 | Azure OpenAI | info-mjnxtt51-eastus2 |

### 3. Kubernetes Cluster

| Namespace | Services |
|-----------|----------|
| vibe (prod) | litellm, stripe-service, user-portal |
| vibe-dev | litellm, stripe-service, user-portal |

### 4. Error Monitoring

| Source | Projects |
|--------|----------|
| Sentry | vibebrowserextension, vibe-api-gateway, vibeteam |
| Langfuse | Latency, error rates, token usage |

### 5. GitHub Integration

| Check | Description |
|-------|-------------|
| Customer Requests | Issue #322 accessible and updateable |
| API Access | Can create issues, PRs, reviews |

## Manual Checks

### Check Kubernetes Pods

```bash
# Get kubeconfig
cd ~/workspace/vibebrowser/vibe.2
bun run services/k3s/setup-k3s-access.ts

# Check prod pods
kubectl get pods -n vibe
kubectl get pods -n vibe-dev

# Check for restarts or errors
kubectl get pods -n vibe -o wide
kubectl describe pods -n vibe -l app=litellm
```

### Check Pod Logs

```bash
# LiteLLM logs (last 100 lines)
kubectl logs -n vibe -l app=litellm --tail=100

# Stripe service logs
kubectl logs -n vibe -l app=stripe-service --tail=100

# Look for errors
kubectl logs -n vibe -l app=litellm --tail=500 | grep -i error
```

### Check Sentry Issues

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python -c "
from vibeteam.connectors.sentry import SentryConnector
sentry = SentryConnector()
issues = sentry.fetch_unresolved_issues(hours=24)
print(f'Unresolved issues (24h): {len(issues)}')
for i in issues[:5]:
    print(f'  [{i.level}] {i.title} ({i.count} events)')
"
```

### Check Langfuse Anomalies

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python -c "
from vibeteam.connectors.langfuse import LangfuseConnector
lf = LangfuseConnector()
stats = lf.get_stats(hours=1)
anomalies = lf.detect_anomalies(hours=1)
print(f'Last hour: {stats.total_traces} traces, {stats.error_count} errors')
print(f'Anomalies: {len(anomalies)}')
for a in anomalies:
    print(f'  [{a.severity}] {a.type}: {a.message}')
"
```

### Test LLM Response

```bash
source .env
python -c "
import litellm
import os
response = litellm.completion(
    model='azure/gpt-5-2',
    messages=[{'role': 'user', 'content': 'Say hello in 5 words'}],
    api_base=os.environ['AZURE_API_BASE'],
    api_key=os.environ['AZURE_API_KEY'],
    api_version='2024-08-01-preview',
    max_tokens=50,
)
print('LLM Response:', response.choices[0].message.content)
print('Tokens:', response.usage.total_tokens)
"
```

### Test Docs Chat

```bash
curl -s -X POST "https://docs.vibebrowser.app/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is VibeBrowser?"}]}' | jq '.content[:200]'
```

## Readiness Criteria

### GREEN - All Systems Go

All conditions must be true:

- [ ] All critical endpoints return 200
- [ ] Kubernetes pods are Running (no CrashLoopBackOff)
- [ ] No pod restarts in last hour
- [ ] LLM responds in < 10 seconds
- [ ] Sentry has no P0/P1 unresolved issues
- [ ] Langfuse shows < 5% error rate
- [ ] GitHub API accessible

### YELLOW - Degraded

One or more non-critical issues:

- [ ] Dev endpoints down (but prod OK)
- [ ] Langfuse shows elevated latency
- [ ] Some pod restarts (but pods now stable)
- [ ] Sentry has P2/P3 issues

### RED - Not Ready

Any critical failure:

- [ ] Production API down
- [ ] LLM not responding
- [ ] Kubernetes pods in CrashLoopBackOff
- [ ] GitHub API inaccessible
- [ ] Sentry has P0 issues

## Automated Alerts

VibeTeam monitors itself using the ReleaseEngineer role:

```python
from vibeteam.roles import ReleaseEngineer

engineer = ReleaseEngineer()

# Run health check
health = await engineer.check_health()

# Monitor Sentry
sentry_report = await engineer.monitor_sentry()

# Monitor Langfuse
langfuse_report = await engineer.monitor_langfuse()
```

## Troubleshooting

### Pod CrashLoopBackOff

```bash
# Get pod events
kubectl describe pod -n vibe <pod-name>

# Check logs
kubectl logs -n vibe <pod-name> --previous

# Common causes:
# - Missing env vars/secrets
# - Database connection failed
# - Out of memory
```

### High Latency

1. Check Langfuse for slow traces
2. Check k8s resource usage: `kubectl top pods -n vibe`
3. Check Azure OpenAI rate limits
4. Check database connections

### LLM Errors

1. Verify Azure deployment exists: `az cognitiveservices account deployment list`
2. Check API key validity
3. Check rate limits in Azure portal
4. Verify model name format (`gpt-5-2` not `gpt-5.2`)

### GitHub API Errors

1. Verify `GITHUB_TOKEN` is set and valid
2. Check token permissions (issues, PRs)
3. Verify rate limits: `gh api /rate_limit`

## Environment Variables

Required for full readiness:

```bash
# Azure OpenAI
AZURE_API_KEY=
AZURE_API_BASE=https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/
AZURE_API_VERSION=2024-08-01-preview

# GitHub
GITHUB_TOKEN=

# Sentry (optional but recommended)
SENTRY_AUTH_TOKEN=

# Langfuse (optional but recommended)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://langfuse.vibebrowser.app
```

## Scheduled Checks

For production reliability, run readiness checks:

| Frequency | Check |
|-----------|-------|
| Every 5 min | Health endpoints |
| Every 15 min | Kubernetes pod status |
| Every 1 hour | Sentry issues, Langfuse anomalies |
| Daily | Full readiness report |

Example cron:

```bash
# Every 5 minutes - quick health check
*/5 * * * * cd /path/to/VibeTeam && source .env && python scripts/check_readiness.py --quick

# Hourly - full check
0 * * * * cd /path/to/VibeTeam && source .env && python scripts/check_readiness.py --full
```
