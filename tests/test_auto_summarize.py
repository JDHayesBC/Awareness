"""
Tests for check_unsummarized_count() in scripts/auto_summarize.py.

Regression: the old implementation called GET /health which has no 'unsummarized_count'
key, so stats.get("unsummarized_count", 0) always silently returned 0 — the threshold
check never fired and summarization was never triggered.

The fix reads from GET /tools/summary_stats?token=TOKEN which returns:
    {"unsummarized_messages": N, "recent_summaries": N, ...}
and the function now looks up stats.get("unsummarized_messages", 0).

These tests run against live localhost:8201 — no mocking per project rule.
"""

import sys
from pathlib import Path

import pytest

# Allow importing from scripts/ without installing the package
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auto_summarize import check_unsummarized_count


class TestCheckUnsummarizedCount:
    """Tests for check_unsummarized_count() against the live PPS server."""

    def test_returns_nonzero_count(self):
        """
        The fixed implementation reads from /tools/summary_stats and returns
        the real unsummarized message count.

        REGRESSION: the old code used GET /health, which has no
        'unsummarized_count' key, so .get() silently returned 0 every time.
        This asserts the bug is gone: the returned count must be > 0 because
        we know unsummarized messages exist in the live database.
        """
        count = check_unsummarized_count()
        assert count > 0, (
            f"check_unsummarized_count() returned {count}. "
            "A return of 0 is the regression symptom — the function may be "
            "reading from GET /health instead of GET /tools/summary_stats."
        )

    def test_returns_int(self):
        """Return value must be an int (not None, float, str, etc.)."""
        count = check_unsummarized_count()
        assert isinstance(count, int), (
            f"Expected int, got {type(count).__name__}: {count!r}"
        )

    def test_idempotent_across_two_calls(self):
        """
        Calling the function twice in quick succession should return equal
        values (no summarization happens between calls, so the count is stable).
        """
        count_a = check_unsummarized_count()
        count_b = check_unsummarized_count()
        assert count_a == count_b, (
            f"First call returned {count_a}, second call returned {count_b}. "
            "The count should be stable between back-to-back reads."
        )
