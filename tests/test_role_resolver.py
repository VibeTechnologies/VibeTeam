"""
Unit tests for the consolidated role resolver.

Tests that all mention patterns from all previous systems are recognized.
"""

from __future__ import annotations

import re

import pytest

from agent_service.shared.role_resolver import (
    KEYWORD_ROUTING,
    ROLE_MENTION_MAP,
    ROLE_PATTERN,
    get_display_name,
    parse_first_role_mention,
    parse_role_mentions,
    route_by_keywords,
)
from vibeteam.agents_config import get_slack_handle


def _handle_key(role: str) -> str:
    handle = get_slack_handle(role) or role
    return re.sub(r"\\W+", "", handle).lower()


class TestRoleMentionMap:
    """Verify ROLE_MENTION_MAP contains all expected aliases."""

    def test_full_names(self):
        assert ROLE_MENTION_MAP[_handle_key("software_engineer")] == "software_engineer"
        assert ROLE_MENTION_MAP[_handle_key("release_engineer")] == "release_engineer"
        assert ROLE_MENTION_MAP[_handle_key("support_engineer")] == "support_engineer"
        assert ROLE_MENTION_MAP[_handle_key("product_manager")] == "product_manager"
        assert ROLE_MENTION_MAP[_handle_key("marketing_manager")] == "marketing_manager"

    def test_short_forms(self):
        assert ROLE_MENTION_MAP["swe"] == "software_engineer"
        assert ROLE_MENTION_MAP["release"] == "release_engineer"
        assert ROLE_MENTION_MAP["support"] == "support_engineer"
        assert ROLE_MENTION_MAP["pm"] == "product_manager"
        assert ROLE_MENTION_MAP["marketing"] == "marketing_manager"

    def test_persona_names(self):
        assert ROLE_MENTION_MAP["einstein"] == "release_engineer"
        assert ROLE_MENTION_MAP["ada"] == "marketing_manager"
        assert ROLE_MENTION_MAP["grace"] == "support_engineer"

    def test_extra_aliases(self):
        assert ROLE_MENTION_MAP["dev"] == "software_engineer"
        assert ROLE_MENTION_MAP["product"] == "product_manager"
        assert ROLE_MENTION_MAP["marketer"] == "marketing_manager"
        assert ROLE_MENTION_MAP["supervisor"] == "product_manager"


