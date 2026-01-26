#!/usr/bin/env bun
/**
 * Script to create VibeTeam GitHub App using manifest flow.
 * 
 * Usage:
 *   bun scripts/create-github-app.ts
 * 
 * This will:
 * 1. Open browser to create the GitHub App
 * 2. Save credentials to .secrets/github-app.json
 */

import { $ } from "bun";

const MANIFEST = {
  name: "VibeTeam Bot",
  url: "https://github.com/VibeTechnologies/VibeTeam",
  description: "AI agents for automated issue resolution and PR creation",
  public: false,
  default_permissions: {
    contents: "write",
    issues: "write",
    pull_requests: "write",
    metadata: "read",
  },
  default_events: [
    "issues",
    "issue_comment",
    "pull_request",
    "pull_request_review_comment",
  ],
};

async function main() {
  console.log("Creating VibeTeam GitHub App...\n");
  console.log("Manifest:", JSON.stringify(MANIFEST, null, 2));
  
  // GitHub App creation requires browser interaction
  // We'll use the manifest approach with URL parameters
  const manifestJson = encodeURIComponent(JSON.stringify(MANIFEST));
  const url = `https://github.com/organizations/VibeTechnologies/settings/apps/new`;
  
  console.log("\n=== Manual Steps Required ===\n");
  console.log("1. Go to:", url);
  console.log("\n2. Fill in the form with:");
  console.log("   - GitHub App name: VibeTeam Bot");
  console.log("   - Homepage URL: https://github.com/VibeTechnologies/VibeTeam");
  console.log("   - Webhook: UNCHECK 'Active' (we use GitHub Actions, not webhooks)");
  console.log("\n3. Repository permissions:");
  console.log("   - Contents: Read and write");
  console.log("   - Issues: Read and write");
  console.log("   - Pull requests: Read and write");
  console.log("   - Metadata: Read-only (automatic)");
  console.log("\n4. Subscribe to events:");
  console.log("   - Issues");
  console.log("   - Issue comment");
  console.log("   - Pull request");
  console.log("   - Pull request review comment");
  console.log("\n5. Where can this GitHub App be installed?");
  console.log("   - Only on this account");
  console.log("\n6. Click 'Create GitHub App'");
  console.log("\n7. After creation:");
  console.log("   - Note the App ID (shown on the page)");
  console.log("   - Click 'Generate a private key' and download the PEM file");
  console.log("   - Click 'Install App' on the left sidebar");
  console.log("   - Install on VibeTechnologies organization");
  console.log("   - Select repositories: VibeTeam, VibeWebAgent");
  console.log("   - Note the Installation ID from the URL after install");
  console.log("\n8. Run this command to save credentials:");
  console.log("   bun scripts/save-github-app-creds.ts <app-id> <installation-id> <path-to-pem>");
  
  // Open the URL
  console.log("\nOpening browser...");
  await $`open ${url}`.quiet();
}

main().catch(console.error);
