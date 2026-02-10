# Webhook Routing Guide

This guide explains how VibeTeam's webhook system routes external events to the appropriate agents.

## Architecture Overview

```
External Events (GitHub, Sentry, Slack)
            ↓
    Gateway Server (port 8080)
            ↓
    Route based on event type
            ↓
    ┌─────────┬──────────┬──────────┐
    │         │          │          │
 GitHub    Sentry    Slack      API
 Router    Router    Router     Router
    │         │          │          │
    └─────────┴──────────┴──────────┘
                    ↓
            Agent Microservices
         (OpenHands, AutoGen, CrewAI)
```

## Webhook Endpoints

### 1. GitHub Webhook: `/webhook`

**Events Handled:**
- `issues.assigned` → Triggers Software Engineer agent
- `issue_comment.created` → Responds to @mentions or /RoleName commands
- `pull_request_review_comment.created` → Responds to PR review comments

**Authentication:**
- Webhook signature verification (HMAC-SHA256)
- GitHub App installation tokens for API calls

**Example Webhook Configuration:**
```
URL: https://your-domain.com/webhook
Content type: application/json
Secret: <your-webhook-secret>
Events: Issues, Issue comments, Pull requests
```

**Flow:**
```
Issue assigned to bot
    ↓
Verify webhook signature
    ↓
Check if assignee is our bot
    ↓
Post acknowledgment comment (using GitHub App token)
    ↓
Build task context (issue title, body, number)
    ↓
Call agent service (role: software_engineer)
    ↓
Agent creates PR with fix
```

### 2. Sentry Webhook: `/webhook/sentry`

**Events Handled:**
- `issue.created` → Routes to Release Engineer agent

**Pre-filtering:**
Sentry issues are pre-classified before sending to agents:
- **NOISE**: Common client-side errors, extension errors → Ignored
- **VALID_BUG**: TypeErrors, ReferenceErrors, high-impact issues → Routed to agent
- **NEEDS_INVESTIGATION**: Unclear issues with moderate impact → Routed to agent

**Classification Logic:**
```python
# Noise patterns (skipped)
- Failed to fetch, NetworkError, net::ERR_
- ResizeObserver loop, Script error
- Third-party extension errors (non-VibeTeam)

# Bug patterns (routed to agent)
- TypeError, ReferenceError, Cannot read property
- Unhandled Promise rejections
- High event count (50+) or user impact (10+)

# Low-impact unknown issues
- < 5 events and < 3 users → Noise
```

**Flow:**
```
Sentry webhook received
    ↓
Verify signature (HMAC-SHA256)
    ↓
Classify issue (NOISE/VALID_BUG/NEEDS_INVESTIGATION)
    ↓
Skip if NOISE
    ↓
Build task context (issue title, trace, metadata)
    ↓
Call Release Engineer agent
    ↓
Agent investigates logs, creates GitHub issue if needed
```

### 3. Slack Webhook: `/slack/events`

**Events Handled:**
- `app_mention` → @VibeTeam in channels
- `message.im` → Direct messages to bot

**Authentication:**
- Request signature verification (HMAC-SHA256)
- Timestamp validation (5-minute window for replay protection)

**Flow:**
```
Slack event received
    ↓
Verify signature and timestamp
    ↓
Ignore bot's own messages (prevent loops)
    ↓
Parse /RoleName mentions
    ↓
Route to appropriate agent(s)
    ↓
Send acknowledgment to Slack
    ↓
Agent processes request
    ↓
Post result to Slack thread
```

## Agent Routing Logic

### Role-Based Routing

The system supports routing based on role mentions:

```
/SoftwareEngineer  → software_engineer role → Code fixes, PR creation
/ReleaseEngineer   → release_engineer role  → Deployment, infrastructure
/SupportEngineer   → support_engineer role  → Customer issues, Gmail
/ProductManager    → product_manager role   → Requirements, roadmap
/MarketingManager  → marketing_manager role → Documentation, announcements
```

**Example Comment:**
```
This needs a code fix and deployment.
/SoftwareEngineer /ReleaseEngineer
```

Results in:
1. Software Engineer agent creates PR with fix
2. Release Engineer agent deploys the change

### Context Injection

Agents automatically receive relevant context based on the event source:

#### GitHub Context
```python
{
    "repo": "VibeTechnologies/VibeTeam",
    "issue_number": 123,
    "issue_title": "Bug: Authentication fails",
    "issue_body": "When trying to login...",
    "context_type": "github_issue",
    "context_id": "VibeTechnologies/VibeTeam:123"
}
```

#### Sentry Context
```python
{
    "issue_id": "VIBETEAM-123",
    "title": "TypeError: Cannot read property 'user' of undefined",
    "classification": "VALID_BUG",
    "count": 150,
    "user_count": 45,
    "first_seen": "2024-02-10T00:00:00Z",
    "last_seen": "2024-02-10T03:00:00Z",
    "context_type": "sentry_issue",
    "context_id": "VIBETEAM-123"
}
```

