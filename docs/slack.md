# Slack Integration Setup

This guide covers how to configure the Slack app for VibeTeam, including event subscriptions, OAuth scopes, and the gateway routing logic.

## Prerequisites

- A Slack workspace where you have admin permissions
- The VibeTeam gateway deployed and reachable via HTTPS (e.g. `https://webhook.team.vibebrowser.app`)

## 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Choose **From a manifest** and paste the contents of [`templates/slack-app/manifest.yaml`](../templates/slack-app/manifest.yaml)
3. Update the `request_url` values to point to your gateway's public URL

Alternatively, create the app manually following the sections below.

## 2. OAuth Scopes

Under **OAuth & Permissions**, add these **Bot Token Scopes**:

| Scope | Required For |
|-------|-------------|
| `app_mentions:read` | Receiving `@VibeTeam` mentions |
| `channels:history` | Reading messages in public channels (needed for `message.channels` event + `conversations.replies` API for thread participation check) |
| `channels:read` | Listing public channels |
| `chat:write` | Posting agent responses |
| `groups:history` | Reading messages in private channels (needed for `message.groups` event) |
| `groups:read` | Listing private channels |
| `im:history` | Reading direct messages |
| `im:read` | Listing DM conversations |
| `im:write` | Sending DMs to users |
| `users:read` | Resolving user IDs to display names |

After adding scopes, install or reinstall the app to the workspace to generate the bot token.

## 3. Event Subscriptions

Under **Event Subscriptions**, enable events and set the request URL to:

```
https://<your-gateway-host>/slack/events
```

Slack will send a verification challenge to this URL. The gateway responds to it automatically.

Subscribe to these **bot events**:

| Event | Purpose |
|-------|---------|
| `app_mention` | Triggers when a user mentions `@VibeTeam` in a channel. This is the primary entry point for agent interactions. |
| `message.channels` | Delivers all messages in public channels the bot is in. Required for thread follow-ups -- without this, the gateway cannot receive thread replies that don't explicitly `@VibeTeam`. |
| `message.groups` | Same as above but for private channels. |
| `message.im` | Delivers direct messages to the bot. |

### Why `message.channels` is required

When a user starts a conversation with `@VibeTeam @SupportEngineer please investigate X`, Slack delivers this as an `app_mention` event. The agent responds in the thread.

For follow-up messages like `@SupportEngineer what did you find?`, the user does **not** re-mention `@VibeTeam`. `@SupportEngineer` is just plain text to Slack (not a real Slack user). Without `message.channels` subscribed, Slack will **not deliver** these thread replies to the gateway at all.

With `message.channels` enabled, the gateway receives all channel messages and uses the thread participation handler to detect whether the bot previously replied in the thread. If it did, the message is routed to the appropriate agent.

## 4. Interactivity (Optional)

If you want interactive components (buttons, modals), enable interactivity and set the request URL to:

```
https://<your-gateway-host>/slack/interactive
```

## 5. Environment Variables

The gateway requires these environment variables for Slack integration:

| Variable | Description | Where to find |
|----------|-------------|---------------|
| `SLACK_BOT_TOKEN` | Bot user OAuth token (`xoxb-...`) | **OAuth & Permissions** page after installing the app |
| `SLACK_SIGNING_SECRET` | Used to verify incoming Slack requests | **Basic Information** > **App Credentials** |
| `SLACK_TRIGGER_SECRET` | Bearer token for the `/slack/trigger` endpoint (used by eval tests and manual triggering) | Self-generated; set in both `.env` and K8s secrets |

For Kubernetes deployments, these are stored in the `vibeteam-secrets` secret:

```bash
kubectl create secret generic vibeteam-secrets -n vibeteam \
  --from-literal=SLACK_BOT_TOKEN="xoxb-..." \
  --from-literal=SLACK_SIGNING_SECRET="..." \
  --from-literal=SLACK_TRIGGER_SECRET="..." \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 6. Invite the Bot

After installing the app, invite the bot to channels where you want it to operate:

```
/invite @VibeTeam
```

The bot must be a member of a channel to receive `message.channels` events from it.

## Message Routing Flow

```
User posts in Slack channel
        |
        v
  Slack delivers event to gateway (/slack/events)
        |
        v
  +----- Is it an app_mention? (@VibeTeam mentioned)
  |  YES: Strip bot mention, parse @RoleName, route to agent
  |
  +----- Is it a DM to the bot?
  |  YES: Route to agent (keyword-based role selection)
  |
  +----- Is it a thread reply? (thread_ts present)
  |  YES: Check if bot participated in thread
  |  |      - Fast path: in-memory subscriptions
  |  |      - Slow path: conversations.replies API
  |  |
  |  +-- Bot participated? Route to agent
  |  +-- Bot not in thread? Ignore
  |
  +----- Is it a bot message with @RoleName?
  |  YES: Process as handoff between agents
  |
  +----- None of the above
       IGNORE
```

## Applying Manifest Changes

The canonical Slack app manifest lives at `templates/slack-app/manifest.yaml`. After modifying it, apply to the Slack app:

```bash
# Via Slack CLI
slack manifest update --app-id A0AAZGWEAVA --manifest templates/slack-app/manifest.yaml

# Or manually at:
# https://api.slack.com/apps/A0AAZGWEAVA/app-manifest
```

Changes to event subscriptions or OAuth scopes require **reinstalling the app** to the workspace to take effect.

## Troubleshooting

### Thread replies are ignored

**Symptom:** Agent responds to the initial `@VibeTeam` message but ignores follow-up messages in the thread.

**Cause:** The Slack app is not subscribed to `message.channels` events. Without it, Slack only delivers `app_mention` events (which require explicitly mentioning `@VibeTeam`).

**Fix:** Add `message.channels` (and `message.groups` for private channels) to the app's event subscriptions. See [Section 3](#3-event-subscriptions).

### Gateway receives events but returns "ignored"

**Symptom:** Gateway logs show `Received Slack event: message` but the message is not processed.

**Cause:** The message doesn't match any handler. Check the log for `subtype`, `thread_ts`, and `channel_type` to understand why.

Common reasons:
- Message is not in a thread (`thread_ts` is missing) and doesn't mention `@VibeTeam`
- Message is from a bot (`bot_id` present) without a `@RoleName` mention
- Message is in a channel the bot hasn't participated in before

### Bot doesn't react with eyes emoji

**Symptom:** No `:eyes:` reaction appears on the message.

**Cause:** `SLACK_BOT_TOKEN` is not set or the bot is not a member of the channel.

### "Invalid signature" errors

**Symptom:** Gateway returns 401 for Slack events.

**Cause:** `SLACK_SIGNING_SECRET` doesn't match the app's signing secret. Check **Basic Information** > **App Credentials** in the Slack app settings.
