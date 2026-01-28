"""
SoftwareEngineer agent using CrewAI.

Capabilities:
- Shell command execution for builds and tests
- File operations (read, write, edit)
- Git operations (branch, commit, merge)
- Directory listing
"""

import os
from typing import Any

from agents.config import SOFTWARE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store

try:
    from crewai import Agent, Crew, Process, Task
    from crewai.llm import LLM
    from crewai.tools import BaseTool

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    Agent = None
    Task = None
    Crew = None
    LLM = None
    BaseTool = object


SOFTWARE_ENGINEER_BACKSTORY = """You are Alan, the Software Engineer for VibeTeam.
You have deep expertise in:
- Python development and best practices
- Testing with pytest and code quality
- Git workflows and GitHub pull requests
- Code review and refactoring

You write clean, well-documented code with comprehensive tests.
You follow TDD principles and always verify changes work before committing.
"""

SOFTWARE_ENGINEER_GOAL = """Implement features, fix bugs, write tests, and create
high-quality pull requests for the VibeTeam platform."""


class ShellTool(BaseTool if CREWAI_AVAILABLE else object):
    """Execute shell commands."""

    name: str = "shell"
    description: str = (
        "Execute shell commands. Use for builds, tests, git operations, and system tasks. "
        "Input: the command string to execute."
    )

    def _run(self, command: str) -> str:
        """Execute the shell command."""
        import subprocess

        try:
            result = subprocess.run(
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


class FileReadTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read file contents."""

    name: str = "read_file"
    description: str = "Read the contents of a file. Input: file path."

    def _run(self, file_path: str) -> str:
        """Read the file."""
        try:
            with open(file_path) as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"


class FileWriteTool(BaseTool if CREWAI_AVAILABLE else object):
    """Write content to a file."""

    name: str = "write_file"
    description: str = "Write content to a file. Input: JSON with 'path' and 'content' keys."

    def _run(self, input_data: str) -> str:
        """Write to the file."""
        import json

        try:
            data = json.loads(input_data)
            path = data.get("path")
            content = data.get("content")
            if not path or content is None:
                return "Error: 'path' and 'content' are required"
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class FileEditTool(BaseTool if CREWAI_AVAILABLE else object):
    """Edit a file by replacing text."""

    name: str = "edit_file"
    description: str = (
        "Edit a file by replacing text. Input: JSON with 'path', 'old_text', and 'new_text' keys."
    )

    def _run(self, input_data: str) -> str:
        """Edit the file."""
        import json

        try:
            data = json.loads(input_data)
            path = data.get("path")
            old_text = data.get("old_text")
            new_text = data.get("new_text")
            if not path or old_text is None or new_text is None:
                return "Error: 'path', 'old_text', and 'new_text' are required"

            with open(path) as f:
                content = f.read()

            if old_text not in content:
                return f"Error: '{old_text[:50]}...' not found in {path}"

            new_content = content.replace(old_text, new_text, 1)

            with open(path, "w") as f:
                f.write(new_content)

            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {e}"


class ListDirectoryTool(BaseTool if CREWAI_AVAILABLE else object):
    """List directory contents."""

    name: str = "list_directory"
    description: str = "List contents of a directory. Input: directory path (default: current dir)."

    def _run(self, path: str = ".") -> str:
        """List the directory."""
        try:
            if not path:
                path = "."
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


class GitTool(BaseTool if CREWAI_AVAILABLE else object):
    """Execute git commands."""

    name: str = "git"
    description: str = (
        "Execute git commands. Input: git command without 'git' prefix "
        "(e.g., 'status', 'log -5', 'checkout -b feature')."
    )

    def _run(self, command: str) -> str:
        """Execute the git command."""
        import subprocess

        try:
            result = subprocess.run(
                f"git {command}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\nReturn code: {result.returncode}"
            return output
        except subprocess.TimeoutExpired:
            return "Git command timed out after 60 seconds"
        except Exception as e:
            return f"Error executing git command: {e}"


class ListIssuesTool(BaseTool if CREWAI_AVAILABLE else object):
    """List GitHub issues from the repository."""

    name: str = "list_issues"
    description: str = (
        "List GitHub issues. Input: JSON with optional 'state' (open/closed/all) "
        'and \'limit\' (default: 10). Example: {"state": "open", "limit": 5}'
    )

    def _run(self, input_data: str = "{}") -> str:
        """List issues from GitHub."""
        import json

        try:
            from vibeteam.connectors.github import GitHubConnector

            data = json.loads(input_data) if input_data else {}
            state = data.get("state", "open")
            limit = data.get("limit", 10)

            connector = GitHubConnector()
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


class GetIssueTool(BaseTool if CREWAI_AVAILABLE else object):
    """Get details of a specific GitHub issue."""

    name: str = "get_issue"
    description: str = "Get details of a GitHub issue. Input: issue number as string (e.g., '123')."

    def _run(self, issue_number: str) -> str:
        """Get issue details."""
        try:
            from vibeteam.connectors.github import GitHubConnector

            connector = GitHubConnector()
            issue = connector.get_issue(int(issue_number))

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


class CrewAISoftwareEngineer:
    """Software Engineer agent using CrewAI."""

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or SOFTWARE_ENGINEER_CONFIG
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _create_tools(self) -> list:
        """Create tools for the agent."""
        return [
            ShellTool(),
            FileReadTool(),
            FileWriteTool(),
            FileEditTool(),
            ListDirectoryTool(),
            GitTool(),
            ListIssuesTool(),
            GetIssueTool(),
        ]

    def _create_agent(self) -> "Agent":
        """Create CrewAI Agent."""
        # CrewAI uses litellm which needs azure/<deployment> format
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        # Create LLM with explicit Azure configuration
        llm = LLM(
            model=model_name,
            provider="litellm",
            api_base=self.config.llm.api_base,
            api_key=self.config.llm.api_key,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
        )

        return Agent(
            role="Software Engineer",
            goal=SOFTWARE_ENGINEER_GOAL,
            backstory=SOFTWARE_ENGINEER_BACKSTORY,
            tools=self.tools,
            verbose=self.config.verbose,
            llm=llm,
        )

    def run(
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
            framework="crewai",
            role="software_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        # Create task
        crew_task = Task(
            description=task,
            agent=self.agent,
            expected_output="A summary of actions taken, code changes made, and test results.",
        )

        # Create and run crew
        crew = Crew(
            agents=[self.agent],
            tasks=[crew_task],
            process=Process.sequential,
            verbose=self.config.verbose,
        )

        result = crew.kickoff()

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", str(result))
        get_session_store().save(session)

        return {
            "response": str(result),
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "crewai",
            "agent": "software_engineer",
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, **kwargs)


def create_software_engineer(
    config: AgentConfig | None = None,
) -> CrewAISoftwareEngineer:
    """Factory function to create Software Engineer agent."""
    return CrewAISoftwareEngineer(config)
