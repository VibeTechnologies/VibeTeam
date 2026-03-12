---
name: slack-app
description: Create and configure VibeTeam Slack apps (one ingress app plus role-scoped responder apps), wire role tokens/secrets, and validate routing/identity behavior.
---

# Slack App Provisioning

Use this skill when you need to create, update, or audit Slack apps for VibeTeam.

## Inputs

- Target environment host (for example `https://webhook.team.vibebrowser.app`)
- Slack workspace with admin access
- Roles from `agents/agents.yaml`
- Optional: `gh` auth for uploading JSON secrets

## Required References

1. Read `docs/slack.md`.
2. Read `docs/requirements.md` Slack env naming.
3. Read `agents/agents.yaml` for role handles and credential placeholders.

## Workflow

1. Build the app inventory.
   - Ingress app: `VibeTeam`
   - Role apps: `SoftwareEngineer`, `SupportEngineer`, `ReleaseEngineer`, `ProductManager`, `MarketingManager`
2. Configure ingress app.
   - Use `templates/slack-app/manifest.yaml`.
   - Set Event Subscriptions request URL to `<gateway>/slack/events`.
   - Ensure ingress bot events: `app_mention`, `message.channels`, `message.groups`, `message.im`.
3. Configure each role app.
   - App/bot display name must match the role handle.
   - Keep Event Subscriptions disabled for role apps.
   - Add required scopes: `chat:write`, `reactions:write`, `channels:history`, `groups:history`, `im:history`, `users:read`.
   - Add `assistant:write` when role-specific assistant status is required.
4. Install/Reinstall all apps.
   - Reinstall after any scope changes.
5. Invite apps to channels.
   - `/invite @VibeTeam`
   - `/invite @SoftwareEngineer @SupportEngineer @ReleaseEngineer @ProductManager @MarketingManager`
6. Map credentials to env keys.
   - Ingress fallback:
     - `SLACK_BOT_TOKEN`, `SLACK_ASSISTANT_TOKEN`, `SLACK_SIGNING_SECRET`
   - Role-scoped:
     - `SLACK_BOT_TOKEN_<ROLE>`
     - `SLACK_ASSISTANT_TOKEN_<ROLE>`
     - `SLACK_SIGNING_SECRET_<ROLE>`
   - Shared trigger secret:
     - `SLACK_TRIGGER_SECRET`
7. Populate JSON deploy secret.
   - Start from `config/secrets/slack_role_secrets.template.json`.
   - Store real values in a local temp file only.
   - Upload to GitHub Secret:
     - `gh secret set SLACK_ROLE_SECRETS_JSON < /tmp/slack_role_secrets.json`
8. Validate behavior.
   - Confirm each role token resolves to a distinct bot user ID (Slack `auth.test`).
   - Run a smoke evaluation:
     - `uv run python scripts/eval_slack_e2e.py --scenario support_notify_check --channel C0ALG01DLJV --timeout 300 --skip-eval`
   - Verify response identity is by Slack app user and reply text has no legacy `[Role]` prefix.

## Output Checklist

- App IDs for ingress + each role app
- Bot user IDs for each role token
- Confirmed env/secret key mapping
- Slack thread URL for smoke test evidence

