# VibeTeam Readiness

Use the OpenCode skill or the playbook to verify system readiness.

## OpenCode Skill (Recommended)

The readiness checks are available as an OpenCode skill that AI agents can invoke:

```
/skill vibeteam-readiness
```

This provides intelligent evaluation with:
- All infrastructure health checks
- Integration verification (Slack, GitHub, Gmail, Sentry, Langfuse)
- Kubernetes agent status
- GREEN/YELLOW/RED assessment with reasoning

## Manual Playbook

For detailed investigation or when you need to run checks manually:

```bash
cat readiness/playbook.md
```

The playbook provides:
- Commands to execute
- Expected results
- Evaluation criteria
- Judgment guidelines for ambiguous cases
- Report template

## Quick Manual Checks

```bash
# Load environment
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a

# Check infrastructure endpoints
curl -s -o /dev/null -w "%{http_code}" https://api.vibebrowser.app/health
curl -s -o /dev/null -w "%{http_code}" https://portal.vibebrowser.app

# Check Slack auth
curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" | jq '.ok'

# Check GitHub
gh api /rate_limit --jq '.rate.remaining'

# Check LLM
curl -s -X POST "${AZURE_API_BASE}openai/deployments/gpt-4.1-mini/chat/completions?api-version=2024-08-01-preview" \
  -H "api-key: ${AZURE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say OK"}],"max_tokens":10}' | jq -r '.choices[0].message.content'
```

## Files

| File | Purpose |
|------|---------|
| `playbook.md` | Detailed GenAI evaluation playbook |
| `README.md` | This file |

## OpenCode Skill Location

The skill is defined at:
```
.opencode/skills/vibeteam-readiness/SKILL.md
```

## Environment Variables

Required:
```bash
AZURE_API_KEY=           # or AZURE_OPENAI_API_KEY
AZURE_API_BASE=          # or AZURE_OPENAI_ENDPOINT
GITHUB_TOKEN=
SLACK_BOT_TOKEN=
```

Optional:
```bash
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
SLACK_SIGNING_SECRET=
```
