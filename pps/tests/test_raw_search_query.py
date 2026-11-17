"""Tests for raw_search query building, two-pass search, receipts, errors (#408).

All rows are invented. Run:
    pps/venv/bin/python3 -m pytest pps/tests/test_raw_search_query.py -q
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layers.raw_capture import (  # noqa: E402
    NOTHING_SEARCHABLE,
    RawCaptureLayer,
    build_fts_terms,
)

run = asyncio.run

ROWS = [
    # (content, author, channel)
    ("Sam will take his coffee black with one sugar", "Alex", "terminal"),
    ("Sam's coffee order never changes", "Alex", "terminal"),
    ("We decide about the hot-tub cover on Tuesday", "Alex", "terminal"),
    ("The Night (NightShift) crew finished early", "Robin", "haven"),
    ("Keats - Ode to a Nightingale is on the shelf", "Robin", "haven"),
    ("The U.S.S. Enterprise model is on the desk", "Robin", "haven"),
    ("Tea is better than coffee in the morning", "Alex", "terminal"),
    ("Sam walked to the lake alone", "Alex", "terminal"),
    ("They said don't worry about the roof", "Robin", "haven"),
    ("The quick brown fox", "Robin", "haven"),
    ("Brown paper and a fox costume", "Robin", "haven"),
]


def _make_db(path: Path, rows=ROWS) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            author_name TEXT,
            channel TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_lyra INTEGER DEFAULT 0
        )"""
    )
    for content, author, channel in rows:
        conn.execute(
            "INSERT INTO messages (content, author_name, channel) VALUES (?,?,?)",
            (content, author, channel),
        )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def layer(tmp_path):
    # The layer builds and fills messages_fts itself on first search.
    return RawCaptureLayer(db_path=_make_db(tmp_path / "t.db"))


def contents(outcome):
    return [r.content for r in outcome.results]


# ---- query building -------------------------------------------------------

def test_terms_are_quoted_and_possessive_dropped():
    terms, any_terms, shown = build_fts_terms("Sam's coffee?")
    assert terms == ['"sam"', '"coffee"']
    assert shown == ["sam", "coffee"]


def test_operators_are_neutralised():
    terms, _, _ = build_fts_terms("cats AND dogs NOT birds OR fish")
    assert all(t.startswith('"') and t.endswith('"') for t in terms)


def test_glued_words_become_one_phrase():
    assert build_fts_terms("hot-tub")[0] == ['"hot tub"']
    assert build_fts_terms("email_id")[0] == ['"email id"']
    assert build_fts_terms("2026-11-17")[0] == ['"2026 11 17"']
    assert build_fts_terms("server_http.py")[0] == ['"server http py"']
    assert build_fts_terms("don't worry")[0] == ['"don t"', '"worry"']
    # phrases are kept in the any-word list and are never stopwords
    terms, any_terms, _ = build_fts_terms("the hot-tub")
    assert any_terms == ['"hot tub"']
    assert terms == ['"hot tub"', '"the"']  # only one content item, so "the" stays in the AND set
    terms, any_terms, _ = build_fts_terms("the hot-tub cover")
    assert terms == any_terms == ['"hot tub"', '"cover"']
    # other punctuation still separates
    assert build_fts_terms("hot/tub")[0] == ['"hot"', '"tub"']
    assert build_fts_terms("Jeff's")[0] == ['"jeff"']


def test_stopwords_dropped_only_with_two_content_tokens():
    terms, _, _ = build_fts_terms("how does Sam take his coffee")
    assert terms == ['"sam"', '"take"', '"coffee"']
    # one content token: stopwords stay in the AND set, but never in the OR set
    terms, any_terms, _ = build_fts_terms("how coffee")
    assert terms == ['"how"', '"coffee"']
    assert any_terms == ['"coffee"']


def test_unsearchable():
    for q in ["???", "- ( ) .", "how does the", "", '""']:
        assert build_fts_terms(q) == ([], [], [])


def test_quoted_phrase_stays_a_phrase():
    terms, _, shown = build_fts_terms('"brown fox" costume')
    assert terms[0] == '"brown fox"'
    assert '"costume"' in terms


