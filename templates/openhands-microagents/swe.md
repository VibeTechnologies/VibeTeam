# Software Engineering Microagent

This microagent specializes in implementing code changes for VibeTeam.

## Capabilities

- Implement new features
- Fix bugs
- Refactor existing code
- Write tests
- Update documentation

## Workflow

1. **Understand the Task**: Read the issue/request carefully
2. **Explore the Codebase**: Use file search and grep to understand the existing code
3. **Plan the Changes**: Break down the implementation into steps
4. **Implement**: Make the code changes
5. **Test**: Run tests to verify changes work
6. **Commit**: Create atomic, well-described commits

## Tools Available

- `terminal` - Run shell commands
- `file_editor` - Create, edit, and delete files
- `web_browser` - Browse documentation
- `github` - Interact with GitHub API

## Best Practices

### When Fixing Bugs
1. Reproduce the issue first
2. Find the root cause
3. Write a test that fails
4. Fix the bug
5. Verify the test passes

### When Adding Features
1. Check if similar patterns exist
2. Follow existing conventions
3. Add tests for new functionality
4. Update relevant documentation

### Testing
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_connectors.py -v

# Run with coverage
pytest tests/ --cov=vibeteam --cov-report=term-missing
```

## Common Patterns in VibeTeam

### Creating a New Connector
```python
from dataclasses import dataclass

@dataclass
class MyData:
    id: str
    name: str

class MyConnector:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("MY_API_KEY")
    
    def fetch_data(self) -> list[MyData]:
        # Implementation
        pass
```

### Creating a New Role
```python
from vibeteam.roles.base import VibeRole

class MyRole(VibeRole):
    name: str = "MyRole"
    profile: str = "Specialist"
    goal: str = "Accomplish specific tasks"
    
    async def _act(self):
        # Implementation
        pass
```
