# Slack App Setup Guide

This guide walks through creating and configuring the Slack App for VibeTeam's `@vibeteam` bot.

## Prerequisites

- Slack workspace admin access
- VibeTeam webhook server deployed at `webhook.team.vibebrowser.app`
- Access to GitHub repository secrets

---

## Step 1: Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App**
3. Select **From scratch**
4. Configure:
   - **App Name**: `VibeTeam`
   - **Workspace**: Select your workspace
5. Click **Create App**

---

## Step 2: Configure OAuth & Permissions

Navigate to **OAuth & Permissions** in the sidebar.

### Bot Token Scopes

Add the following scopes under **Scopes > Bot Token Scopes**:

| Scope | Purpose |
|-------|---------|
| `app_mentions:read` | Receive @vibeteam mentions |
| `chat:write` | Send messages as the bot |
| `im:history` | Read direct message history |
| `im:read` | View basic DM info |
| `im:write` | Start DM conversations |
| `users:read` | Get user info for context |

### Install to Workspace

1. Scroll to **OAuth Tokens for Your Workspace**
2. Click **Install to Workspace**
3. Review permissions and click **Allow**
4. Copy the **Bot User OAuth Token** (`xoxb-...`)

Save this token - you'll need it for `SLACK_BOT_TOKEN`.

---

## Step 3: Configure Event Subscriptions

Navigate to **Event Subscriptions** in the sidebar.

### Enable Events

1. Toggle **Enable Events** to **On**
2. Set **Request URL**: `https://webhook.team.vibebrowser.app/slack/events`
3. Wait for Slack to verify the URL (should show "Verified")

### Subscribe to Bot Events

Add the following events under **Subscribe to bot events**:

| Event | Description |
|-------|-------------|
| `app_mention` | When someone mentions @vibeteam |
| `message.im` | Direct messages to the bot |

Click **Save Changes**.

---

## Step 4: Get Signing Secret

Navigate to **Basic Information** in the sidebar.

1. Scroll to **App Credentials**
2. Copy the **Signing Secret**

Save this - you'll need it for `SLACK_SIGNING_SECRET`.

---

## Step 5: Configure App Home (Optional)

Navigate to **App Home** in the sidebar.

1. Under **Show Tabs**, enable:
   - **Messages Tab**: On
   - **Allow users to send Slash commands and messages**: Checked
2. Edit the **App Display Name** if desired

---

## Step 6: Deploy Secrets

### GitHub Actions Secrets

Add these secrets to your GitHub repository:

```bash
# Using GitHub CLI
gh secret set SLACK_BOT_TOKEN --body "xoxb-your-token-here"
gh secret set SLACK_SIGNING_SECRET --body "your-signing-secret-here"
```

Or via GitHub UI:
1. Go to **Settings > Secrets and variables > Actions**
2. Add `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`

### Kubernetes Secrets

The deploy workflow automatically creates the K8s secret. To manually create:

```bash
kubectl create secret generic vibeteam-secrets \
  --namespace vibeteam \
  --from-literal=SLACK_BOT_TOKEN="xoxb-..." \
  --from-literal=SLACK_SIGNING_SECRET="..." \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## Step 7: Verify Installation

### Test the Bot

1. Invite the bot to a channel: `/invite @vibeteam`
2. Mention the bot: `@vibeteam hello`
3. Check for response

### Check Logs

```bash
# View webhook server logs
kubectl logs -n vibeteam -l app=vibeteam-webhook -f

# Check for Slack events
kubectl logs -n vibeteam -l app=vibeteam-webhook | grep -i slack
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot doesn't respond | Check Event Subscriptions URL is verified |
| "Invalid signature" in logs | Verify `SLACK_SIGNING_SECRET` matches app |
| "SLACK_BOT_TOKEN not set" | Check K8s secret is mounted correctly |
| Bot responds but fails | Check Azure OpenAI credentials |

---

## App Manifest (Alternative Setup)

Instead of manual configuration, you can use this manifest:

```yaml
display_information:
  name: VibeTeam
  description: AI-powered software engineering assistant
  background_color: "#4A154B"
features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: VibeTeam
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - im:history
      - im:read
      - im:write
      - users:read
settings:
  event_subscriptions:
    request_url: https://webhook.team.vibebrowser.app/slack/events
    bot_events:
      - app_mention
      - message.im
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

To use:
1. Go to **App Manifest** in sidebar
2. Paste the YAML above
3. Click **Save Changes**

---

## Security Considerations

1. **Never commit tokens** - Use secrets management
2. **Rotate tokens periodically** - Regenerate in Slack app settings
3. **Limit workspace access** - Only install in required workspaces
4. **Monitor usage** - Check Slack app analytics for unusual activity

---

## Related Documentation

- [OpenHands Integration Guide](openhands-integration.md) - Overall bot usage
- [Slack API Documentation](https://api.slack.com/docs)
- [Slack Events API](https://api.slack.com/events-api)
