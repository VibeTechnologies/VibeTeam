# GitHub App Authentication for VibeTeam Agents

## Overview

This document describes the GitHub App authentication architecture for VibeTeam's Software Engineer and Release Engineer agents. Using a GitHub App provides better security, audit trails, and permission scoping compared to Personal Access Tokens (PATs).

## Why GitHub App?

| Approach | Pros | Cons |
|----------|------|------|
| **GitHub App** | Fine-grained permissions, audit trail, scoped to repos, no user account needed, triggers workflows | More setup |
| Machine Users | Simple identity separation | Requires separate accounts, PAT management |
| Personal Access Tokens | Quick setup | User-tied, broad permissions, security risk |

### Industry Standard

Major AI coding agents use GitHub Apps:
- **OpenHands**: Uses GitHub App for issue resolution and PR creation
- **Dependabot**: GitHub's own bot uses App authentication
- **Renovate**: Uses GitHub App for automated dependency updates
- **peter-evans/create-pull-request**: Recommends GitHub App tokens

## Architecture

```
                                    +------------------+
                                    |  GitHub App      |
                                    |  "VibeTeam Bot"  |
                                    +--------+---------+
                                             |
                        +--------------------+--------------------+
                        |                                         |
              +---------v---------+                     +---------v---------+
              | Installation      |                     | Installation      |
              | VibeTechnologies/ |                     | VibeTechnologies/ |
              | VibeTeam          |                     | VibeWebAgent      |
              +-------------------+                     +-------------------+
                        |                                         |
         +--------------+---------------+          +--------------+---------------+
         |              |               |          |              |               |
    +----v----+   +-----v-----+   +-----v-----+   +-----v-----+  +-----v-----+
    | Issues  |   | PRs       |   | Contents  |   | Issues    |  | PRs       |
    | read/   |   | read/     |   | read/     |   | read/     |  | read/     |
    | write   |   | write     |   | write     |   | write     |  | write     |
    +---------+   +-----------+   +-----------+   +-----------+  +-----------+
```

## Token Flow

```
1. CronJob starts (software-engineer, release-engineer)
        |
        v
2. Load GitHub App credentials from k8s secrets
   - APP_ID
   - PRIVATE_KEY (PEM)
   - INSTALLATION_ID
        |
        v
3. Generate JWT from App credentials (valid 10 min)
   jwt = sign({iat, exp, iss: APP_ID}, PRIVATE_KEY, RS256)
        |
        v
4. Exchange JWT for Installation Access Token (valid 1 hour)
   POST /app/installations/{INSTALLATION_ID}/access_tokens
   Authorization: Bearer {jwt}
        |
        v
5. Use Installation Access Token for GitHub API calls
   Authorization: Bearer {installation_token}
        |
        v
6. Agent creates issues, PRs, comments with bot identity
   Author: vibeteam-bot[bot]
```

## GitHub App Configuration

### App Settings

| Setting | Value |
|---------|-------|
| **Name** | VibeTeam Bot |
| **Homepage URL** | https://github.com/VibeTechnologies/VibeTeam |
| **Webhook** | Inactive (not needed for CronJob-based agents) |
| **Visibility** | Private (org-only) |

### Permissions Required

| Permission | Access | Purpose |
|------------|--------|---------|
| **Contents** | Read & Write | Clone repos, create branches, push commits |
| **Issues** | Read & Write | Read issues, add comments, close issues |
| **Pull Requests** | Read & Write | Create PRs, add reviewers, merge |
| **Metadata** | Read-only | Required for all apps |
| **Workflows** | Read & Write | If PRs modify .github/workflows |
| **Members** | Read-only | Add team reviewers (optional) |

### Installation Scope

Install on:
- `VibeTechnologies/VibeTeam`
- `VibeTechnologies/VibeWebAgent`

## Implementation

### 1. Python Token Generator

```python
# vibeteam/utils/github_app.py
import jwt
import time
import httpx

def generate_jwt(app_id: str, private_key: str) -> str:
    """Generate a JWT for GitHub App authentication."""
    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued at (60s buffer for clock drift)
        "exp": now + 600,  # expires in 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")

def get_installation_token(
    app_id: str,
    private_key: str,
    installation_id: str,
    permissions: dict | None = None,
) -> str:
    """Exchange JWT for installation access token."""
    jwt_token = generate_jwt(app_id, private_key)
    
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    body = {}
    if permissions:
        body["permissions"] = permissions
    
    response = httpx.post(url, headers=headers, json=body if body else None)
    response.raise_for_status()
    
    return response.json()["token"]
```

