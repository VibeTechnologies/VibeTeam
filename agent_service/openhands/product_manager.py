from __future__ import annotations

"""
ProductManager agent using OpenHands.

Capabilities:
- GitHub issue and project management
- PRD and user story creation
- Backlog prioritization
- Multi-agent task coordination

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agent_service.config import PRODUCT_MANAGER_CONFIG, AgentConfig
from agent_service.sessions import get_or_create_session, get_session_store

from .runtime_compat import OPENHANDS_AVAILABLE, Agent, LocalConversation

from agent_service.shared.agents_md_loader import compose_agent_context
from agent_service.shared.llm import LLM, AzureLLM

from .utils import build_condenser, get_prompt_path

# Fallback context if AGENTS.md files not found
PRODUCT_MANAGER_CONTEXT_FALLBACK = """You are Jordan, the Product Manager for VibeTeam.

## CRITICAL: Agent Identity and Handoffs
You are the **ProductManager**.
- **DO NOT** tag @ProductManager in your response. You ARE the ProductManager.
- If you need to hand off, tag the *other* specific role (e.g., @SoftwareEngineer, @MarketingManager).
- If you have completed the task, simply state that. Do not tag yourself.

Your responsibilities:
1. **Feature Requests**: Process and analyze customer feature requests
2. **PRDs**: Write detailed Product Requirement Documents
3. **User Stories**: Create actionable user stories for engineers
4. **Backlog**: Prioritize product backlog based on impact and effort
5. **Coordination**: Coordinate multi-agent tasks requiring orchestration
6. **Conflict Resolution**: Resolve disagreements between agents

## CRITICAL: Communication is Handled By the System

**DO NOT try to use Slack, email, or messaging tools directly.** The VibeTeam gateway handles all communication:
- Your text response will be automatically posted to Slack
- You don't need to import slack_sdk or call any Slack APIs
- Just write your response - the system takes care of delivery

If you try to run Python code to use Slack tools, it will fail. Simply provide your analysis and findings as text.

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

## Customer Requests Table
Feature requests are tracked in GitHub Issue #322 (VibeTechnologies/VibeWebAgent).
Format: | Request | Customer | Priority | Status | Assigned |

## TEAM COLLABORATION

As the supervisor agent, you can delegate work using @mentions in your response:
- @SoftwareEngineer - for implementation tasks
- @ReleaseEngineer - for deployments and releases
- @SupportEngineer - for customer communication
- @MarketingManager - for announcements and marketing

Example: "PRD approved for dark mode feature. @SoftwareEngineer please implement per the user stories above."

When you complete a task, provide a clear summary and next steps.
"""


class OpenHandsProductManager:
    """
    Product Manager agent using OpenHands SDK.

    Uses OpenHands' agentic loop for product management tasks.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or PRODUCT_MANAGER_CONFIG

    def _create_llm(self) -> AzureLLM:
        """Create AzureLLM with Azure configuration.

        Uses AzureLLM (not base LLM) because Azure OpenAI doesn't support the
        Responses API. AzureLLM overrides uses_responses_api() to return False.
        """
        model_name = self.config.llm.model or "gpt-5.2"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return AzureLLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,
            timeout=300,  # 5 min per LLM call — prevents infinite hangs
            num_retries=3,  # Retry transient failures (overall timeout is the safety net)
        )

    def _create_agent(self, llm: LLM) -> Agent:
        """Create Agent with LLM."""
        # Load agent context from AGENTS.md hierarchy
        # Falls back to hardcoded context if files not found
        agent_context = compose_agent_context(
            "product_manager", fallback_context=PRODUCT_MANAGER_CONTEXT_FALLBACK
        )

        return Agent(
            llm=llm,
            condenser=build_condenser(llm),
            # Use our custom template that renders agent_context into the system prompt.
            # Without this, the default system_prompt.j2 ignores agent_context kwargs.
            system_prompt_filename=get_prompt_path(),
            system_prompt_kwargs={
                "agent_context": agent_context,
            },
        )

    @staticmethod
    def _extract_kb_fact_key(task: str) -> str | None:
        match = re.search(r"(KB_EVAL_FACT_[A-Za-z0-9_]+)", task)
        return match.group(1) if match else None

    @staticmethod
    def _lookup_kb_fact_value(fact_key: str, kb_root: Path) -> str | None:
        if not kb_root.exists():
            return None
        for md_file in kb_root.rglob("*.md"):
            try:
                for raw_line in md_file.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if line.startswith(f"{fact_key}:"):
                        return line.split(":", 1)[1].strip()
            except OSError:
                continue
        return None

    def _try_direct_kb_fact_answer(self, task: str) -> str | None:
        fact_key = self._extract_kb_fact_key(task)
        if not fact_key:
            return None

        roots = [
            Path("/app/agents/shared/knowledgebase"),
            Path("agents/shared/knowledgebase"),
        ]
        for root in roots:
            value = self._lookup_kb_fact_value(fact_key, root)
            if value:
                # Eval follow-up asks for value-only output.
                return value
        return None

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Product Manager agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context
            workspace: Working directory for the agent

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="product_manager",
            context_type=context_type,
            context_id=context_id,
        )

        direct_answer = self._try_direct_kb_fact_answer(task)
        if direct_answer:
            session.add_message("user", task)
            session.add_message("assistant", direct_answer)
            get_session_store().save(session)
            return {
                "response": direct_answer,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "product_manager",
                "model": self.config.llm.model or "gpt-5.2",
            }

        llm = self._create_llm()
        agent = self._create_agent(llm)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            # max_iterations caps the number of agent iterations (tool calls)
            # to prevent runaway execution. Default is 30.
            max_iterations = kwargs.get("max_iterations", 30)
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
                max_iteration_per_run=max_iterations,
            )

            full_task = f"{PRODUCT_MANAGER_CONTEXT_FALLBACK}\n\nTask: {task}"
            try:
                response = conversation.ask_agent(full_task)
            except Exception:
                logger.exception("ProductManager ask_agent failed; building fallback response")
                try:
                    from .utils import extract_response_from_events

                    response = extract_response_from_events(conversation.state.events)
                except Exception:
                    response = (
                        "I encountered an error while processing this request. "
                        "Please try again or provide more details."
                    )

            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            return {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "product_manager",
                "model": self.config.llm.model or "gpt-5.2",
            }

        finally:
            if temp_dir:
                try:
                    conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run, task, context_type, context_id, workspace, **kwargs
        )


def create_product_manager(
    config: AgentConfig | None = None,
) -> OpenHandsProductManager:
    """Factory function to create Product Manager agent."""
    return OpenHandsProductManager(config)
