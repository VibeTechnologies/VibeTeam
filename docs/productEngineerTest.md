# Product Engineer Test Guide

This guide describes how to test the VibeTeam Product Manager feature request processing workflow.

## Prerequisites

1. **Environment Variables**

```bash
# Required - Azure OpenAI
export AZURE_API_KEY="your-azure-api-key"
export AZURE_API_BASE="https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/"
export AZURE_API_VERSION="2024-08-01-preview"

# Required - GitHub
export GITHUB_TOKEN="your-github-token"
```

Or copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
# Edit .env with your values
```

2. **Dependencies**

```bash
pip install litellm requests
```

## E2E Test: Feature Request Processing

This test verifies the full workflow:
1. Simulates a feature request from docs-chat
2. PM analyzes with real Azure LLM (gpt-5-2)
3. Updates GitHub Customer Requests issue #322

### Run the Test

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env  # or: export $(grep -v '^#' .env | xargs)
python scripts/test_e2e_feature_request.py
```

### Expected Output

```
=== E2E Test: PM Processing Feature Request ===
Request: I want to integrate with Slack to receive browser automation notifications
Source: docs-chat

Step 1: Calling Azure LLM (gpt-5-2) for analysis...
LLM Response received (524 chars)

Step 2: Parsed analysis:
  Priority: P1
  Summary: Slack alerts for automation runs
  Analysis: Teams want automation results delivered where they already work...
  Status: Analyzing

Step 3: Updating GitHub Customer Requests issue...
Updated issue #322
URL: https://github.com/VibeTechnologies/VibeWebAgent/issues/322

Step 4: Verifying table update...
Customer Requests table now has 2 entries:
  - [P1] Slack alerts for automation runs (Analyzing)
  - [P1] Notion.so integration for note sync (Analyzing)

=== E2E TEST PASSED ===
```

### Verify on GitHub

Check the Customer Requests issue:
- URL: https://github.com/VibeTechnologies/VibeWebAgent/issues/322
- Or: `gh issue view 322 --repo VibeTechnologies/VibeWebAgent`

## Full Workflow Test

Test the complete flow from docs chat to PM processing:

### Step 1: Submit Feature Request via Docs Chat

```bash
cd ~/workspace/vibebrowser/vibe.2
node tests/feature-request.test.js --request "I want calendar integration"
```

This submits to `https://docs.vibebrowser.app/api/chat` and saves the response.

### Step 2: PM Processes the Request

```bash
cd ~/workspace/vibebrowser/VibeTeam
source .env
python scripts/test_e2e_feature_request.py
```

### Step 3: Verify GitHub Update

```bash
gh issue view 322 --repo VibeTechnologies/VibeWebAgent
```

## Testing Individual Components

### Test GitHub Connector Only

```python
import os
os.environ['GITHUB_TOKEN'] = 'your-token'

import importlib.util
spec = importlib.util.spec_from_file_location('github', 'vibeteam/connectors/github.py')
github = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github)

gh = github.GitHubConnector()

# Read current requests
body, requests = gh.get_customer_requests_table()
print(f"Found {len(requests)} requests")

# Add a test request
issue = gh.add_customer_request(
    request="Test request",
    source="test",
    priority="P3",
    status="New",
    analysis="Test entry",
)
print(f"Updated issue #{issue.number}")
```

### Test LLM Analysis Only

```python
import os
import litellm

response = litellm.completion(
    model="azure/gpt-5-2",
    messages=[{"role": "user", "content": "Analyze: I want Notion integration"}],
    api_base=os.environ["AZURE_API_BASE"],
    api_key=os.environ["AZURE_API_KEY"],
    api_version="2024-08-01-preview",
    max_tokens=500,
)
print(response.choices[0].message.content)
```

## Troubleshooting

### "DeploymentNotFound" Error

The Azure deployment name is `gpt-5-2` (with hyphen), not `gpt-5.2` (with dot).

```python
# Correct
model="azure/gpt-5-2"

# Wrong
model="azure/gpt-5.2"
```

### "GITHUB_TOKEN not set" Error

```bash
export GITHUB_TOKEN="ghp_..."
# Or add to .env file
```

### "metagpt not installed" Error

The test script uses `importlib` to load only the connector without the full package. This is intentional to avoid metagpt dependency for simple tests.

## Customer Requests Issue

The PM tracks all feature requests in a single GitHub issue:

- **Issue**: #322 in VibeTechnologies/VibeWebAgent
- **URL**: https://github.com/VibeTechnologies/VibeWebAgent/issues/322

### Table Format

| Date | Source | Request | Priority | Status | Analysis |
|------|--------|---------|----------|--------|----------|
| 2026-01-24 | docs-chat | Slack alerts | P1 | Analyzing | Teams want... |

### Priority Levels

- **P0**: Critical - blocks major use cases
- **P1**: High - significant user value
- **P2**: Medium - nice to have
- **P3**: Low - future consideration

### Status Values

- **New**: Just received
- **Analyzing**: PM reviewing
- **Approved**: Added to roadmap
- **Rejected**: Not aligned with product vision
- **Implemented**: Feature shipped
