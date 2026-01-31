"""Multi-agent claim arbitration.

When multiple agents claim responsibility for a broadcast message,
the arbitrator decides who should act and in what capacity.

Arbitration modes:
- single: One high-confidence claim -> that agent handles it
- collaborative: Multiple claims -> primary agent with assistants
- escalate_to_human: No claims or conflicting claims -> human needed
"""

from __future__ import annotations

from vibeteam.team.schemas import ArbitrationResult, ClaimDecision


def resolve_claims(
    claims: list[ClaimDecision],
    *,
    high_confidence_threshold: float = 0.8,
    claim_threshold: float = 0.5,
    max_assistants: int = 2,
) -> ArbitrationResult:
    """Determine which agents should act on a broadcast message.

    This implements a three-tier arbitration strategy:

    1. **Single high-confidence claim**: If exactly one agent has confidence > 0.8
       and should_claim=True, that agent takes full ownership.

    2. **Collaborative mode**: If multiple agents claim with lower confidence,
       the highest-confidence claimer becomes primary and others can assist.

    3. **Escalate to human**: If no agent claims or there's a conflict that
       can't be resolved automatically.

    Args:
        claims: List of ClaimDecision from all agents
        high_confidence_threshold: Confidence level for single-agent mode (default 0.8)
        claim_threshold: Minimum confidence to be considered a valid claim (default 0.5)
        max_assistants: Maximum number of assistant agents (default 2)

    Returns:
        ArbitrationResult with mode, primary agent, and optional assistants

    Example:
        >>> claims = [
        ...     ClaimDecision(agent_id="support_engineer", should_claim=True, confidence=0.9, ...),
        ...     ClaimDecision(agent_id="software_engineer", should_claim=False, confidence=0.3, can_assist=True, ...),
        ... ]
        >>> result = resolve_claims(claims)
        >>> result.mode
        'single'
        >>> result.primary
        'support_engineer'
    """
    if not claims:
        return ArbitrationResult(
            mode="escalate_to_human",
            primary=None,
            assistants=[],
            reasoning="No agents evaluated the message",
            claim_summary={},
        )

    # Build claim summary
    claim_summary = {c.agent_id: c.confidence for c in claims}

    # Filter to actual claimers (should_claim=True AND confidence >= threshold)
    claimers = [
        c for c in claims if c.should_claim and c.confidence >= claim_threshold
    ]

    # Case 1: No valid claims -> escalate
    if not claimers:
        # Check if anyone can assist even without claiming
        potential_assistants = [c for c in claims if c.can_assist]
        if potential_assistants:
            # Weak match - let highest-confidence assistant handle with advisory
            best = max(potential_assistants, key=lambda c: c.confidence)
            return ArbitrationResult(
                mode="single",
                primary=best.agent_id,
                assistants=[],
                reasoning=f"No strong claims; {best.agent_id} volunteered to assist",
                claim_summary=claim_summary,
            )

        return ArbitrationResult(
            mode="escalate_to_human",
            primary=None,
            assistants=[],
            reasoning="No agent claimed responsibility or offered to assist",
            claim_summary=claim_summary,
        )

    # Case 2: Single high-confidence claim -> single mode
    high_confidence_claims = [
        c for c in claimers if c.confidence >= high_confidence_threshold
    ]

    if len(high_confidence_claims) == 1:
        primary = high_confidence_claims[0]
        # Find potential assistants (can_assist=True, not the primary)
        assistants = [
            c.agent_id
            for c in claims
            if c.can_assist and c.agent_id != primary.agent_id
        ][:max_assistants]

        return ArbitrationResult(
            mode="single",
            primary=primary.agent_id,
            assistants=assistants,
            reasoning=f"High-confidence claim by {primary.agent_id} ({primary.confidence:.2f})",
            claim_summary=claim_summary,
        )

    # Case 3: Multiple high-confidence claims -> need to pick primary
    if len(high_confidence_claims) > 1:
        # Sort by confidence, pick highest
        sorted_claims = sorted(
            high_confidence_claims, key=lambda c: c.confidence, reverse=True
        )
        primary = sorted_claims[0]

        # Other high-confidence claimers become assistants
        assistants = [c.agent_id for c in sorted_claims[1 : max_assistants + 1]]

        return ArbitrationResult(
            mode="collaborative",
            primary=primary.agent_id,
            assistants=assistants,
            reasoning=(
                f"Multiple high-confidence claims; "
                f"{primary.agent_id} ({primary.confidence:.2f}) as primary, "
                f"{len(assistants)} assistants"
            ),
            claim_summary=claim_summary,
        )

    # Case 4: Multiple lower-confidence claims -> collaborative
    if len(claimers) > 1:
        sorted_claims = sorted(claimers, key=lambda c: c.confidence, reverse=True)
        primary = sorted_claims[0]

        # Include other claimers as assistants
        assistants = [c.agent_id for c in sorted_claims[1 : max_assistants + 1]]

        # Also add any agents who offered to assist but didn't claim
        for c in claims:
            if (
                c.can_assist
                and c.agent_id != primary.agent_id
                and c.agent_id not in assistants
                and len(assistants) < max_assistants
            ):
                assistants.append(c.agent_id)

        return ArbitrationResult(
            mode="collaborative",
            primary=primary.agent_id,
            assistants=assistants,
            reasoning=(
                f"Multiple claims with moderate confidence; "
                f"{primary.agent_id} ({primary.confidence:.2f}) leads"
            ),
            claim_summary=claim_summary,
        )

    # Case 5: Single lower-confidence claim -> single mode
    primary = claimers[0]
    assistants = [
        c.agent_id for c in claims if c.can_assist and c.agent_id != primary.agent_id
    ][:max_assistants]

    return ArbitrationResult(
        mode="single",
        primary=primary.agent_id,
        assistants=assistants,
        reasoning=f"Single claim by {primary.agent_id} ({primary.confidence:.2f})",
        claim_summary=claim_summary,
    )


def should_escalate(result: ArbitrationResult) -> bool:
    """Check if an arbitration result requires human escalation.

    Args:
        result: The arbitration result to check

    Returns:
        True if the result requires human intervention
    """
    return result.mode == "escalate_to_human"


def get_active_agents(result: ArbitrationResult) -> list[str]:
    """Get list of all agents that should take action.

    Args:
        result: The arbitration result

    Returns:
        List of agent IDs (primary first, then assistants)
    """
    agents = []
    if result.primary:
        agents.append(result.primary)
    agents.extend(result.assistants)
    return agents
