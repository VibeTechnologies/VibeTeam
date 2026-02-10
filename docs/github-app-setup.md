# GitHub App Setup Guide

This guide explains how to set up and use GitHub App authentication for VibeTeam.

## Why GitHub App Authentication?

GitHub App authentication is preferred over Personal Access Tokens (PAT) for production deployments:

- **Security**: Short-lived tokens (1 hour) vs long-lived PATs
- **Rate Limits**: 5,000 requests/hour vs 1,000 for PATs
- **Granular Permissions**: Fine-grained repository access
- **Audit Trail**: Better visibility of API usage

## Step 1: Register a GitHub App

1. Go to **GitHub Settings** → **Developer settings** → **GitHub Apps** → **New GitHub App**

2. **Basic Information:**
   - **Name**: `VibeTeam Bot` (or your preferred name)
   - **Homepage URL**: `https://github.com/VibeTechnologies/VibeTeam`
   - **Webhook URL**: `https://your-domain.com/webhook` (or leave blank if not using webhooks yet)
   - **Webhook Secret**: Generate a secure random string (save this)

3. **Permissions** (Repository permissions):
   - **Contents**: Read & Write (for cloning and pushing code)
   - **Issues**: Read & Write (for creating/updating issues)
   - **Pull Requests**: Read & Write (for creating/reviewing PRs)
   - **Metadata**: Read (automatically required)

4. **Subscribe to events** (optional, for webhook support):
   - Issues
   - Issue comments
   - Pull requests
   - Pull request reviews

5. **Where can this GitHub App be installed?**
   - Select "Only on this account" or "Any account" depending on your needs

6. Click **Create GitHub App**

## Step 2: Generate Private Key

1. After creating the app, scroll down to **Private keys** section
2. Click **Generate a private key**
3. Save the downloaded `.pem` file securely
4. Note the **App ID** displayed at the top of the page

## Step 3: Install the App

1. On your GitHub App page, click **Install App** in the left sidebar
2. Select the organization/account where you want to install it
3. Choose:
   - **All repositories** (easier but less secure)
   - **Only select repositories** (recommended for production)
4. Click **Install**
5. Note the **Installation ID** from the URL: `https://github.com/settings/installations/{installation_id}`

## Step 4: Configure VibeTeam

### For Development (`.env` file):

```bash
# GitHub App Configuration
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
...
-----END RSA PRIVATE KEY-----"

# Optional: Keep PAT as fallback
GITHUB_TOKEN=ghp_your_pat_token

# Webhook configuration (if using)
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
```

**Tip**: For the private key, you can either:
1. Inline it with escaped newlines: `"-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"`
2. Reference a file: `GITHUB_APP_PRIVATE_KEY="$(cat path/to/private-key.pem)"`

### For Production (Kubernetes):

#### Option A: Direct Secret (not recommended for production)

```bash
kubectl create secret generic github-app \
  --from-literal=app-id=123456 \
  --from-literal=installation-id=12345678 \
  --from-file=private-key=path/to/private-key.pem \
  -n vibeteam
```

#### Option B: Sealed Secrets (recommended)

```bash
# 1. Create a temporary secret file
cat << EOF > github-app-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-app
  namespace: vibeteam
type: Opaque
stringData:
  app-id: "123456"
  installation-id: "12345678"
  private-key: |
$(cat path/to/private-key.pem | sed 's/^/    /')
EOF

# 2. Seal it with kubeseal
kubeseal --format yaml < github-app-secret.yaml > sealed-github-app-secret.yaml

# 3. Apply the sealed secret
kubectl apply -f sealed-github-app-secret.yaml

# 4. Clean up temporary file
rm github-app-secret.yaml
```

## Step 5: Verify Configuration

### Test Authentication