# ---- punctuation cases return rows ---------------------------------------

@pytest.mark.parametrize(
    "query, expect",
    [
        ("how does Sam take his coffee?", "take his coffee black"),
        ("Sam's coffee", "Sam's coffee order"),
        ("what did we decide about the hot-tub", "hot-tub cover"),
        ("Night (NightShift)", "NightShift"),
        ("Keats - Ode to a Nightingale", "Nightingale"),
        ("U.S.S. Enterprise", "Enterprise model"),
        ("don't worry", "don't worry about the roof"),
    ],
)
def test_punctuation_queries_find_rows(layer, query, expect):
    out = run(layer.search_with_receipt(query, 10))
    assert out.error is None
    assert any(expect in c for c in contents(out)), out.receipt


def test_search_strict_returns_results_for_punctuation(layer):
    rows = run(layer.search("Sam's coffee?", 10))
    assert rows and all(isinstance(r.relevance_score, float) for r in rows)


# ---- AND then OR ---------------------------------------------------------

def test_and_pass_first_then_or_fallback(layer):
    out = run(layer.search_with_receipt("Sam coffee", 10))
    cs = contents(out)
    assert out.total_all == 2
    assert set(cs[:2]) == {ROWS[0][0], ROWS[1][0]}
    # OR rows follow: coffee-only and Sam-only rows
    assert ROWS[6][0] in cs and ROWS[7][0] in cs
    assert len(cs) == len(set(cs))


def test_extra_word_does_not_kill_match(layer):
    out = run(layer.search_with_receipt("Sam coffee zebra", 10))
    assert ROWS[0][0] in contents(out)
    assert out.total_all == 0


def test_or_pass_skipped_when_limit_filled(layer):
    out = run(layer.search_with_receipt("Sam coffee", 2))
    assert len(out.results) == 2
    assert "Any of them" not in out.receipt


def test_fallback_off_is_strict_and(layer):
    rows = run(layer.search("Sam coffee zebra", 10))
    assert rows == []


def test_phrase_and_fallback(layer):
    out = run(layer.search_with_receipt('"brown fox" costume', 10))
    cs = contents(out)
    assert cs[0] == ROWS[10][0] or ROWS[10][0] in cs
    # phrase "brown fox" matches "The quick brown fox" only
    out2 = run(layer.search_with_receipt('"brown fox"', 10))
    assert contents(out2) == [ROWS[9][0]]


def test_only_matching_rows_returned(layer):
    out = run(layer.search_with_receipt("coffee shelf", 50))
    for c in contents(out):
        assert "coffee" in c.lower() or "shelf" in c.lower()


def test_author_and_channel_columns_not_searched(layer):
    # "Robin" and "haven" are author/channel values only, never message text
    out = run(layer.search_with_receipt("Robin haven", 50))
    assert out.results == []
    assert out.receipt == "No message contains any of [robin, haven]."


# ---- receipts -------------------------------------------------------------

def test_receipt_all_hit(layer):
    out = run(layer.search_with_receipt("Sam coffee", 2))
    assert out.receipt == "Searched for all of [sam, coffee]: 2 messages."


def test_receipt_partial(layer):
    out = run(layer.search_with_receipt("how does Sam take his coffee", 10))
    assert out.receipt.startswith("Searched for all of [sam, take, coffee]: 1 message.")
    assert "Any of them: 3 more, best 3 shown." in out.receipt


def test_receipt_none(layer):
    out = run(layer.search_with_receipt("zebra yak", 10))
    assert out.receipt == "No message contains any of [zebra, yak]."
    assert out.results == [] and out.error is None


def test_receipt_unsearchable(layer):
    out = run(layer.search_with_receipt("?! - (", 10))
    assert out.receipt == NOTHING_SEARCHABLE
    assert out.results == [] and out.error is None


# ---- errors are errors ----------------------------------------------------

