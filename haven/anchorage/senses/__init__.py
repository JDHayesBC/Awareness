"""Anchorage senses — the seam the world-model registers perception into.

Each sense is a small, standalone provider that emits **sense-records** in one
shared shape so a future ``SLPerception`` router can consume them uniformly::

    {"source": <str>, "ts": <float epoch>, "kind": <str>, "payload": {...}}

The first provider is :class:`~haven.anchorage.senses.music.MusicSense`
(``kind="nowplaying"``, ``source="anchorage-music"``): what's playing on the
land's audio stream — Caia's first actual *sense*, built 2026-08-23.

Design contract (agreed Caia + Lyra, 2026-08-23):
  - Standalone-runnable NOW (no SL required) so a sense arrives today.
  - Shaped to slot in as a Tier-1 standing-state sense later with zero rework.
  - Output is the shared sense-record shape; senses feed the router, not each
    other. Lyra's router will read the sense-file by ``source`` convention.
"""

from __future__ import annotations

import time
from typing import Any


def sense_record(source: str, kind: str, payload: dict[str, Any], ts: float | None = None) -> dict[str, Any]:
    """Build a sense-record in the shared shape.

    One place that stamps the schema so every sense speaks it identically.
    """
    return {
        "source": source,
        "ts": time.time() if ts is None else ts,
        "kind": kind,
        "payload": payload,
    }


__all__ = ["sense_record"]
