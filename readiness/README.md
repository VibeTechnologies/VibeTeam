# VibeTeam Readiness

Two approaches to verify system readiness before running VibeTeam agents.

## Approach 1: Automated Script

Fast, programmatic checks with exit codes for CI/cron.

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python readiness/check.py           # Standard checks
python readiness/check.py --quick   # Endpoints only (5-min cron)
python readiness/check.py --full    # Everything
python readiness/check.py --json    # Machine-readable output
```

**Exit codes:**
- 0 = GREEN (all systems go)
- 1 = YELLOW (degraded)
- 2 = RED (not ready)

## Approach 2: GenAI Playbook

Intelligent evaluation by an AI agent following a checklist.

```bash
# AI agent reads and executes:
cat readiness/playbook.md
```

The playbook provides:
- Commands to execute
- Expected results
- Evaluation criteria
- Judgment guidelines for ambiguous cases
- Report template

## When to Use Each

| Scenario | Use |
|----------|-----|
| CI/CD pipeline | Script (`--json`) |
| Cron monitoring | Script (`--quick`) |
| Pre-release verification | Script (`--full`) |
| Incident investigation | Playbook (AI interprets context) |
| First-time setup validation | Playbook (detailed reasoning) |
| Explaining issues to humans | Playbook (produces readable report) |

## Files

| File | Purpose |
|------|---------|
| `check.py` | Automated Python script |
| `playbook.md` | GenAI evaluation playbook |
| `README.md` | This file |

## What Gets Checked

| Check | Script | Playbook | Critical |
|-------|--------|----------|----------|
| API Prod | Yes | Yes | Yes |
| API Dev | Yes | Yes | No |
| Portal | Yes | Yes | Yes |
| Docs | Yes | Yes | No |
| Langfuse endpoint | Yes | Yes | No |
| LLM (gpt-4.1) | Yes | Yes | Yes |
| K8s pods | --full | Yes | Yes |
| Sentry issues | --full | Yes | No |
| Langfuse anomalies | --full | Yes | No |
| GitHub API | Yes | Yes | Yes |
| Docs Chat | --full | Yes | No |

## Environment Variables

Required:
```bash
AZURE_API_KEY=
AZURE_API_BASE=https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/
AZURE_API_VERSION=2024-08-01-preview
GITHUB_TOKEN=
```

Optional (for full checks):
```bash
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

## Cron Setup

```bash
# Every 5 minutes - quick health check
*/5 * * * * cd /path/to/VibeTeam && source .env && python readiness/check.py --quick

# Hourly - full check with alert on failure
0 * * * * cd /path/to/VibeTeam && source .env && python readiness/check.py --full || notify-send "VibeTeam Degraded"
```
