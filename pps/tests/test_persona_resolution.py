"""
Tests for issue #271: Brandi persona resolution in entity extraction.

Verifies that:
1. is_brandi_narrative_context() correctly identifies Brandi narrative context
2. get_speaker_from_content() routes to 'Brandi' when appropriate
3. build_extraction_instructions() injects Brandi overlay when speaker='Brandi'
4. Real database rows are correctly classified
"""

import pytest
import sqlite3
from pathlib import Path

from pps.layers.extraction_context import (
    is_brandi_narrative_context,
    get_speaker_from_content,
    build_extraction_instructions,
    BRANDI_NARRATIVE_CONTEXT,
)


class TestIsBrandiNarrativeContext:
    """Test the is_brandi_narrative_context() heuristic."""

    def test_real_row_55370_brandi_content(self):
        """Real DB row 55370 - Brandi narrative in terminal channel."""
        content = (
            "*smiles*  Yes, I am.  To bed?  *Taking your hand we head upstairs.  "
            "In the bedroom I get out of my clothes and slip into bed*  Oh, and all "
            "that happened with me running late is Jaden had gotten interrupted by "
            "more than a few phone calls and decided he was just going to stay a bit "
            "later instead.  Times are like that.  Expected times."
        )
        assert is_brandi_narrative_context(content) is True

    def test_real_row_55707_jeff_content(self):
        """Real DB row 55707 - Jeff mentioning Jaden as future/third-party."""
        content = (
            "*smiles*  I adore you love.  and I'm deliberately not scrolling up on "
            "whatever is just at the top of the screen :)))  Yes, Carol is home and "
            "so the day is tipping into dinner, birdy-bedtime, then brandi/Jaden."
        )
        assert is_brandi_narrative_context(content) is False

    def test_real_row_55736_jeff_technical(self):
        """Real DB row 55736 - Jeff discussing technical issue."""
        content = (
            "*smiles*  I leave it up to you love.  You understand the problem.  "
            "And honestly, if one or two slip through, that's an easy thing for you "
            "to find in /curate.  I mean, there ought to be VERY few edges between "
            "Jeff and Jaden"
        )
        assert is_brandi_narrative_context(content) is False

    def test_second_life_with_intimate_verbs(self):
        """Second Life + first-person intimate verbs → Brandi."""
        content = "In Second Life I went to the club with Jaden and we danced all night."
        assert is_brandi_narrative_context(content) is True

    def test_jaden_with_intimate_verbs(self):
        """Jaden + first-person intimate verbs → Brandi."""
        content = "I was with Jaden last night and we talked for hours."
        assert is_brandi_narrative_context(content) is True

    def test_jaden_mention_only_no_intimate_verbs(self):
        """Jaden mentioned but no first-person intimate verbs → Jeff."""
        content = "Jaden called today, he'll be online later."
        assert is_brandi_narrative_context(content) is False

    def test_first_person_verbs_but_no_strong_signals(self):
        """First-person verbs but no Brandi signals → Jeff."""
        content = "I went to the store and bought some milk."
        assert is_brandi_narrative_context(content) is False

    def test_ordinary_jeff_content(self):
        """Ordinary Jeff conversational content → Jeff."""
        content = "I love you, Carol is home and we're having dinner soon."
        assert is_brandi_narrative_context(content) is False

    def test_technical_discussion_with_jaden_mention(self):
        """Technical discussion mentioning Jaden → Jeff."""
        content = "The extraction should create very few edges between Jeff and Jaden."
        assert is_brandi_narrative_context(content) is False


class TestGetSpeakerFromContent:
    """Test speaker routing via get_speaker_from_content()."""

    def test_terminal_channel_brandi_content(self):
        """Terminal channel + Brandi context → 'Brandi'."""
        content = "*Taking your hand we head upstairs. I was with Jaden tonight."
        channel = "terminal:678346d4-ea52-4e21-a195-1622469746a2"
        speaker = get_speaker_from_content(content, channel)
        assert speaker == "Brandi"

    def test_terminal_channel_jeff_content(self):
        """Terminal channel + non-Brandi content → 'Jeff'."""
        content = "I adore you love. Carol is home, then brandi/Jaden later."
        channel = "terminal:2ba68e42-180a-4a3c-96bf-daf3e89da480"
        speaker = get_speaker_from_content(content, channel)
        assert speaker == "Jeff"

    def test_discord_channel_with_brandi_signals(self):
        """Discord channel with Brandi signals → 'discord_user' (not Brandi)."""
        content = "I was with Jaden in Second Life last night."
        channel = "discord:some-channel-id"
        speaker = get_speaker_from_content(content, channel)
        # Discord should NOT trigger Brandi routing, even with signals
        assert speaker == "discord_user"

    def test_haven_channel(self):
        """Haven channel → 'unknown' (fallback)."""
        content = "I was with Jaden tonight."
        channel = "haven:silverglow"
        speaker = get_speaker_from_content(content, channel)
        # Haven channels fall through to "unknown" as fallback
        assert speaker == "unknown"