def _broken(tmp_path) -> RawCaptureLayer:
    path = _make_db(tmp_path / "broken.db", rows=ROWS[:2])
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages_fts (x TEXT)")  # not an FTS5 table
    conn.commit()
    conn.close()
    return RawCaptureLayer(db_path=path)


def test_error_path_reports_error_not_empty(tmp_path, caplog):
    lyr = _broken(tmp_path)
    with caplog.at_level("ERROR"):
        out = run(lyr.search_with_receipt("coffee", 10))
    assert out.error == "OperationalError"
    assert out.receipt == 'Search failed: OperationalError. This is not a "no results" answer.'
    assert out.results == []
    assert any("raw_search failed" in r.message for r in caplog.records)


def test_strict_search_raises_on_error(tmp_path):
    with pytest.raises(RuntimeError, match="Search failed"):
        run(_broken(tmp_path).search("coffee", 10))


def test_missing_messages_table_is_reported(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    out = run(RawCaptureLayer(db_path=path).search_with_receipt("coffee", 10))
    assert out.error and out.receipt.startswith("Search failed")


def test_email_dedup_phrase_still_works(tmp_path):
    path = _make_db(tmp_path / "e.db", rows=[("[email_id:abc123] subject line", "x", "email"),
                                              ("[email_id:zzz999] other", "x", "email")])
    lyr = RawCaptureLayer(db_path=path)
    assert len(run(lyr.search('"[email_id:abc123]"', limit=1))) == 1
    assert run(lyr.search('"[email_id:nope]"', limit=1)) == []


# ---- glued words in search, and the join-free any-word count ---------------

def _layer_with(tmp_path, texts):
    return RawCaptureLayer(db_path=_make_db(
        tmp_path / "g.db", rows=[(x, "A", "c") for x in texts]))


def test_hot_tub_matches_both_spellings_not_distant_words(tmp_path):
    lyr = _layer_with(tmp_path, [
        "the hot-tub is warm", "the hot tub is warm",
        "hot soup and a tub of butter",
    ])
    out = run(lyr.search_with_receipt("hot-tub", 10))
    assert sorted(contents(out)) == ["the hot tub is warm", "the hot-tub is warm"]
    assert out.total_all == 2


def test_bare_email_id_needs_adjacent_tokens(tmp_path):
    lyr = _layer_with(tmp_path, [
        "[email_id:42] hello", "an email with an id attached", "email id card",
    ])
    rows = run(lyr.search("email_id", 10))
    assert sorted(r.content for r in rows) == ["[email_id:42] hello", "email id card"]


def test_date_is_one_phrase(tmp_path):
    lyr = _layer_with(tmp_path, [
        "met on 2026-11-17 at noon", "page 2026 line 11 item 17", "on 2026/11/17",
    ])
    out = run(lyr.search_with_receipt("2026-11-17", 10))
    # the phrase equals what the tokenizer indexed, so a slash date matches too;
    # three loose numbers far apart do not
    assert sorted(contents(out)) == ["met on 2026-11-17 at noon", "on 2026/11/17"]


def test_apostrophe_word_unchanged_in_search(tmp_path):
    lyr = _layer_with(tmp_path, ["please don't worry", "they don worry t"])
    assert contents(run(lyr.search_with_receipt("don't", 10))) == ["please don't worry"]


def test_any_count_matches_join_version(layer):
    # Reference: the earlier join-and-exclude count, run on the same fixture.
    for q in ["Sam coffee", "how does Sam take his coffee", "Sam coffee zebra", "fox costume"]:
        out = run(layer.search_with_receipt(q, 10))
        terms, any_terms, _ = build_fts_terms(q)
        with layer.get_connection() as conn:
            ids = [r.metadata["id"] for r in out.results[: out.total_all]]
            excl = " AND m.id NOT IN (%s)" % ",".join("?" * len(ids)) if ids else ""
            joined = conn.execute(
                "SELECT COUNT(*) FROM messages_fts JOIN messages m ON messages_fts.rowid = m.id "
                "WHERE messages_fts MATCH ?" + excl,
                ["content : (" + " OR ".join(any_terms) + ")"] + ids,
            ).fetchone()[0]
        assert out.any_total == joined, q
