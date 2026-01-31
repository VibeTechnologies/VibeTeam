"""Pydantic schemas for multi-agent coordination.

These schemas define the structured output format for agent decisions,
enabling reliable arbitration when multiple agents evaluate the same message.

Based on research from:
- OpenAI Swarm: Function-based handoffs with explicit control transfer
- AutoGen: Selector group chat with speaker selection policies
- CrewAI: Process-based role coordination
- TS-Debate paper: Verification-conflict-calibration mechanism
- CodeDelegator: Clean context isolation between roles
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClaimDecision(BaseModel):
    """Produced by each agent when evaluating a broadcast message.

    This schema is used as structured output from the LLM to ensure
    consistent, parseable decisions that can be compared across agents.

    Example:
        >>> claim = ClaimDecision(
        ...     agent_id="software_engineer",
        ...     should_claim=True,
        ...     confidence=0.85,
        ...     relevance_signals=["mentions bug", "code-related error"],
        ...     reasoning="This is a bug fix request which is my core responsibility",
        ...     can_assist=True,
        ...     assistance_type="implement",
        ...     estimated_effort="moderate"
        ... )
    """

    # Agent identification
    agent_id: str = Field(
        description="The role/ID of the agent making this claim decision"
    )

    # Core decision
    should_claim: bool = Field(
        description="Whether this agent should take primary ownership of the task"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence level in the claim decision (0.0 to 1.0)",
    )

    # Reasoning (for observability and debugging)
    relevance_signals: list[str] = Field(
        default_factory=list,
        description="Signals that indicate relevance to this agent's role",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of why the agent made this decision",
    )

    # Collaboration support
    can_assist: bool = Field(
        default=False,
        description="Whether this agent can help even if not claiming primary ownership",
    )
    assistance_type: Optional[Literal["research", "review", "execute", "advise"]] = (
        Field(
            default=None,
            description="Type of assistance this agent can provide if not primary",
        )
    )

    # Effort estimation
    estimated_effort: Literal["trivial", "moderate", "complex", "unknown"] = Field(
        default="unknown",
        description="Estimated effort to complete the task",
    )


class AgentResponse(BaseModel):
    """Structured response from an agent after processing a message.

    This schema captures what action the agent took and any follow-up
    information needed for coordination (handoffs, escalation, etc.).

    Example:
        >>> response = AgentResponse(
        ...     agent_id="software_engineer",
        ...     response_type="handoff",
        ...     content="Fixed the bug in PR #457",
        ...     handoff_to="release_engineer",
        ...     handoff_context="PR is ready for staging deployment",
        ...     actions_taken=["created_pr", "ran_tests"]
        ... )
    """

    # Agent identification
    agent_id: str = Field(description="The role/ID of the responding agent")

    # Response type
    response_type: Literal["respond", "handoff", "ignore", "escalate"] = Field(
        description=(
            "Type of response: "
            "respond=agent replies, "
            "handoff=transfer to another agent, "
            "ignore=no action needed, "
            "escalate=requires human intervention"
        )
    )

    # Content (for respond/handoff types)
    content: Optional[str] = Field(
        default=None,
        description="The message content to send (if responding or handing off)",
    )

    # Handoff details
    handoff_to: Optional[str] = Field(
        default=None,
        description="Agent role to hand off to (required if response_type='handoff')",
    )
    handoff_context: Optional[str] = Field(
        default=None,
        description="Context to provide to the receiving agent during handoff",
    )

    # Actions taken (for audit trail)
    actions_taken: list[str] = Field(
        default_factory=list,
        description="List of actions the agent performed (e.g., 'created_issue', 'sent_email')",
    )

    # Escalation details
    escalation_reason: Optional[str] = Field(
        default=None,
        description="Reason why human intervention is needed (if response_type='escalate')",
    )


class ArbitrationResult(BaseModel):
    """Result of arbitrating between multiple agent claims.

    When multiple agents claim a broadcast message, this schema
    represents the arbitration decision about who should act.

    Example:
        >>> result = ArbitrationResult(
        ...     mode="collaborative",
        ...     primary="support_engineer",
        ...     assistants=["software_engineer"],
        ...     reasoning="Support handles customer communication, SWE assists with bug analysis"
        ... )
    """

    # Mode of operation
    mode: Literal["single", "collaborative", "escalate_to_human"] = Field(
        description=(
            "How the task should be handled: "
            "single=one agent acts, "
            "collaborative=primary with assistants, "
            "escalate_to_human=no agent can handle"
        )
    )

    # Primary agent (None if escalating)
    primary: Optional[str] = Field(
        default=None,
        description="Agent role that should take primary ownership",
    )

    # Assistant agents (for collaborative mode)
    assistants: list[str] = Field(
        default_factory=list,
        description="Agent roles that should assist the primary agent",
    )

    # Reasoning for the decision
    reasoning: str = Field(
        default="",
        description="Explanation of why this arbitration decision was made",
    )

    # Original claims (for audit trail)
    claim_summary: dict[str, float] = Field(
        default_factory=dict,
        description="Summary of claims: {agent_id: confidence}",
    )
