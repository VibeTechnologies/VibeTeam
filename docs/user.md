# User Guide

This guide explains how end users install the VibeTeam GitHub Apps in their org and
what to expect when interacting with the agents inside GitHub threads.

## Install the GitHub Apps in Your Org

You need **org owner** privileges to install GitHub Apps.

1. Open the GitHub App settings page for each VibeTeam role app.
2. Click **Install App**.
3. Select your org.
4. Choose repositories:
   - Recommended: **All repositories**.
   - If you select specific repos, include any repo where you want agent replies.
5. Repeat for each role app (Software Engineer, Support Engineer, etc.).
6. If you later change permissions (for example, enable Discussions), return to the
   **Install App** page and approve the updated permissions.

Notes:
- Discussions require the **Discussions: Read & Write** permission.
- If the app is not installed on a repo, agents cannot read/write that repo’s threads.

## Mentioning the Agents

GitHub App users always have a `[bot]` suffix. The mention must match the exact
login, for example:

- `@software-engineer[bot]`
- `@vibeteam-support-bot-260301[bot]`

If you omit `[bot]`, GitHub will not resolve the mention.

## Can We Use Simpler Bot Names?

Yes, but the `[bot]` suffix cannot be removed. The visible login is derived from the
GitHub App name (slug), so pick a short name when you create the app:

- App name `SoftwareEngineer` -> `@softwareengineer[bot]`
- App name `Software Engineer` -> `@software-engineer[bot]`

If you need a different login, create a new app with the desired name and reinstall it.
Renaming an existing app is not a reliable way to change the login.

## Want It to Feel Like “Real People”?

Two options:

1. **Recommended (GitHub App, secure):** keep role apps and use `/RoleName` commands
   inside comments (`/SoftwareEngineer`, `/SupportEngineer`). This avoids relying on
   `@mentions` and still yields clear, human‑readable responses.
2. **Not recommended (machine user):** create a dedicated GitHub user per role and
   use PATs. This removes the `[bot]` suffix but is less secure and harder to audit
   than GitHub Apps.
