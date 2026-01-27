# Multi-Framework Agent Implementation Progress

Last Updated: 2026-01-27

## Implementation Status

### Legend
- ✅ Completed
- 🔄 In Progress  
- ⬜ Not Started

## Agent Matrix

| Agent | AutoGen | CrewAI | OpenHands |
|-------|---------|--------|-----------|
| **ProductManager** | ✅ | ✅ | ✅ |
| **ReleaseEngineer** | ✅ | ✅ | ✅ |
| **MarketingManager** | ✅ | ✅ | ✅ |
| **SoftwareEngineer** | ✅ | ✅ | ✅ |
| **SupportEngineer** | ✅ | ✅ | ✅ |
| **Team Orchestration** | ✅ | ✅ | ⬜ |

## Azure OpenAI Compatibility

All three frameworks now work with Azure OpenAI:

| Framework | Version | Solution |
|-----------|---------|----------|
| **AutoGen** | 0.4+ | Use `model_info` parameter to bypass model validation |
| **CrewAI** | 1.9.0 | Use `provider='litellm'` to bypass native Azure SDK |
| **OpenHands** | 1.2.1 | Set `max_output_tokens=4096` (default 32768 exceeds Azure limits) |

## Files Created/Modified

### AutoGen Agents
- `agents/autogen/software_engineer.py` - ✅ Created
- `agents/autogen/product_manager.py` - ✅ Created
- `agents/autogen/__init__.py` - ✅ Updated exports

### CrewAI Agents
- `agents/crewai/software_engineer.py` - ✅ Created
- `agents/crewai/product_manager.py` - ✅ Created
- `agents/crewai/__init__.py` - ✅ Updated exports

### OpenHands Agents
- `agents/openhands/release_engineer.py` - ✅ Fixed API (workspace, ask_agent)
- `agents/openhands/support_engineer.py` - ✅ Fixed API
- `agents/openhands/marketing_manager.py` - ✅ Fixed API
- `agents/openhands/software_engineer.py` - ✅ Created
- `agents/openhands/product_manager.py` - ✅ Created
- `agents/openhands/__init__.py` - ✅ Updated exports

### Configuration
- `agents/config.py` - ✅ Added SOFTWARE_ENGINEER_CONFIG, PRODUCT_MANAGER_CONFIG

## OpenHands SDK API Reference

```python
from openhands.sdk import LLM, Agent, LocalConversation

# Create LLM with Azure
llm = LLM(
    model='azure/gpt-4.1-mini',
    api_key=os.getenv('AZURE_API_KEY'),
    base_url=os.getenv('AZURE_API_BASE'),
    api_version='2024-08-01-preview',
    max_output_tokens=4096,  # CRITICAL for Azure
)

# Create Agent (uses template-based system prompts)
agent = Agent(
    llm=llm,
    system_prompt_kwargs={'agent_context': '...'},
)

# Run conversation
with tempfile.TemporaryDirectory() as workspace:
    conv = LocalConversation(agent=agent, workspace=workspace)
    response = conv.ask_agent(task)  # Combines send_message + run
    conv.close()
```

## CrewAI Azure Configuration

```python
from crewai.llm import LLM

llm = LLM(
    model='azure/gpt-4.1-mini',
    provider='litellm',  # CRITICAL - bypass native Azure SDK
    api_key=os.getenv('AZURE_API_KEY'),
    api_base=os.getenv('AZURE_API_BASE'),
    api_version='2024-08-01-preview',
)
```

## AutoGen Azure Configuration

```python
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",
    "structured_output": True,
}

client = AzureOpenAIChatCompletionClient(
    azure_deployment='gpt-4.1-mini',
    model='gpt-4.1-mini',
    azure_endpoint=os.getenv('AZURE_API_BASE'),
    api_key=os.getenv('AZURE_API_KEY'),
    api_version='2024-08-01-preview',
    model_info=MODEL_INFO,  # Bypass model validation
)
```

## Remaining Tasks

1. ⬜ Create OpenHands team.py for agent orchestration
2. ⬜ Add integration tests for new agents
3. ⬜ Upgrade CI Python from 3.11 to 3.12
4. ⬜ Update docs/design.md with findings
5. ⬜ Run local tests to verify all agents work
6. ⬜ Post update to GitHub issue #29

## Environment Variables

Required:
```bash
AZURE_API_KEY=<your-key>
AZURE_API_BASE=https://eastus.api.cognitive.microsoft.com/
AZURE_API_VERSION=2024-08-01-preview
GITHUB_TOKEN=<your-token>
```

## Test Commands

```bash
# Source environment
set -a && source .env && set +a

# Run all integration tests
pytest tests/test_integration.py -v --run-integration

# Test specific framework
pytest tests/test_integration.py -v --run-integration -k "AutoGen"
pytest tests/test_integration.py -v --run-integration -k "CrewAI"
pytest tests/test_integration.py -v --run-integration -k "OpenHands"
```
