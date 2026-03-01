# GitHub App Setup and Authentication

This guide covers GitHub App setup plus the auth flow used by VibeTeam agents. It replaces the older auth-only doc.

## Why GitHub App Authentication

- Short-lived tokens (1 hour) instead of long-lived PATs.
- Fine-grained permissions and audit trail.
- Works well for bot identities and CI.

## Architecture and Token Flow (Short)

1. Load `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_INSTALLATION_ID`.
2. Generate a JWT (10 min) signed with the App private key.
3. Exchange the JWT for an installation access token (1 hour).
4. Use the installation token for GitHub API calls.

## Step 1: Register a GitHub App

1. GitHub Settings -> Developer settings -> GitHub Apps -> New GitHub App
2. Basic info:
   - Name: `VibeTeam Bot` (or per-agent: `VibeTeam SoftwareEngineer`, etc.)
   - Homepage: `https://github.com/VibeTechnologies/VibeTeam`
3. Permissions (repository):
   - Contents: Read & Write
   - Issues: Read & Write
   - Pull Requests: Read & Write
   - Metadata: Read
4. Optional webhook events if using `/webhook`:
   - Issues, Issue comments, Pull requests, Pull request reviews
5. Create the app.

## Step 2: Generate a Private Key

1. In the app settings, generate a private key.
2. Save the `.pem` file securely.
3. Record the App ID.

## Step 3: Install the App

1. Install the app in the target org or account.
2. Choose repositories (all or select).
3. Record the Installation ID from the URL.

## Step 4: Configure VibeTeam

### Development (.env)

```bash
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Optional PAT fallback
GITHUB_TOKEN=ghp_your_pat_token
```

### Per-Agent GitHub Apps (Recommended)

If you want PRs and comments to show which agent acted, create one GitHub App per
agent role and configure role-scoped env vars:

```bash
# Software Engineer
GITHUB_APP_ID_SOFTWARE_ENGINEER=123456
GITHUB_APP_INSTALLATION_ID_SOFTWARE_ENGINEER=12345678
GITHUB_APP_PRIVATE_KEY_SOFTWARE_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Support Engineer
GITHUB_APP_ID_SUPPORT_ENGINEER=123457
GITHUB_APP_INSTALLATION_ID_SUPPORT_ENGINEER=12345679
GITHUB_APP_PRIVATE_KEY_SUPPORT_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Release Engineer
GITHUB_APP_ID_RELEASE_ENGINEER=123458
GITHUB_APP_INSTALLATION_ID_RELEASE_ENGINEER=12345680
GITHUB_APP_PRIVATE_KEY_RELEASE_ENGINEER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Product Manager
GITHUB_APP_ID_PRODUCT_MANAGER=123459
GITHUB_APP_INSTALLATION_ID_PRODUCT_MANAGER=12345681
GITHUB_APP_PRIVATE_KEY_PRODUCT_MANAGER="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

Role-scoped credentials take precedence over the shared `GITHUB_APP_*` variables.

### Production (Kubernetes)

```bash
kubectl create secret generic github-app \
  --from-literal=app-id=123456 \
  --from-literal=installation-id=12345678 \
  --from-file=private-key=path/to/private-key.pem \
  -n vibeteam
```

## Verification (Optional)

```python
from vibeteam.connectors.github import GitHubConnector

connector = GitHubConnector()  # reads GITHUB_APP_* env vars
issues = connector.search_issues("test", state="open")
print(f"Found {len(issues)} issues")
```

## Troubleshooting (Short)

- JWT expired: system clock drift.
- 404 when getting installation token: wrong Installation ID.
- 401 unauthorized: missing permissions or app not installed on repo.

## References

- https://docs.github.com/en/developers/apps/getting-started-with-apps/about-apps
- https://docs.github.com/en/developers/apps/building-github-apps/authenticating-with-github-apps
