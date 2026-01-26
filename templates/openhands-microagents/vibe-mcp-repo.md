---
name: repo
agent: CodeActAgent
triggers:
  - keyword: ""
---

# vibe-mcp Repository

You are working on **vibe-mcp**, the MCP (Model Context Protocol) server implementations for VibeTechnologies.

## Project Overview

vibe-mcp provides MCP servers that enable AI agents to interact with various tools and services. These servers follow the MCP specification and can be used with any MCP-compatible client.

## Tech Stack

- **Language**: Python 3.11+
- **Framework**: FastMCP / mcp-server
- **Package Manager**: uv (preferred) or pip
- **Test Framework**: pytest
- **Type Checking**: mypy

## Development Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Type checking
uv run mypy .

# Run a specific MCP server
uv run python -m vibe_mcp.servers.{server_name}
```

## Code Style Guidelines

- Use type hints for all function signatures
- Follow PEP 8 with ruff formatting
- Write docstrings for public functions
- Keep MCP tool functions focused and atomic
- Handle errors gracefully with descriptive messages

## Important Files

- `pyproject.toml` - Project configuration and dependencies
- `src/vibe_mcp/` - Main package directory
- `src/vibe_mcp/servers/` - Individual MCP server implementations
- `tests/` - Test files

## Common Patterns

### MCP Tool Definition
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server-name")

@mcp.tool()
async def my_tool(param: str) -> str:
    """Tool description for the AI."""
    return f"Result: {param}"
```

### Error Handling
```python
from mcp.types import ToolError

@mcp.tool()
async def risky_operation(id: str) -> str:
    try:
        result = await do_something(id)
        return result
    except NotFoundError:
        raise ToolError(f"Item {id} not found")
```

## Debugging Tips

- Use `MCP_DEBUG=1` environment variable for verbose logging
- Test tools individually with `mcp-client` CLI
- Check server stdout for tool invocation logs
- Use pytest fixtures for mocking external services
