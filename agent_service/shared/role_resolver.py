"""
Consolidated role resolution for VibeTeam.

Single source of truth for:
- Role mention parsing (@RoleName, /RoleName, persona names)
- Role name normalization (mention text -> snake_case role)
- Display name mapping (snake_case role -> PascalCase display name)
- Keyword-based routing (fallback when no @mention)

Previously this logic was duplicated across multiple locations:
- vibeteam/router/models.py (ROLE_MENTION_MAP)
- vibeteam/router/router.py (ROLE_PATTERN regex + parse_role_mentions)
- vibeteam/gateway/routes/slack.py (keyword routing fallback)
- agent_service/openhands/team.py (parse_mention + route_by_keywords)
- tests/e2e/test_slack_routing.py (ROLE_PATTERN + ROLE_MAP copy)

All consumers should now import from this module.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Core type
# ---------------------------------------------------------------------------

AgentRole = Literal[
    "software_engineer",
    "release_engineer",
    "support_engineer",
    "product_manager",
    "marketing_manager",
]

# ---------------------------------------------------------------------------
# Mention-text -> role mapping (superset of all previous systems)
# ---------------------------------------------------------------------------

BASE_ROLE_MENTION_MAP: dict[str, AgentRole] = {
    # Short forms (gateway)
    "swe": "software_engineer",
    "release": "release_engineer",
    "support": "support_engineer",
    "pm": "product_manager",
    "marketing": "marketing_manager",
    # Aliases from team.py
    "dev": "software_engineer",
    "product": "product_manager",
    # Persona names from team.py
    "einstein": "release_engineer",
    "ada": "marketing_manager",
    "grace": "support_engineer",
    # Aliases from slack_tools.py
    "marketer": "marketing_manager",
    "supervisor": "product_manager",
}


@lru_cache(maxsize=1)
def _load_agents_yaml() -> dict:
    path = Path(os.environ.get("AGENTS_CONFIG_PATH", "agents/agents.yaml"))
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_handle_map() -> dict[str, AgentRole]:
    config = _load_agents_yaml()
    agents = config.get("agents", {}) if isinstance(config, dict) else {}
    handle_map: dict[str, AgentRole] = {}
    if not isinstance(agents, dict):
        return handle_map
    for role, cfg in agents.items():
        if not isinstance(cfg, dict):
            continue
        handle = cfg.get("slack_handle")
        if not handle:
            continue
        key = re.sub(r"\\W+", "", str(handle)).lower()
        if key:
            handle_map[key] = role  # type: ignore[assignment]
    return handle_map


ROLE_MENTION_MAP: dict[str, AgentRole] = {
    **_load_handle_map(),
    **BASE_ROLE_MENTION_MAP,
}

# Compiled regex (matches all keys from ROLE_MENTION_MAP after @ or /)
# ---------------------------------------------------------------------------

# Build alternation from all mention keys, longest first to avoid partial matches.
# For example, "softwareengineer" must be tried before "software".
_mention_keys = sorted(ROLE_MENTION_MAP.keys(), key=len, reverse=True)
_alternation = "|".join(re.escape(k) for k in _mention_keys)

ROLE_PATTERN = re.compile(
    rf"[@/]({_alternation})\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# GitHub App bot handles (optional mention aliases)
# ---------------------------------------------------------------------------

_github_bot_pattern = re.compile(
    r"@?(?P<login>vibeteam-[a-z0-9-]+-bot(?:-\d+)?)(?:\[bot\])?",
    re.IGNORECASE,
)

_github_bot_role_hints: list[tuple[str, AgentRole]] = [
    ("swe", "software_engineer"),
    ("software", "software_engineer"),
    ("support", "support_engineer"),
    ("release", "release_engineer"),
    ("product", "product_manager"),
    ("pm", "product_manager"),
    ("marketing", "marketing_manager"),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_role_mentions(text: str) -> list[AgentRole]:
    """
    Extract all role mentions from text.

    Matches @RoleName or /RoleName patterns, including short forms,
    persona names, aliases, and GitHub bot handles.

    Returns a deduplicated list in order of first appearance.
    """
    roles: list[AgentRole] = []
    matches = ROLE_PATTERN.findall(text)
    for match in matches:
        key = match.lower()
        role = ROLE_MENTION_MAP.get(key)
        if role and role not in roles:
            roles.append(role)
    for bot_match in _github_bot_pattern.finditer(text):
        login = bot_match.group("login").lower()
        for hint, role in _github_bot_role_hints:
            if hint in login and role not in roles:
                roles.append(role)
                break
    return roles


def parse_first_role_mention(text: str) -> AgentRole | None:
    """
    Extract the first role mention from text.

    Returns None if no mention found.
    """
    roles = parse_role_mentions(text)
    return roles[0] if roles else None


def get_display_name(role: AgentRole) -> str:
    """Get the Slack handle/display name for a role from agents/agents.yaml."""
    config = _load_agents_yaml()
    agents = config.get("agents", {}) if isinstance(config, dict) else {}
    if isinstance(agents, dict):
        cfg = agents.get(role, {})
        if isinstance(cfg, dict):
            handle = cfg.get("slack_handle")
            if handle:
                return str(handle)
    return role.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Keyword-based routing (fallback when no @mention found)
# ---------------------------------------------------------------------------

# Ordered by specificity: more specific roles first, default (support) last.
# Keywords use word-boundary regex matching to avoid false positives
# (e.g., "pr" should not match inside "sprint" or "prioritize").
KEYWORD_ROUTING: list[tuple[AgentRole, list[str]]] = [
    (
        "release_engineer",
        [
            "deploy",
            "release",
            "k8s",
            "kubernetes",
            "pipeline",
            "ci/cd",
            "build",
            "version",
            "infrastructure",
            "production",
            "sentry",
            "error",
            "crash",
            "exception",
        ],
    ),
    (
        "software_engineer",
        [
            "code",
            "implement",
            "refactor",
            "debug",
            "fix bug",
            "pull request",
            "review code",
            "unit test",
            "function",
            "class",
            "api",
            "bug",
        ],
    ),
    (
        "product_manager",
        [
            "roadmap",
            "prioritize",
            "feature request",
            "user story",
            "requirements",
            "stakeholder",
            "product manager",
            "backlog",
            "sprint",
            "prd",
        ],
    ),
    (
        "marketing_manager",
        [
            "tweet",
            "linkedin",
            "social media",
            "blog",
            "announcement",
            "marketing",
            "brand",
        ],
    ),
    (
        "support_engineer",
        [
            "email",
            "customer",
            "support",
            "ticket",
            "calendar",
            "meeting",
            "langfuse",
            "schedule",
        ],
    ),
]

# Pre-compile keyword patterns with word boundaries for each role.
_KEYWORD_PATTERNS: list[tuple[AgentRole, re.Pattern[str]]] = [
    (
        role,
        re.compile(
            r"|".join(rf"\b{re.escape(kw)}\b" for kw in keywords),
            re.IGNORECASE,
        ),
    )
    for role, keywords in KEYWORD_ROUTING
]

DEFAULT_ROLE: AgentRole = "support_engineer"


def route_by_keywords(text: str) -> AgentRole:
    """
    Route to an agent role based on keyword matching.

    Used as a fallback when no @mention is found in the message.
    Checks keywords in order of specificity (release > software >
    product > marketing > support) and returns the first match.
    Falls back to support_engineer if no keywords match.

    Uses word-boundary regex to prevent false positives from substring
    matches (e.g., "pr" won't match inside "sprint" or "prioritize").

    Args:
        text: Message text to analyze.

    Returns:
        The matched agent role.
    """
    for role, pattern in _KEYWORD_PATTERNS:
        if pattern.search(text):
            return role

    return DEFAULT_ROLE
