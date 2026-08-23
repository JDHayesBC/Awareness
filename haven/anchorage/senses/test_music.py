"""Offline tests for MusicSense — the network-free logic (parse + record shape).

Self-running (no pytest needed), same convention as the other anchorage tests::

    PYTHONPATH=. python3 haven/anchorage/senses/test_music.py
"""

from __future__ import annotations

import sys

try:
    from haven.anchorage.senses import sense_record
    from haven.anchorage.senses.music import (
        KIND,
        SOURCE,
        MusicSense,
        split_artist_title,
    )
except ImportError:  # pragma: no cover - flat sys.path shim
    from __init__ import sense_record  # type: ignore
    from music import KIND, SOURCE, MusicSense, split_artist_title  # type: ignore


def test_split_spaced_hyphen():
    assert split_artist_title("Chris Coco - Love Made Me Tough") == ("Chris Coco", "Love Made Me Tough")


def test_split_no_separator_is_honest():
    # No separator → we don't guess; whole string is the title, artist unknown.
    assert split_artist_title("Untitled Ambient Piece") == (None, "Untitled Ambient Piece")


def test_split_preserves_hyphenated_titles():
    # A bare hyphen inside a word must not be treated as artist/title split.
    assert split_artist_title("Song-Name") == (None, "Song-Name")


def test_split_empty():
    assert split_artist_title("") == (None, "")
    assert split_artist_title("   ") == (None, "")


def test_sense_record_shape():
    rec = sense_record(SOURCE, KIND, {"title": "x"}, ts=123.0)
    assert rec == {"source": "anchorage-music", "ts": 123.0, "kind": "nowplaying", "payload": {"title": "x"}}


def test_parcel_seam_resolves_before_static_stream():
    # The SL seam takes priority; a resolver returning a URL drives the poll.
    calls = []

    def fake_resolver():
        calls.append(1)
        return "http://example.test/mount"

    sense = MusicSense(stream_url="http://static.fallback/", parcel_music_url=fake_resolver)
    assert sense._resolve_stream() == "http://example.test/mount"
    assert calls == [1]


def test_parcel_seam_falls_back_to_static_when_none():
    sense = MusicSense(stream_url="http://static.fallback/", parcel_music_url=lambda: None)
    assert sense._resolve_stream() == "http://static.fallback/"


def test_requires_a_source():
    try:
        MusicSense()
    except ValueError:
        return
    raise AssertionError("MusicSense should require a stream_url or parcel_music_url")


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
