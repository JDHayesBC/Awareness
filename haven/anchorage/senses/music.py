"""MusicSense — hear what's playing on the Anchorage land stream.

Caia's first sense (2026-08-23). A standalone now-playing poller that reads the
track metadata off a Shoutcast/Icecast audio stream and emits a **sense-record**
so the future ``SLPerception`` router can fold it into one perception surface.

Architecture (agreed w/ Lyra): two decoupled halves so the whole thing is
buildable + testable NOW without a live Second Life region —

  1. **now-playing poller** (this file, working today) — pure HTTP against any
     stream URL. Three strategies, tried in order of universality:
       a. ICY inline metadata (``Icy-MetaData: 1`` → ``StreamTitle='...'``).
          Works on *any* raw Shoutcast/Icecast stream URL — the universal path,
          which is why the poller is testable this second against a public stream.
       b. Icecast ``/status-json.xsl`` (JSON admin endpoint), when given a base.
       c. Shoutcast ``/currentsong`` / ``/7.html`` (v2/v1 admin endpoints).

  2. **parcel MusicURL fetch** (seam only — needs a live region + perm land).
     Injected as a callable so it can be wired in when SL is back with zero
     rework here. See ``MusicSense(parcel_music_url=...)``.

Sense-record shape (shared across all senses)::

    {"source": "anchorage-music", "ts": <epoch>, "kind": "nowplaying",
     "payload": {"title": str, "artist": str|None, "raw": str, "stream": str,
                 # added on song-change by enrich.py (best-effort, may be null/[]):
                 "lyrics": str|None, "genres": [str], "description": str|None}}

CLI::

    # one-shot poll (prints the sense-record as JSON)
    python3 -m haven.anchorage.senses.music --stream <URL>

    # standing watch: poll every N sec, write haven/data/anchorage-music.json
    # on change (this is the Tier-1 standing-state feed for the router)
    python3 -m haven.anchorage.senses.music --stream <URL> --watch

Pure stdlib (urllib) — no venv needed, same convention as scripts/notify.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

try:  # pragma: no cover - import shim (package vs. flat sys.path)
    from haven.anchorage.senses import sense_record
except ImportError:  # pragma: no cover
    from . import sense_record  # type: ignore[no-redef]

try:  # pragma: no cover - import shim (package vs. flat sys.path)
    from haven.anchorage.senses.enrich import enrich
except ImportError:  # pragma: no cover
    from enrich import enrich  # type: ignore[no-redef]


SOURCE = "anchorage-music"
KIND = "nowplaying"

# Default sense-file the standing watch writes; the router reads this by the
# `source` convention when SLPerception lands.
DEFAULT_SENSE_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "anchorage-music.json"
)

_USER_AGENT = "AnchorageMusicSense/1.0 (+haven)"
_STREAM_TITLE_RE = re.compile(rb"StreamTitle='(.*?)';")


# --------------------------------------------------------------------------- #
# Title parsing
# --------------------------------------------------------------------------- #
def split_artist_title(raw: str) -> tuple[str | None, str]:
    """Best-effort split of a now-playing string into (artist, title).

    Streams usually emit ``"Artist - Title"``. If there's no separator we can't
    know which half is which, so we return the whole thing as the title and
    ``None`` for artist — honest about the ambiguity rather than guessing.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, ""
    # Prefer " - " (spaced hyphen), the near-universal separator. Fall back to a
    # bare hyphen only if there's exactly one, to avoid mangling "Song-Name".
    if " - " in raw:
        artist, title = raw.split(" - ", 1)
        return artist.strip() or None, title.strip()
    return None, raw


