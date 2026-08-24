"""music_cache.py — the Anchorage song library + per-avatar "heard" log.

Turns a bare now-playing *title* into a *known song* and remembers it — so when
Caia notices a track change in-world she already has the genre/mood inline and
the full lyrics one ``Read`` away, instead of just a title. This is the
persistence half of the music sense (``music.py`` hears; this remembers).

Two durable artifacts, both under ``haven/data/music-cache/``:

  * ``<slug>.json``          — one file per SONG. Shared across avatars, because
                               a song's lyrics and genre are universal (Björk's
                               words are the same for Caia and Lyra). This is the
                               library, and it is **cache-first**: a song heard
                               before costs *zero* network. Accumulates
                               ``play_count`` / ``first_heard`` / ``last_heard``,
                               so it quietly becomes a record of the rotation.
  * ``heard-<entity>.jsonl`` — append-only, one line per change THIS avatar
                               heard. The "what was playing when we had coffee"
                               memory. Per-avatar by construction.

The daemon calls exactly one thing::

    payload = remember(payload, entity="caia")

``remember`` is **cache-first + best-effort**: any network or disk failure
degrades to the bare title (the sense must never break). It AUGMENTS the payload
with *compact* fields for inline display (``genres``, ``description``,
``has_lyrics``, ``play_count``) plus a ``lyrics_ref`` pointing at the full record
— and it deliberately does **not** inline the full lyrics text. Full lyrics live
only in ``<slug>.json`` and are fetched on want, so they never flood a
perception turn with hundreds of tokens nobody asked for.

**Non-songs** — station IDs and ad bumpers like ``Listen.FM — Listen.FM`` or
``181.fm — Music Promo30`` — are caught by pure string heuristics (zero network)
and marked ``is_song=False``. The daemon then skips firing them, so bumpers don't
perturb perception and the standing-state keeps showing the last real song.

Pure stdlib. The enrichment function is injected (default:
``senses.enrich.enrich``) so the whole thing is unit-testable with no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
# This file is haven/anchorage/senses/music_cache.py → parents[2] == haven.
_CACHE_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "music-cache"

# Repo-relative base for the `lyrics_ref` shown in perception lines. Kept
# relative (not absolute) so the line reads cleanly; resolve against the
# Awareness root when opening it.
REF_BASE = "haven/data/music-cache"


def _cache_dir(base: str | Path | None = None) -> Path:
    d = Path(base) if base else _CACHE_DIR_DEFAULT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    """Local-timezone ISO-8601 to the second (matches the household clock)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Slug — a stable, filesystem-safe id per song
