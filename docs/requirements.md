# VibeTeam Requirements

## Overview

VibeTeam is a multi-agent AI system that automates VibeBrowser SaaS operations. Agents collaborate via `/RoleName` mentions in Discord/Slack channels, ensuring human visibility into all activities.

## Agents

| Role | Mention | Function | Tools |
|------|---------|----------|-------|
| **SoftwareEngineer** | `/SoftwareEngineer` | Code implementation, bug fixes, tests, PRs | Shell, Git, GitHub |
| **ReleaseEngineer** | `/ReleaseEngineer` | Deployments, releases, k3s/k8s, CI/CD | kubectl, GitHub |
| **SupportEngineer** | `/SupportEngineer` | Customer support, error analysis | Sentry, Gmail, Langfuse |
| **ProductManager** | `/ProductManager` | PRDs, backlog prioritization, user stories | GitHub |
| **MarketingManager** | `/MarketingManager` | Social media, announcements, content | Chrome DevTools MCP |

## Message Routing

### Thread-Based Subscription Model

When `@VibeTeam` is mentioned in a message, the router tracks that thread and routes to agents based on `/RoleName` mentions.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MESSAGE FLOW                                    │
│                                                                              │
│  User: "@VibeTeam /SoftwareEngineer fix bug #345"                           │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ROUTER                                                              │    │
│  │  1. Detect @VibeTeam → track this thread                            │    │
│  │  2. Parse /SoftwareEngineer → subscribe agent to thread             │    │
│  │  3. React with :eyes: emoji (acknowledged)                          │    │
│  │  4. Forward to Agent Service with context                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  AGENT SERVICE                                                       │    │
│  │  1. Get or create session for (slack, thread_id, software_engineer) │    │
│  │  2. Create agent with pre-configured send_message tool              │    │
│  │  3. Agent processes message and responds                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                      │
│       ▼                                                                      │
│  Agent calls send_message("/ReleaseEngineer please deploy PR #457")         │
│       │                                                                      │
│       ▼                                                                      │
│  Posted to Slack: "[SoftwareEngineer] /ReleaseEngineer please deploy..."    │
│       │                                                                      │
│       ▼                                                                      │
│  Router sees /ReleaseEngineer in bot message → subscribes ReleaseEngineer   │
│  Router forwards to ReleaseEngineer agent                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Routing Rules

1. **Thread Activation**: A thread becomes "active" when `@VibeTeam` is mentioned
2. **Agent Subscription**: `/RoleName` mentions subscribe that agent to the thread
3. **Persistent Subscription**: Once subscribed, agent receives ALL subsequent messages in that thread
4. **Handoffs**: Agents mention `/OtherAgent` in responses to bring them into the thread
5. **Bot Messages**: Router processes bot's own messages to detect handoffs

### Thread Subscription Table

```sql
CREATE TABLE thread_subscriptions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,        -- slack, discord, github_issue, github_pr
    thread_id VARCHAR(255) NOT NULL,    -- thread_ts, message_id, issue_number
    agent_role VARCHAR(50) NOT NULL,    -- software_engineer, release_engineer, etc.
    session_id UUID NOT NULL,           -- link to agent session
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, thread_id, agent_role)
);
```

### Thread ID Formats

| Source | Thread ID Format | Example |
|--------|------------------|---------|
| Slack | `{thread_ts}` | `1234567890.123456` |
| Discord | `{channel_id}:{message_id}` | `123456789:987654321` |
| GitHub Issue | `{repo}:{issue_number}` | `VibeTechnologies/VibeWebAgent:345` |
| GitHub PR | `{repo}:pr:{pr_number}` | `VibeTechnologies/VibeWebAgent:pr:123` |

## Agent Sessions

Each agent maintains a session per thread with:

- **Conversation history**: All messages in the thread
- **Workspace**: Persistent directory for file operations (7-day TTL)
- **Tools**: Pre-configured `send_message` tool for responding

### Session Key Format

```
{framework}:{role}:{source}:{thread_id}
```

Example: `openhands:software_engineer:slack:1234567890.123456`