class TestParseRoleMentions:
    """Test parse_role_mentions() with various input patterns."""

    # --- @ prefix patterns (gateway + team.py) ---

    @pytest.mark.parametrize(
        "text,expected",
        [
            (f"@{get_slack_handle('software_engineer') or 'SoftwareEngineer'} please fix this", ["software_engineer"]),
            (f"@{get_slack_handle('release_engineer') or 'ReleaseEngineer'} deploy v2.1", ["release_engineer"]),
            (f"@{get_slack_handle('support_engineer') or 'SupportEngineer'} check Sentry", ["support_engineer"]),
            (f"@{get_slack_handle('product_manager') or 'ProductManager'} prioritize this", ["product_manager"]),
            (f"@{get_slack_handle('marketing_manager') or 'MarketingManager'} draft announcement", ["marketing_manager"]),
        ],
    )
    def test_at_prefix_full_names(self, text, expected):
        assert parse_role_mentions(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@SWE implement the fix", ["software_engineer"]),
            ("@Release deploy now", ["release_engineer"]),
            ("@Support investigate error", ["support_engineer"]),
            ("@PM prioritize", ["product_manager"]),
            ("@Marketing write post", ["marketing_manager"]),
        ],
    )
    def test_at_prefix_short_forms(self, text, expected):
        assert parse_role_mentions(text) == expected

    # --- / prefix patterns (gateway) ---

    @pytest.mark.parametrize(
        "text,expected",
        [
            (f"/{get_slack_handle('software_engineer') or 'SoftwareEngineer'} fix the bug", ["software_engineer"]),
            ("/SWE implement this", ["software_engineer"]),
            ("/PM check roadmap", ["product_manager"]),
        ],
    )
    def test_slash_prefix(self, text, expected):
        assert parse_role_mentions(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@vibeteam-support-bot-260301", ["support_engineer"]),
            ("@vibeteam-support-bot-260301[bot]", ["support_engineer"]),
            ("vibeteam-swe-bot-260301[bot]", ["software_engineer"]),
            ("@vibeteam-release-bot", ["release_engineer"]),
            ("@vibeteam-product-bot-260301", ["product_manager"]),
            ("@vibeteam-marketing-bot-260301", ["marketing_manager"]),
            ("@software-engineer[bot]", ["software_engineer"]),
        ],
    )
    def test_github_bot_mentions(self, text, expected):
        assert parse_role_mentions(text) == expected

    # --- Persona names (team.py) ---

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@einstein deploy the update", ["release_engineer"]),
            ("@ada draft the blog post", ["marketing_manager"]),
            ("@grace check customer email", ["support_engineer"]),
        ],
    )
    def test_persona_names(self, text, expected):
        assert parse_role_mentions(text) == expected

    # --- Extra aliases (team.py + slack_tools.py) ---

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@dev implement this feature", ["software_engineer"]),
            ("@product review the backlog", ["product_manager"]),
        ],
    )
    def test_extra_aliases(self, text, expected):
        assert parse_role_mentions(text) == expected

    # --- Case insensitivity ---

    def test_case_insensitive(self):
        handle = get_slack_handle("software_engineer") or "SoftwareEngineer"
        assert parse_role_mentions(f"@{handle.lower()}") == ["software_engineer"]
        assert parse_role_mentions(f"@{handle.upper()}") == ["software_engineer"]
        assert parse_role_mentions(f"@{handle}") == ["software_engineer"]

    # --- Multiple mentions ---

    def test_multiple_mentions(self):
        text = "@SupportEngineer investigate, then @ReleaseEngineer rollback"
        result = parse_role_mentions(text)
        assert result == ["support_engineer", "release_engineer"]

    def test_duplicate_mentions_deduped(self):
        text = "@SupportEngineer check logs @support check again"
        result = parse_role_mentions(text)
        assert result == ["support_engineer"]

    def test_mixed_prefix_mentions(self):
        text = "@SWE fix bug, /PM review, @einstein deploy"
        result = parse_role_mentions(text)
        assert result == ["software_engineer", "product_manager", "release_engineer"]

    # --- No mentions ---

    def test_no_mentions(self):
        assert parse_role_mentions("just a regular message") == []
        assert parse_role_mentions("") == []

    def test_mention_without_prefix(self):
        """Bare role names without @ or / should NOT match."""
        assert parse_role_mentions("SoftwareEngineer fix this") == []

    # --- Word boundary ---

    def test_word_boundary(self):
        """Mentions must end at a word boundary."""
        # "@pm" should match, but "@pms" should not match as "pm"
        assert parse_role_mentions("@pms are busy") == []
        assert parse_role_mentions("@pm is busy") == ["product_manager"]


class TestParseFirstRoleMention:
    """Test parse_first_role_mention()."""

    def test_returns_first(self):
        text = "@SupportEngineer investigate, then @ReleaseEngineer rollback"
        assert parse_first_role_mention(text) == "support_engineer"

    def test_returns_none_when_empty(self):
        assert parse_first_role_mention("no mentions here") is None


class TestGetDisplayName:
    """Test get_display_name()."""

    def test_known_roles(self):
        assert get_display_name("software_engineer") == (get_slack_handle("software_engineer") or "Software Engineer")
        assert get_display_name("release_engineer") == (get_slack_handle("release_engineer") or "Release Engineer")
        assert get_display_name("support_engineer") == (get_slack_handle("support_engineer") or "Support Engineer")
        assert get_display_name("product_manager") == (get_slack_handle("product_manager") or "Product Manager")
        assert get_display_name("marketing_manager") == (get_slack_handle("marketing_manager") or "Marketing Manager")

    def test_fallback_for_unknown(self):
        # Should title-case with underscores replaced
        assert get_display_name("unknown_role") == "Unknown Role"


