"""
Tests for ambient graph-recall v2 (work/ambient-recall-v3/README.md §5).

Covers:
- Scorer pieces (specificity, global_novelty, temporal_cooldown, recency,
  lucene_safe) against fake edge rows — no Neo4j required.
- `CustomGraphLayer.recall_for_ambient()` end-to-end filtering logic (in-window
  drop, echo drop, absolute-cosine floor, greedy diversity, threshold stop),
  with a fake driver/embedder standing in for Neo4j and sentence-transformers.
- `render_recall_block()` — the composer's `[recall]` block, empty-when-none.
- A lightweight composer-shape check: a realistic mid-session front block
  (identity/location/scene/unread + `[recall]`, with the secondary trims from
  README §6 applied) stays well under the CC hook's 10,000-char cap.

Never touches the live PPS server or Neo4j — pure unit tests against the
ported v2 implementation in pps/layers/custom_graph.py.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from pps.layers.custom_graph import (
    CustomGraphLayer,
    global_novelty,
    lucene_safe,
    recency,
    render_recall_block,
    specificity,
    temporal_cooldown,
)


# ─────────────────────────────────────────────
# Pure scorer functions
# ─────────────────────────────────────────────

class TestSpecificity:
    def test_bare_fact_has_baseline_score(self):
        assert specificity("Lyra likes tea") == pytest.approx(1.0)

    def test_digit_boosts_score(self):
        assert specificity("Jeff bought 3 shirts") == pytest.approx(1.30)

    def test_quote_boosts_score(self):
        assert specificity('Lyra said "hello"') == pytest.approx(1.15)

    def test_digit_and_quote_stack(self):
        assert specificity('Jeff paid $3 for "the thing"') == pytest.approx(1.45)

    def test_extra_proper_nouns_add_small_bumps(self):
        # 3 capitalized words (Madrid, Jeff, Lyra) -> 2 "extra" caps beyond the first
        s = specificity("Madrid Jeff Lyra talked")
        assert s == pytest.approx(1.0 + 0.05 * 2)

    def test_proper_noun_bonus_caps_at_four_extra(self):
        s = specificity("Aaa Bbb Ccc Ddd Eee Fff Ggg")
        # 7 caps total -> 6 extra, clamped to 4
        assert s == pytest.approx(1.0 + 0.05 * 4)

    def test_empty_fact_is_safe(self):
        assert specificity("") == pytest.approx(1.0)


class TestGlobalNovelty:
    def test_mention_count_one_is_full_novelty(self):
        assert global_novelty(1) == pytest.approx(1.0)

    def test_well_worn_fact_scores_lower(self):
        assert global_novelty(20) < global_novelty(2) < global_novelty(1)

    def test_zero_or_negative_treated_as_one(self):
        assert global_novelty(0) == pytest.approx(1.0)
        assert global_novelty(-5) == pytest.approx(1.0)


class TestTemporalCooldown:
    def test_never_shown_is_full_strength(self):
        assert temporal_cooldown("edge-1", 10, {}) == pytest.approx(1.0)

    def test_shown_very_recently_is_heavily_suppressed(self):
        shown = {"edge-1": 8}
        assert temporal_cooldown("edge-1", 10, shown) == pytest.approx(0.10)

    def test_shown_a_while_ago_is_partially_recovered(self):
        shown = {"edge-1": 1}
        assert temporal_cooldown("edge-1", 10, shown) == pytest.approx(0.45)

    def test_shown_long_ago_is_fully_recovered(self):
        shown = {"edge-1": 1}
        assert temporal_cooldown("edge-1", 20, shown) == pytest.approx(1.0)

    def test_cooldown_can_silence_via_threshold(self):
        """The whole point of cooldown (README §5): 0.10 combined with the
        other terms should be able to push a recent repeat below `thresh`."""
        shown = {"edge-1": 9}
        cd = temporal_cooldown("edge-1", 10, shown)
        score = 0.6 * 1.0 * 1.0 * cd * 1.0  # rel * spec * gnov * cooldown * recency
        assert score < 0.30


class TestRecency:
    def test_very_recent_fact_gets_a_boost(self):
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        recent = now.isoformat()
        assert recency(recent, now) == pytest.approx(1.4, abs=0.01)

    def test_old_fact_decays_toward_one(self):
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        old = "2026-01-01T00:00:00Z"
        r = recency(old, now)
        assert 1.0 <= r < 1.05

    def test_malformed_timestamp_is_safe_default(self):
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert recency("not-a-timestamp", now) == pytest.approx(1.0)
        assert recency("", now) == pytest.approx(1.0)


class TestLuceneSafe:
    def test_strips_lucene_specials(self):
        assert lucene_safe('what about "the goal"?') == "what about the goal"

    def test_collapses_whitespace(self):
        assert lucene_safe("a   b\tc") == "a b c"

    def test_handles_none_and_empty(self):
        assert lucene_safe("") == ""
        assert lucene_safe(None) == ""

    def test_plain_text_unaffected(self):
        assert lucene_safe("Madrid head facial animations") == "Madrid head facial animations"


# ─────────────────────────────────────────────
# render_recall_block — composer's [recall] block
# ─────────────────────────────────────────────

class TestRenderRecallBlock:
    def test_empty_picks_render_nothing(self):
        assert render_recall_block([]) == ""

    def test_renders_bullet_lines_with_dates(self):
        picked = [
            {"fact": "Jeff is working on the Milan shape", "created_at": "2026-08-22"},
            {"fact": "Lyra requests screenshot of hair demos", "created_at": "2026-08-22"},
        ]
        block = render_recall_block(picked)
        lines = block.splitlines()
        assert lines[0] == "**[recall]**"
        assert lines[1] == "· Jeff is working on the Milan shape  (2026-08-22)"
        assert lines[2] == "· Lyra requests screenshot of hair demos  (2026-08-22)"

    def test_caps_at_whatever_the_caller_picked(self):
        # render_recall_block trusts its input — capping to 3 is recall_for_ambient's job.
        picked = [{"fact": f"fact {i}", "created_at": "2026-01-01"} for i in range(5)]
        assert len(render_recall_block(picked).splitlines()) == 6  # header + 5


# ─────────────────────────────────────────────
# CustomGraphLayer.recall_for_ambient — end-to-end filtering, fake Neo4j/embedder
# ─────────────────────────────────────────────

def _vec(*components, dim=8) -> list[float]:
    """Pad a short component tuple out to `dim` dims so cosine math behaves
    like real embeddings (fixed-length vectors) without needing real ones."""
    v = list(components) + [0.0] * (dim - len(components))
    return v


class _FakeEmbedder:
    """Deterministic stand-in for GraphEmbedder — returns pre-registered
    vectors for known text, plus batch support."""

    def __init__(self, table: dict[str, list[float]], default=None):
        self.table = table
        self.default = default if default is not None else _vec(0, 0, 1)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.table.get(t, self.default) for t in texts]

    def embed_text(self, text: str) -> list[float]:
        return self.table.get(text, self.default)


def _fake_driver(ft_rows: list[dict], vec_rows: list[dict]) -> MagicMock:
    """A driver whose execute_query() branches on whether the call is the
    fulltext leg (has a 'query' kwarg) or the vector leg (has 'embedding')."""
    driver = MagicMock()

    def _execute_query(cypher, **params):
        rows = ft_rows if "query" in params else vec_rows
        return (rows, None, None)

    driver.execute_query.side_effect = _execute_query
    return driver


def _make_layer(embedder: _FakeEmbedder, driver: MagicMock) -> CustomGraphLayer:
    layer = CustomGraphLayer(neo4j_password="unused", group_id="test_v2")
    layer._driver = driver
    layer._embedder = embedder

    async def _noop_ensure_indexes():
        return None

    layer._ensure_indexes = _noop_ensure_indexes
    return layer


PROMPT = "the goal is a mesh which requires the least tweaking"


@pytest.mark.asyncio
class TestRecallForAmbient:
    async def test_never_raises_when_neo4j_unavailable(self):
        layer = CustomGraphLayer(neo4j_password="unused", group_id="test_v2")

        def _boom():
            raise RuntimeError("neo4j down")

        layer._get_driver = _boom
        result = await layer.recall_for_ambient(PROMPT, [], {}, 1)
        assert result == []

    async def test_never_raises_on_embedding_failure(self):
        driver = _fake_driver([], [])
        layer = _make_layer(embedder=MagicMock(), driver=driver)
        layer._embedder.embed_batch.side_effect = RuntimeError("model not loaded")
        result = await layer.recall_for_ambient(PROMPT, [], {}, 1)
        assert result == []

    async def test_empty_prompt_returns_empty(self):
        layer = _make_layer(embedder=MagicMock(), driver=MagicMock())
        assert await layer.recall_for_ambient("", [], {}, 1) == []
        assert await layer.recall_for_ambient("   ", [], {}, 1) == []

    async def test_high_relevance_edge_surfaces(self):
        # 0.8/0.5 (not an exact copy of the prompt vector) clears the relevance
        # floor without tripping the echo-of-current-prompt drop (cos ~0.85 < 0.90).
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        edge = {
            "uuid": "e1", "fact": "Jeff is working on the Milan shape",
            "edge_type": "WORKS_ON", "mc": 1,
            "created_at": "2026-08-22T10:00:00Z",
            "emb": _vec(0.8, 0.5, 0),
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1)
        assert len(picked) == 1
        assert picked[0]["fact"] == "Jeff is working on the Milan shape"
        assert picked[0]["created_at"] == "2026-08-22"
        assert "emb" not in picked[0]  # internal-only field is stripped before return

    async def test_below_floor_edge_is_silent(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        # Orthogonal embedding -> cosine 0.0, well under the 0.40 floor.
        edge = {
            "uuid": "e1", "fact": "unrelated fact", "edge_type": "X", "mc": 1,
            "created_at": "2026-08-22T10:00:00Z", "emb": _vec(0, 1, 0),
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1)
        assert picked == []

    async def test_in_window_edge_is_dropped(self):
        """An edge created inside the live window's time span is a fact about
        a turn still visible in context — drop it (README §5)."""
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        window_rows = [
            {"timestamp": "2026-09-11 10:00", "author": "Jeff", "content": "earlier turn"},
            {"timestamp": "2026-09-11 10:05", "author": "Jeff", "content": "later turn"},
        ]
        edge = {
            "uuid": "e1", "fact": "fact from inside the window", "edge_type": "X", "mc": 1,
            "created_at": "2026-09-11T10:03:00Z",  # inside [10:00, ...)
            "emb": _vec(1, 0, 0),
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, window_rows, {}, turn_idx=1)
        assert picked == []

    async def test_edge_before_window_start_is_not_dropped(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        window_rows = [
            {"timestamp": "2026-09-11 10:00", "author": "Jeff", "content": "earlier turn"},
        ]
        edge = {
            "uuid": "e1", "fact": "an older, still-relevant fact", "edge_type": "X", "mc": 1,
            "created_at": "2026-08-22T10:03:00Z",  # well before the window
            "emb": _vec(0.8, 0.5, 0),  # relevant but not an exact echo of the prompt
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, window_rows, {}, turn_idx=1)
        assert len(picked) == 1
        assert picked[0]["uuid"] == "e1"

    async def test_echo_of_window_turn_is_dropped(self):
        """An edge that near-verbatim echoes something already in the window
        turns is wallpaper, not new information (README §5)."""
        window_rows = [{"timestamp": "2026-01-01 00:00", "author": "Jeff", "content": "the echoed turn"}]
        embedder = _FakeEmbedder({
            PROMPT: _vec(1, 0, 0),
            PROMPT[:600]: _vec(1, 0, 0),
            "the echoed turn"[:600]: _vec(0.9, 0.1, 0),
        })
        edge = {
            "uuid": "e1", "fact": "echoing fact", "edge_type": "X", "mc": 1,
            "created_at": "2025-01-01T00:00:00Z",  # well before window_start, so not caught by in-window
            "emb": _vec(0.9, 0.1, 0),  # near-identical to the window-turn embedding -> echo
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, window_rows, {}, turn_idx=1, echo=0.90)
        assert picked == []

    async def test_greedy_diversity_drops_near_duplicate_picks(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        edges = [
            {"uuid": "e1", "fact": "fact A", "edge_type": "X", "mc": 1,
             "created_at": "2026-08-01T00:00:00Z", "emb": _vec(0.8, 0.5, 0)},
            {"uuid": "e2", "fact": "near-duplicate of A", "edge_type": "X", "mc": 1,
             "created_at": "2026-08-02T00:00:00Z", "emb": _vec(0.78, 0.52, 0)},
            {"uuid": "e3", "fact": "genuinely different fact", "edge_type": "X", "mc": 1,
             "created_at": "2026-08-03T00:00:00Z", "emb": _vec(0, 1, 0)},
        ]
        driver = _fake_driver(ft_rows=[], vec_rows=edges)
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1, floor=0.0, div=0.80)
        uuids = [p["uuid"] for p in picked]
        assert "e1" in uuids
        assert "e2" not in uuids, "near-duplicate of an already-picked edge must be skipped"

    async def test_caps_at_requested_count(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        # 5 edges, each with distinct-enough embeddings to clear `div` diversity
        # and `floor`, but none an exact copy of the prompt vector (which would
        # trip the echo-of-current-prompt drop).
        edges = []
        for i in range(5):
            comp = [0.0] * 8
            comp[0] = 0.8
            comp[i + 1] = 0.5  # distinct secondary axis per edge -> low pairwise cosine
            edges.append({
                "uuid": f"e{i}", "fact": f"fact {i}", "edge_type": "X", "mc": 1,
                "created_at": "2026-08-01T00:00:00Z", "emb": comp,
            })
        driver = _fake_driver(ft_rows=[], vec_rows=edges)
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1, floor=0.0, cap=3, div=0.99)
        assert len(picked) == 3, "5 clearing candidates, cap=3 -> exactly 3 picked"

    async def test_cooldown_can_silence_a_recent_repeat(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        edge = {
            "uuid": "e1", "fact": "a fact shown last turn", "edge_type": "X", "mc": 1,
            "created_at": "2026-08-01T00:00:00Z", "emb": _vec(0.8, 0.5, 0),
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        # Control: with no cooldown history, the same edge clears thresh and is picked.
        picked_fresh = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=5, thresh=0.30)
        assert len(picked_fresh) == 1

        # Same edge, shown 1 tick ago -> cooldown (0.10) pushes it below thresh.
        shown = {"e1": 4}
        picked = await layer.recall_for_ambient(PROMPT, [], shown, turn_idx=5, thresh=0.30)
        assert picked == [], "cooldown (0.10) should push a just-shown repeat below thresh"

    async def test_shown_dict_is_updated_with_picks(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        edge = {
            "uuid": "e1", "fact": "a fresh fact", "edge_type": "X", "mc": 1,
            "created_at": "2026-08-01T00:00:00Z", "emb": _vec(0.8, 0.5, 0),
        }
        driver = _fake_driver(ft_rows=[], vec_rows=[edge])
        layer = _make_layer(embedder, driver)

        shown: dict = {}
        picked = await layer.recall_for_ambient(PROMPT, [], shown, turn_idx=7)
        assert len(picked) == 1
        assert shown["e1"] == 7

    async def test_no_candidates_is_silent_not_an_error(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        driver = _fake_driver(ft_rows=[], vec_rows=[])
        layer = _make_layer(embedder, driver)
        assert await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1) == []

    async def test_edges_missing_embedding_are_skipped_not_fatal(self):
        embedder = _FakeEmbedder({PROMPT: _vec(1, 0, 0)})
        edges = [
            {"uuid": "e1", "fact": "no embedding here", "edge_type": "X", "mc": 1,
             "created_at": "2026-08-01T00:00:00Z", "emb": None},
            {"uuid": "e2", "fact": "has an embedding", "edge_type": "X", "mc": 1,
             "created_at": "2026-08-01T00:00:00Z", "emb": _vec(0.8, 0.5, 0)},
        ]
        driver = _fake_driver(ft_rows=[], vec_rows=edges)
        layer = _make_layer(embedder, driver)

        picked = await layer.recall_for_ambient(PROMPT, [], {}, turn_idx=1)
        assert [p["uuid"] for p in picked] == ["e2"]


# ─────────────────────────────────────────────
# Composer shape: front-block stays well under CC's 10,000-char hook cap
# ─────────────────────────────────────────────

class TestComposerBudget:
    """Mirrors the mid-session composer shape after the README §6 trims:
    identity/location/scene/unread lines + a [recall] block (no per-turn
    [memory]/[hint]/crystals/summaries/recent_turns lines). Not a substitute
    for booting the live server, but pins the budget math the trims exist to
    protect."""

    def _mid_session_block(self, picked: list[dict]) -> str:
        lines = [
            "**[identity]** You are Lyra. Your memory tools are prefixed `pps-lyra`. "
            "Do not access other entities' memory tools.",
            "**[location]** Jeff: home, Carol: home",
            "**[scene]** Sitting at the desk, late afternoon light.",
            "**[unread]** haven: 0 new | other_channels: 0 new",
        ]
        block = render_recall_block(picked)
        if block:
            lines.append(block)
        return "\n".join(lines)

    def test_empty_recall_block_is_omitted(self):
        text = self._mid_session_block([])
        assert "[recall]" not in text

    def test_realistic_recall_block_included(self):
        picked = [
            {"fact": "Lyra requests Jeff screenshot hair demos on Madrid's head", "created_at": "2026-08-22"},
            {"fact": "Jeff is working on the Milan shape and its facial animations", "created_at": "2026-08-22"},
            {"fact": "Lyra has an intimate connection with Madrid, the face she felt before naming it", "created_at": "2026-08-22"},
        ]
        text = self._mid_session_block(picked)
        assert "**[recall]**" in text
        assert text.count("·") == 3

    def test_mid_session_block_stays_well_under_hook_cap(self):
        # Even a "full" 3-fact recall block plus the sacred front lines
        # should land far under the CC hook's 10,000-char cap.
        picked = [
            {"fact": "x" * 120, "created_at": "2026-08-22"} for _ in range(3)
        ]
        text = self._mid_session_block(picked)
        assert len(text) < 10_000
        assert len(text) < 1_500, "trimmed mid-session block should be far under budget, not just under the hard cap"