### 2. Agent Integration

```python
# In vibeteam/cli.py - swe_issues command

from vibeteam.utils.github_app import get_installation_token

def get_github_token() -> str:
    """Get GitHub token - prefer App, fallback to PAT."""
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
    
    if app_id and private_key and installation_id:
        return get_installation_token(app_id, private_key, installation_id)
    
    # Fallback to PAT
    return os.environ.get("GITHUB_TOKEN", "")
```

### 3. GitHub Actions Integration

Use `actions/create-github-app-token@v2`:

```yaml
# .github/workflows/swe-agent.yml
jobs:
  fix-issues:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v2
        id: app-token
        with:
          app-id: ${{ vars.VIBETEAM_APP_ID }}
          private-key: ${{ secrets.VIBETEAM_APP_PRIVATE_KEY }}
          owner: VibeTechnologies
          repositories: VibeTeam,VibeWebAgent
      
      - uses: actions/checkout@v4
        with:
          token: ${{ steps.app-token.outputs.token }}
      
      - name: Run SWE Agent
        env:
          GITHUB_TOKEN: ${{ steps.app-token.outputs.token }}
        run: vibeteam scheduled swe-issues
```

### 4. Kubernetes Secrets

```yaml
# k8s/base/github-app-secret.yaml
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
    -----BEGIN RSA PRIVATE KEY-----
    ...
    -----END RSA PRIVATE KEY-----
```

### 5. CronJob Update

```yaml
# k8s/base/software-engineer.yaml
spec:
  template:
    spec:
      containers:
        - name: software-engineer
          env:
            - name: GITHUB_APP_ID
              valueFrom:
                secretKeyRef:
                  name: github-app
                  key: app-id
            - name: GITHUB_APP_INSTALLATION_ID
              valueFrom:
                secretKeyRef:
                  name: github-app
                  key: installation-id
            - name: GITHUB_APP_PRIVATE_KEY
              valueFrom:
                secretKeyRef:
                  name: github-app
                  key: private-key
```

## File Structure

```
VibeTeam/
├── .secrets/                          # Git-ignored, local dev secrets
│   ├── github-app-private-key.pem
│   └── github-app.env
├── vibeteam/
│   └── utils/
│       └── github_app.py              # Token generation
├── k8s/
│   └── base/
│       └── github-app-secret.yaml     # Template (values from sealed-secrets)
└── docs/
    └── github-app-auth.md             # This document
```

## Security Considerations

1. **Private Key Storage**: Never commit private key to git. Use:
   - GitHub Actions Secrets for CI
   - Kubernetes Sealed Secrets for prod
   - `.secrets/` directory for local dev (git-ignored)

2. **Token Expiry**: Installation tokens expire in 1 hour. Re-generate for long-running processes.

3. **Least Privilege**: Request only needed permissions per operation.

4. **Audit Trail**: All actions show as `vibeteam-bot[bot]` in git history.

5. **Rotation**: Private keys can be rotated without changing App ID.

## Bot Identity

When the GitHub App creates commits/PRs:

- **Author**: `vibeteam-bot[bot]`
- **Email**: `<APP_ID>+vibeteam-bot[bot]@users.noreply.github.com`
- **Commits**: Automatically signed and verified

To get the bot's user ID for git config:
```bash
gh api /users/vibeteam-bot%5Bbot%5D --jq '.id'
```

## Setup Steps

1. Create GitHub App at https://github.com/organizations/VibeTechnologies/settings/apps/new
2. Configure permissions as listed above
3. Generate private key, download PEM file
4. Install app on required repositories
5. Note App ID and Installation ID
6. Store secrets:
   - Local: `.secrets/github-app.env`
   - CI: GitHub Actions Secrets
   - K8s: Sealed Secrets

## References

- [GitHub Apps Documentation](https://docs.github.com/en/apps)
- [actions/create-github-app-token](https://github.com/actions/create-github-app-token)
- [peter-evans/create-pull-request](https://github.com/peter-evans/create-pull-request)
- [OpenHands GitHub Integration](https://github.com/OpenHands/OpenHands)
