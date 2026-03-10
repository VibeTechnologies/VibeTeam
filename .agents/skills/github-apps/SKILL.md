---
name: github-apps
description: Create and configure role-scoped GitHub Apps for VibeTeam, map credentials to agents placeholders, and validate installation permissions/identity.
---

# GitHub Apps Provisioning

Use this skill when you need to create, rotate, or validate GitHub Apps used by VibeTeam agents.

## Inputs

- GitHub org/repo targets (typically `VibeTechnologies`)
- Roles from `agents/agents.yaml`
- Org admin permissions to create/install GitHub Apps
- Optional: `gh` auth for secret uploads

## Required References

1. Read `docs/github.md`.
2. Read `docs/requirements.md` GitHub env naming.
3. Read `agents/agents.yaml` credential placeholders (`credentials.github_app.*`).

## Workflow

1. Determine app strategy.
   - Preferred: one GitHub App per role
   - Roles: `software_engineer`, `support_engineer`, `release_engineer`, `product_manager`, `marketing_manager`
2. Create each role app.
   - Name should map clearly to role handle.
   - Homepage: `https://github.com/VibeTechnologies/VibeTeam`
   - Repository permissions:
     - `Contents: Read and write`
     - `Issues: Read and write`
     - `Pull requests: Read and write`
     - `Discussions: Read and write`
     - `Metadata: Read`
   - Enable webhook if webhook signature validation is required.
3. Generate credentials per role app.
   - App ID
   - Installation ID (after org install)
   - Private key PEM
   - Webhook secret
   - Bot username (if used in eval/assignment mapping)
4. Install each app.
   - Install to org `VibeTechnologies`.
   - Grant access to required repos (`VibeTeam`, `VibeWebAgent`, `vibeteam-eval-hello-world` at minimum).
   - Re-approve app permissions after permission changes.
5. Map credentials to env keys.
   - `GITHUB_APP_ID_<ROLE>`
   - `GITHUB_APP_INSTALLATION_ID_<ROLE>`
   - `GITHUB_APP_PRIVATE_KEY_<ROLE>`
   - `GITHUB_WEBHOOK_SECRET_<ROLE>`
   - `GITHUB_APP_BOT_USERNAME_<ROLE>` (when used)
6. Populate JSON deploy secret.
   - Start from `config/secrets/github_app_role_secrets.template.json`.
   - Fill local temp file with role credentials.
   - Upload:
     - `gh secret set GITHUB_APP_ROLE_SECRETS_JSON < /tmp/github_app_role_secrets.json`
7. Validate permissions and assignment readiness.
   - `uv run python scripts/check_github_app_permissions.py --repo VibeTechnologies/vibeteam-eval-hello-world --require-discussions --require-assignable-assignee`
   - Verify assignable bot handles:
     - `gh api repos/VibeTechnologies/vibeteam-eval-hello-world/assignees --jq '.[].login'`
8. Validate runtime attribution.
   - Run at least one GitHub attribution eval scenario after deploy:
     - `uv run python scripts/eval_slack_e2e.py --scenario software_engineer_pr_attribution --channel C0AATPSADB8 --timeout 600`
   - Confirm PR author is the intended role app bot.

## Output Checklist

- App IDs and Installation IDs per role
- Installed repository scope
- Secret/env mapping confirmation
- Permission check command outputs
- URL evidence of bot-attributed PR/comment activity

