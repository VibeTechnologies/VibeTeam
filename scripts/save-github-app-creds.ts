#!/usr/bin/env bun
/**
 * Save GitHub App credentials after manual creation.
 * 
 * Usage:
 *   bun scripts/save-github-app-creds.ts <app-id> <installation-id> <path-to-pem>
 * 
 * Example:
 *   bun scripts/save-github-app-creds.ts 123456 12345678 ~/Downloads/vibeteam-bot.pem
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";

async function main() {
  const [appId, installationId, pemPath] = process.argv.slice(2);
  
  if (!appId || !installationId || !pemPath) {
    console.error("Usage: bun scripts/save-github-app-creds.ts <app-id> <installation-id> <path-to-pem>");
    process.exit(1);
  }
  
  // Read PEM file
  if (!existsSync(pemPath)) {
    console.error(`PEM file not found: ${pemPath}`);
    process.exit(1);
  }
  const privateKey = readFileSync(pemPath, "utf-8");
  
  // Create .secrets directory if needed
  const secretsDir = join(process.cwd(), ".secrets");
  if (!existsSync(secretsDir)) {
    mkdirSync(secretsDir, { recursive: true });
  }
  
  // Save credentials as JSON
  const credsPath = join(secretsDir, "github-app.json");
  const creds = {
    app_id: appId,
    installation_id: installationId,
    private_key: privateKey,
  };
  writeFileSync(credsPath, JSON.stringify(creds, null, 2));
  console.log(`Saved credentials to ${credsPath}`);
  
  // Save as env file for easy sourcing
  const envPath = join(secretsDir, "github-app.env");
  const envContent = `# GitHub App credentials for VibeTeam Bot
GITHUB_APP_ID=${appId}
GITHUB_APP_INSTALLATION_ID=${installationId}
GITHUB_APP_PRIVATE_KEY='${privateKey.replace(/\n/g, "\\n")}'
`;
  writeFileSync(envPath, envContent);
  console.log(`Saved env file to ${envPath}`);
  
  // Copy PEM file
  const pemDestPath = join(secretsDir, "github-app-private-key.pem");
  writeFileSync(pemDestPath, privateKey);
  console.log(`Copied PEM to ${pemDestPath}`);
  
  console.log("\n=== Next Steps ===");
  console.log("1. Add secrets to GitHub repo:");
  console.log(`   gh secret set VIBETEAM_APP_PRIVATE_KEY < ${pemDestPath}`);
  console.log(`   gh variable set VIBETEAM_APP_ID --body "${appId}"`);
  console.log(`   gh variable set VIBETEAM_APP_INSTALLATION_ID --body "${installationId}"`);
  console.log("\n2. Test the GitHub App authentication:");
  console.log("   source .secrets/github-app.env && python -c \"from vibeteam.utils.github_app import get_app_info; import os; print(get_app_info(os.environ['GITHUB_APP_ID'], os.environ['GITHUB_APP_PRIVATE_KEY'].replace('\\\\n', '\\n')))\"");
}

main().catch(console.error);