## Environment Variables

### Required for Webhooks

```bash
# GitHub
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_BOT_USERNAME=vibeteam-bot[bot]
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
GITHUB_APP_INSTALLATION_ID=12345678

# Sentry
SENTRY_CLIENT_SECRET=your_sentry_secret

# Slack
SLACK_SIGNING_SECRET=your_slack_signing_secret
SLACK_BOT_TOKEN=xoxb-your-token

# Agent Services
OPENHANDS_SERVICE_URL=http://openhands-svc:8080
AUTOGEN_SERVICE_URL=http://autogen-svc:8080
CREWAI_SERVICE_URL=http://crewai-svc:8080
DEFAULT_FRAMEWORK=openhands
```

## Testing Webhooks

### Test GitHub Webhook

```bash
# Generate signature
SECRET="your_webhook_secret"
PAYLOAD='{"action":"assigned","issue":{"number":1,"title":"Test","body":"Description"},"assignee":{"login":"vibeteam-bot[bot]"},"repository":{"full_name":"VibeTechnologies/VibeTeam"}}'
SIGNATURE="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"

# Send webhook
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: $SIGNATURE" \
  -d "$PAYLOAD"
```

### Test Sentry Webhook

```bash
SECRET="your_sentry_secret"
PAYLOAD='{"action":"created","data":{"issue":{"id":"123","title":"TypeError","count":50,"userCount":10}}}'
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)

curl -X POST http://localhost:8080/webhook/sentry \
  -H "Content-Type: application/json" \
  -H "Sentry-Hook-Signature: $SIGNATURE" \
  -d "$PAYLOAD"
```

### Monitor Webhook Logs

```bash
# Local development
python -m vibeteam.gateway.server

# Kubernetes
kubectl logs -f deployment/vibeteam-gateway -n vibeteam

# Check for specific events
kubectl logs deployment/vibeteam-gateway -n vibeteam | grep "Received.*issues.assigned"
kubectl logs deployment/vibeteam-gateway -n vibeteam | grep "Sentry webhook"
```

## Troubleshooting

### Webhook Not Received

1. **Check public accessibility**: Ensure your webhook URL is publicly accessible
   ```bash
   curl https://your-domain.com/health
   ```

2. **Check GitHub webhook delivery**:
   - Go to GitHub App settings → Advanced → Recent Deliveries
   - Look for failed deliveries and error messages

3. **Check firewall rules**: Ensure port 8080 is open

### Signature Verification Fails

1. **Check secret matches**: Verify webhook secret in both GitHub and your env vars
2. **Check payload encoding**: Ensure no trailing newlines or modifications
3. **Check logs**:
   ```bash
   kubectl logs deployment/vibeteam-gateway -n vibeteam | grep "Invalid.*signature"
   ```

### Agent Not Triggered

1. **Check bot username**: Verify `GITHUB_BOT_USERNAME` matches your GitHub App
2. **Check assignment**: Issue must be assigned to the bot user
3. **Check agent service health**:
   ```bash
   curl http://localhost:8080/health
   ```

### Token Issues

1. **Check token generation**:
   ```python
   from vibeteam.utils.github_app import get_installation_token
   token = get_installation_token(app_id, private_key, installation_id)
   print(token)  # Should start with "ghs_"
   ```

2. **Check token permissions**: Verify GitHub App has required permissions

3. **Check token expiry**: Tokens expire after 1 hour (automatic refresh)

## Performance Considerations

### Webhook Processing

- Webhook handlers return immediately (200 OK)
- Actual agent work happens asynchronously in background tasks
- This prevents webhook timeouts (GitHub retries after 10 seconds)

### Rate Limiting

- GitHub App: 5,000 requests/hour
- PAT: 1,000 requests/hour
- Tokens automatically refresh before expiry

### Scaling

- Gateway is stateless and can be scaled horizontally
- Agent microservices can be scaled independently
- Use connection pooling for agent service calls

## Security Best Practices

1. **Always verify webhook signatures**: Never process unverified webhooks
2. **Use HTTPS**: Encrypt webhook traffic
3. **Rotate secrets regularly**: Change webhook secrets periodically
4. **Monitor for replay attacks**: Check timestamp on Slack webhooks
5. **Limit IP ranges**: Restrict webhook access to known IPs (GitHub, Sentry, Slack)
6. **Log suspicious activity**: Monitor for signature failures and unusual patterns

## References

- [GitHub Webhook Documentation](https://docs.github.com/en/developers/webhooks-and-events/webhooks/about-webhooks)
- [Sentry Webhook Documentation](https://docs.sentry.io/product/integrations/integration-platform/webhooks/)
- [Slack Events API](https://api.slack.com/apis/connections/events-api)
