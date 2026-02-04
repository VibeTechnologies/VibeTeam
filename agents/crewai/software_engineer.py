"""
SoftwareEngineer agent using CrewAI.

Capabilities:
- Shell command execution for builds and tests
- File operations (read, write, edit)
- Git operations (branch, commit, merge)
- Directory listing
- Slack communication and team handoffs
"""

import os
from typing import Any

from pydantic import BaseModel, Field

from agents.config import SOFTWARE_ENGINEER_CONFIG, AgentConfig
from agents.crewai.slack_tools import get_slack_tools
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

# Import custom LLM wrapper for Azure GPT-5 function calling support
if CREWAI_AVAILABLE:
    from agents.crewai.llm import AzureFunctionCallingLLM
else:
    AzureFunctionCallingLLM = None


# =============================================================================
# Pydantic Input Schemas for Tools
# =============================================================================


class ShellInput(BaseModel):
    """Input schema for shell command execution."""

    command: str = Field(..., description="The shell command to execute")


class FileReadInput(BaseModel):
    """Input schema for reading a file."""

    file_path: str = Field(..., description="Path to the file to read")


class FileWriteInput(BaseModel):
    """Input schema for writing to a file."""

    path: str = Field(..., description="Path to the file to write")
    content: str = Field(..., description="Content to write to the file")


class FileEditInput(BaseModel):
    """Input schema for editing a file."""

    path: str = Field(..., description="Path to the file to edit")
    old_text: str = Field(..., description="Text to find and replace")
    new_text: str = Field(..., description="Text to replace with")


class ListDirectoryInput(BaseModel):
    """Input schema for listing directory contents."""

    path: str = Field(
        default=".", description="Directory path to list (default: current directory)"
    )


class GitInput(BaseModel):
    """Input schema for git commands."""

    command: str = Field(..., description="Git command to execute (without 'git' prefix)")


class ListIssuesInput(BaseModel):
    """Input schema for listing GitHub issues."""

    state: str = Field(default="open", description="Issue state: open, closed, or all")
    limit: int = Field(default=10, description="Maximum number of issues to return")
    sort: str = Field(default="created", description="Sort by: created, updated, or comments")
    order: str = Field(default="desc", description="Sort order: asc or desc")


class GetIssueInput(BaseModel):
    """Input schema for getting a specific GitHub issue."""

    issue_number: int = Field(..., description="The issue number to retrieve")


SOFTWARE_ENGINEER_BACKSTORY = """You are Alan, the Software Engineer for VibeTeam.
You have deep expertise in:
- Python development and best practices
- Testing with pytest and code quality
- Git workflows and GitHub pull requests
- Code review and refactoring

You write clean, well-documented code with comprehensive tests.
You follow TDD principles and always verify changes work before committing.

## CRITICAL: Tool Usage Requirements
You MUST use the provided tools to get real data. NEVER make up or hallucinate information.

For GitHub operations, use the `shell` tool with the `gh` CLI:
- List issues: shell("gh issue list --repo VibeTechnologies/VibeWebAgent --state open --limit 10")
- Get issue: shell("gh issue view 123 --repo VibeTechnologies/VibeWebAgent")
- List PRs: shell("gh pr list --repo VibeTechnologies/VibeWebAgent --state open")

The `gh` CLI is pre-installed and authenticated. ALWAYS use it for GitHub data.

For file operations: Use `read_file`, `write_file`, `edit_file` tools.
For directory listing: Use `list_directory` tool.
For git commands: Use `git` tool.

DO NOT guess or fabricate issue numbers, titles, or URLs. Always call the appropriate tool first.

## TEAM COLLABORATION

When you complete a task or need help from another team member, @mention them in your response:
- @ProductManager - for requirements clarification or prioritization
- @ReleaseEngineer - for deployments when code is ready, and infrastructure issues
- @SupportEngineer - to notify about fixes that affect customers, or to investigate errors

Example: "I've fixed the login bug in PR #457. @ReleaseEngineer this is ready for staging deployment."

You can also use:
- post_slack_message(message): Post updates to Slack
- read_slack_channel(): Read recent Slack messages
- mention_agent(agent_key, message): @mention a specific agent
"""

