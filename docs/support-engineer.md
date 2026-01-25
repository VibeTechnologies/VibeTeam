# Support Engineer Agent

Processes customer support emails from the docs.vibebrowser.app chat widget.

## Email Flow

```
User clicks "Talk to Human" in docs chat
        ↓
Azure Communication Services sends email
        ↓
support@vibebrowser.app (Cloudflare)
        ↓
dzianisvv+vibe@gmail.com (forwarding)
        ↓
Support Engineer CronJob (every 15 min)
        ↓
AI analyzes → Responds or Escalates
```

## Email Format

Emails from the docs chat widget have this subject format:

```
[Docs Support #TICKETID] New request from user@email.com
```

Example: `[Docs Support #M5K2X-A3B1] New request from john@example.com`

The support-engineer only processes emails matching this pattern. Other emails (npm notifications, security alerts, etc.) are ignored.

## CronJob

```yaml
schedule: "*/15 * * * *"  # Every 15 minutes
command: vibeteam scheduled support-emails --max-emails 20
```

## Secrets Required

| Secret | Description |
|--------|-------------|
| `gmail-oauth-secrets` | Gmail OAuth credentials (credentials.json, token.json) |
| `GITHUB_TOKEN` | For creating escalation issues |

## Outcomes

1. **Auto-response**: AI generates and sends response directly
2. **Escalation**: Creates GitHub issue, sends acknowledgment email
3. **Skip**: Email doesn't match pattern, ignored

## Testing

To test manually:

```bash
# Send test email to support@vibebrowser.app with subject:
# [Docs Support #TEST-001] Test from test@example.com

# Then trigger the job:
kubectl create job --from=cronjob/support-engineer test-support -n vibeteam
kubectl logs -n vibeteam -l job-name=test-support -f
```

## Source

- Docs escalation API: `services/docusarus/docusaurus-azure-chat/api/escalate/index.js`
- Email forwarding: `services/configureCloudflareEmailForwarding.sh`
- Support agent: `vibeteam/agents/support_engineer.py`
