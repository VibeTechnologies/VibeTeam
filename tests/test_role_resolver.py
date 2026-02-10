"""
Unit tests for the consolidated role resolver.

Tests that all mention patterns from all previous systems are recognized.
"""

from __future__ import annotations

import pytest

from agents.shared.role_resolver import (
    ROLE_DISPLAY_NAMES,
    ROLE_MENTION_MAP,
    ROLE_PATTERN,
    get_display_name,
    parse_first_role_mention,
    parse_role_mentions,
)


class TestRoleMentionMap:
    """Verify ROLE_MENTION_MAP contains all expected aliases."""

    def test_full_names(self):
        assert ROLE_MENTION_MAP["softwareengineer"] == "software_engineer"
        assert ROLE_MENTION_MAP["releaseengineer"] == "release_engineer"
        assert ROLE_MENTION_MAP["supportengineer"] == "support_engineer"
        assert ROLE_MENTION_MAP["productmanager"] == "product_manager"
        assert ROLE_MENTION_MAP["marketingmanager"] == "marketing_manager"

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
            ("@SoftwareEngineer please fix this", ["software_engineer"]),
            ("@ReleaseEngineer deploy v2.1", ["release_engineer"]),
            ("@SupportEngineer check Sentry", ["support_engineer"]),
            ("@ProductManager prioritize this", ["product_manager"]),
            ("@MarketingManager draft announcement", ["marketing_manager"]),
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
            ("/SoftwareEngineer fix the bug", ["software_engineer"]),
            ("/SWE implement this", ["software_engineer"]),
            ("/PM check roadmap", ["product_manager"]),
        ],
    )
    def test_slash_prefix(self, text, expected):
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
        assert parse_role_mentions("@softwareengineer") == ["software_engineer"]
        assert parse_role_mentions("@SOFTWAREENGINEER") == ["software_engineer"]
        assert parse_role_mentions("@SoftwareEngineer") == ["software_engineer"]

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
        assert get_display_name("software_engineer") == "SoftwareEngineer"
        assert get_display_name("release_engineer") == "ReleaseEngineer"
        assert get_display_name("support_engineer") == "SupportEngineer"
        assert get_display_name("product_manager") == "ProductManager"
        assert get_display_name("marketing_manager") == "MarketingManager"

    def test_fallback_for_unknown(self):
        # Should title-case with underscores replaced
        assert get_display_name("unknown_role") == "Unknown Role"


class TestDisplayNames:
    """Verify ROLE_DISPLAY_NAMES covers all 5 roles."""

    def test_all_roles_have_display_names(self):
        expected_roles = {
            "software_engineer",
            "release_engineer",
            "support_engineer",
            "product_manager",
            "marketing_manager",
        }
        assert set(ROLE_DISPLAY_NAMES.keys()) == expected_roles


class TestRolePattern:
    """Verify the compiled regex matches expected patterns."""

    def test_pattern_matches_at_prefix(self):
        assert ROLE_PATTERN.search("@SoftwareEngineer")
        assert ROLE_PATTERN.search("@swe")
        assert ROLE_PATTERN.search("@einstein")

    def test_pattern_matches_slash_prefix(self):
        assert ROLE_PATTERN.search("/SoftwareEngineer")
        assert ROLE_PATTERN.search("/pm")

    def test_pattern_rejects_bare_text(self):
        assert ROLE_PATTERN.search("SoftwareEngineer") is None
