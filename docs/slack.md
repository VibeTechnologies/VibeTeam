# Slack Integration Setup

This guide covers how to configure the Slack app for VibeTeam, including event subscriptions, OAuth scopes, and the gateway routing logic.

## Quick Links

- Slack apps dashboard: `https://api.slack.com/apps`
- OAuth & permissions: `https://api.slack.com/apps/<app-id>/oauth`
- App manifest: `https://api.slack.com/apps/<app-id>/app-manifest`

## Prerequisites

- A Slack workspace where you have admin permissions
- The VibeTeam gateway deployed and reachable via HTTPS (e.g. `https://webhook.team.vibebrowser.app`)

## Multi-App and Environment Constraints

Slack Event Subscriptions use one Request URL per app. One app cannot send inbound
events to multiple gateways at once (for example, dev and prod).

Current deployment policy:

- Use one **ingress app** for inbound events to `/slack/events`.
- Use role-specific **responder apps** for outbound identity:
  `SoftwareEngineer`, `SupportEngineer`, `ReleaseEngineer`,
  `ProductManager`, and `MarketingManager`.
- Configure role-scoped tokens in gateway env vars:
  `SLACK_BOT_TOKEN_<ROLE>` and `SLACK_ASSISTANT_TOKEN_<ROLE>`.
- If a role-scoped token is missing, gateway falls back to global
  `SLACK_BOT_TOKEN` / `SLACK_ASSISTANT_TOKEN`.
- Response attribution is by Slack app identity, not text prefixing.
  Gateway responses should be plain text (no legacy `[Role]` message prefix).

## 1. App Inventory (Ingress + Role Apps)

Create **six** Slack apps total for one workspace:

| App Type | Slack Display Name | Purpose | Inbound Events |
|---------|---------------------|---------|----------------|
| Ingress | `VibeTeam` | Receives Slack events and routes work | **Required** (`/slack/events`) |
| Role responder | `SoftwareEngineer` | Posts as SWE role identity | Not required |
| Role responder | `SupportEngineer` | Posts as Support role identity | Not required |
| Role responder | `ReleaseEngineer` | Posts as Release role identity | Not required |
| Role responder | `ProductManager` | Posts as PM role identity | Not required |
| Role responder | `MarketingManager` | Posts as Marketing role identity | Not required |

Use the same role handles as `agents/agents.yaml` (`slack_handle`) so mention parsing and identity mapping stay consistent.

## 2. Create and Configure the Apps

### 2.1 Create the ingress app (`VibeTeam`)