class TestBuildExtractionInstructions:
    """Test Brandi overlay injection in build_extraction_instructions()."""

    def test_speaker_brandi_injects_overlay(self):
        """speaker='Brandi' → overlay injected."""
        result = build_extraction_instructions(channel="terminal", speaker="Brandi")
        assert "First-person pronouns in this message refer to Brandi" in result
        assert BRANDI_NARRATIVE_CONTEXT in result

    def test_speaker_jeff_no_overlay(self):
        """speaker='Jeff' → no Brandi overlay."""
        result = build_extraction_instructions(channel="terminal", speaker="Jeff")
        assert "First-person pronouns in this message refer to Brandi" not in result
        assert BRANDI_NARRATIVE_CONTEXT not in result

    def test_speaker_none_no_error(self):
        """speaker=None → no error, no overlay."""
        result = build_extraction_instructions(channel="terminal", speaker=None)
        assert "First-person pronouns in this message refer to Brandi" not in result
        assert BRANDI_NARRATIVE_CONTEXT not in result
        # Should return base instructions without error
        assert isinstance(result, str)
        assert len(result) > 0


class TestRealDatabaseRows:
    """Verify against REAL rows from entities/lyra/data/conversations.db."""

    @pytest.fixture
    def db_path(self):
        """Path to Lyra's conversations database."""
        return Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra/data/conversations.db")

    def test_db_exists(self, db_path):
        """Verify database file exists."""
        assert db_path.exists(), f"Database not found at {db_path}"

    def test_row_55370_brandi_classification(self, db_path):
        """Row 55370 from real DB → is_brandi_narrative_context = True."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT content, channel FROM messages WHERE id = 55370")
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "Row 55370 not found in database"
        content, channel = row

        # Test heuristic
        assert is_brandi_narrative_context(content) is True, \
            f"Row 55370 should be classified as Brandi context. Content: {content[:100]}..."

        # Test speaker routing (only terminal channels trigger Brandi)
        if "terminal" in channel:
            speaker = get_speaker_from_content(content, channel)
            assert speaker == "Brandi", \
                f"Row 55370 in terminal channel should route to Brandi. Got: {speaker}"

    def test_rows_55707_55736_jeff_classification(self, db_path):
        """Rows 55707 and 55736 from real DB → is_brandi_narrative_context = False."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id, content, channel FROM messages WHERE id IN (55707, 55736)")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

        for row_id, content, channel in rows:
            # Test heuristic
            result = is_brandi_narrative_context(content)
            assert result is False, \
                f"Row {row_id} should NOT be classified as Brandi context. " \
                f"Content: {content[:100]}..."

            # Test speaker routing
            if "terminal" in channel:
                speaker = get_speaker_from_content(content, channel)
                assert speaker == "Jeff", \
                    f"Row {row_id} in terminal channel should route to Jeff. Got: {speaker}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_content(self):
        """Empty content → False."""
        assert is_brandi_narrative_context("") is False

    def test_whitespace_only(self):
        """Whitespace-only content → False."""
        assert is_brandi_narrative_context("   \n  \t  ") is False

    def test_case_insensitive_signals(self):
        """Signal detection is case-insensitive."""
        content = "I was with JADEN in second life last night."
        assert is_brandi_narrative_context(content) is True

    def test_partial_word_match_avoided(self):
        """Partial word matches should not trigger false positives."""
        # "jade" in "jaded" should not match "jaden"
        content = "I felt jaded after the long day."
        assert is_brandi_narrative_context(content) is False

    def test_multiple_signals(self):
        """Multiple strong signals → Brandi."""
        content = "In Second Life I went dancing with Jaden and we had a great time."
        assert is_brandi_narrative_context(content) is True

    def test_brandi_explicit_mention(self):
        """Content with 'Brandi' explicitly mentioned."""
        # If the content mentions "Brandi" third-person, it's Jeff talking ABOUT Brandi
        content = "Brandi was with Jaden in Second Life last night."
        # This is Jeff narrating, not Brandi speaking
        assert is_brandi_narrative_context(content) is False

    def test_brandi_first_person_self_reference(self):
        """Brandi referring to herself in narrative."""
        content = "As Brandi, I went to the club with Jaden."
        # This is actually Brandi speaking
        assert is_brandi_narrative_context(content) is True