```python
from vibeteam.connectors.github import GitHubConnector

# Test with GitHub App credentials
connector = GitHubConnector(
    app_id="123456",
    private_key=open("private-key.pem").read(),
    installation_id="12345678"
)

# Or use environment variables
connector = GitHubConnector()  # Reads from GITHUB_APP_* env vars

# Test API call
try:
    issues = connector.search_issues("test", state="open")
    print(f"✓ Successfully authenticated! Found {len(issues)} issues")
except Exception as e:
    print(f"✗ Authentication failed: {e}")
```

### Test Token Generation

```python
from vibeteam.utils.github_app import get_installation_token, get_app_info

app_id = "123456"
private_key = open("private-key.pem").read()
installation_id = "12345678"

# Get app info (verifies App ID and private key)
try:
    info = get_app_info(app_id, private_key)
    print(f"✓ App Name: {info['name']}")
    print(f"✓ App Owner: {info['owner']['login']}")
except Exception as e:
    print(f"✗ Failed to get app info: {e}")

# Get installation token (verifies all three credentials)
try:
    token = get_installation_token(app_id, private_key, installation_id)
    print(f"✓ Generated installation token: {token[:20]}...")
except Exception as e:
    print(f"✗ Failed to generate token: {e}")
```

## Step 6: Webhook Configuration (Optional)

If you're using webhooks for automated issue assignment and comments:

1. **Set up webhook endpoint**: Your server must be publicly accessible
2. **Configure webhook secret**: Set `GITHUB_WEBHOOK_SECRET` env var
3. **Test webhook delivery**:
   - Go to your GitHub App settings → Advanced → Recent Deliveries
   - Click "Redeliver" on a recent webhook
   - Check your server logs for the received payload

### Webhook Testing

```bash
# Start the webhook server locally
python -m vibeteam.gateway.server

# In another terminal, send a test webhook
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"action":"opened"}' | openssl dgst -sha256 -hmac "your_webhook_secret" | cut -d' ' -f2)" \
  -d '{"action":"opened","issue":{"number":1,"title":"Test"},"repository":{"full_name":"owner/repo"}}'
```

## Troubleshooting

### Error: "JWT expired"
- **Cause**: System clock is out of sync
- **Solution**: Sync your system clock with NTP

### Error: "Could not parse the provided public key"
- **Cause**: Invalid private key format
- **Solution**: Ensure the private key includes header/footer and all newlines

### Error: "404 Not Found" when getting installation token
- **Cause**: Invalid installation ID
- **Solution**: Check the installation ID from GitHub App installations page

### Error: "401 Unauthorized" on API calls
- **Cause**: Token expired or invalid permissions
- **Solution**: Check that the App has the required permissions and is installed on the repo

### Token not refreshing automatically
- **Cause**: Check logs for import errors or exceptions
- **Solution**: Ensure `vibeteam.utils.github_app` is accessible and dependencies are installed

## Migration from PAT to GitHub App

If you're currently using a PAT, you can migrate gradually:

1. **Install the GitHub App** (Steps 1-3 above)
2. **Add GitHub App env vars** alongside existing `GITHUB_TOKEN`
3. **Test with App auth**: The connector will prefer App auth if credentials are present
4. **Monitor for issues**: Check logs for any authentication failures
5. **Remove PAT**: Once confident, remove `GITHUB_TOKEN` env var

The `GitHubConnector` automatically prefers GitHub App authentication when credentials are available, falling back to PAT if needed.

## Security Best Practices

1. **Rotate Private Keys**: Generate new keys periodically (e.g., every 90 days)
2. **Use Sealed Secrets**: Never commit private keys to source control
3. **Limit Permissions**: Only grant permissions the app actually needs
4. **Monitor Usage**: Check GitHub API usage in app settings
5. **Audit Installations**: Regularly review where the app is installed
6. **Secure Webhooks**: Always use webhook secrets and verify signatures

## References

- [GitHub Apps Documentation](https://docs.github.com/en/developers/apps/getting-started-with-apps/about-apps)
- [Authenticating as a GitHub App](https://docs.github.com/en/developers/apps/building-github-apps/authenticating-with-github-apps)
- [GitHub API Rate Limits](https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting)
