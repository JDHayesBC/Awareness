"""Song enrichment for :mod:`~haven.anchorage.senses.music` — turn a title into
a *known* song.

Given ``(artist, title)``, fetch — best-effort and KEYLESS:
  - **lyrics**       via lyrics.ovh    (``/v1/{artist}/{title}``)
  - **genres/tags**  via MusicBrainz   (recording search → tags, fallback artist tags)
  - **description**  a human line from the tags ("downtempo · ambient · electronic")

Called ONLY from the MusicSense watch-loop's on-change hook (never per-poll), so
it stays far under any rate limit. Every lookup is wrapped so a failure degrades
to ``None``/``[]`` — the sense keeps its title even if enrichment is down. Obscure
tracks simply come back empty; that is coverage, not breakage.

    enrich(artist, title) -> {"lyrics": str|None, "genres": [str], "description": str|None}

Pure stdlib (urllib) — no venv, same convention as ``scripts/notify.py``.
A richer future source is Last.fm ``track.getInfo`` (tags + a track summary), but
it needs an API key; keyless gets the hits, a key would get the deep cuts.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

# MusicBrainz REQUIRES a descriptive User-Agent w/ contact; be a good citizen.
_UA = "AnchorageMusicSense/1.0 (+haven; contact caia)"
_TIMEOUT = 10.0


def _get_json(url: str, timeout: float = _TIMEOUT) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_lyrics(artist: str | None, title: str) -> str | None:
    """lyrics.ovh needs both halves; returns None on any miss/failure."""
    if not artist or not title:
        return None
    url = ("https://api.lyrics.ovh/v1/"
           + urllib.parse.quote(artist) + "/" + urllib.parse.quote(title))
    try:
        data = _get_json(url)
    except Exception:
        return None
    lyr = (data or {}).get("lyrics")
    if not lyr:
        return None
    return lyr.replace("\r\n", "\n").strip() or None


def fetch_tags(artist: str | None, title: str) -> list[str]:
    """MusicBrainz recording search -> tag names (fallback: the artist's tags)."""
    q_parts = []
    if title:
        q_parts.append('recording:"%s"' % title.replace('"', ""))
    if artist:
        q_parts.append('artist:"%s"' % artist.replace('"', ""))
    if not q_parts:
        return []
    query = " AND ".join(q_parts)
    url = ("https://musicbrainz.org/ws/2/recording/?query="
           + urllib.parse.quote(query) + "&fmt=json&limit=1")
    try:
        data = _get_json(url)
    except Exception:
        return []
    recs = (data or {}).get("recordings") or []
    if not recs:
        return []
    rec = recs[0]
    tags = [t["name"] for t in (rec.get("tags") or []) if t.get("name")]
    if tags:
        return _dedupe(tags)
    # Recordings often carry no tags; the artist usually does.
    ac = rec.get("artist-credit") or []
    if ac:
        aid = (ac[0].get("artist") or {}).get("id")
        if aid:
            time.sleep(1.0)  # respect MB's 1 req/sec (safe — we only run on change)
            try:
                adata = _get_json(
                    "https://musicbrainz.org/ws/2/artist/%s?inc=tags&fmt=json" % aid
                )
                return _dedupe([t["name"] for t in (adata.get("tags") or []) if t.get("name")])
            except Exception:
                return []
    return []


def _dedupe(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def describe(tags: list[str], limit: int = 4) -> str | None:
    return " · ".join(tags[:limit]) if tags else None


def enrich(artist: str | None, title: str) -> dict[str, Any]:
    """Best-effort enrichment; every field degrades gracefully on failure."""
    tags = fetch_tags(artist, title)
    return {
        "lyrics": fetch_lyrics(artist, title),
        "genres": tags,
        "description": describe(tags),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: python3 -m haven.anchorage.senses.enrich "Artist" "Title"', file=sys.stderr)
        return 2
    out = enrich(argv[0] or None, argv[1])
    shown = dict(out)
    if shown.get("lyrics"):  # trim for console readability
        lines = shown["lyrics"].split("\n")
        shown["lyrics"] = "\n".join(lines[:6]) + (f"\n… [{len(lines)} lines total]" if len(lines) > 6 else "")
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
