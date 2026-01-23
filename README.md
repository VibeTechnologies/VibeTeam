# VibeTeam

MetaGPT-based autonomous AI team for SaaS development.

## Overview

VibeTeam provides a multi-agent system with specialized roles that collaborate autonomously:

| Role | Responsibility |
|------|----------------|
| **Product Manager** | Requirements, roadmap, user stories |
| **Software Engineer** | Implementation, testing, code review |
| **Marketer** | Content, social media, announcements |
| **Support Engineer** | User issues, documentation, FAQ |
| **Reliability Engineer** | Production health, incidents, runbooks |
| **Release Engineer** | Deployments, versioning, releases |

## Installation

```bash
pip install git+https://github.com/VibeTechnologies/VibeTeam.git
```

## Quick Start

```python
from vibeteam import VibeTeam

# Initialize team with all roles
team = VibeTeam()

# Or select specific roles
team = VibeTeam(include_roles=["pm", "swe", "marketer"])

# Run a project
import asyncio
result = asyncio.run(team.run_project("Build a task management app"))
```

## CLI Usage

```bash
# Run team on a requirement
vibeteam run "Build a REST API for user authentication"

# Select specific roles
vibeteam run "Create landing page" -r marketer -r swe

# Show team status
vibeteam status

# List available roles
vibeteam roles
```

## Configuration

Set your API key:

```bash
export OPENAI_API_KEY="your-key"
```

Compatible with GitHub Copilot subscription (uses `openai:gpt-5-mini`).

## Architecture

Built on [MetaGPT](https://github.com/geekan/metagpt):

- **Roles**: Specialized agents with specific actions and goals
- **Actions**: Discrete tasks each role can perform
- **Environment**: Shared context and memory for collaboration
- **Team**: Orchestrator that coordinates roles

## Development

```bash
# Clone repo
git clone https://github.com/VibeTechnologies/VibeTeam.git
cd VibeTeam

# Install dev dependencies
pip install -e .[dev]

# Run tests
pytest tests/ -v

# Lint
ruff check .
black --check .
mypy vibeteam
```

## License

MIT
