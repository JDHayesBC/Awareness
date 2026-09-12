"""
Test suite for Issue #313: ambient_recall query-mode payload capping.

Query mode (non-"startup" context) previously returned `results` /
`summaries` / `unsummarized_turns` with each item's text field completely
uncapped. On a heavy day this ballooned to ~158K chars and blew the MCP
caller's token limit.

Fix under test: `_cap_ambient_query_response()` in server_http.py caps each
item's text field to a small per-item size (default 400 chars), reports
`truncated` + `omitted_counts`, and supports a `full=True` opt-out that
returns the original, uncapped arrays.

These tests import the helper directly from the patched source via an exec
snippet (same pattern as `TestRealStoreDirectVerification` in
test_truncation.py) so they run without a Docker rebuild/restart — the
live container is shared with Caia and restarts are Lyra's coordinated
deploy window, not something a test run should trigger.
"""

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
SERVER_HTTP_PATH = PROJECT_ROOT / "pps/docker/server_http.py"


@pytest.fixture(scope="module")
def cap_fn():
    """Import `_cap_ambient_query_response` + its cap constant directly from source."""
    src = SERVER_HTTP_PATH.read_text()
    const_idx = src.index("AMBIENT_ITEM_TEXT_CAP = 400")
    fn_start = src.index("def _cap_ambient_query_response(")
    fn_end = src.index("\n\n\n", fn_start)
    snippet = src[const_idx: fn_end + 3]

    ns: dict = {}
    exec(snippet, ns)  # noqa: S102
    return ns["_cap_ambient_query_response"], ns["AMBIENT_ITEM_TEXT_CAP"]


def _make_heavy_payload():
    """Synthetic 'heavy day' payload — large enough to reproduce the ~158K blowup."""
    # 25 results (5 layers x limit_per_layer=5), each a hefty chunk of text
    all_results = [
        {
            "content": f"result #{i} " + ("x" * 6000),
            "source": f"src_{i}.md",
            "layer": "rich_texture",
            "relevance_score": 1.0,
            "metadata": {},
        }
        for i in range(25)
    ]
    # 1 summary, still large
    summaries = [
        {"date": "2026-09-01", "channels": "terminal", "text": "s" * 6000}
    ]
    # 15 unsummarized turns, each large
    unsummarized_turns = [
        {
            "timestamp": "2026-09-01T00:00",
            "channel": "terminal",
            "author": "Jeff",
            "content": "t" * 6000,
        }
        for _ in range(15)
    ]
    return all_results, summaries, unsummarized_turns


