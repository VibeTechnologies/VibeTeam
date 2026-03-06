# Webhook Routing Guide

This guide summarizes how external events reach agents. For the canonical routing model and data flow, see [design.md](design.md).

## Endpoints

| Endpoint | Source | Notes |
|----------|--------|-------|
| `/webhook` | GitHub | Issues and PR comments route to SoftwareEngineer by default; role mentions trigger handoffs. |
| `/webhook/sentry` | Sentry | Routes to SupportEngineer (handoff as needed). |
| `/slack/events` | Slack | `@VibeTeam` activates a thread; thread replies are auto-routed. See [slack.md](slack.md). |
| `/slack/trigger` | Slack (eval/tests) | Requires `Authorization: Bearer $SLACK_TRIGGER_SECRET`. |

## Routing Rules (Short)

- Role mentions are parsed via `agent_service/shared/role_resolver.py` and accept `@RoleName` or `/RoleName`.
- Subscribed agents receive all subsequent messages in the thread.
- Bot messages are processed to detect handoff mentions.

## Authentication

- GitHub: HMAC signature verification (required; unsigned webhooks are rejected).
- Sentry: HMAC signature verification.
- Slack: request signature + timestamp validation (required).

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

## Response Flow

When a message is routed to an agent:

1. Gateway adds a `:eyes:` reaction to mark the message as read.
2. Gateway adds a `:thinking_face:` reaction and (if available) sets an assistant thread status.
3. Gateway classifies the message into a **task template** (`investigation`, `feature_request`, or `conversational`) — see [design.md](design.md#task-template-classification).
4. Agent processes the request.
5. Gateway clears the assistant status, removes `:thinking_face:`, and posts the response as new message(s).

Thread follow-ups without investigation keywords get the lightweight `conversational` template so agents respond naturally instead of generating rigid investigation reports.

## Related Docs

- [design.md](design.md)
- [requirements.md](requirements.md)
- [slack.md](slack.md) - Slack app setup, event subscriptions, and troubleshooting