### send_message Tool

Every agent receives a pre-configured `send_message` tool that:

1. Prefixes messages with `[RoleName]` for identification
2. Posts to the correct thread using stored tokens
3. Triggers router to process any `/RoleName` mentions in the response

```python
# Agent's perspective
send_message("Fixed the bug in PR #457. /ReleaseEngineer ready for staging.")

# Posted to Slack as:
# [SoftwareEngineer] Fixed the bug in PR #457. /ReleaseEngineer ready for staging.
```

## Integrations

### Slack

- **Single app**: `@VibeTeam` bot handles all agent roles
- **Role identification**: `[RoleName]` prefix in messages
- **Threading**: All agent responses go to the original thread
- **Acknowledgment**: :eyes: emoji reaction when message is received

### Discord

- **Single bot**: `@VibeTeam` bot handles all agent roles
- **Role identification**: `[RoleName]` prefix in messages
- **Threading**: Responses in the same thread/channel
- **Acknowledgment**: :eyes: emoji reaction when message is received

### GitHub

- **Issue comments**: Agents respond in issue threads
- **PR comments**: Agents respond in PR threads
- **Webhooks**: Issue/PR events trigger agent processing

### Sentry

- **Error alerts**: Webhook triggers `/SupportEngineer` or `/ReleaseEngineer`
- **Auto-routing**: Based on error severity and type

### Gmail

- **Customer emails**: Processed by `/SupportEngineer`
- **Push notifications**: Real-time email handling

## Agent Frameworks

VibeTeam currently supports OpenHands framework:

| Framework | Status | Notes |
|-----------|--------|-------|
| **OpenHands** | Active | Full tool support, session persistence |
| CrewAI | Planned | Multi-agent orchestration |
| AutoGen | Planned | Conversational agents |
| OpenCode | Experimental | CLI-based, limited tool injection |

## Environment Variables

```bash
# Required - LLM
AZURE_API_KEY=
AZURE_API_BASE=
AZURE_API_VERSION=2024-08-01-preview

# Required - GitHub
GITHUB_TOKEN=

# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Discord
DISCORD_BOT_TOKEN=

# Database
DATABASE_URL=postgresql://...

# Optional
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

## Evaluation

Agents are evaluated using **DeepEval** with **G-Eval** methodology, using **Azure GPT-5.2** as the LLM judge.

### Evaluation Framework

```python
# DeepEval with Azure GPT-5.2 configuration
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

evaluator_config = {
    "model": "azure/gpt-5.2",
    "api_key": os.environ["AZURE_API_KEY"],
    "api_base": os.environ["AZURE_API_BASE"],
    "api_version": "2024-12-01-preview",
}
```

### G-Eval Metrics

| Metric | Threshold | Evaluation Criteria |
|--------|-----------|---------------------|
| **TaskCompletion** | 0.7 | Did the agent complete the requested task? Consider tool usage, output quality, and whether the user's intent was satisfied. |
| **HandoffQuality** | 0.7 | Was context preserved during handoff? Did the receiving agent understand the task without re-explanation? |
| **ResponseTime** | < 60s | Time from message receipt to first response. Measured via timestamps. |
| **Professionalism** | 0.7 | Clear, concise, professional communication. Appropriate tone for the audience. |
| **ToolUsage** | 0.7 | Did the agent use appropriate tools? Were tools called with correct parameters? |
| **ContextPreservation** | 0.7 | Does agent maintain conversation context across messages in a thread? |

### Test Scenarios

| Test File | Scenario | Agents Tested | Key Metrics |
|-----------|----------|---------------|-------------|
| `test_slack_routing.py` | Slack message → agent response | All agents | TaskCompletion, ResponseTime |
| `test_discord_routing.py` | Discord message → agent response | All agents | TaskCompletion, ResponseTime |
| `test_github_routing.py` | GitHub issue comment → agent response | SWE, PM | TaskCompletion, Professionalism |
| `test_handoff_chain.py` | Multi-agent handoff chain | Support → Release → Support | HandoffQuality, ContextPreservation |
| `test_sentry_alert.py` | Sentry error → investigation | Support, Release | TaskCompletion, ToolUsage |

### Example Test Implementation

```python
# tests/e2e/test_handoff_chain.py
import pytest
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