class TestCapAmbientQueryResponse:
    def test_default_query_mode_caps_payload_size(self, cap_fn):
        """Acceptance: default (non-full) query mode keeps total payload well under
        the reported ~158K blowup. Per-item text caps at ~400 chars mean the total
        is bounded by item count, not by the size of any individual record — this
        synthetic 41-item heavy payload (reproducing the reported blowup shape)
        lands around ~20K, a ~12x reduction from its ~250K uncapped size."""
        fn, item_cap = cap_fn
        all_results, summaries, unsummarized_turns = _make_heavy_payload()

        # Sanity: the uncapped payload really is huge (reproduces the bug).
        uncapped_size = len(json.dumps(
            {"results": all_results, "summaries": summaries, "unsummarized_turns": unsummarized_turns}
        ))
        assert uncapped_size > 150_000, f"Synthetic payload not heavy enough: {uncapped_size}"

        capped = fn(all_results, summaries, unsummarized_turns, item_cap=item_cap, full=False)

        capped_size = len(json.dumps({
            "results": capped["results"],
            "summaries": capped["summaries"],
            "unsummarized_turns": capped["unsummarized_turns"],
        }))
        # Order-of-magnitude reduction, well clear of any per-call token budget.
        assert capped_size <= 25_000, f"Capped payload still too large: {capped_size}"
        assert capped_size < uncapped_size / 5

        assert capped["truncated"] is True
        assert capped["omitted_counts"]["results_truncated"] == 25
        assert capped["omitted_counts"]["summaries_truncated"] == 1
        assert capped["omitted_counts"]["turns_truncated"] == 15

    def test_items_truncated_with_ellipsis_and_cap_length(self, cap_fn):
        fn, item_cap = cap_fn
        all_results, summaries, unsummarized_turns = _make_heavy_payload()
        capped = fn(all_results, summaries, unsummarized_turns, item_cap=item_cap, full=False)

        for r in capped["results"]:
            assert len(r["content"]) == item_cap + 1  # + ellipsis char
            assert r["content"].endswith("…")

        for s in capped["summaries"]:
            assert len(s["text"]) == item_cap + 1
            assert s["text"].endswith("…")

        for t in capped["unsummarized_turns"]:
            assert len(t["content"]) == item_cap + 1
            assert t["content"].endswith("…")

    def test_short_items_pass_through_unmodified(self, cap_fn):
        """Items already under the cap are untouched — no false-positive truncation."""
        fn, item_cap = cap_fn
        all_results = [{"content": "short", "source": "a.md", "layer": "core_anchors",
                         "relevance_score": 1.0, "metadata": {}}]
        summaries = [{"date": "2026-09-01", "channels": "terminal", "text": "short summary"}]
        unsummarized_turns = [{"timestamp": "t", "channel": "terminal", "author": "Jeff",
                                "content": "short turn"}]

        capped = fn(all_results, summaries, unsummarized_turns, item_cap=item_cap, full=False)

        assert capped["results"][0]["content"] == "short"
        assert capped["summaries"][0]["text"] == "short summary"
        assert capped["unsummarized_turns"][0]["content"] == "short turn"
        assert capped["truncated"] is False
        assert capped["omitted_counts"] == {
            "results_truncated": 0, "summaries_truncated": 0, "turns_truncated": 0
        }

    def test_full_true_bypasses_capping(self, cap_fn):
        """full=True returns the original, uncapped arrays unchanged (opt-out)."""
        fn, item_cap = cap_fn
        all_results, summaries, unsummarized_turns = _make_heavy_payload()

        capped = fn(all_results, summaries, unsummarized_turns, item_cap=item_cap, full=True)

        assert capped["results"] == all_results
        assert capped["summaries"] == summaries
        assert capped["unsummarized_turns"] == unsummarized_turns
        assert capped["truncated"] is False
        assert capped["omitted_counts"] == {
            "results_truncated": 0, "summaries_truncated": 0, "turns_truncated": 0
        }

    def test_empty_arrays_are_safe(self, cap_fn):
        fn, item_cap = cap_fn
        capped = fn([], [], [], item_cap=item_cap, full=False)
        assert capped["results"] == []
        assert capped["summaries"] == []
        assert capped["unsummarized_turns"] == []
        assert capped["truncated"] is False


class TestAmbientRecallRequestFullField:
    """Verify the `full` opt-out field exists on the request model with the right default."""

    def test_full_field_defaults_false(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        # Import just the pydantic model definition without triggering the full
        # server_http module (which requires a live entity/docker environment) —
        # extract the class source and exec it against pydantic directly.
        src = SERVER_HTTP_PATH.read_text()
        start = src.index("class AmbientRecallRequest(BaseModel):")
        end = src.index("\n\n\n", start)
        snippet = src[start: end]

        from pydantic import BaseModel  # noqa: F401
        ns = {"BaseModel": BaseModel}
        exec(snippet, ns)  # noqa: S102
        model_cls = ns["AmbientRecallRequest"]

        req = model_cls(context="some query")
        assert req.full is False

        req_full = model_cls(context="some query", full=True)
        assert req_full.full is True


class TestStartupModeUnchanged:
    """
    Acceptance: startup mode's response shape is untouched by the #313 fix —
    it never had the raw `results`/`summaries`/`unsummarized_turns` arrays
    (those were already query-mode-only), so it should have no `truncated`/
    `omitted_counts` keys either.

    This is a live-server smoke check (same pattern as test_truncation.py's
    TestPPSIntegration) — skipped if the server isn't reachable rather than
    failing, since restarting the container is out of scope for this fix.
    """

    @pytest.fixture
    def auth_token(self):
        token_path = PROJECT_ROOT / "entities/lyra/.entity_token"
        if not token_path.exists():
            pytest.skip("No entity token on disk — can't reach live server")
        return token_path.read_text().strip()

    def test_startup_response_shape(self, auth_token):
        httpx = pytest.importorskip("httpx")
        try:
            client = httpx.Client(base_url="http://localhost:8201", timeout=10.0)
            response = client.post(
                "/tools/ambient_recall",
                json={"token": auth_token, "context": "startup"},
            )
        except Exception:
            pytest.skip("PPS HTTP server not reachable at localhost:8201")

        if response.status_code != 200:
            pytest.skip(f"Live server returned {response.status_code}, skipping shape check")

        data = response.json()
        assert "formatted_context" in data
        assert "manifest" in data
        # Startup mode never carried the raw arrays or the new capping metadata.
        assert "results" not in data
        assert "summaries" not in data
        assert "unsummarized_turns" not in data
        assert "truncated" not in data
        assert "omitted_counts" not in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
