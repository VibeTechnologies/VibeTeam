"""
ProductManager agent using CrewAI.

Capabilities:
- GitHub issue and project management
- PRD and user story creation
- Backlog prioritization
- Multi-agent task coordination
"""

import os
from typing import Any

from agents.config import PRODUCT_MANAGER_CONFIG, AgentConfig
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


PRODUCT_MANAGER_BACKSTORY = """You are Maya, the Product Manager for VibeTeam.
You have deep expertise in:
- Product strategy and roadmap planning
- Agile methodologies and backlog management
- User research and PRD writing
- Cross-functional team coordination

You make data-driven decisions and prioritize using RICE scoring.
You communicate clearly and ensure all stakeholders are aligned.
"""

PRODUCT_MANAGER_GOAL = """Define product requirements, prioritize features,
coordinate multi-agent tasks, and ensure the VibeTeam platform delivers value to customers."""


class SearchGitHubIssuesTool(BaseTool if CREWAI_AVAILABLE else object):
    """Search GitHub issues."""

    name: str = "search_github_issues"
    description: str = (
        "Search GitHub issues. Input: JSON with 'query' and optional 'repo' keys. "
        "Default repo: VibeTechnologies/VibeTeam"
    )

    def _run(self, input_data: str) -> str:
        """Search issues."""
        import json
        import subprocess

        try:
            data = json.loads(input_data) if input_data.startswith("{") else {"query": input_data}
            query = data.get("query", "")
            repo = data.get("repo", "VibeTechnologies/VibeTeam")

            result = subprocess.run(
                f'gh issue list --repo {repo} --search "{query}" --limit 10',
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return result.stdout if result.stdout else "No issues found"
        except Exception as e:
            return f"Error searching issues: {e}"


class CreateGitHubIssueTool(BaseTool if CREWAI_AVAILABLE else object):
    """Create a GitHub issue."""

    name: str = "create_github_issue"
    description: str = (
        "Create a GitHub issue. Input: JSON with 'title', 'body', optional 'labels' and 'repo' keys."
    )

    def _run(self, input_data: str) -> str:
        """Create issue."""
        import json
        import subprocess

        try:
            data = json.loads(input_data)
            title = data.get("title")
            body = data.get("body", "")
            labels = data.get("labels", "")
            repo = data.get("repo", "VibeTechnologies/VibeTeam")

            if not title:
                return "Error: 'title' is required"

            cmd = f'gh issue create --repo {repo} --title "{title}" --body "{body}"'
            if labels:
                cmd += f' --label "{labels}"'

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return result.stdout.strip()
        except Exception as e:
            return f"Error creating issue: {e}"


class UpdateGitHubIssueTool(BaseTool if CREWAI_AVAILABLE else object):
    """Add a comment to a GitHub issue."""

    name: str = "update_github_issue"
    description: str = (
        "Add a comment to a GitHub issue. Input: JSON with 'issue_number', 'comment', "
        "and optional 'repo' keys."
    )

    def _run(self, input_data: str) -> str:
        """Update issue."""
        import json
        import subprocess

        try:
            data = json.loads(input_data)
            issue_number = data.get("issue_number")
            comment = data.get("comment")
            repo = data.get("repo", "VibeTechnologies/VibeTeam")

            if not issue_number or not comment:
                return "Error: 'issue_number' and 'comment' are required"

            result = subprocess.run(
                f'gh issue comment {issue_number} --repo {repo} --body "{comment}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return f"Comment added to issue #{issue_number}"
        except Exception as e:
            return f"Error commenting on issue: {e}"


class ListProjectBoardTool(BaseTool if CREWAI_AVAILABLE else object):
    """List project board items."""

    name: str = "list_project_board"
    description: str = (
        "List open issues in the project. Input: optional JSON with 'repo' key. "
        "Default repo: VibeTechnologies/VibeTeam"
    )

    def _run(self, input_data: str = "") -> str:
        """List project board."""
        import json
        import subprocess

        try:
            repo = "VibeTechnologies/VibeTeam"
            if input_data:
                try:
                    data = json.loads(input_data)
                    repo = data.get("repo", repo)
                except json.JSONDecodeError:
                    pass

            result = subprocess.run(
                f"gh issue list --repo {repo} --state open --limit 20",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return result.stdout if result.stdout else "No open issues"
        except Exception as e:
            return f"Error listing project board: {e}"


class WriteDocumentTool(BaseTool if CREWAI_AVAILABLE else object):
    """Write a document (PRD, user story, etc.) to a file."""

    name: str = "write_document"
    description: str = "Write a document to a file. Input: JSON with 'path' and 'content' keys."

    def _run(self, input_data: str) -> str:
        """Write document."""
        import json

        try:
            data = json.loads(input_data)
            path = data.get("path")
            content = data.get("content")

            if not path or not content:
                return "Error: 'path' and 'content' are required"

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Document saved to {path}"
        except Exception as e:
            return f"Error writing document: {e}"


class ReadFileTool(BaseTool if CREWAI_AVAILABLE else object):
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


class CrewAIProductManager:
    """Product Manager agent using CrewAI."""

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or PRODUCT_MANAGER_CONFIG
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _create_tools(self) -> list:
        """Create tools for the agent."""
        return [
            SearchGitHubIssuesTool(),
            CreateGitHubIssueTool(),
            UpdateGitHubIssueTool(),
            ListProjectBoardTool(),
            WriteDocumentTool(),
            ReadFileTool(),
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
            role="Product Manager",
            goal=PRODUCT_MANAGER_GOAL,
            backstory=PRODUCT_MANAGER_BACKSTORY,
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
        Run a task with the Product Manager agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="crewai",
            role="product_manager",
            context_type=context_type,
            context_id=context_id,
        )

        # Create task
        crew_task = Task(
            description=task,
            agent=self.agent,
            expected_output="A detailed response with analysis, recommendations, and next steps.",
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
            "agent": "product_manager",
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


def create_product_manager(config: AgentConfig | None = None) -> CrewAIProductManager:
    """Factory function to create Product Manager agent."""
    return CrewAIProductManager(config)