class TestRolePattern:
    """Verify the compiled regex matches expected patterns."""

    def test_pattern_matches_at_prefix(self):
        handle = get_slack_handle("software_engineer") or "SoftwareEngineer"
        assert ROLE_PATTERN.search(f"@{handle}")
        assert ROLE_PATTERN.search("@swe")
        assert ROLE_PATTERN.search("@einstein")

    def test_pattern_matches_slash_prefix(self):
        handle = get_slack_handle("software_engineer") or "SoftwareEngineer"
        assert ROLE_PATTERN.search(f"/{handle}")
        assert ROLE_PATTERN.search("/pm")

    def test_pattern_rejects_bare_text(self):
        assert ROLE_PATTERN.search("SoftwareEngineer") is None


class TestRouteByKeywords:
    """Verify keyword-based routing works correctly."""

    # -- Release Engineer --
    @pytest.mark.parametrize(
        "text",
        [
            "please deploy this to production",
            "the k8s cluster is down",
            "kubernetes pod restarting",
            "ci/cd pipeline failed",
            "we need a new release",
            "check sentry for errors",
            "there's a crash in production",
            "exception in the infrastructure",
            "can you tag a new version",
            "the build is broken",
        ],
    )
    def test_release_engineer_keywords(self, text):
        assert route_by_keywords(text) == "release_engineer"

    # -- Software Engineer --
    @pytest.mark.parametrize(
        "text",
        [
            "please implement this feature",
            "code review needed",
            "refactor the auth module",
            "there's a bug in the login",
            "create a pull request",
            "write a unit test for this",
            "fix this function",
            "the api is returning wrong data",
            "debug the class constructor",
        ],
    )
    def test_software_engineer_keywords(self, text):
        assert route_by_keywords(text) == "software_engineer"

    # -- Product Manager --
    @pytest.mark.parametrize(
        "text",
        [
            "update the roadmap",
            "prioritize the backlog",
            "write a user story",
            "what are the requirements",
            "create a prd for this",
            "sprint planning",
            "stakeholder meeting notes",
            "file a feature request",
        ],
    )
    def test_product_manager_keywords(self, text):
        assert route_by_keywords(text) == "product_manager"

    # -- Marketing Manager --
    @pytest.mark.parametrize(
        "text",
        [
            "write a blog about the launch",
            "tweet about the new feature",
            "linkedin announcement",
            "social media strategy",
            "brand guidelines",
            "marketing campaign plan",
        ],
    )
    def test_marketing_manager_keywords(self, text):
        assert route_by_keywords(text) == "marketing_manager"

    # -- Support Engineer --
    @pytest.mark.parametrize(
        "text",
        [
            "check the customer email",
            "support ticket needs review",
            "schedule a meeting",
            "calendar invite for tomorrow",
            "check langfuse traces",
        ],
    )
    def test_support_engineer_keywords(self, text):
        assert route_by_keywords(text) == "support_engineer"

    # -- Default fallback --
    def test_default_is_support_engineer(self):
        assert route_by_keywords("hello there") == "support_engineer"
        assert route_by_keywords("what's up") == "support_engineer"
        assert route_by_keywords("") == "support_engineer"

    # -- Case insensitivity --
    def test_case_insensitive(self):
        assert route_by_keywords("DEPLOY TO PRODUCTION") == "release_engineer"
        assert route_by_keywords("Please Implement") == "software_engineer"
        assert route_by_keywords("UPDATE ROADMAP") == "product_manager"

    # -- Word boundary prevents false positives --
    def test_word_boundary_prevents_substring_matches(self):
        """Keywords should match whole words, not substrings."""
        # "sprint" and "prioritize" should match product_manager (explicit keywords),
        # not software_engineer via accidental "pr" substring
        assert route_by_keywords("prioritize the backlog") == "product_manager"
        assert route_by_keywords("sprint planning") == "product_manager"
        # "prd" should match product_manager, not software_engineer via "pr"
        assert route_by_keywords("create a prd") == "product_manager"

    # -- All roles are covered --
    def test_all_roles_have_keywords(self):
        """Every AgentRole should be reachable via keyword routing."""
        roles_in_routing = {role for role, _ in KEYWORD_ROUTING}
        # Default role doesn't need explicit keywords
        roles_in_routing.add("support_engineer")
        expected_roles = {
            "software_engineer",
            "release_engineer",
            "support_engineer",
            "product_manager",
            "marketing_manager",
        }
        assert roles_in_routing == expected_roles