1. Go to [api.slack.com/apps](https://api.slack.com/apps).
2. Create app **From a manifest**.
3. Use [`templates/slack-app/manifest.yaml`](../templates/slack-app/manifest.yaml).
4. Set request URLs to your gateway host (typically `https://webhook.team.vibebrowser.app`).
5. Install/Reinstall the app to workspace after any scope/event change.

If already created, open directly:

```
https://api.slack.com/apps/A0AAZGWEAVA
```

### 2.2 Create the five role responder apps

For each role app (`SoftwareEngineer`, `SupportEngineer`, `ReleaseEngineer`, `ProductManager`, `MarketingManager`):

1. Create app **From scratch**.
2. App name and bot display name: exactly the role handle (for example `SupportEngineer`).
3. Add OAuth bot scopes from the responder scope set in section 3.
4. Keep **Event Subscriptions disabled** (responder apps do not receive inbound webhooks).
5. Install app to workspace and copy:
   - bot token (`xoxb-...`)
   - assistant token (`xapp-...`) if `assistant:write` is enabled
   - signing secret (only needed if you choose to validate with role-specific secrets)
6. Invite each role app to channels where it should post responses.

## 3. OAuth Scopes

### 3.1 Ingress app (`VibeTeam`) scopes

Under **OAuth & Permissions**, configure these **Bot Token Scopes**:

| Scope | Required For |
|-------|-------------|
| `assistant:write` | Assistant thread status (typing indicator) |
| `app_mentions:read` | Receiving `@VibeTeam` mentions |
| `channels:history` | Thread follow-up handling in public channels |
| `channels:read` | Listing/reading public channel metadata |
| `chat:write` | Posting responses |
| `files:read` | Reading attached kubeconfig files for cluster onboarding |
| `groups:history` | Thread follow-up handling in private channels |
| `groups:read` | Listing/reading private channel metadata |
| `im:history` | Reading direct messages |
| `im:read` | Listing DM conversations |
| `im:write` | Sending DMs |
| `reactions:write` | Adding/removing `:eyes:` and `:thinking_face:` reactions |
| `users:read` | Resolving user IDs/mentions |

### 3.2 Role responder app scopes

Use this responder scope baseline:

| Scope | Why |
|-------|-----|
| `assistant:write` | Optional per-role assistant status |
| `chat:write` | Posting role-attributed responses |
| `reactions:write` | Role-attributed reaction lifecycle |
| `channels:history` | Thread participation and replies |
| `groups:history` | Thread participation in private channels |
| `im:history` | DM thread participation checks |
| `users:read` | Mention/user mapping support |

`channels:read`, `groups:read`, `im:read`, and `im:write` are optional unless you need role apps to perform those operations directly.

After scope updates, always **Reinstall to Workspace** so tokens include new permissions.
If `assistant:write` is missing, enable **Agents & AI Apps**, refresh, then reinstall.

### 3.3 Kubeconfig attachment flow requirements

To support non-technical users onboarding a cluster from Slack attachments:

1. Keep `files:read` on the ingress app.
2. Users can upload a kubeconfig file in the same thread as the request.
3. Gateway validates the attachment as kubeconfig YAML and stores it thread-scoped.
4. Gateway rejects unsafe kubeconfigs with `users[].user.exec` plugins.
5. Release/Support requests mentioning cluster health/config in that thread receive
   the validated kubeconfig context automatically.

## 4. Event Subscriptions

Configure inbound events on the **ingress app only**:

1. Enable Event Subscriptions.
2. Request URL:

```
https://<your-gateway-host>/slack/events
```

Slack will send a verification challenge to this URL. The gateway responds automatically.

Subscribe to these ingress bot events:

| Event | Purpose |
|-------|---------|
| `app_mention` | Primary entry point (`@VibeTeam ...`) |
| `message.channels` | Thread follow-ups in public channels |
| `message.groups` | Thread follow-ups in private channels |
| `message.im` | Direct messages to ingress app |

### Why `message.channels` is required

When a user starts a conversation with `@VibeTeam @SupportEngineer please investigate X`, Slack delivers this as an `app_mention` event. The agent responds in the thread.

For follow-up messages like `@SupportEngineer what did you find?`, the user does **not** re-mention `@VibeTeam`. `@SupportEngineer` is just plain text to Slack (not a real Slack user). Without `message.channels` subscribed, Slack will **not deliver** these thread replies to the gateway at all.

With `message.channels` enabled, the gateway receives all channel messages and uses the thread participation handler to detect whether the bot previously replied in the thread. If it did, the message is routed to the appropriate agent.

## 4.1 User-friendly k3s onboarding flow (attachment-based)

Use this flow for users who do not have shell/kubeconfig access in the runtime:

1. In Slack, post in a thread:
   - `@VibeTeam @ReleaseEngineer configure this k3s cluster`
   - attach a kubeconfig file (`.yaml`, `.yml`, `.kubeconfig`, `.config`)
2. Gateway responds with confirmation that the kubeconfig was received and stored.
3. In the same thread, ask:
   - `@ReleaseEngineer investigate vibe cluster health`
4. Gateway injects validated kubeconfig context into the agent task so the agent can
   run `kubectl` against that uploaded cluster config.

If the attachment is invalid, gateway responds with a warning and asks for a valid
kubeconfig YAML.

## 5. Interactivity (Optional)

If you want interactive components (buttons, modals), enable interactivity and set the request URL to:

```
https://<your-gateway-host>/slack/interactive
```

## 6. Environment Variables

The gateway requires these environment variables for Slack integration:

| Variable | Description | Where to find |
|----------|-------------|---------------|
| `SLACK_BOT_TOKEN` | Fallback bot token (`xoxb-...`) when role-scoped token is not configured | **OAuth & Permissions** page |
| `SLACK_ASSISTANT_TOKEN` | Fallback token with `assistant:write` for thread status | **OAuth & Permissions** page |
| `SLACK_BOT_TOKEN_SOFTWARE_ENGINEER` | Bot token for SoftwareEngineer app identity | SoftwareEngineer app OAuth page |
| `SLACK_BOT_TOKEN_SUPPORT_ENGINEER` | Bot token for SupportEngineer app identity | SupportEngineer app OAuth page |
| `SLACK_BOT_TOKEN_RELEASE_ENGINEER` | Bot token for ReleaseEngineer app identity | ReleaseEngineer app OAuth page |
| `SLACK_BOT_TOKEN_PRODUCT_MANAGER` | Bot token for ProductManager app identity | ProductManager app OAuth page |
| `SLACK_BOT_TOKEN_MARKETING_MANAGER` | Bot token for MarketingManager app identity | MarketingManager app OAuth page |
| `SLACK_ASSISTANT_TOKEN_SOFTWARE_ENGINEER` | Optional assistant token for SoftwareEngineer status updates | SoftwareEngineer app OAuth page |
| `SLACK_ASSISTANT_TOKEN_SUPPORT_ENGINEER` | Optional assistant token for SupportEngineer status updates | SupportEngineer app OAuth page |
| `SLACK_ASSISTANT_TOKEN_RELEASE_ENGINEER` | Optional assistant token for ReleaseEngineer status updates | ReleaseEngineer app OAuth page |
| `SLACK_ASSISTANT_TOKEN_PRODUCT_MANAGER` | Optional assistant token for ProductManager status updates | ProductManager app OAuth page |
| `SLACK_ASSISTANT_TOKEN_MARKETING_MANAGER` | Optional assistant token for MarketingManager status updates | MarketingManager app OAuth page |
| `SLACK_ASSISTANT_STATUS_TEXT` | Optional status text (default: `is thinking...`) | Local configuration |
| `SLACK_SIGNING_SECRET` | Used to verify incoming Slack requests | **Basic Information** > **App Credentials** |
| `SLACK_TRIGGER_SECRET` | Required bearer token for the `/slack/trigger` endpoint (used by eval tests and manual triggering) | Self-generated; set in both `.env` and K8s secrets |

For Kubernetes deployments, these are stored in the `vibeteam-secrets` secret:

```bash
kubectl create secret generic vibeteam-secrets -n vibeteam \
  --from-literal=SLACK_BOT_TOKEN="xoxb-fallback-..." \
  --from-literal=SLACK_BOT_TOKEN_SOFTWARE_ENGINEER="xoxb-..." \
  --from-literal=SLACK_BOT_TOKEN_SUPPORT_ENGINEER="xoxb-..." \
  --from-literal=SLACK_BOT_TOKEN_RELEASE_ENGINEER="xoxb-..." \
  --from-literal=SLACK_BOT_TOKEN_PRODUCT_MANAGER="xoxb-..." \
  --from-literal=SLACK_BOT_TOKEN_MARKETING_MANAGER="xoxb-..." \
  --from-literal=SLACK_ASSISTANT_TOKEN_SOFTWARE_ENGINEER="xapp-..." \
  --from-literal=SLACK_ASSISTANT_TOKEN_SUPPORT_ENGINEER="xapp-..." \
  --from-literal=SLACK_ASSISTANT_TOKEN_RELEASE_ENGINEER="xapp-..." \
  --from-literal=SLACK_ASSISTANT_TOKEN_PRODUCT_MANAGER="xapp-..." \
  --from-literal=SLACK_ASSISTANT_TOKEN_MARKETING_MANAGER="xapp-..." \
  --from-literal=SLACK_SIGNING_SECRET="..." \
  --from-literal=SLACK_TRIGGER_SECRET="..." \
  --dry-run=client -o yaml | kubectl apply -f -
```

For GitHub Actions-based deployment, you can store role-scoped Slack credentials as a single
repository secret (`SLACK_ROLE_SECRETS_JSON`) instead of managing many individual secrets.
The deploy workflows flatten that JSON into the `vibeteam-secrets` keys above at deploy time.
Role-scoped key names are derived from `agents/agents.yaml` credential placeholders so the
mapping is maintained in one place.

Use the template at `config/secrets/slack_role_secrets.template.json`, fill in real values
locally, then upload it as a GitHub repository secret:

```bash
cp config/secrets/slack_role_secrets.template.json /tmp/slack_role_secrets.json
# edit /tmp/slack_role_secrets.json
gh secret set SLACK_ROLE_SECRETS_JSON < /tmp/slack_role_secrets.json
```

## 7. Invite the Bot

After installing the apps, invite the ingress bot and all responder bots to channels
where they should post:

```
/invite @VibeTeam
/invite @SoftwareEngineer
/invite @SupportEngineer
/invite @ReleaseEngineer
/invite @ProductManager
/invite @MarketingManager
```

The ingress app must receive channel events. Responder apps must be channel members to
post role-attributed replies.

## Read Marker (👀)

For every Slack message the gateway receives (`app_mention` or `message` events), it adds a `:eyes:` reaction to mark the message as read. This happens even if the message is later ignored for routing (for example, thread replies where the bot never participated).

## Typing Indicator

When a message is routed to an agent, the gateway:

- Adds a `:eyes:` reaction as a read marker (if it has not already been added).
- Adds a `:thinking_face:` reaction immediately.
- Uses role-scoped assistant token when configured; otherwise fallback token.
- If a usable app token has `assistant:write`, sets an assistant thread status
  (e.g. "is thinking...") and clears it when the response is posted.

This avoids noisy "thinking..." messages while still giving real-time feedback.

## Task Template Classification

The gateway classifies incoming messages to select the appropriate task template for agents:

```python
def classify_task_template(role, user_message, is_thread_reply=False) -> str:
    # Returns one of: "investigation", "feature_request", "conversational"
```

| Template | When Used | Description |
|----------|-----------|-------------|
| `investigation` | Initial messages with error/debug/issue keywords | Full structured template with required kubectl/Sentry steps |
| `feature_request` | Messages with feature/implement/build keywords | Template for PRDs and implementation planning |
| `conversational` | Thread follow-ups without investigation keywords | Lightweight prompt — agent responds naturally without rigid structure |

The `conversational` template prevents agents from responding with a rigid 5-section investigation report when the user simply asks a follow-up question like "what did you find?" in a thread. Investigation keywords in thread replies still route to the full investigation template.

## Message Routing Flow

```
User posts in Slack channel
        |
        v
  Slack delivers event to gateway (/slack/events)
        |
        v
  Gateway adds :eyes: reaction to mark the message as read
        |
        v
  +----- Is it an app_mention? (@VibeTeam mentioned)
  |  YES: Strip bot mention, parse @RoleName, route to agent
  |       Add :thinking_face: + assistant status, then submit to agent
  |
  +----- Is it a DM to the bot?
  |  YES: Route to agent (keyword-based role selection)
  |
  +----- Is it a thread reply? (thread_ts present)
  |  YES: Check if bot participated in thread
  |  |      - Fast path: in-memory subscriptions
  |  |      - Slow path: conversations.replies API
  |  |
  |  +-- Bot participated? Classify template (conversational vs investigation)
  |  |   Add :thinking_face: + assistant status, route to agent
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

**Cause:** The role-scoped `SLACK_BOT_TOKEN_<ROLE>` (or fallback `SLACK_BOT_TOKEN`) is
not set, or that role bot is not a member of the channel.

### "Invalid signature" errors

**Symptom:** Gateway returns 401 for Slack events.

**Cause:** `SLACK_SIGNING_SECRET` doesn't match the app's signing secret. Check **Basic Information** > **App Credentials** in the Slack app settings.
