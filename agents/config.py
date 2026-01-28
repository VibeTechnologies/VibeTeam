"""
Shared configuration for all agent frameworks.

MCP server configurations, session storage, and common settings.
"""

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None  # For HTTP-based MCP servers
    auth: str | None = None  # OAuth token or auth type


# MCP Server Configurations
MCP_SERVERS = {
    # Gmail - for SupportEngineer
    "gmail": MCPServerConfig(
        command="npx",
        args=["-y", "@anthropic/mcp-server-gmail"],
        env={"GMAIL_CREDENTIALS_PATH": os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")},
    ),
    # Google Calendar - for SupportEngineer
    "gcalendar": MCPServerConfig(
        command="npx",
        args=["-y", "@anthropic/mcp-server-google-calendar"],
        env={"GCAL_CREDENTIALS_PATH": os.getenv("GCAL_CREDENTIALS_PATH", "credentials.json")},
    ),
    # Chrome DevTools - for MarketingManager
    "chrome": MCPServerConfig(
        command="npx",
        args=["-y", "@anthropic/mcp-server-chrome-devtools"],
    ),
    # GitHub - for ReleaseEngineer
    "github": MCPServerConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "")},
    ),
    # Filesystem - for ReleaseEngineer
    "filesystem": MCPServerConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/"],
    ),
    # Sentry - for SupportEngineer
    "sentry": MCPServerConfig(
        command="npx",
        args=["-y", "mcp-server-sentry"],
        env={"SENTRY_AUTH_TOKEN": os.getenv("SENTRY_AUTH_TOKEN", "")},
    ),
}


@dataclass
class SessionConfig:
    """Configuration for session/state management."""

    storage_type: str = "local"  # "local", "redis", "s3"
    storage_path: str = "./.sessions"
    redis_url: str | None = None
    s3_bucket: str | None = None
    ttl_seconds: int = 86400 * 7  # 7 days default


@dataclass
class LLMConfig:
    """LLM configuration for agents."""

    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self):
        # Use AZURE_OPENAI_DEPLOYMENT if available, otherwise fall back to gpt-4.1-mini
        if self.model is None:
            self.model = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
        # Use AZURE_OPENAI_ENDPOINT/API_KEY first, then fall back to AZURE_API_BASE/KEY
        self.api_base = (
            self.api_base or os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_API_BASE")
        )
        self.api_key = (
            self.api_key or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
        )


@dataclass
class AgentConfig:
    """Base configuration for all agents."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    slack_channel: str = "#ai-team"
    verbose: bool = True


# Pre-configured agent configs
RELEASE_ENGINEER_CONFIG = AgentConfig(
    mcp_servers={
        "github": MCP_SERVERS["github"],
        "filesystem": MCP_SERVERS["filesystem"],
    },
)

MARKETING_MANAGER_CONFIG = AgentConfig(
    mcp_servers={
        "chrome": MCP_SERVERS["chrome"],
    },
)

SUPPORT_ENGINEER_CONFIG = AgentConfig(
    mcp_servers={
        "gmail": MCP_SERVERS["gmail"],
        "gcalendar": MCP_SERVERS["gcalendar"],
        "sentry": MCP_SERVERS["sentry"],
    },
)

SOFTWARE_ENGINEER_CONFIG = AgentConfig(
    mcp_servers={
        "github": MCP_SERVERS["github"],
        "filesystem": MCP_SERVERS["filesystem"],
    },
)

PRODUCT_MANAGER_CONFIG = AgentConfig(
    mcp_servers={
        "github": MCP_SERVERS["github"],
    },
)


def get_mcp_config_dict(servers: dict[str, MCPServerConfig]) -> dict[str, Any]:
    """Convert MCPServerConfig objects to dict format for frameworks."""
    result = {"mcpServers": {}}
    for name, config in servers.items():
        server_config: dict[str, Any] = {
            "command": config.command,
            "args": config.args,
        }
        if config.env:
            server_config["env"] = config.env
        if config.url:
            server_config["url"] = config.url
        if config.auth:
            server_config["auth"] = config.auth
        result["mcpServers"][name] = server_config
    return result
