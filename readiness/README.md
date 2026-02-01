# VibeTeam Readiness

Use the GenAI playbook to verify system readiness before running VibeTeam agents.

## Usage

AI agent reads and executes the playbook:

```bash
cat readiness/playbook.md
```

The playbook provides:
- Commands to execute
- Expected results
- Evaluation criteria
- Judgment guidelines for ambiguous cases
- Report template

## When to Use

| Scenario | Action |
|----------|--------|
| Incident investigation | Follow playbook (AI interprets context) |
| First-time setup validation | Follow playbook (detailed reasoning) |
| Explaining issues to humans | Follow playbook (produces readable report) |
| Pre-deployment verification | Follow playbook |

## Files

| File | Purpose |
|------|---------|
| `playbook.md` | GenAI evaluation playbook |
| `README.md` | This file |

## What Gets Checked

| Check | Critical | Notes |
|-------|----------|-------|
| vibeteam namespace pods | Yes | Gateway, Agent Services, Slack agents |
| Postgres database | Yes | Session storage |
| LLM (Azure OpenAI) | Yes | Core agent functionality |
| Slack/Discord connectivity | Yes | Message routing |
| GitHub API | Yes | Issue/PR operations |
| Sentry | No | Error monitoring |
| Langfuse | No | LLM observability |

## Environment Variables

Required:
```bash
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview
GITHUB_TOKEN=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
```

Optional:
```bash
DISCORD_BOT_TOKEN=
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```