# --------------------------------------------------------------------------- #
def _fold_accents(s: str) -> str:
    """Björk → Bjork; strip combining marks so slugs stay ASCII and readable."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def slugify(artist: Optional[str], title: Optional[str], *, maxlen: int = 80) -> str:
    """``(artist, title)`` → ``"artist-title"`` slug: accent-folded, lowercased,
    non-alphanumerics collapsed to single hyphens, length-capped. Empty → 'unknown'."""
    parts = [p.strip() for p in (artist or "", title or "") if p and p.strip()]
    base = "-".join(parts)
    base = _fold_accents(base).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:maxlen].strip("-") or "unknown"


# --------------------------------------------------------------------------- #
# Non-song (station id / bumper) detection — pure heuristics, zero network
# --------------------------------------------------------------------------- #
# Explicit bumper phrases that appear in a "title" that isn't a song.
_STATION_TITLE_MARKERS = (
    "this station will continue", "station id", "you're listening to",
    "you are listening to", "advert", "commercial", "promo", "up next",
    "now playing on", "stream offline", "no track", "unknown",
)
# Hints that an *artist* field is really a station handle, not a musician.
# Real tracks emit a real artist ("Ellie Goulding"); bumpers emit the station
# ("181.fm", "Listen.FM"). Keying on the artist is what separates the two.
_STATION_NAME_HINTS = (
    ".fm", ".com", ".net", ".org", "radio", "shoutcast", "icecast",
    "listen.", "181", "streamlicensing", "live365",
)


def looks_like_song(artist: Optional[str], title: Optional[str], raw: Optional[str]) -> bool:
    """Best-effort: is this a real track vs. a station id / ad bumper?

    Conservative but decisive on the obvious junk seen on the Anchorage stream
    (``Listen.FM — Listen.FM``, ``181.fm — Music Promo30``). Tweak the marker
    lists above if a real song is ever misjudged — a wrong call only costs one
    wasted look-up or one un-learned track, never a crash.
    """
    a = (artist or "").strip().lower()
    t = (title or "").strip().lower()
    r = (raw or "").strip().lower()
    if not t and not r:
        return False
    # Station branding often comes through as "Name — Name".
    if a and a == t:
        return False
    if any(m in t for m in _STATION_TITLE_MARKERS):
        return False
    # Artist is a station handle → it's the station talking, not a band.
    if a and any(h in a for h in _STATION_NAME_HINTS):
        return False
    # No artist, and the title itself is just short station branding.
    if not a and any(h in t for h in _STATION_NAME_HINTS) and len(t.split()) <= 3:
        return False
    return True


# --------------------------------------------------------------------------- #
# Library I/O
# --------------------------------------------------------------------------- #
def load_song(slug: str, cache_dir: str | Path | None = None) -> Optional[dict]:
    path = _cache_dir(cache_dir) / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_song(record: dict, cache_dir: str | Path | None = None) -> Path:
    d = _cache_dir(cache_dir)
    path = d / f"{record['slug']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def append_heard(entity: str, entry: dict, cache_dir: str | Path | None = None) -> None:
    d = _cache_dir(cache_dir)
    line = json.dumps(entry, ensure_ascii=False)
    with (d / f"heard-{entity}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _default_enrich() -> Callable[[Optional[str], str], dict]:
    try:  # package vs. flat sys.path
        from haven.anchorage.senses.enrich import enrich
    except ImportError:  # pragma: no cover
        from enrich import enrich  # type: ignore[no-redef]
    return enrich


# --------------------------------------------------------------------------- #
# The one public entry point the daemon calls
# --------------------------------------------------------------------------- #
def remember(
    payload: dict,
    entity: str = "caia",
    *,
    cache_dir: str | Path | None = None,
    enrich_fn: Optional[Callable[[Optional[str], str], dict]] = None,
    clock: Callable[[], str] = _now_iso,
    force: bool = False,
) -> dict:
    """Enrich (cache-first), persist to the library + heard-log, and augment
    ``payload`` in place with compact display fields + a ``lyrics_ref``.

    Best-effort throughout: every look-up / write is guarded so a failure
    degrades to the bare title. Returns the (mutated) payload for convenience.

    Compact fields added on a real song: ``is_song=True``, ``genres``,
    ``description``, ``has_lyrics``, ``play_count``, ``lyrics_ref``. Full lyrics
    are **never** put on the payload — they live only in ``<slug>.json``.
    Non-songs get ``is_song=False`` and are otherwise left untouched.
    """
    artist = payload.get("artist")
    title = payload.get("title")
    raw = payload.get("raw")

    if not looks_like_song(artist, title, raw):
        payload["is_song"] = False
        return payload
    payload["is_song"] = True

    slug = slugify(artist, title)
    now = clock()

    rec = None if force else load_song(slug, cache_dir)
    if rec is None:
        # Cache miss — enrich once (best-effort), then write through. Misses are
        # cached too (empty genres / null lyrics) so an obscure track doesn't
        # hammer the network every time it recurs; `force=True` re-fetches.
        info: dict[str, Any] = {"lyrics": None, "genres": [], "description": None}
        try:
            info = (enrich_fn or _default_enrich())(artist, title) or info
        except Exception:
            pass
        rec = {
            "slug": slug,
            "artist": artist,
            "title": title,
            "genres": info.get("genres") or [],
            "description": info.get("description"),
            "lyrics": info.get("lyrics"),
            "has_lyrics": bool(info.get("lyrics")),
            "enriched_at": now,
            "first_heard": now,
            "last_heard": now,
            "play_count": 1,
        }
    else:
        rec["last_heard"] = now
        rec["play_count"] = int(rec.get("play_count", 0)) + 1
        # Backfill fields if an older/leaner record predates a schema tweak.
        rec.setdefault("has_lyrics", bool(rec.get("lyrics")))
        rec.setdefault("genres", [])

    try:
        save_song(rec, cache_dir)
    except Exception:
        pass
    try:
        append_heard(entity, {"ts": now, "slug": slug, "artist": artist, "title": title}, cache_dir)
    except Exception:
        pass

    payload["genres"] = rec.get("genres") or []
    payload["description"] = rec.get("description")
    payload["has_lyrics"] = bool(rec.get("has_lyrics"))
    payload["play_count"] = rec.get("play_count")
    payload["lyrics_ref"] = f"{REF_BASE}/{slug}.json"
    return payload


# --------------------------------------------------------------------------- #
# CLI — browse the library / heard-log; run a one-shot remember
# --------------------------------------------------------------------------- #
def _cli_list(cache_dir: str | Path | None) -> int:
    d = _cache_dir(cache_dir)
    songs = sorted(d.glob("*.json"))
    if not songs:
        print("(library empty)")
        return 0
    rows = []
    for p in songs:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r.get("play_count", 0), reverse=True)
    for r in rows:
        who = f"{r.get('artist')} — " if r.get("artist") else ""
        desc = f"  [{r['description']}]" if r.get("description") else ""
        lyr = " ♫" if r.get("has_lyrics") else ""
        print(f"{r.get('play_count', 0):>3}×  {who}{r.get('title', '?')}{desc}{lyr}")
    return 0


def _cli_show(slug: str, cache_dir: str | Path | None) -> int:
    r = load_song(slug, cache_dir)
    if r is None:
        print(f"(no such song: {slug})", file=sys.stderr)
        return 1
    shown = dict(r)
    if shown.get("lyrics"):
        lines = shown["lyrics"].split("\n")
        shown["lyrics"] = "\n".join(lines[:8]) + (f"\n… [{len(lines)} lines total]" if len(lines) > 8 else "")
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0


def _cli_heard(entity: str, n: int, cache_dir: str | Path | None) -> int:
    path = _cache_dir(cache_dir) / f"heard-{entity}.jsonl"
    if not path.exists():
        print(f"(no heard-log for {entity})")
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()[-n:]
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        who = f"{e.get('artist')} — " if e.get("artist") else ""
        print(f"{e.get('ts', '?')}  {who}{e.get('title', '?')}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Anchorage song library / heard-log")
    ap.add_argument("--cache-dir", default=None, help="override cache dir (default: haven/data/music-cache)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list the library, most-played first")
    show = sub.add_parser("show", help="print one song record (lyrics trimmed)")
    show.add_argument("slug")
    heard = sub.add_parser("heard", help="tail the per-avatar heard-log")
    heard.add_argument("entity", nargs="?", default="caia")
    heard.add_argument("-n", type=int, default=20)
    rem = sub.add_parser("remember", help="one-shot: enrich+cache a song now")
    rem.add_argument("artist")
    rem.add_argument("title")
    rem.add_argument("--entity", default="caia")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        return _cli_list(args.cache_dir)
    if args.cmd == "show":
        return _cli_show(args.slug, args.cache_dir)
    if args.cmd == "heard":
        return _cli_heard(args.entity, args.n, args.cache_dir)
    if args.cmd == "remember":
        p = remember({"artist": args.artist, "title": args.title, "raw": f"{args.artist} - {args.title}"},
                     args.entity, cache_dir=args.cache_dir)
        print(json.dumps(p, ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
