"""
Test suite for Issue #125: PPS Large-Result Truncation

Tests the _truncate_with_followon() helper and pagination implementation
across 7 PPS endpoints that return large result sets.

Acceptance criteria:
1. Under-limit: result set < block_size → no followon_note, has_more=false
2. Exactly-at-limit: result set == block_size → no followon_note
3. Over-limit: result set > block_size → has_more=true, correct followon_note with offset
4. Follow-on call: calling again with offset=N returns next page
5. Real store integration: exercise at least ONE tool against live store at localhost:8201
"""

import pytest
import httpx
from pathlib import Path


# ============================================================================
# Unit Tests — Pure _truncate_with_followon() Logic (No Server)
# ============================================================================

def _truncate_with_followon(
    results: list,
    offset: int,
    block_size: int,
    tool_name: str,
) -> dict:
    """
    Pure copy of the helper from server_http.py for unit testing.
    """
    total = len(results)
    page = results[offset: offset + block_size]
    remaining = total - (offset + len(page))
    has_more = remaining > 0
    next_offset = offset + len(page)
    note = (
        f"\n** NOTE: {remaining} more results available. "
        f"Call {tool_name}(offset={next_offset}) for the next block."
        if has_more else None
    )
    return {
        "page": page,
        "count": len(page),
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
        "followon_note": note,
    }


class TestTruncateWithFollowonUnit:
    """Unit tests for _truncate_with_followon() logic."""

    def test_under_limit(self):
        """Acceptance #1: result set < block_size → no followon_note, has_more=false"""
        results = [{"id": i} for i in range(30)]
        output = _truncate_with_followon(results, offset=0, block_size=50, tool_name="test_tool")

        assert output["count"] == 30
        assert output["total_count"] == 30
        assert output["has_more"] is False
        assert output["followon_note"] is None
        assert output["offset"] == 0
        assert len(output["page"]) == 30

    def test_exactly_at_limit(self):
        """Acceptance #2: result set == block_size → no followon_note, has_more=false"""
        results = [{"id": i} for i in range(50)]
        output = _truncate_with_followon(results, offset=0, block_size=50, tool_name="test_tool")

        assert output["count"] == 50
        assert output["total_count"] == 50
        assert output["has_more"] is False
        assert output["followon_note"] is None
        assert output["offset"] == 0
        assert len(output["page"]) == 50

    def test_over_limit(self):
        """Acceptance #3: result set > block_size → has_more=true, correct followon_note"""
        results = [{"id": i} for i in range(125)]
        output = _truncate_with_followon(results, offset=0, block_size=50, tool_name="anchor_search")

        assert output["count"] == 50
        assert output["total_count"] == 125
        assert output["has_more"] is True
        assert output["offset"] == 0
        assert len(output["page"]) == 50

        # Verify followon_note content
        assert output["followon_note"] is not None
        assert "75 more results available" in output["followon_note"]
        assert "anchor_search(offset=50)" in output["followon_note"]

    def test_second_page(self):
        """Acceptance #4: calling with offset=N returns next page"""
        results = [{"id": i} for i in range(125)]

        # First page
        page1 = _truncate_with_followon(results, offset=0, block_size=50, tool_name="test_tool")
        assert page1["page"][0]["id"] == 0
        assert page1["page"][-1]["id"] == 49
        assert page1["has_more"] is True

        # Second page (offset from followon_note would be 50)
        page2 = _truncate_with_followon(results, offset=50, block_size=50, tool_name="test_tool")
        assert page2["page"][0]["id"] == 50
        assert page2["page"][-1]["id"] == 99
        assert page2["offset"] == 50
        assert page2["has_more"] is True
        assert "25 more results available" in page2["followon_note"]
        assert "test_tool(offset=100)" in page2["followon_note"]

        # Third page
        page3 = _truncate_with_followon(results, offset=100, block_size=50, tool_name="test_tool")
        assert page3["page"][0]["id"] == 100
        assert page3["page"][-1]["id"] == 124
        assert len(page3["page"]) == 25
        assert page3["has_more"] is False
        assert page3["followon_note"] is None

    def test_offset_beyond_results(self):
        """Edge case: offset beyond total results → empty page"""
        results = [{"id": i} for i in range(30)]
        output = _truncate_with_followon(results, offset=50, block_size=50, tool_name="test_tool")

        assert output["count"] == 0
        assert output["total_count"] == 30
        assert output["has_more"] is False
        assert output["followon_note"] is None
        assert len(output["page"]) == 0

    def test_empty_results(self):
        """Edge case: no results at all"""
        results = []
        output = _truncate_with_followon(results, offset=0, block_size=50, tool_name="test_tool")

        assert output["count"] == 0
        assert output["total_count"] == 0
        assert output["has_more"] is False
        assert output["followon_note"] is None
        assert len(output["page"]) == 0


