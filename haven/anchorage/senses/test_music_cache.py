"""Offline tests for music_cache — slug, station-id filter, cache-first remember,
heard-log, payload augmentation, and the perception music_tail rendering.

Network-free (enrichment is injected). Self-running, same convention as the
other anchorage tests::

    PYTHONPATH=. python3 haven/anchorage/senses/test_music_cache.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    from haven.anchorage.senses.music_cache import (
        looks_like_song,
        remember,
        slugify,
    )
    from haven.anchorage.perception import music_tail
except ImportError:  # pragma: no cover - flat sys.path shim
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from haven.anchorage.senses.music_cache import (  # type: ignore[no-redef]
        looks_like_song,
        remember,
        slugify,
    )
    from haven.anchorage.perception import music_tail  # type: ignore[no-redef]


_FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        _FAILS.append(name)


def _boom(*_a, **_k):
    raise AssertionError("enrich must NOT be called on a cache hit")


def test_slugify() -> None:
    check("accents fold (Björk)", slugify("Björk", "All Is Full Of Love") == "bjork-all-is-full-of-love")
    check("collapse punctuation", slugify("AC/DC", "T.N.T.") == "ac-dc-t-n-t")
    check("empty → unknown", slugify(None, "") == "unknown")
    check("length capped", len(slugify("x" * 90, "y" * 90)) <= 80)


def test_station_filter() -> None:
    check("real song is a song", looks_like_song("Ellie Goulding", "Destiny", "Ellie Goulding - Destiny"))
    check("name==name is not", not looks_like_song("Listen.FM", "Listen.FM", "Listen.FM - Listen.FM"))
    check("station handle artist is not", not looks_like_song("181.fm", "Music Promo30", "181.fm - Music Promo30"))
    check("bumper phrase is not", not looks_like_song("181.fm", "THIS STATION WILL CONTINUE AFTER THIS BREAK", "x"))
    check("no artist real title is a song", looks_like_song(None, "Some Song Title Here", "Some Song Title Here"))


def test_remember_miss_then_hit() -> None:
    with tempfile.TemporaryDirectory() as d:
        calls = {"n": 0}

        def fake_enrich(artist, title):
            calls["n"] += 1
            return {"lyrics": "line one\nline two", "genres": ["electronic", "trip hop", "ethereal"],
                    "description": "electronic · trip hop · ethereal"}

        p1 = remember({"artist": "Björk", "title": "All Is Full Of Love", "raw": "Björk - All Is Full Of Love"},
                      "caia", cache_dir=d, enrich_fn=fake_enrich)
        check("miss: enrich called once", calls["n"] == 1)
        check("miss: is_song True", p1.get("is_song") is True)
        check("miss: genres augmented", p1.get("genres") == ["electronic", "trip hop", "ethereal"])
        check("miss: has_lyrics True", p1.get("has_lyrics") is True)
        check("miss: ref points at slug", p1.get("lyrics_ref") == "haven/data/music-cache/bjork-all-is-full-of-love.json")
        check("miss: FULL lyrics NOT on payload", "lyrics" not in p1)
        check("miss: play_count 1", p1.get("play_count") == 1)

        song_file = Path(d) / "bjork-all-is-full-of-love.json"
        check("miss: song file written", song_file.exists())
        rec = json.loads(song_file.read_text(encoding="utf-8"))
        check("miss: full lyrics in FILE", rec.get("lyrics") == "line one\nline two")

        heard = Path(d) / "heard-caia.jsonl"
        check("miss: heard-log appended", heard.exists() and len(heard.read_text().splitlines()) == 1)

        # Second hearing → cache HIT: enrich must not run; play_count bumps.
        p2 = remember({"artist": "Björk", "title": "All Is Full Of Love", "raw": "Björk - All Is Full Of Love"},
                      "caia", cache_dir=d, enrich_fn=_boom)
        check("hit: enrich NOT called", calls["n"] == 1)
        check("hit: play_count 2", p2.get("play_count") == 2)
        check("hit: heard-log has 2 lines", len(heard.read_text().splitlines()) == 2)


def test_remember_non_song() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = remember({"artist": "Listen.FM", "title": "Listen.FM", "raw": "Listen.FM - Listen.FM"},
                     "caia", cache_dir=d, enrich_fn=_boom)
        check("non-song: is_song False", p.get("is_song") is False)
        check("non-song: no ref", "lyrics_ref" not in p)
        check("non-song: nothing written", not any(Path(d).glob("*.json")))


def test_remember_enrich_failure_degrades() -> None:
    with tempfile.TemporaryDirectory() as d:
        def raises(*_a, **_k):
            raise RuntimeError("network down")
        p = remember({"artist": "Obscure", "title": "B-Side", "raw": "Obscure - B-Side"},
                     "caia", cache_dir=d, enrich_fn=raises)
        check("degrade: still a song", p.get("is_song") is True)
        check("degrade: has_lyrics False", p.get("has_lyrics") is False)
        check("degrade: empty genres", p.get("genres") == [])
        check("degrade: ref still present", p.get("lyrics_ref", "").endswith("obscure-b-side.json"))


def test_music_tail() -> None:
    enriched = {"is_song": True, "description": "electronic · trip hop", "has_lyrics": True,
                "lyrics_ref": "haven/data/music-cache/x.json"}
    with_ref = music_tail(enriched, include_ref=True)
    no_ref = music_tail(enriched, include_ref=False)
    check("tail: desc present", "electronic · trip hop" in with_ref)
    check("tail: ref shown when asked", "→ haven/data/music-cache/x.json" in with_ref)
    check("tail: ref hidden on delta", "→" not in no_ref and "♫ lyrics" in no_ref)
    check("tail: non-song empty", music_tail({"is_song": False, "description": "x"}, include_ref=True) == "")
    check("tail: bare payload empty", music_tail({"artist": "a", "title": "b"}, include_ref=True) == "")
    check("tail: genres fallback when no description",
          "rock · pop" in music_tail({"is_song": True, "genres": ["rock", "pop"]}, include_ref=True))


def test_canonical() -> None:
    from haven.anchorage.senses.music_cache import canonical, clean_title
    # Jeff's real-world YouTube formats → base track.
    check("official music video", clean_title("The Fate of Ophelia (Official Music Video)") == "The Fate of Ophelia")
    check("double-paren version+video", clean_title("Enchanted (Taylor's Version) (Lyric Video)") == "Enchanted")
    check("paren video + trailing remix", clean_title("Collateral Damage (Lyrics / Lyric Video) Anki Remix") == "Collateral Damage")
    check("paren remix + pipe tail", clean_title("I Turn To You (Sadrican 2026 Progressive Remix) | Club Anthem") == "I Turn To You")
    check("the terranova case", clean_title("Chase The Blues (Cameron McVey Mix)") == "Chase The Blues")
    # Must NOT over-strip real titles:
    check("keep 'Video Games'", clean_title("Video Games") == "Video Games")
    check("keep 'Radio Ga Ga'", clean_title("Radio Ga Ga") == "Radio Ga Ga")
    check("keep leading 'Live and Let Die'", clean_title("Live and Let Die") == "Live and Let Die")
    check("keep clean paren '(Part 1)'", clean_title("Marquee Moon (Part 1)") == "Marquee Moon (Part 1)")
    # feat / artist handling:
    check("strip feat from title", clean_title("Song feat. Rihanna") == "Song")
    ca, ct = canonical("Drake feat. Rihanna", "Take Care")
    check("strip feat from artist", ca == "Drake")
    check("keep co-primary '&'", canonical("Simon & Garfunkel", "America")[0] == "Simon & Garfunkel")


def test_remember_collapses_versions() -> None:
    with tempfile.TemporaryDirectory() as d:
        calls = {"n": 0}

        def fake_enrich(artist, title):
            calls["n"] += 1
            return {"lyrics": "la la", "genres": ["house"], "description": "house"}

        p1 = remember({"artist": "X", "title": "Song (Radio Edit)", "raw": "X - Song (Radio Edit)"},
                      "caia", cache_dir=d, enrich_fn=fake_enrich)
        p2 = remember({"artist": "X", "title": "Song (Live)", "raw": "X - Song (Live)"},
                      "caia", cache_dir=d, enrich_fn=fake_enrich)
        check("collapse: same ref for both versions", p1["lyrics_ref"] == p2["lyrics_ref"])
        check("collapse: ref is clean base", p1["lyrics_ref"].endswith("x-song.json"))
        check("collapse: enrich ran once", calls["n"] == 1)
        check("collapse: exactly one library file", len(list(Path(d).glob("*.json"))) == 1)
        rec = json.loads((Path(d) / "x-song.json").read_text(encoding="utf-8"))
        check("collapse: play_count 2", rec.get("play_count") == 2)
        check("collapse: canonical title is base", rec.get("title") == "Song")
        check("collapse: both versions in variants",
              set(rec.get("variants") or []) == {"Song (Radio Edit)", "Song (Live)"})


def main() -> int:
    for fn in (test_slugify, test_station_filter, test_canonical, test_remember_miss_then_hit,
               test_remember_non_song, test_remember_enrich_failure_degrades,
               test_remember_collapses_versions, test_music_tail):
        print(fn.__name__)
        fn()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): {', '.join(_FAILS)}")
        return 1
    print("all music_cache tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
