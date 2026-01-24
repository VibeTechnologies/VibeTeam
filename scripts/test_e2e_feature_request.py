#!/usr/bin/env python3
"""
E2E Test: Feature Request Processing

Tests the full flow:
1. Simulates a feature request from docs-chat
2. PM analyzes with real LLM
3. Updates GitHub Customer Requests issue

Usage:
    source .env && python scripts/test_e2e_feature_request.py
"""

import json
import os
import sys
import importlib.util

# Check env vars
required_vars = ['AZURE_API_KEY', 'AZURE_API_BASE', 'GITHUB_TOKEN']
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing environment variables: {', '.join(missing)}")
    print("Run: source .env")
    sys.exit(1)

import litellm

# Test data
REQUEST = "I want to integrate with Slack to receive browser automation notifications"
SOURCE = "docs-chat"

def main():
    print("=== E2E Test: PM Processing Feature Request ===")
    print(f"Request: {REQUEST}")
    print(f"Source: {SOURCE}")
    print()

    # Step 1: Call LLM for analysis
    print("Step 1: Calling Azure LLM (gpt-5-2) for analysis...")

    prompt = f"""
You are a Product Manager for VibeBrowser, an AI-powered browser automation extension.

Analyze this customer feature request:

## Request
{REQUEST}

## Source
{SOURCE}

## VibeBrowser Context
VibeBrowser is a Chrome extension that:
- Uses AI to understand natural language commands
- Automates browser tasks (clicking, typing, navigation)
- Integrates with external tools via MCP (Model Context Protocol)
- Supports voice input for hands-free operation

## Your Task
Analyze this request and provide:

1. **Priority** (choose one):
   - P0: Critical - blocks major use cases, many users affected
   - P1: High - significant user value, clear demand
   - P2: Medium - nice to have, moderate user value
   - P3: Low - future consideration, limited demand

2. **Short Summary** (max 50 chars): Brief description for the tracking table

3. **Analysis** (2-3 sentences): Why this priority? What's the user need? Implementation complexity?

4. **Status**: Always "Analyzing" for new requests

Respond in this exact JSON format:
```json
{{
    "priority": "P1",
    "summary": "Slack notifications for automation",
    "analysis": "High value integration. Slack is popular among teams. Can use webhooks.",
    "status": "Analyzing"
}}
```
"""

    try:
        response = litellm.completion(
            model="azure/gpt-5-2",
            messages=[{"role": "user", "content": prompt}],
            api_base=os.environ["AZURE_API_BASE"],
            api_key=os.environ["AZURE_API_KEY"],
            api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
            max_tokens=500,
        )
    except Exception as e:
        print(f"ERROR: LLM call failed: {e}")
        sys.exit(1)

    content = response.choices[0].message.content
    print(f"LLM Response received ({len(content)} chars)")
    print()

    # Parse JSON
    try:
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()
        result = json.loads(json_str)
    except (json.JSONDecodeError, IndexError) as e:
        print(f"ERROR: Failed to parse JSON: {e}")
        print(f"Raw response: {content}")
        sys.exit(1)

    print("Step 2: Parsed analysis:")
    print(f"  Priority: {result['priority']}")
    print(f"  Summary: {result['summary']}")
    print(f"  Analysis: {result['analysis']}")
    print(f"  Status: {result['status']}")
    print()

    # Step 3: Update GitHub
    print("Step 3: Updating GitHub Customer Requests issue...")

    # Load GitHub connector without importing full package
    github_spec = importlib.util.spec_from_file_location(
        "github", "vibeteam/connectors/github.py"
    )
    github = importlib.util.module_from_spec(github_spec)
    github_spec.loader.exec_module(github)

    try:
        gh = github.GitHubConnector()
        issue = gh.add_customer_request(
            request=result["summary"],
            source=SOURCE,
            priority=result["priority"],
            status=result["status"],
            analysis=result["analysis"][:100],
        )
        print(f"Updated issue #{issue.number}")
        print(f"URL: {issue.html_url}")
    except Exception as e:
        print(f"ERROR: GitHub update failed: {e}")
        sys.exit(1)

    print()

    # Step 4: Verify
    print("Step 4: Verifying table update...")
    body, requests = gh.get_customer_requests_table()
    print(f"Customer Requests table now has {len(requests)} entries:")
    for req in requests:
        print(f"  - [{req['priority']}] {req['request']} ({req['status']})")
    print()

    print("=== E2E TEST PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
