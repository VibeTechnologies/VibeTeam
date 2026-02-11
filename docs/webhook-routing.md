# Webhook Routing Guide

This guide summarizes how external events reach agents. For the canonical routing model and data flow, see [design.md](design.md).

## Endpoints

| Endpoint | Source | Notes |
|----------|--------|-------|
| `/webhook` | GitHub | Issues and PR comments route to SoftwareEngineer by default; role mentions trigger handoffs. |
| `/webhook/sentry` | Sentry | Routes to SupportEngineer (handoff as needed). |
| `/slack/events` | Slack | `@VibeTeam` activates a thread; `@RoleName` or `/RoleName` subscribes agents. |
| `/slack/trigger` | Slack (eval/tests) | Requires `Authorization: Bearer $SLACK_TRIGGER_SECRET`. |

## Routing Rules (Short)

- Role mentions are parsed via `agents/shared/role_resolver.py` and accept `@RoleName` or `/RoleName`.
- Subscribed agents receive all subsequent messages in the thread.
- Bot messages are processed to detect handoff mentions.

## Authentication

- GitHub: HMAC signature verification.
- Sentry: HMAC signature verification.
- Slack: request signature + timestamp validation.

## Required Environment Variables

```bash
GITHUB_WEBHOOK_SECRET=
SENTRY_CLIENT_SECRET=
SLACK_SIGNING_SECRET=
SLACK_BOT_TOKEN=
SLACK_TRIGGER_SECRET=
CALLBACK_SECRET=
DEFAULT_FRAMEWORK=openhands
```

## Related Docs

- [design.md](design.md)
- [requirements.md](requirements.md)