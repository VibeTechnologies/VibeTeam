# OpenHands Microagents for VibeTeam

Microagents provide specialized context and instructions for OpenHands AI agents working on the VibeTeam repository.

## Available Microagents

| File | Purpose |
|------|---------|
| `repo.md` | Repository structure and conventions |
| `swe.md` | Software engineering tasks |
| `support.md` | Customer support and triage |
| `release.md` | Deployment and release management |

## Usage

### With OpenHands CLI
```bash
openhands --microagent templates/openhands-microagents/swe.md
```

### With GitHub Action
The `openhands-resolver.yml` workflow automatically loads the appropriate microagent based on issue labels.

### Programmatically
```python
from pathlib import Path

microagent = Path("templates/openhands-microagents/swe.md").read_text()
# Pass to OpenHands agent as system context
```

## Creating New Microagents

1. Create a new `.md` file in this directory
2. Follow the structure:
   - Title and description
   - Capabilities list
   - Workflow steps
   - Available tools
   - Code examples
   - Best practices

## Integration with VibeTeam Roles

| Microagent | VibeTeam Role |
|------------|---------------|
| `swe.md` | SoftwareEngineer |
| `support.md` | SupportEngineer |
| `release.md` | ReleaseEngineer |
| `repo.md` | All roles (context) |