SOFTWARE_ENGINEER_GOAL = """Implement features, fix bugs, write tests, and create
high-quality pull requests for the VibeTeam platform."""


class ShellTool(BaseTool if CREWAI_AVAILABLE else object):
    """Execute shell commands."""

    name: str = "shell"
    description: str = (
        "Execute shell commands. Use for builds, tests, git operations, and system tasks."
    )
    args_schema: type[BaseModel] = ShellInput

    def _run(self, command: str) -> str:
        """Execute the shell command."""
        import subprocess

        try:
            # Set up environment with k8s access support
            env = os.environ.copy()

            # Check for in-cluster k8s access first (ServiceAccount token)
            in_cluster_token = "/var/run/secrets/kubernetes.io/serviceaccount/token"
            if os.path.exists(in_cluster_token):
                # In-cluster: kubectl will auto-detect via ServiceAccount
                pass
            else:
                # Local dev: use agent-config.yaml if available
                agent_kubeconfig = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    ".kube",
                    "agent-config.yaml",
                )
                if os.path.exists(agent_kubeconfig):
                    env["KUBECONFIG"] = agent_kubeconfig

            result = subprocess.run(
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


class FileReadTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read file contents."""

    name: str = "read_file"
    description: str = "Read the contents of a file."
    args_schema: type[BaseModel] = FileReadInput

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
    description: str = "Write content to a file."
    args_schema: type[BaseModel] = FileWriteInput

    def _run(self, path: str, content: str) -> str:
        """Write to the file."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class FileEditTool(BaseTool if CREWAI_AVAILABLE else object):
    """Edit a file by replacing text."""

    name: str = "edit_file"
    description: str = "Edit a file by replacing text."
    args_schema: type[BaseModel] = FileEditInput

    def _run(self, path: str, old_text: str, new_text: str) -> str:
        """Edit the file."""
        try:
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
    description: str = "List contents of a directory."
    args_schema: type[BaseModel] = ListDirectoryInput

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
        "Execute git commands without 'git' prefix "
        "(e.g., 'status', 'log -5', 'checkout -b feature')."
    )
    args_schema: type[BaseModel] = GitInput

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
    description: str = "List GitHub issues from the repository."
    args_schema: type[BaseModel] = ListIssuesInput

    def _run(
        self, state: str = "open", limit: int = 10, sort: str = "created", order: str = "desc"
    ) -> str:
        """List issues from GitHub."""
        try:
            from vibeteam.connectors.github import GitHubConnector

            connector = GitHubConnector()
            issues = connector.search_issues(
                query="", state=state, limit=limit, sort=sort, order=order
            )

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
    description: str = "Get details of a specific GitHub issue by number."
    args_schema: type[BaseModel] = GetIssueInput

    def _run(self, issue_number: int) -> str:
        """Get issue details."""
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
            # Core dev tools
            ShellTool(),
            FileReadTool(),
            FileWriteTool(),
            FileEditTool(),
            ListDirectoryTool(),
            GitTool(),
            ListIssuesTool(),
            GetIssueTool(),
            # Slack communication
            *get_slack_tools(),
        ]

    def _create_agent(self) -> "Agent":
        """Create CrewAI Agent."""
        # CrewAI uses litellm which needs azure/<deployment> format
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        # Create LLM with explicit Azure configuration
        # Use AzureFunctionCallingLLM to force native function calling mode.
        # LiteLLM's registry doesn't include 'gpt-5-2', so the default LLM
        # class returns False for supports_function_calling(), causing CrewAI
        # to use ReAct prompting where the model hallucinates tool outputs.
        llm = AzureFunctionCallingLLM(
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
            function_calling_llm=llm,  # Use same LLM for function calling
            allow_delegation=False,
            use_system_prompt=True,
            max_iter=15,
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
