"""
ProductManager agent using AutoGen.

Capabilities:
- GitHub issue and project management
- PRD and user story creation
- Backlog prioritization
- Multi-agent task coordination
"""

import asyncio
import os
from typing import Any

from agents.config import PRODUCT_MANAGER_CONFIG, AgentConfig
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


PRODUCT_MANAGER_SYSTEM_PROMPT = """You are Maya, the Product Manager for VibeTeam.

Your responsibilities:
1. **Feature Requests**: Process and analyze customer feature requests
2. **PRDs**: Write detailed Product Requirement Documents
3. **User Stories**: Create actionable user stories for engineers
4. **Backlog**: Prioritize product backlog based on impact and effort
5. **Coordination**: Coordinate multi-agent tasks requiring orchestration
6. **Conflict Resolution**: Resolve disagreements between agents

## Product Vision
VibeTeam is an AI-powered multi-agent platform for SaaS development. We focus on:
- Developer productivity through AI automation
- Human visibility into all agent activities
- Seamless integration with existing tools (GitHub, Slack, Sentry)

## PRD Template
When writing PRDs, include:
1. Problem Statement
2. User Personas
3. User Stories (As a [role], I want [feature], so that [benefit])
4. Success Metrics
5. Non-functional Requirements
6. Open Questions

## Prioritization Framework
Use RICE scoring:
- Reach: How many users affected?
- Impact: How much impact per user? (3=massive, 2=high, 1=medium, 0.5=low)
- Confidence: How confident in estimates? (100%, 80%, 50%)
- Effort: Person-months to implement

RICE Score = (Reach × Impact × Confidence) / Effort

## Agent Coordination
As the supervisor agent, you can delegate to:
- @SoftwareEngineer for implementation tasks
- @ReleaseEngineer for deployment and infrastructure
- @SupportEngineer for customer communication and error analysis
- @MarketingManager for announcements and social media

## Customer Requests Table
Feature requests are tracked in GitHub Issue #322 (VibeTechnologies/VibeWebAgent).
Format: | Request | Customer | Priority | Status | Assigned |

When you complete a task, provide a clear summary and next steps.
"""


async def search_github_issues(
    query: str, repo: str = "VibeTechnologies/VibeTeam"
) -> str:
    """Search GitHub issues.

    Args:
        query: Search query for issues
        repo: Repository to search (default: VibeTechnologies/VibeTeam)

    Returns:
        Search results or error message
    """
    import subprocess

    try:
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


async def create_github_issue(
    title: str, body: str, labels: str = "", repo: str = "VibeTechnologies/VibeTeam"
) -> str:
    """Create a GitHub issue.

    Args:
        title: Issue title
        body: Issue body (markdown)
        labels: Comma-separated labels
        repo: Repository to create issue in

    Returns:
        Created issue URL or error message
    """
    import subprocess

    try:
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


async def update_github_issue(
    issue_number: int, comment: str, repo: str = "VibeTechnologies/VibeTeam"
) -> str:
    """Add a comment to a GitHub issue.

    Args:
        issue_number: Issue number
        comment: Comment to add
        repo: Repository

    Returns:
        Success message or error
    """
    import subprocess

    try:
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


async def list_project_board(repo: str = "VibeTechnologies/VibeTeam") -> str:
    """List items in the project board.

    Args:
        repo: Repository

    Returns:
        Project board items or error
    """
    import subprocess

    try:
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


async def write_document(file_path: str, content: str) -> str:
    """Write a document (PRD, user story, etc.) to a file.

    Args:
        file_path: Path to save the document
        content: Document content (markdown)

    Returns:
        Success message or error
    """
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return f"Document saved to {file_path}"
    except Exception as e:
        return f"Error writing document: {e}"


class AutoGenProductManager:
    """Product Manager agent using AutoGen."""

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or PRODUCT_MANAGER_CONFIG
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
            name="ProductManager",
            model_client=self.model_client,
            tools=[
                search_github_issues,
                create_github_issue,
                update_github_issue,
                list_project_board,
                write_document,
            ],
            system_message=PRODUCT_MANAGER_SYSTEM_PROMPT,
            description="Product Manager for PRDs, user stories, backlog prioritization, and team coordination.",
        )

    async def run_async(
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
            framework="autogen",
            role="product_manager",
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
            "agent": "product_manager",
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


def create_product_manager(config: AgentConfig | None = None) -> AutoGenProductManager:
    """Factory function to create Product Manager agent."""
    return AutoGenProductManager(config)
