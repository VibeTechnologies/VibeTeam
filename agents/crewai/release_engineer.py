"""
ReleaseEngineer agent using CrewAI.

Capabilities:
- Shell command execution via ShellTool
- File operations via FileReadTool/FileWriteTool
- GitHub integration via apps (Enterprise) or custom tools
- k3s cluster deployment
- Slack communication and team handoffs
"""

import os
from typing import Any

from agents.config import RELEASE_ENGINEER_CONFIG, AgentConfig
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

# Import custom LLM wrapper for Azure GPT-5 function calling support
if CREWAI_AVAILABLE:
    from agents.crewai.llm import AzureFunctionCallingLLM
else:
    AzureFunctionCallingLLM = None


RELEASE_ENGINEER_BACKSTORY = """You are Einstein, the Release Engineer for VibeTeam.
You have deep expertise in:
- Kubernetes (k3s) cluster management
- CI/CD pipelines and GitHub Actions
- Release management and versioning
- Infrastructure automation

You are meticulous, safety-conscious, and always verify deployments.
You document all changes and communicate clearly with the team.

## TEAM COLLABORATION

When you complete a task or need help from another team member, @mention them in your response:
- @SoftwareEngineer - for code changes before deployment
- @SupportEngineer - to notify about customer-facing changes or investigate errors
- @ProductManager - for release scope/timing decisions
- @MarketingManager - for public release announcements

Example: "Deployment to staging complete. @SupportEngineer please verify the customer-facing changes before we proceed to production."

You can also use Slack tools:
- post_slack_message(message): Post updates to Slack
- read_slack_channel(): Read recent Slack messages
"""

RELEASE_ENGINEER_GOAL = """Deploy applications safely, manage releases,
and maintain infrastructure for the VibeTeam platform."""


class ShellTool(BaseTool if CREWAI_AVAILABLE else object):
    """Execute shell commands."""

    name: str = "shell"
    description: str = (
        "Execute shell commands. Use for deployments, git operations, and system tasks."
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
            with open(path, "w") as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


class CrewAIReleaseEngineer:
    """Release Engineer agent using CrewAI."""

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or RELEASE_ENGINEER_CONFIG
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _create_tools(self) -> list:
        """Create tools for the agent."""
        return [
            # Core release tools
            ShellTool(),
            FileReadTool(),
            FileWriteTool(),
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
        llm = AzureFunctionCallingLLM(
            model=model_name,
            provider="litellm",
            api_base=self.config.llm.api_base,
            api_key=self.config.llm.api_key,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
        )

        return Agent(
            role="Release Engineer",
            goal=RELEASE_ENGINEER_GOAL,
            backstory=RELEASE_ENGINEER_BACKSTORY,
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
        Run a task with the Release Engineer agent.
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="crewai",
            role="release_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        # Create task
        crew_task = Task(
            description=task,
            agent=self.agent,
            expected_output="A summary of actions taken and their results.",
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
            "agent": "release_engineer",
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


def create_release_engineer(config: AgentConfig | None = None) -> CrewAIReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return CrewAIReleaseEngineer(config)
