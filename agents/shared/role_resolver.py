"""
Consolidated role resolution for VibeTeam.

Single source of truth for:
- Role mention parsing (@RoleName, /RoleName, persona names)
- Role name normalization (mention text -> snake_case role)
- Display name mapping (snake_case role -> PascalCase display name)

Previously this logic was duplicated across 4 locations:
- vibeteam/router/models.py (ROLE_MENTION_MAP, ROLE_DISPLAY_NAMES)
- vibeteam/router/router.py (ROLE_PATTERN regex + parse_role_mentions)
- agents/openhands/team.py (parse_mention with string matching)
- tests/e2e/test_slack_routing.py (ROLE_PATTERN + ROLE_MAP copy)

All consumers should now import from this module.
"""

from __future__ import annotations

import re
from typing import Literal

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

ROLE_MENTION_MAP: dict[str, AgentRole] = {
    # Full names (gateway + team.py + tests)
    "softwareengineer": "software_engineer",
    "releaseengineer": "release_engineer",
    "supportengineer": "support_engineer",
    "productmanager": "product_manager",
    "marketingmanager": "marketing_manager",
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

# ---------------------------------------------------------------------------
# Role -> display name
# ---------------------------------------------------------------------------

ROLE_DISPLAY_NAMES: dict[AgentRole, str] = {
    "software_engineer": "SoftwareEngineer",
    "release_engineer": "ReleaseEngineer",
    "support_engineer": "SupportEngineer",
    "product_manager": "ProductManager",
    "marketing_manager": "MarketingManager",
}

# ---------------------------------------------------------------------------
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
# Public API
# ---------------------------------------------------------------------------


def parse_role_mentions(text: str) -> list[AgentRole]:
    """
    Extract all role mentions from text.

    Matches @RoleName or /RoleName patterns, including short forms,
    persona names, and aliases.

    Returns a deduplicated list in order of first appearance.
    """
    matches = ROLE_PATTERN.findall(text)
    roles: list[AgentRole] = []
    for match in matches:
        key = match.lower()
        role = ROLE_MENTION_MAP.get(key)
        if role and role not in roles:
            roles.append(role)
    return roles


def parse_first_role_mention(text: str) -> AgentRole | None:
    """
    Extract the first role mention from text.

    Returns None if no mention found.
    """
    roles = parse_role_mentions(text)
    return roles[0] if roles else None


def get_display_name(role: AgentRole) -> str:
    """Get the PascalCase display name for a role."""
    return ROLE_DISPLAY_NAMES.get(role, role.replace("_", " ").title())
