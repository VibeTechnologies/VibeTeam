# GitHub App Setup

This guide explains how to create and install GitHub Apps for VibeTeam agents and
configure credentials so each agent uses its own GitHub identity.

## Why GitHub Apps

- Short‑lived tokens (1 hour) instead of long‑lived PATs
- Fine‑grained permissions and audit trail
- Clear attribution per agent

## Recommended: One App Per Agent

Create one GitHub App per agent role so PRs and comments show which agent acted.
Role‑scoped env vars take precedence over shared `GITHUB_APP_*` variables.

Supported role suffixes:
- `SOFTWARE_ENGINEER`
- `SUPPORT_ENGINEER`
- `RELEASE_ENGINEER`
- `PRODUCT_MANAGER`
- `MARKETING_MANAGER`

## Create the App

1. Go to GitHub Settings → Developer settings → GitHub Apps → New GitHub App
2. Basic info:
   - Name: `VibeTeam SWE Bot` (or per role)
   - Homepage URL: `https://github.com/VibeTechnologies/VibeTeam`
3. Permissions (Repository):
   - Contents: Read & Write
   - Issues: Read & Write
   - Pull Requests: Read & Write
   - Metadata: Read
4. Webhooks (optional, only if using `/webhook`):
   - Enable webhooks
   - Events: Issues, Issue comments, Pull requests, Pull request reviews
5. Create the app

## Generate a Private Key

1. In the app settings, click “Generate a private key”
2. Save the `.pem` file securely
3. Record the App ID

## Install the App on the Org

1. From the app settings page, click “Install App”
2. Choose the `VibeTechnologies` org
3. Select repositories:
   - Recommended: All repositories
   - If selected: at least `VibeTeam`, `VibeWebAgent`, and `vibeteam-eval-hello-world`
4. Record the Installation ID from the URL
   - Example: `https://github.com/organizations/VibeTechnologies/settings/installations/<ID>`

## Configure VibeTeam

### Development (.env)

Shared app:
```bash
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Optional PAT fallback
GITHUB_TOKEN=ghp_your_pat_token
```

Per‑agent apps (recommended):
```bash
GITHUB_APP_ID_SOFTWARE_ENGINEER=123456
GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER=12345678
GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

GITHUB_APP_ID_SUPPORT_ENGINEER=123457
GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER=12345679
GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

GITHUB_APP_ID_RELEASE_ENGINEER=123458
GITHUB_APP_INSTALLATION_ID_RELEASE_ENGINEER=12345680
GITHUB_APP_PRIVATE_KEY_RELEASE_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

GITHUB_APP_ID_PRODUCT_MANAGER=123459
GITHUB_APP_INSTALLATION_ID_PRODUCT_MANAGER=12345681
GITHUB_APP_PRIVATE_KEY_PRODUCT_MANAGER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

GITHUB_APP_ID_MARKETING_MANAGER=123460
GITHUB_APP_INSTALLATION_ID_MARKETING_MANAGER=12345682
GITHUB_APP_PRIVATE_KEY_MARKETING_MANAGER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

### Production (Kubernetes)

Store the shared (non-role) GitHub App credentials in `github-app-secret` for
the gateway/webhook services:

```bash
kubectl create secret generic github-app-secret -n vibeteam \
  --from-literal=app-id=123456 \
  --from-literal=installation-id=12345678 \
  --from-literal=private-key="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----" \
  --dry-run=client -o yaml | kubectl apply -f -
```

#### Role-Specific Apps in Production

CI/CD expects per-role GitHub App secrets to be present in GitHub Secrets and
will generate the `github-app-role-secrets` secret for agent pods. Required
GitHub Secrets:

```
GITHUB_APP_ID_SOFTWARE_ENGINEER
GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER
GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER
GITHUB_APP_ID_SUPPORT_ENGINEER
GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER
GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER
GITHUB_APP_ID_RELEASE_ENGINEER
GITHUB_APP_INSTALLATION_ID_RELEASE_ENGINEER
GITHUB_APP_PRIVATE_KEY_RELEASE_ENGINEER
GITHUB_APP_ID_PRODUCT_MANAGER
GITHUB_APP_INSTALLATION_ID_PRODUCT_MANAGER
GITHUB_APP_PRIVATE_KEY_PRODUCT_MANAGER
GITHUB_APP_ID_MARKETING_MANAGER
GITHUB_APP_INSTALLATION_ID_MARKETING_MANAGER
GITHUB_APP_PRIVATE_KEY_MARKETING_MANAGER
```

### Private Key Formatting

For local `.env` usage with `export $( < .env )`, replace spaces with underscores:
`BEGIN_RSA_PRIVATE_KEY` / `END_RSA_PRIVATE_KEY`. The runtime normalizes these
back to standard PEM headers.

## Verify

```python
from vibeteam.connectors.github import GitHubConnector

connector = GitHubConnector()  # reads env vars
issues = connector.search_issues("test", state="open")
print(f"Found {len(issues)} issues")
```

## Troubleshooting

- JWT expired: system clock drift
- 404 when getting installation token: wrong Installation ID
- 401 unauthorized: app missing permissions or not installed on repo
