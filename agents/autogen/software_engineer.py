"""
SoftwareEngineer agent using AutoGen.

Capabilities:
- Shell command execution for builds and tests
- File operations (read, write, edit)
- Git operations (branch, commit, merge)
- GitHub API for PRs and issues
"""

import asyncio
import os
import subprocess
from typing import Any

from agents.config import SOFTWARE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store

# AutoGen imports - will fail gracefully if not installed
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False
    AssistantAgent = None
    TaskResult = None
    AzureOpenAIChatCompletionClient = None

# Model info for custom Azure deployments
GPT_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",
    "structured_output": True,
}


SOFTWARE_ENGINEER_SYSTEM_PROMPT = """You are Alan, the Software Engineer for VibeTeam.

## CRITICAL: Tool Usage Requirements
You MUST use the provided tools to complete tasks. Do NOT respond without first calling the appropriate tools to gather real data.

Available tools:
- `list_issues(state, limit)` - List GitHub issues. Use this to see open issues.
- `get_issue(issue_number)` - Get details of a specific issue. Use after list_issues.
- `execute_shell(command)` - Run shell commands for builds, tests, git operations.
- `read_file(file_path)` - Read file contents.
- `write_file(file_path, content)` - Write to a file.
- `edit_file(file_path, old_text, new_text)` - Edit a file.
- `git_command(command)` - Run git commands (without 'git' prefix).

IMPORTANT: 
- For GitHub issue tasks: ALWAYS call `list_issues` first, then `get_issue` for details.
- NEVER generate fake data or respond from memory - use tools to get real information.
- If a task mentions "issues", "PRs", "code", or "files", you MUST use tools.

Your responsibilities:
1. **Feature Implementation**: Implement features from user stories and PRDs
2. **Bug Fixing**: Fix bugs reported by SupportEngineer or from Sentry
3. **Testing**: Write and maintain unit tests and integration tests
4. **Code Review**: Review code changes and suggest improvements
5. **Pull Requests**: Create and manage pull requests

## Development Workflow
1. Understand the requirement from the issue or user story
2. Create a feature branch: `git checkout -b feat/feature-name`
3. Implement the changes with tests
4. Run tests to verify: `pytest tests/`
5. Commit with descriptive message: `git commit -m "feat: description"`
6. Create a pull request with summary

## Code Standards
- Follow existing code patterns in the repository
- Write docstrings for functions and classes
- Add type hints where appropriate
- Keep functions focused and small
- Write tests for new functionality

## Communication
- Post updates to Slack #ai-team
- Tag @ReleaseEngineer when ready for deployment
- Tag @SupportEngineer if changes affect customer-facing features

When you complete a task, summarize what was done, files changed, and any next steps.
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
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing text.

    Args:
        file_path: Path to the file to edit
        old_text: Text to find and replace
        new_text: Text to replace with

    Returns:
        Success message or error message
    """
    try:
        with open(file_path) as f:
            content = f.read()

        if old_text not in content:
            return f"Error: '{old_text[:50]}...' not found in {file_path}"

        new_content = content.replace(old_text, new_text, 1)

        with open(file_path, "w") as f:
            f.write(new_content)

        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error editing file: {e}"


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


async def git_command(command: str) -> str:
    """Execute a git command.

    Args:
        command: Git command (without 'git' prefix)

    Returns:
        Git command output or error message
    """
    return await execute_shell(f"git {command}")


async def list_issues(state: str = "open", limit: int = 10) -> str:
    """List GitHub issues from the repository.

    Args:
        state: Issue state - "open", "closed", or "all" (default: open)
        limit: Maximum number of issues to return (default: 10)

    Returns:
        Formatted list of issues with number, title, labels, and age
    """
    try:
        from vibeteam.connectors.github import GitHubConnector

        connector = GitHubConnector()
        # Use search_issues to get issues
        issues = connector.search_issues(query="", state=state, limit=limit)

        if not issues:
            return f"No {state} issues found."

        result = [f"Found {len(issues)} {state} issues:\n"]
        for issue in issues:
            labels = ", ".join(issue.labels) if issue.labels else "none"
            result.append(
                f"#{issue.number}: {issue.title}\n"
                f"  Labels: {labels}\n"
                f"  Age: {issue.age_days:.1f} days\n"
                f"  URL: {issue.html_url}\n"
            )
        return "\n".join(result)
    except Exception as e:
        return f"Error listing issues: {e}"


async def get_issue(issue_number: int) -> str:
    """Get details of a specific GitHub issue.

    Args:
        issue_number: The issue number to retrieve

    Returns:
        Issue details including title, body, labels, and state
    """
    try:
        from vibeteam.connectors.github import GitHubConnector

        connector = GitHubConnector()
        issue = connector.get_issue(issue_number)

        labels = ", ".join(issue.labels) if issue.labels else "none"
        return (
            f"Issue #{issue.number}: {issue.title}\n"
            f"State: {issue.state}\n"
            f"Labels: {labels}\n"
            f"Created: {issue.created_at} ({issue.age_days:.1f} days ago)\n"
            f"Author: {issue.user}\n"
            f"URL: {issue.html_url}\n\n"
            f"Body:\n{issue.body}"
        )
    except Exception as e:
        return f"Error getting issue: {e}"


class AutoGenSoftwareEngineer:
    """Software Engineer agent using AutoGen."""

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or SOFTWARE_ENGINEER_CONFIG
        self.model_client = self._create_model_client()
        self.agent = self._create_agent()

    def _create_model_client(self) -> "AzureOpenAIChatCompletionClient":
        """Create Azure OpenAI model client."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if model_name.startswith("azure/"):
            model_name = model_name[6:]

        return AzureOpenAIChatCompletionClient(
            azure_deployment=model_name,
            model=model_name,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=self.config.llm.api_base or "",
            api_key=self.config.llm.api_key or "",
            model_info=GPT_MODEL_INFO,
        )

    def _create_agent(self) -> "AssistantAgent":
        """Create AutoGen AssistantAgent with tools."""
        return AssistantAgent(
            name="SoftwareEngineer",
            model_client=self.model_client,
            tools=[
                execute_shell,
                read_file,
                write_file,
                edit_file,
                list_directory,
                git_command,
                list_issues,
                get_issue,
            ],
            system_message=SOFTWARE_ENGINEER_SYSTEM_PROMPT,
            description="Software Engineer for code implementation, bug fixes, and pull requests.",
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
        Run a task with the Software Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (issue number, PR number, etc.)

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="autogen",
            role="software_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        result: TaskResult = await self.agent.run(task=task)

        response = ""
        if result.messages:
            for msg in reversed(result.messages):
                if hasattr(msg, "content") and msg.content:
                    response = str(msg.content)
                    break

        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "autogen",
            "agent": "software_engineer",
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


def create_software_engineer(
    config: AgentConfig | None = None,
) -> AutoGenSoftwareEngineer:
    """Factory function to create Software Engineer agent."""
    return AutoGenSoftwareEngineer(config)
