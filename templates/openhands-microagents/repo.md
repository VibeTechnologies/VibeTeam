# Repository Microagent for VibeTeam

This microagent provides context about the VibeTeam repository structure and conventions.

## Repository Overview

VibeTeam is an autonomous AI team for SaaS product development and operations. It provides specialized agents for different roles including Product Management, Software Engineering, Marketing, Support, Reliability, and Release Engineering.

## Directory Structure

```
vibeteam/
  __init__.py           # Package initialization
  cli.py                # Command-line interface
  team.py               # VibeTeam orchestrator
  roles/                # Agent role definitions
    base.py             # Base role class
    product_manager.py  # Product Manager agent
    software_engineer.py # Software Engineer agent
    marketer.py         # Marketer agent
    support_engineer.py # Support Engineer agent
    reliability_engineer.py # Reliability Engineer agent
    release_engineer.py # Release Engineer agent
  connectors/           # External service integrations
    github.py           # GitHub API connector
    sentry.py           # Sentry error tracking
    langfuse.py         # LLM observability
    gmail.py            # Email processing
    health.py           # Endpoint monitoring
```

## Key Patterns

### Environment Variables
- `AZURE_API_KEY` - Azure OpenAI API key
- `AZURE_API_BASE` - Azure OpenAI endpoint
- `AZURE_API_VERSION` - API version (2024-08-01-preview)
- `GITHUB_TOKEN` - GitHub Personal Access Token
- `SENTRY_AUTH_TOKEN` - Sentry authentication
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` - Langfuse observability

### Model Configuration
The default model is `azure/gpt-5-2`. Always use hyphen notation (not dots) for Azure model names.

### Running Tests
```bash
pytest tests/ -v
```

### Building
```bash
pip install -e .
```

## Code Style

- Use Python 3.11+
- Follow PEP 8
- Use type hints
- Prefer async/await for I/O operations
- Use pydantic for data models

## Commit Conventions

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions/changes
- `chore:` - Maintenance tasks