# ============================================================================
# Integration Tests — Real PPS Server at localhost:8201 (Lyra)
# ============================================================================

class TestPPSIntegration:
    """
    Acceptance #5: exercise at least ONE tool against actual live store.

    Uses get_turns_since_summary because it has real data in Lyra's DB.
    """

    @pytest.fixture
    def auth_token(self):
        """Read Lyra's entity token from disk."""
        token_path = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra/.entity_token")
        return token_path.read_text().strip()

    @pytest.fixture
    def client(self):
        """HTTP client for PPS server."""
        return httpx.Client(base_url="http://localhost:8201", timeout=30.0)

    def test_get_turns_since_summary_pagination(self, client, auth_token):
        """
        Integration test: get_turns_since_summary with real data.

        Verifies:
        - Response includes has_more, offset, followon_note fields
        - If total_count > limit, followon_note is present with correct offset
        - Second call with offset returns different page
        """
        # First call with small limit to force pagination
        response = client.post(
            "/tools/get_turns_since_summary",
            json={
                "token": auth_token,
                "limit": 10,
                "offset": 0,
            }
        )

        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()

        # Verify pagination fields exist
        assert "has_more" in data
        assert "offset" in data
        assert "followon_note" in data
        assert "total_count" in data
        assert "count" in data
        assert "turns" in data

        print(f"\nFirst call returned {data['count']} turns out of {data['total_count']} total")
        print(f"has_more: {data['has_more']}")
        print(f"followon_note: {data['followon_note']}")

        # If there are more results, test follow-on call
        if data["has_more"]:
            assert data["followon_note"] is not None
            assert "offset=" in data["followon_note"]

            # Parse offset from followon_note
            # Format: "Call get_turns_since_summary(offset=N) for the next block."
            import re
            match = re.search(r"offset=(\d+)", data["followon_note"])
            assert match is not None, f"Could not parse offset from: {data['followon_note']}"
            next_offset = int(match.group(1))

            # Second call with offset
            response2 = client.post(
                "/tools/get_turns_since_summary",
                json={
                    "token": auth_token,
                    "limit": 10,
                    "offset": next_offset,
                }
            )

            assert response2.status_code == 200
            data2 = response2.json()

            print(f"\nSecond call (offset={next_offset}) returned {data2['count']} turns")
            print(f"has_more: {data2['has_more']}")

            # Verify we got different data
            if data["turns"] and data2["turns"]:
                # Compare first turn ID to ensure different pages
                first_page_first_id = data["turns"][0]["id"]
                second_page_first_id = data2["turns"][0]["id"]
                assert first_page_first_id != second_page_first_id, \
                    "Second page returned same data as first page"
        else:
            # If no more results, followon_note should be None
            assert data["followon_note"] is None

    def test_anchor_search_response_structure(self, client, auth_token):
        """
        Verify anchor_search endpoint returns correct pagination fields.
        Uses a generic query that should return some results.
        """
        response = client.post(
            "/tools/anchor_search",
            json={
                "token": auth_token,
                "query": "memory",  # Generic query likely to match something
                "limit": 100,  # Request more than block_size to test pagination
                "offset": 0,
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all pagination fields exist
        assert "has_more" in data
        assert "offset" in data
        assert "followon_note" in data
        assert "total_count" in data
        assert "count" in data
        assert "results" in data

        print(f"\nanchor_search returned {data['count']} results out of {data['total_count']} total")
        print(f"has_more: {data['has_more']}")

        # Verify pagination logic
        if data["total_count"] > 50:  # RESULT_BLOCK_SIZE
            assert data["has_more"] is True
            assert data["followon_note"] is not None
        else:
            assert data["has_more"] is False
            assert data["followon_note"] is None

    def test_texture_search_response_structure(self, client, auth_token):
        """
        Verify texture_search endpoint returns correct pagination fields.
        """
        response = client.post(
            "/tools/texture_search",
            json={
                "token": auth_token,
                "query": "Jeff",  # Should match many entities/facts
                "limit": 100,
                "offset": 0,
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify pagination fields
        required_fields = ["has_more", "offset", "followon_note", "total_count", "count"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        print(f"\ntexture_search returned {data['count']} results out of {data['total_count']} total")
        print(f"has_more: {data['has_more']}")


class TestRealStoreDirectVerification:
    """
    Acceptance #5 (real-data path): exercise _truncate_with_followon against the
    actual SQLite store without requiring Docker rebuild.

    Imports the helper directly from the patched server_http.py and runs it
    on real rows from conversations.db.
    """

    @pytest.fixture(scope="class")
    def helper_and_turns(self):
        """Load the real helper + real rows from Lyra's DB."""
        import sqlite3
        import re
        from pathlib import Path

        project_root = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
        db_path = project_root / "entities/lyra/data/conversations.db"

        # Import helper directly from patched server_http.py
        server_src = (project_root / "pps/docker/server_http.py").read_text()
        const_idx = server_src.index("RESULT_BLOCK_SIZE = 50")
        helper_start = server_src.index("def _truncate_with_followon(")
        helper_end = server_src.index("\n\n\n", helper_start)
        snippet = server_src[const_idx : helper_end + 3]
        ns: dict = {}
        exec(snippet, ns)  # noqa: S102

        fn = ns["_truncate_with_followon"]
        block_size = ns["RESULT_BLOCK_SIZE"]

        # Fetch real unsummarized turns
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT MAX(time_span_end) as last_summary FROM message_summaries")
        row = c.fetchone()
        last_summary_time = row["last_summary"] if row else None

        if last_summary_time:
            c.execute(
                "SELECT author_name, content, created_at, channel FROM messages "
                "WHERE created_at > ? ORDER BY created_at DESC",
                (last_summary_time,),
            )
        else:
            c.execute(
                "SELECT author_name, content, created_at, channel FROM messages "
                "ORDER BY created_at DESC LIMIT 200"
            )
        rows = c.fetchall()
        conn.close()

        turns = [
            {
                "timestamp": r["created_at"][:16] if r["created_at"] else "?",
                "channel": r["channel"] or "",
                "author": r["author_name"] or "Unknown",
                "content": r["content"] or "",
            }
            for r in rows
        ]
        return fn, block_size, turns

    def test_real_store_has_data(self, helper_and_turns):
        _, _, turns = helper_and_turns
        assert len(turns) > 0, "Real store has no unsummarized turns — cannot verify"

    def test_real_store_first_page_structure(self, helper_and_turns):
        """First page returns correct pagination fields."""
        fn, block_size, turns = helper_and_turns
        page1 = fn(turns, offset=0, block_size=block_size, tool_name="get_turns_since_summary")

        assert "page" in page1
        assert "count" in page1
        assert "offset" in page1
        assert "total_count" in page1
        assert "has_more" in page1
        assert "followon_note" in page1
        assert page1["offset"] == 0
        assert page1["total_count"] == len(turns)
        assert page1["count"] == min(block_size, len(turns))

    def test_real_store_pagination_over_limit(self, helper_and_turns):
        """When real store exceeds block_size, has_more=True with correct hint."""
        fn, block_size, turns = helper_and_turns
        if len(turns) <= block_size:
            pytest.skip(f"Real store has only {len(turns)} turns — under block_size {block_size}")

        page1 = fn(turns, offset=0, block_size=block_size, tool_name="get_turns_since_summary")
        assert page1["has_more"] is True
        assert page1["followon_note"] is not None
        assert f"offset={block_size}" in page1["followon_note"]
        remaining = len(turns) - block_size
        assert f"{remaining} more results available" in page1["followon_note"]

    def test_real_store_second_page_disjoint(self, helper_and_turns):
        """Second page returns different items than first page."""
        fn, block_size, turns = helper_and_turns
        if len(turns) <= block_size:
            pytest.skip(f"Real store has only {len(turns)} turns — need more than {block_size}")

        page1 = fn(turns, offset=0, block_size=block_size, tool_name="test")
        page2 = fn(turns, offset=block_size, block_size=block_size, tool_name="test")

        # Pages must be disjoint
        p1_timestamps = {t["timestamp"] + t["content"][:20] for t in page1["page"]}
        p2_timestamps = {t["timestamp"] + t["content"][:20] for t in page2["page"]}
        assert p1_timestamps.isdisjoint(p2_timestamps), "Pages overlap — pagination broken"


if __name__ == "__main__":
    # Run with: pps/venv/bin/python3 pps/tests/test_truncation.py
    pytest.main([__file__, "-v", "-s"])
