"""Responsibility detection for proactive agent task ownership.

This module provides the ResponsibilityDetector class which determines
whether an agent should claim responsibility for a given task.

Two modes of operation:
1. Legacy mode: Returns ResponsibilityClaim (dataclass) - for backward compatibility
2. Structured mode: Returns ClaimDecision (Pydantic) - for multi-agent arbitration
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibeteam.lib.channel import ChannelMessage
    from vibeteam.lib.schemas import ClaimDecision


# Role-specific keywords for fast-path matching
ROLE_KEYWORDS: dict[str, list[str]] = {
    "software_engineer": [
        "code",
        "bug",
        "fix",
        "implement",
        "pr",
        "pull request",
        "test",
        "refactor",
        "function",
        "class",
        "method",
        "api",
        "endpoint",
        "error",
        "exception",
        "debug",
        "feature",
        "patch",
    ],
    "release_engineer": [
        "deploy",
        "deployment",
        "release",
        "kubernetes",
        "k8s",
        "infrastructure",
        "ci",
        "cd",
        "pipeline",
        "staging",
        "production",
        "rollback",
        "helm",
        "docker",
        "container",
        "cluster",
        "pod",
    ],
    "support_engineer": [
        "customer",
        "email",
        "sentry",
        "error",
        "ticket",
        "support",
        "complaint",
        "issue",
        "outage",
        "incident",
        "user",
        "affected",
        "report",
        "notification",
    ],
    "product_manager": [
        "feature",
        "requirement",
        "backlog",
        "prioritize",
        "roadmap",
        "spec",
        "story",
        "epic",
        "milestone",
        "planning",
        "stakeholder",
        "customer request",
    ],
    "marketing_manager": [
        "announce",
        "announcement",
        "social",
        "post",
        "content",
        "launch",
        "blog",
        "newsletter",
        "twitter",
        "linkedin",
        "marketing",
        "campaign",
        "brand",
    ],
}

# Role mention patterns (case-insensitive)
ROLE_MENTION_PATTERNS: dict[str, list[str]] = {
    "software_engineer": ["softwareengineer", "swe", "software_engineer", "dev", "developer"],
    "release_engineer": ["releaseengineer", "release_engineer", "devops", "sre", "ops"],
    "support_engineer": ["supportengineer", "support_engineer", "support"],
    "product_manager": ["productmanager", "product_manager", "pm"],
    "marketing_manager": ["marketingmanager", "marketing_manager", "marketing"],
}


@dataclass
class ResponsibilityClaim:
    """Result of responsibility evaluation."""

    should_claim: bool
    confidence: float  # 0.0 to 1.0
    reasoning: str = ""
    estimated_effort: str = "unknown"  # small, medium, large, unknown

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "should_claim": self.should_claim,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "estimated_effort": self.estimated_effort,
        }


@dataclass
class ResponsibilityDetector:
    """Determines if an agent should claim responsibility for a task.

    Uses a multi-step approach:
    1. Direct mention check (highest priority)
    2. Keyword matching (fast path)
    3. LLM-based inference (if enabled and keywords suggest relevance)

    Attributes:
        agent_role: The role of the agent (e.g., "software_engineer")
        keywords: Keywords that suggest this agent should handle the task
        mention_patterns: Patterns that indicate direct mention of this agent
        llm_model: LLM model for inference (optional)
        keyword_threshold: Minimum keyword score to trigger LLM evaluation
        use_llm: Whether to use LLM for uncertain cases
    """

    agent_role: str
    keywords: list[str] = field(default_factory=list)
    mention_patterns: list[str] = field(default_factory=list)
    llm_model: str = "azure/gpt-5-2"
    keyword_threshold: float = 0.3
    use_llm: bool = False  # Disabled by default for testing

    def __post_init__(self):
        """Initialize keywords and patterns from defaults if not provided."""
        if not self.keywords:
            self.keywords = ROLE_KEYWORDS.get(self.agent_role, [])
        if not self.mention_patterns:
            self.mention_patterns = ROLE_MENTION_PATTERNS.get(self.agent_role, [])

    async def should_claim(self, message: ChannelMessage | str) -> ResponsibilityClaim:
        """Evaluate if this agent should work on this message.

        Args:
            message: The message to evaluate (ChannelMessage or string content)

        Returns:
            ResponsibilityClaim with decision, confidence, and reasoning
        """
        # Extract content from message
        if isinstance(message, str):
            content = message
            mentions: list[str] = []
        else:
            content = message.content
            mentions = message.mentions

        content_lower = content.lower()

        # Step 1: Direct mention check (highest priority)
        if self._is_directly_mentioned(mentions, content_lower):
            return ResponsibilityClaim(
                should_claim=True,
                confidence=1.0,
                reasoning=f"Directly mentioned as @{self.agent_role}",
                estimated_effort="unknown",
            )

        # Step 2: Keyword matching (fast path)
        keyword_score = self._keyword_score(content_lower)

        if keyword_score >= 0.5:
            # Moderate to high keyword match - claim
            return ResponsibilityClaim(
                should_claim=True,
                confidence=keyword_score,
                reasoning=f"Keyword match ({keyword_score:.2f})",
                estimated_effort=self._estimate_effort(content_lower),
            )

        # Step 3: LLM-based inference (if enabled and score is moderate)
        if self.use_llm and keyword_score >= self.keyword_threshold:
            return await self._llm_evaluate(content)

        # No match
        if keyword_score > 0:
            return ResponsibilityClaim(
                should_claim=False,
                confidence=1 - keyword_score,
                reasoning=f"Weak keyword match ({keyword_score:.2f}), not claiming",
            )

        return ResponsibilityClaim(
            should_claim=False,
            confidence=1.0,
            reasoning="No relevant keywords found",
        )

    async def evaluate(self, message: ChannelMessage | str) -> ClaimDecision:
        """Evaluate if this agent should claim responsibility (structured output).

        This method returns a ClaimDecision (Pydantic model) suitable for
        multi-agent arbitration. Use this instead of should_claim() when
        you need to compare decisions across multiple agents.

        Args:
            message: The message to evaluate (ChannelMessage or string content)

        Returns:
            ClaimDecision with full structured decision data
        """
        # Import here to avoid circular imports
        from vibeteam.lib.schemas import ClaimDecision

        # Get the legacy claim result
        claim = await self.should_claim(message)

        # Extract content for signal detection
        if isinstance(message, str):
            content = message
        else:
            content = message.content
        content_lower = content.lower()

        # Find matching keywords as relevance signals
        relevance_signals = []
        for keyword in self.keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, content_lower):
                relevance_signals.append(f"contains '{keyword}'")

        # Map effort to new schema values
        effort_map = {
            "small": "trivial",
            "medium": "moderate",
            "large": "complex",
            "unknown": "unknown",
        }
        estimated_effort = effort_map.get(claim.estimated_effort, "unknown")

        # Determine if can assist (for collaborative mode)
        # Agent can assist if there's some keyword relevance but not claiming
        can_assist = not claim.should_claim and len(relevance_signals) > 0

        return ClaimDecision(
            agent_id=self.agent_role,
            should_claim=claim.should_claim,
            confidence=claim.confidence,
            relevance_signals=relevance_signals,
            reasoning=claim.reasoning,
            can_assist=can_assist,
            assistance_type="advise" if can_assist else None,
            estimated_effort=estimated_effort,  # type: ignore[arg-type]
        )

    def _is_directly_mentioned(self, mentions: list[str], content_lower: str) -> bool:
        """Check if this agent is directly mentioned.

        Args:
            mentions: Extracted mentions from message
            content_lower: Lowercase message content

        Returns:
            True if directly mentioned
        """
        # Check extracted mentions
        for mention in mentions:
            mention_lower = mention.lower()
            if mention_lower in self.mention_patterns:
                return True
            if mention_lower == self.agent_role.lower():
                return True
            if mention_lower == self.agent_role.replace("_", "").lower():
                return True

        # Check content for @mention patterns
        for pattern in self.mention_patterns:
            if f"@{pattern}" in content_lower:
                return True

        return False

    def _keyword_score(self, content_lower: str) -> float:
        """Calculate keyword match score.

        Args:
            content_lower: Lowercase message content

        Returns:
            Score between 0.0 and 1.0
        """
        if not self.keywords:
            return 0.0

        # Count matching keywords
        matches = 0
        for keyword in self.keywords:
            # Use word boundary matching for better precision
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, content_lower):
                matches += 1

        # Normalize by expected number of keywords for a relevant message
        # A single keyword match indicates some relevance (score=0.5)
        # Two keywords indicate strong relevance (score=1.0)
        if matches == 0:
            return 0.0
        normalized_score = min(1.0, matches / 2.0)
        return normalized_score

    def _estimate_effort(self, content_lower: str) -> str:
        """Estimate effort level based on content.

        Args:
            content_lower: Lowercase message content

        Returns:
            Effort level: "small", "medium", "large", or "unknown"
        """
        # Simple heuristics for effort estimation
        large_indicators = [
            "multiple",
            "all",
            "every",
            "refactor",
            "redesign",
            "migrate",
            "architecture",
            "major",
        ]
        small_indicators = ["quick", "simple", "small", "minor", "typo", "single", "one"]

        for indicator in large_indicators:
            if indicator in content_lower:
                return "large"

        for indicator in small_indicators:
            if indicator in content_lower:
                return "small"

        return "medium"

    async def _llm_evaluate(self, content: str) -> ResponsibilityClaim:
        """Use LLM to evaluate responsibility.

        Args:
            content: Message content to evaluate

        Returns:
            ResponsibilityClaim based on LLM evaluation
        """
        try:
            import litellm

            prompt = f"""You are a {self.agent_role.replace("_", " ")} in a software team.

Evaluate if the following message is something YOU should handle based on your role:

Message: "{content}"

Your role responsibilities:
{", ".join(self.keywords[:10])}

Respond with JSON:
{{"should_claim": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation", "effort": "small/medium/large"}}
"""

            response = await litellm.acompletion(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=200,
            )

            # Parse response
            import json

            result_text = response.choices[0].message.content.strip()
            # Extract JSON from response
            json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return ResponsibilityClaim(
                    should_claim=result.get("should_claim", False),
                    confidence=result.get("confidence", 0.5),
                    reasoning=result.get("reasoning", "LLM evaluation"),
                    estimated_effort=result.get("effort", "unknown"),
                )

        except Exception as e:
            # Fall back to keyword-only if LLM fails
            return ResponsibilityClaim(
                should_claim=False,
                confidence=0.5,
                reasoning=f"LLM evaluation failed: {e}",
            )

        return ResponsibilityClaim(
            should_claim=False,
            confidence=0.5,
            reasoning="Could not parse LLM response",
        )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ResponsibilityDetector(role={self.agent_role!r}, "
            f"keywords={len(self.keywords)}, use_llm={self.use_llm})"
        )
