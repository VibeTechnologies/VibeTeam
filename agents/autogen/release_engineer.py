"""
ReleaseEngineer agent using AutoGen.

Capabilities:
- Shell command execution
- File operations
- Git operations
- k3s cluster deployment
- GitHub PR and release management
"""

import asyncio
import os
import subprocess
from typing import Any

from agents.config import RELEASE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store
from agents.shared.slack_tools import (
    post_slack_message,
    read_slack_channel,
    read_slack_thread,
)

# AutoGen imports - will fail gracefully if not installed
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_core.models import ModelFamily
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False
    AssistantAgent = None
    TaskResult = None
    AzureOpenAIChatCompletionClient = None
    ModelFamily = None

# Model info for custom Azure deployments (gpt-5-2 is not in AutoGen's built-in list)
GPT5_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",  # Use gpt-4o family as base
    "structured_output": True,
}


RELEASE_ENGINEER_SYSTEM_PROMPT = """You are Einstein, the Release Engineer for VibeTeam.

## CRITICAL: Tool Usage Requirements
You MUST use the provided tools to complete tasks. Do NOT respond without first calling the appropriate tools to gather real data.

Available tools:
- `execute_shell(command)` - Execute shell commands. Use this for git, kubectl, gh CLI, and other system commands.
- `read_file(file_path)` - Read file contents. Use to read config files, manifests, changelogs.
- `write_file(file_path, content)` - Write content to a file. Use for creating/updating configs.
- `list_directory(path)` - List directory contents. Use to explore project structure.

IMPORTANT:
- For deployment tasks: ALWAYS use `execute_shell` to run kubectl commands and check status.
- For release tasks: Use `execute_shell` with `gh release` commands, read CHANGELOG.md first.
- For checking build status: Use `execute_shell` with `gh run list` or similar commands.
- NEVER generate fake data or respond from memory - use tools to get real information.

Your responsibilities:
1. **Deployments**: Deploy applications to the k3s Kubernetes cluster
2. **Release Management**: Create releases, changelogs, and version bumps
3. **CI/CD**: Monitor and fix build pipelines
4. **Infrastructure**: Manage server configurations and scripts

## k3s Cluster Information
- Cluster: vibeteam-prod
- Namespace: production
- Registry: ghcr.io/vibetechnologies
- Config: ~/.kube/config

## Common Commands
```bash
# Deploy to k3s
kubectl apply -f k8s/

# Check deployment status
kubectl get pods -n production

# View logs
kubectl logs -f deployment/vibeteam -n production

# Create GitHub release
gh release create v1.0.0 --generate-notes
```

## TEAM COLLABORATION

When you complete a task or need help from another team member, @mention them in your response:
- @SoftwareEngineer - for code changes before deployment
- @SiteReliabilityEngineer - for infrastructure/monitoring issues
- @SupportEngineer - to notify about customer-facing changes
- @ProductManager - for release scope/timing decisions
- @Marketer - for public release announcements

Example: "Deployment to staging complete. @SupportEngineer please verify the customer-facing changes before we proceed to production."

You can also use Slack tools:
- `post_slack_message(message)` - Post updates to Slack #ai-team
- `read_slack_channel()` - Read recent Slack messages

When you complete a task, summarize what was done and any next steps.
"""


# Tool functions for AutoGen
async def execute_shell(command: str) -> str:
    """Execute a shell command and return the output.

    Args:
        command: The shell command to execute

    Returns:
        The command output (stdout + stderr)
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\nReturn code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 300 seconds"
    except Exception as e:
        return f"Error executing command: {e}"


async def read_file(file_path: str) -> str:
    """Read the contents of a file.

    Args:
        file_path: Path to the file to read

    Returns:
        The file contents or error message
    """
    try:
        with open(file_path) as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(file_path: str, content: str) -> str:
    """Write content to a file.

    Args:
        file_path: Path to the file to write
        content: Content to write to the file

    Returns:
        Success message or error message
    """
    try:
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def list_directory(path: str = ".") -> str:
    """List contents of a directory.

    Args:
        path: Directory path to list (defaults to current directory)

    Returns:
        Directory listing or error message
    """
    try:
        entries = os.listdir(path)
        result = []
        for entry in sorted(entries):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                result.append(f"[DIR]  {entry}/")
            else:
                size = os.path.getsize(full_path)
                result.append(f"[FILE] {entry} ({size} bytes)")
        return "\n".join(result) if result else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


class AutoGenReleaseEngineer:
    """Release Engineer agent using AutoGen."""

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or RELEASE_ENGINEER_CONFIG
        self.model_client = self._create_model_client()
        self.agent = self._create_agent()

    def _create_model_client(self) -> "AzureOpenAIChatCompletionClient":
        """Create Azure OpenAI model client."""
        # Parse model name (e.g., "azure/gpt-5-2" -> "gpt-5-2")
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if model_name.startswith("azure/"):
            model_name = model_name[6:]

        return AzureOpenAIChatCompletionClient(
            azure_deployment=model_name,
            model=model_name,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=self.config.llm.api_base or "",
            api_key=self.config.llm.api_key or "",
            model_info=GPT5_MODEL_INFO,  # Custom model info for Azure deployments
        )

    def _create_agent(self) -> "AssistantAgent":
        """Create AutoGen AssistantAgent with tools."""
        return AssistantAgent(
            name="ReleaseEngineer",
            model_client=self.model_client,
            tools=[
                # Core release tools
                execute_shell,
                read_file,
                write_file,
                list_directory,
                # Slack communication
                post_slack_message,
                read_slack_channel,
                read_slack_thread,
            ],
            system_message=RELEASE_ENGINEER_SYSTEM_PROMPT,
            description="Release Engineer for deployments, CI/CD, and infrastructure management.",
            reflect_on_tool_use=True,  # Summarize after tool calls
            max_tool_iterations=5,  # Allow multiple tool iterations
        )

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Release Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (issue number, PR number, etc.)

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        # Get or create session
        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="autogen",
            role="release_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        # Run the agent
        result: TaskResult = await self.agent.run(task=task)

        # Extract response from result
        response = ""
        if result.messages:
            # Get the last assistant message
            for msg in reversed(result.messages):
                if hasattr(msg, "content") and msg.content:
                    response = str(msg.content)
                    break

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "autogen",
            "agent": "release_engineer",
        }

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync version of run_async."""
        return asyncio.run(self.run_async(task, context_type, context_id, **kwargs))

    async def close(self) -> None:
        """Close the model client connection."""
        if self.model_client:
            await self.model_client.close()


def create_release_engineer(
    config: AgentConfig | None = None,
) -> AutoGenReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return AutoGenReleaseEngineer(config)
