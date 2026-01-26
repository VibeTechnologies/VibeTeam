# Slack App Setup Guide

This guide explains how to create and configure the Slack app for VibeTeam's `@vibeteam` bot.

## Overview

The `@vibeteam` Slack bot allows team members to interact with AI agents directly from Slack. When mentioned, the bot:

1. Receives the message via Slack Events API
2. Processes the request using OpenHands/VibeTeam agents
3. Responds in the same channel/thread

---

## Prerequisites

- Slack workspace admin access
- VibeTeam deployed to Kubernetes (for webhook endpoint)
- Azure OpenAI credentials configured

---

## Step 1: Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. Enter app details:
   - **App Name:** `VibeTeam`
   - **Workspace:** Select your workspace
5. Click **"Create App"**

---

## Step 2: Configure Bot User

1. In the left sidebar, click **"OAuth & Permissions"**
2. Scroll to **"Scopes"** section
3. Under **"Bot Token Scopes"**, add these scopes:
   - `app_mentions:read` - Read messages that mention the bot
   - `chat:write` - Send messages
   - `channels:history` - Read channel messages (for context)
   - `groups:history` - Read private channel messages
   - `im:history` - Read DM history
   - `im:read` - Read DM metadata
   - `im:write` - Send DMs
   - `users:read` - Get user info

---

## Step 3: Enable Event Subscriptions

1. In the left sidebar, click **"Event Subscriptions"**
2. Toggle **"Enable Events"** to ON
3. Enter your **Request URL:**
   ```
   https://webhook.team.vibebrowser.app/slack/events
   ```
   (Slack will verify this endpoint immediately)
4. Under **"Subscribe to bot events"**, add:
   - `app_mention` - When someone @mentions the bot
   - `message.im` - Direct messages to the bot
5. Click **"Save Changes"**

---

## Step 4: Install App to Workspace

1. In the left sidebar, click **"Install App"**
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. After installation, copy the **"Bot User OAuth Token"**
   - Format: `xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx`

---

## Step 5: Get Signing Secret

1. In the left sidebar, click **"Basic Information"**
2. Scroll to **"App Credentials"**
3. Copy the **"Signing Secret"**
   - This is used to verify requests come from Slack

---

## Step 6: Configure Secrets

### Local Development

Create `.secrets/slack.json`:

```json
{
  "SLACK_BOT_TOKEN": "xoxb-your-token-here",
  "SLACK_SIGNING_SECRET": "your-signing-secret",
  "SLACK_APP_ID": "A0XXXXXXXXX",
  "SLACK_WORKSPACE_ID": "T0XXXXXXXXX",
  "CLIENT_ID": "1234567890.1234567890",
  "CLIENT_SECRET": "your-client-secret",
  "VERIFICATION_TOKEN": "your-verification-token"
}
```

Add to `.env`:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_SIGNING_SECRET=your-signing-secret
```

### Kubernetes Deployment

Create the secret:

```bash
kubectl create secret generic slack-bot-secrets \
  --from-literal=SLACK_BOT_TOKEN=xoxb-your-token-here \
  --from-literal=SLACK_SIGNING_SECRET=your-signing-secret \
  -n vibeteam
```

Or from the JSON file:

```bash
kubectl create secret generic slack-bot-secrets \
  --from-file=slack.json=.secrets/slack.json \
  -n vibeteam
```

### GitHub Actions

Add these secrets to your repository:

1. Go to **Settings > Secrets and variables > Actions**
2. Add:
   - `SLACK_BOT_TOKEN` - The `xoxb-...` token
   - `SLACK_SIGNING_SECRET` - The signing secret

---

## Step 7: Invite Bot to Channels

In Slack, invite the bot to channels where it should respond:

```
/invite @vibeteam
```

Or add the bot via channel settings:
1. Open channel settings
2. Go to **"Integrations"** tab
3. Click **"Add apps"**
4. Select **"VibeTeam"**

---

## Step 8: Test the Integration

Send a test message in a channel where the bot is present:

```
@vibeteam Hello! Can you confirm you're working?
```

Expected behavior:
1. Bot acknowledges the message (typing indicator)
2. Processes the request (may take 10-60 seconds)
3. Replies in the same thread

---

## Webhook Server Architecture

The Slack webhook server runs as a Kubernetes deployment:

```yaml
# k8s/base/slack-webhook-bot.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: slack-webhook-bot
  namespace: vibeteam
spec:
  replicas: 1
  selector:
    matchLabels:
      app: slack-webhook-bot
  template:
    spec:
      containers:
        - name: webhook
          image: ghcr.io/vibetechnologies/vibeteam:latest
          command: ["python", "-m", "vibeteam.webhook.server"]
          envFrom:
            - secretRef:
                name: vibeteam-secrets
            - secretRef:
                name: slack-bot-secrets
          ports:
            - containerPort: 8080
```

---

## Troubleshooting

### Bot Not Responding

1. **Check bot is in channel:**
   ```
   /invite @vibeteam
   ```

2. **Check webhook server logs:**
   ```bash
   kubectl logs -n vibeteam -l app=slack-webhook-bot --tail=50
   ```

3. **Verify token is valid:**
   ```bash
   curl -s -X POST "https://slack.com/api/auth.test" \
     -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
     | jq
   ```

### Request URL Verification Failed

1. Ensure webhook server is deployed and accessible
2. Check ingress configuration
3. Verify SSL certificate is valid
4. Check server responds to challenge:
   ```bash
   curl -X POST https://team.vibebrowser.app/slack/events \
     -H "Content-Type: application/json" \
     -d '{"type":"url_verification","challenge":"test123"}'
   ```
   Should return: `{"challenge":"test123"}`

### Signature Verification Failed

1. Verify `SLACK_SIGNING_SECRET` matches app settings
2. Check server time is synchronized (NTP)
3. Ensure request body is not modified by proxies

### Rate Limiting

Slack has rate limits. If you see 429 errors:

1. Implement exponential backoff
2. Use message queuing for high-volume channels
3. Consider using Slack's Web API for bulk operations

---

## Security Best Practices

1. **Never commit tokens** - Use secrets management
2. **Rotate tokens regularly** - Regenerate in app settings if compromised
3. **Verify signatures** - Always validate `X-Slack-Signature` header
4. **Limit scopes** - Only request permissions you need
5. **Monitor usage** - Check Slack app analytics for anomalies

---

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/slack/events` | POST | Receives Slack events |
| `/slack/interactivity` | POST | Handles button clicks, etc. |
| `/slack/commands` | POST | Slash command handler |

### Event Types Handled

| Event | Description |
|-------|-------------|
| `app_mention` | User @mentions the bot |
| `message.im` | Direct message to bot |
| `url_verification` | Slack URL verification challenge |

---

## Related Documentation

- [OpenHands Integration Guide](openhands-integration.md)
- [Team Readiness Requirements](team-readiness-requirements.md)
- [Slack API Documentation](https://api.slack.com/docs)