class TestHandoffChain:
    """Test multi-agent handoff scenarios with DeepEval."""
    
    @pytest.fixture
    def gpt52_evaluator(self):
        """GPT-5.2 evaluator configuration."""
        return {
            "model": "azure/gpt-5.2",
            "api_key": os.environ["AZURE_API_KEY"],
            "api_base": os.environ["AZURE_API_BASE"],
        }
    
    @pytest.mark.asyncio
    async def test_support_to_release_handoff(self, mock_slack, gpt52_evaluator):
        """
        Scenario: Customer reports outage, Support hands off to Release.
        
        Flow:
        1. User: @SupportEngineer customer reports GenAI Gateway down
        2. SupportEngineer: checks Gmail, responds, mentions @ReleaseEngineer
        3. ReleaseEngineer: investigates, reports status
        """
        # Arrange
        user_message = "Customer emailed that GenAI Gateway is returning 500 errors"
        
        # Act
        support_response = await run_agent("support_engineer", user_message)
        release_response = await run_agent("release_engineer", support_response)
        
        # Evaluate with DeepEval
        test_case = LLMTestCase(
            input=user_message,
            actual_output=f"{support_response}\n\n{release_response}",
            expected_output="Support checks email, identifies issue, hands off to Release who investigates",
        )
        
        handoff_metric = GEval(
            name="HandoffQuality",
            criteria="Was the handoff context-preserving and actionable?",
            threshold=0.7,
            **gpt52_evaluator,
        )
        
        task_metric = GEval(
            name="TaskCompletion", 
            criteria="Did both agents contribute to resolving the customer issue?",
            threshold=0.7,
            **gpt52_evaluator,
        )
        
        # Assert
        results = evaluate([test_case], [handoff_metric, task_metric])
        assert results.passed, f"Evaluation failed: {results.summary}"
```

### Running Evaluation Tests

```bash
# Install DeepEval
pip install deepeval>=0.21.0

# Set required environment variables
export AZURE_API_KEY="your-key"
export AZURE_API_BASE="https://your-endpoint.openai.azure.com"
export AZURE_API_VERSION="2024-12-01-preview"

# Run all E2E evaluation tests
pytest tests/e2e/ -v -s

# Run specific test
pytest tests/e2e/test_handoff_chain.py -v -s --tb=short

# Run with DeepEval dashboard reporting
deepeval test run tests/e2e/

# Generate evaluation report
python scripts/run_evaluation.py --output results/eval_report.json
```

### Evaluation CI/CD Integration

```yaml
# .github/workflows/evaluation.yml
name: Agent Evaluation

on:
  pull_request:
    branches: [main, master]
  schedule:
    - cron: '0 6 * * *'  # Daily at 6 AM UTC

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run E2E Evaluation
        env:
          AZURE_API_KEY: ${{ secrets.AZURE_API_KEY }}
          AZURE_API_BASE: ${{ secrets.AZURE_API_BASE }}
        run: pytest tests/e2e/ -v --tb=short
      
      - name: Upload Results
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-results
          path: results/
```

### Evaluation Thresholds

All agents must meet these minimum thresholds before release:

| Agent | TaskCompletion | HandoffQuality | Professionalism |
|-------|----------------|----------------|-----------------|
| SoftwareEngineer | ≥ 0.75 | ≥ 0.70 | ≥ 0.70 |
| ReleaseEngineer | ≥ 0.75 | ≥ 0.70 | ≥ 0.70 |
| SupportEngineer | ≥ 0.80 | ≥ 0.75 | ≥ 0.80 |
| ProductManager | ≥ 0.70 | ≥ 0.70 | ≥ 0.80 |
| MarketingManager | ≥ 0.70 | ≥ 0.65 | ≥ 0.85 |

SupportEngineer has higher thresholds due to customer-facing nature of the role.