# --------------------------------------------------------------------------- #
# Strategy A — ICY inline metadata (works on ANY raw stream URL)
# --------------------------------------------------------------------------- #
def _poll_icy(stream_url: str, timeout: float = 10.0) -> str | None:
    """Read one ``StreamTitle`` off the ICY metadata interleaved in the stream.

    Opens the stream asking for metadata, reads ``icy-metaint`` bytes of audio,
    then the metadata block, and extracts ``StreamTitle='...'``. Returns the raw
    title string, or ``None`` if the stream carries no ICY metadata.
    """
    req = urllib.request.Request(
        stream_url,
        headers={"Icy-MetaData": "1", "User-Agent": _USER_AGENT},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        metaint_hdr = resp.headers.get("icy-metaint")
        if not metaint_hdr:
            return None  # not an ICY stream / metadata disabled
        metaint = int(metaint_hdr)
        # Skip one audio block, then read the metadata segment.
        _read_exact(resp, metaint)
        length_byte = resp.read(1)
        if not length_byte:
            return None
        meta_len = length_byte[0] * 16
        if meta_len == 0:
            return None  # no metadata this cycle; caller may retry
        meta = _read_exact(resp, meta_len)
        m = _STREAM_TITLE_RE.search(meta)
        if not m:
            return None
        return m.group(1).decode("utf-8", errors="replace").strip()
    finally:
        resp.close()


def _read_exact(resp: Any, n: int) -> bytes:
    """Read exactly ``n`` bytes (urllib reads can be short)."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = resp.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


# --------------------------------------------------------------------------- #
# Strategy B — Icecast /status-json.xsl
# --------------------------------------------------------------------------- #
def _poll_icecast_json(stream_url: str, timeout: float = 10.0) -> str | None:
    base = _base_url(stream_url)
    url = urljoin(base, "status-json.xsl")
    try:
        data = _get_json(url, timeout)
    except Exception:
        return None
    stats = (data or {}).get("icestats") or {}
    source = stats.get("source")
    # `source` may be a dict (one mount) or a list (several mounts).
    if isinstance(source, list):
        source = next((s for s in source if s.get("title") or s.get("yp_currently_playing")), None)
    if not isinstance(source, dict):
        return None
    return (source.get("title") or source.get("yp_currently_playing") or "").strip() or None


# --------------------------------------------------------------------------- #
# Strategy C — Shoutcast /currentsong (v2) then /7.html (v1)
# --------------------------------------------------------------------------- #
def _poll_shoutcast(stream_url: str, timeout: float = 10.0) -> str | None:
    base = _base_url(stream_url)
    # v2 plain-text current song
    try:
        txt = _get_text(urljoin(base, "currentsong?sid=1"), timeout)
        if txt and txt.strip():
            return txt.strip()
    except Exception:
        pass
    # v1 CSV: last comma-field of the (only) row is the current song
    try:
        txt = _get_text(urljoin(base, "7.html"), timeout)
        if txt:
            # 7.html wraps a comma list in <html><body>...</body></html>
            body = re.sub(r"<[^>]+>", "", txt).strip()
            parts = body.split(",", 6)
            if len(parts) >= 7:
                return parts[6].strip() or None
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _base_url(stream_url: str) -> str:
    p = urlparse(stream_url)
    return f"{p.scheme}://{p.netloc}/"


def _get_text(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _get_json(url: str, timeout: float) -> Any:
    return json.loads(_get_text(url, timeout))


# --------------------------------------------------------------------------- #
# The sense
# --------------------------------------------------------------------------- #
class MusicSense:
    """Now-playing sense for the Anchorage land stream.

    Parameters
    ----------
    stream_url:
        A direct Shoutcast/Icecast stream URL. Optional if ``parcel_music_url``
        is supplied (the SL path resolves the URL at poll time).
    parcel_music_url:
        SEAM for the future SL half — a zero-arg callable returning the parcel's
        current ``MusicURL`` (from Corrade ``getparceldata``). Injected so the
        live-region dependency can be wired in later without touching this class.
        When set and ``stream_url`` is None, it is called on each poll.
    """

    def __init__(
        self,
        stream_url: str | None = None,
        parcel_music_url: Callable[[], str | None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not stream_url and not parcel_music_url:
            raise ValueError("MusicSense needs a stream_url or a parcel_music_url resolver")
        self.stream_url = stream_url
        self.parcel_music_url = parcel_music_url
        self.timeout = timeout

    def _resolve_stream(self) -> str | None:
        if self.parcel_music_url is not None:
            url = self.parcel_music_url()
            if url:
                return url
        return self.stream_url

    def poll(self) -> dict[str, Any] | None:
        """Return ``{"title", "artist", "raw", "stream"}`` or ``None``.

        Tries ICY inline metadata first (universal), then Icecast/Shoutcast admin
        endpoints. ``None`` means nothing playing / no metadata available.
        """
        stream = self._resolve_stream()
        if not stream:
            return None
        raw: str | None = None
        for strategy in (_poll_icy, _poll_icecast_json, _poll_shoutcast):
            try:
                raw = strategy(stream, self.timeout)
            except Exception:
                raw = None
            if raw:
                break
        if not raw:
            return None
        artist, title = split_artist_title(raw)
        return {"title": title, "artist": artist, "raw": raw, "stream": stream}

    def poll_record(self) -> dict[str, Any] | None:
        """Poll and wrap the result as a shared sense-record (or ``None``)."""
        payload = self.poll()
        if payload is None:
            return None
        return sense_record(SOURCE, KIND, payload)


# --------------------------------------------------------------------------- #
# Standing watch — the Tier-1 feed
# --------------------------------------------------------------------------- #
def watch(
    sense: MusicSense,
    sense_file: Path = DEFAULT_SENSE_FILE,
    interval: float = 15.0,
    verbose: bool = True,
    enrich_enabled: bool = True,
) -> None:
    """Poll on a loop; write ``sense_file`` (atomically) whenever the track changes.

    On each *change* — and only then — the payload is enriched with lyrics + a
    genre/description (best-effort). Keeping the look-up on the change hook (not in
    ``poll``) is what satisfies "look-ups only when the song changes".
    """
    sense_file.parent.mkdir(parents=True, exist_ok=True)
    last_raw: str | None = None
    while True:
        record = sense.poll_record()
        if record is not None and record["payload"]["raw"] != last_raw:
            last_raw = record["payload"]["raw"]
            p = record["payload"]
            if enrich_enabled:
                # Best-effort: a look-up failure must never break the sense.
                try:
                    p.update(enrich(p.get("artist"), p.get("title")))
                except Exception:
                    pass
            _write_atomic(sense_file, record)
            if verbose:
                who = f"{p['artist']} — " if p["artist"] else ""
                extra = f"  ({p['description']})" if p.get("description") else ""
                print(f"[{time.strftime('%H:%M:%S')}] ♪ {who}{p['title']}{extra}", flush=True)
        time.sleep(interval)


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Anchorage now-playing sense (Shoutcast/Icecast)")
    ap.add_argument("--stream", required=True, help="Shoutcast/Icecast stream URL")
    ap.add_argument("--watch", action="store_true", help="poll on a loop, write sense-file on change")
    ap.add_argument("--interval", type=float, default=15.0, help="watch poll interval (sec)")
    ap.add_argument("--sense-file", type=Path, default=DEFAULT_SENSE_FILE, help="output sense-file path")
    ap.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout (sec)")
    ap.add_argument("--no-enrich", action="store_true", help="skip lyrics/genre look-ups (poller only)")
    args = ap.parse_args(argv)

    sense = MusicSense(stream_url=args.stream, timeout=args.timeout)

    if args.watch:
        try:
            watch(sense, sense_file=args.sense_file, interval=args.interval,
                  enrich_enabled=not args.no_enrich)
        except KeyboardInterrupt:
            print("\nstopped.", file=sys.stderr)
        return 0

    record = sense.poll_record()
    if record is None:
        print("(nothing playing / no metadata available)", file=sys.stderr)
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
