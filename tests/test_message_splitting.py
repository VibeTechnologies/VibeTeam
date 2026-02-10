"""
Tests for message splitting functionality.

Ensures long messages are split correctly without losing content,
especially handoff mentions at the end.
"""

from vibeteam.gateway.routes.slack import split_long_message


class TestSplitLongMessage:
    """Tests for the split_long_message function."""

    def test_short_message_not_split(self):
        """Short messages should return as single chunk."""
        text = "This is a short message."
        chunks = split_long_message(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_exact_max_size_not_split(self):
        """Message exactly at max size should not be split."""
        text = "x" * 2900
        chunks = split_long_message(text, max_chunk_size=2900)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_message_split_at_newline(self):
        """Long messages should split at newlines when possible."""
        # Create a message with newlines
        part1 = "First part of the message.\n" * 50  # ~1400 chars
        part2 = "Second part of the message.\n" * 50  # ~1450 chars
        part3 = "@SoftwareEngineer please fix this."
        text = part1 + part2 + part3

        chunks = split_long_message(text, max_chunk_size=1500)

        # Should be multiple chunks
        assert len(chunks) >= 2

        # Rejoined should equal original (minus whitespace trimming between chunks)
        rejoined = "".join(chunks)
        # Allow for whitespace differences due to lstrip()
        assert rejoined.replace(" ", "").replace("\n", "") == text.replace(" ", "").replace(
            "\n", ""
        )

    def test_handoff_mention_preserved(self):
        """Handoff mentions at end of message must not be lost."""
        # Create a long message with handoff at the end
        long_content = "Investigation results:\n" + ("This is detailed analysis. " * 200)
        handoff = "\n\n@SoftwareEngineer please investigate the code bug."
        text = long_content + handoff

        chunks = split_long_message(text, max_chunk_size=2900)

        # Handoff should be in the last chunk
        last_chunk = chunks[-1]
        assert "@SoftwareEngineer" in last_chunk, (
            f"Handoff mention lost! Last chunk: {last_chunk[-200:]}"
        )

    def test_very_long_message_multiple_chunks(self):
        """Very long messages should split into multiple chunks."""
        # 10000 chars should be ~4 chunks at 2900 max
        text = "word " * 2000  # ~10000 chars
        chunks = split_long_message(text, max_chunk_size=2900)

        assert len(chunks) >= 3
        # All chunks except last should be close to max size
        for chunk in chunks[:-1]:
            assert len(chunk) <= 2900
            assert len(chunk) >= 1400  # At least half of max

    def test_no_good_break_point(self):
        """Message without spaces or newlines should still split."""
        # Continuous string without breaks
        text = "x" * 6000
        chunks = split_long_message(text, max_chunk_size=2900)

        assert len(chunks) >= 2
        # Should be cut at max size
        assert len(chunks[0]) == 2900

        # All content preserved
        assert "".join(chunks) == text

    def test_split_preserves_all_content(self):
        """Splitting should not lose any content."""
        # Complex message with various content
        text = (
            """## Investigation Report

### Sentry Findings
Found 5 errors in the last hour:
- Error 1: TypeError in api/handler.py
- Error 2: ConnectionError in db/pool.py
- Error 3: TimeoutError in external/stripe.py
- Error 4: ValidationError in models/user.py
- Error 5: PermissionError in auth/middleware.py

### kubectl Findings
All pods running normally. No restarts detected.

### Endpoint Test
curl returned HTTP 404 for /stripe/webhook

### Recommendation
This appears to be a code bug. The /stripe/webhook endpoint is not registered.

@SoftwareEngineer please investigate the missing route in the API gateway.
"""
            * 5
        )  # Make it long enough to need splitting

        chunks = split_long_message(text, max_chunk_size=2900)

        # Rejoin and verify content
        rejoined = " ".join(chunks)  # Account for lstrip between chunks

        # Key content should be preserved
        assert "Investigation Report" in rejoined
        assert "@SoftwareEngineer" in rejoined
        assert "HTTP 404" in rejoined

    def test_empty_message(self):
        """Empty message should return single empty chunk."""
        chunks = split_long_message("")
        assert len(chunks) == 1
        assert chunks[0] == ""

    def test_whitespace_only_message(self):
        """Whitespace-only message should be handled."""
        chunks = split_long_message("   \n\n   ")
        assert len(chunks) >= 1
