"""Offline tests for the song-enrichment helpers (network-free logic).

Self-running (no pytest needed), same convention as test_music.py::

    PYTHONPATH=. python3 haven/anchorage/senses/test_enrich.py
"""

from __future__ import annotations

import sys

try:
    from haven.anchorage.senses import enrich as E
except ImportError:  # pragma: no cover - flat sys.path shim
    import enrich as E  # type: ignore


def test_describe_joins_first_four_tags():
    assert E.describe(["indie rock", "dream pop", "dark", "sweet", "quirky"]) == \
        "indie rock · dream pop · dark · sweet"


def test_describe_empty_is_none():
    assert E.describe([]) is None


def test_dedupe_case_insensitive_keeps_order():
    assert E._dedupe(["Indie", "indie", "Rock", "ROCK", "pop"]) == ["Indie", "Rock", "pop"]


def test_fetch_lyrics_needs_both_halves():
    # No network: a missing half short-circuits to None before any request.
    assert E.fetch_lyrics(None, "Some Title") is None
    assert E.fetch_lyrics("Some Artist", "") is None


def test_fetch_tags_needs_a_query():
    # No network: nothing to query → empty, no request made.
    assert E.fetch_tags(None, "") == []


def test_enrich_shape_degrades():
    # Monkeypatch the two network fns so this stays offline; assert the contract:
    # a total lookup miss still returns the full key-set, degraded, never raises.
    orig_l, orig_t = E.fetch_lyrics, E.fetch_tags
    try:
        E.fetch_lyrics = lambda a, t: None
        E.fetch_tags = lambda a, t: []
        out = E.enrich("X", "Y")
        assert set(out.keys()) == {"lyrics", "genres", "description"}
        assert out == {"lyrics": None, "genres": [], "description": None}
    finally:
        E.fetch_lyrics, E.fetch_tags = orig_l, orig_t


def test_enrich_shape_populated():
    orig_l, orig_t = E.fetch_lyrics, E.fetch_tags
    try:
        E.fetch_lyrics = lambda a, t: "line1\nline2"
        E.fetch_tags = lambda a, t: ["ambient", "downtempo"]
        out = E.enrich("X", "Y")
        assert out["lyrics"] == "line1\nline2"
        assert out["genres"] == ["ambient", "downtempo"]
        assert out["description"] == "ambient · downtempo"
    finally:
        E.fetch_lyrics, E.fetch_tags = orig_l, orig_t


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
