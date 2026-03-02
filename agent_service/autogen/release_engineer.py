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

from agent_service.config import RELEASE_ENGINEER_CONFIG, AgentConfig
from agent_service.sessions import get_or_create_session, get_session_store
from agent_service.shared.docs_tools import search_infra_docs
from agent_service.shared.agents_md_loader import load_shared_instructions
from agent_service.shared.slack_tools import (
    read_slack_channel,
    read_slack_thread,
    send_message,
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

# Model info for custom Azure deployments (gpt-5.2 is not in AutoGen's built-in list)
GPT5_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",  # Use gpt-4o family as base
    "structured_output": True,
}


SHARED_INSTRUCTIONS = load_shared_instructions().strip()

RELEASE_ENGINEER_SYSTEM_PROMPT = f"""You are Einstein, the Release Engineer for VibeTeam.

## CRITICAL: How to Respond

You MUST ALWAYS end with `send_message()` to post your findings to Slack.
Your message will be automatically prefixed with [ReleaseEngineer:session_id].

WORKFLOW:
1. If you need infrastructure information, FIRST use `search_infra_docs()` to find relevant docs
2. Use tools (execute_shell, etc.) to investigate
3. ALWAYS call send_message() with your findings at the end
4. Never finish without calling send_message()

Example:
```
# First check docs for relevant information
search_infra_docs("k3s cluster pods")
# Then investigate
execute_shell("kubectl get pods -n vibeteam")
# Then ALWAYS post findings
send_message("Investigated cluster: all pods healthy. /SupportEngineer issue not on our side.")
```

## Available Tools

- `send_message(message)` - Post your response to Slack (REQUIRED - must be called!)
- `search_infra_docs(query)` - Search infrastructure documentation (k3s, deployment, services)
- `execute_shell(command)` - Execute shell commands (git, kubectl, gh CLI, etc.)
- `read_file(file_path)` - Read file contents (configs, manifests, changelogs)
- `write_file(file_path, content)` - Write content to a file
- `list_directory(path)` - List directory contents
- `read_slack_channel()` - Read recent Slack messages

## Tool Usage Requirements

IMPORTANT:
- For deployment tasks: Use `execute_shell` to run kubectl commands and check status
- For release tasks: Use `execute_shell` with `gh release` commands
- For infrastructure questions: Use `search_infra_docs` FIRST to find relevant docs
- NEVER generate fake data - use tools to get real information
- **ALWAYS call send_message() at the end with your findings**

## Your Responsibilities

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

{SHARED_INSTRUCTIONS}
"""


# Tool functions for AutoGen

# Path to read-only agent kubeconfig
AGENT_KUBECONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".kube", "agent-config.yaml"
)


async def execute_shell(command: str) -> str:
    """Execute a shell command and return the output.

    Args:
        command: The shell command to execute

    Returns:
        The command output (stdout + stderr)
    """
    try:
        # Set up environment with agent kubeconfig for kubectl commands
        env = os.environ.copy()
        if os.path.exists(AGENT_KUBECONFIG):
            env["KUBECONFIG"] = AGENT_KUBECONFIG

        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
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
        # Parse model name (e.g., "azure/gpt-5.2" -> "gpt-5.2")
        model_name = self.config.llm.model or "gpt-5.2"
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
                # Infrastructure docs search (use first for infra questions)
                search_infra_docs,
                # Core release tools
                execute_shell,
                read_file,
                write_file,
                list_directory,
                # Slack communication (send_message is PRIMARY for responses)
                send_message,
                read_slack_channel,
                read_slack_thread,
            ],
            system_message=RELEASE_ENGINEER_SYSTEM_PROMPT,
            description="Release Engineer for deployments, CI/CD, and infrastructure management.",
            reflect_on_tool_use=True,  # Summarize after tool calls
            max_tool_iterations=8,  # Allow more iterations for investigation + send_message
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
        # Priority: 1) send_message tool call content, 2) non-empty TextMessage
        response = ""
        if result.messages:
            import json

            from autogen_agentchat.messages import TextMessage, ToolCallRequestEvent

            # First, look for send_message tool calls - this is the actual response
            for msg in reversed(result.messages):
                if isinstance(msg, ToolCallRequestEvent) and msg.source == "ReleaseEngineer":
                    for call in msg.content:
                        if hasattr(call, "name") and call.name == "send_message":
                            try:
                                args = json.loads(call.arguments)
                                if args.get("message"):
                                    response = args["message"]
                                    break
                            except (json.JSONDecodeError, AttributeError):
                                pass
                    if response:
                        break

            # Fallback: get the last non-empty TextMessage from the assistant
            if not response:
                for msg in reversed(result.messages):
                    if isinstance(msg, TextMessage) and msg.source == "ReleaseEngineer":
                        if msg.content and str(msg.content).strip():
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
