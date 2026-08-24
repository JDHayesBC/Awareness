"""pose_cache.py — the Anchorage furniture-pose library + per-avatar "posed" log.

The persistence + resolution half of the **pose sense** (``pose.py`` observes raw
positions/anim-UUIDs off Corrade; this turns them into a *known pose* and remembers
it). Sibling of ``music_cache.py`` and built to the same discipline — but where music
is *ambient* (one track for everyone), a pose is *agent-attributed*: it is emitted **by**
an avatar, so every record carries a **subject** ("whose body is this?"). See
``work/secondlife/animation-awareness-design.md``.

Two durable artifacts, both under ``haven/data/pose-cache/``:

  * ``furniture/<key>.json`` — one file per FURNITURE, **shared across avatars** (a chair's
                               pose set is universal). Carries, per pose:
                               ``{anim_uuid, position, rotation, menu, label, gender, kind}``.
                               Built from an AVpos notecard (``posedict`` tooling) — the
                               reference library, cache-first.
  * ``uuid-index.json``      — derived global ``anim_uuid -> {furniture_key, label, menu,
                               gender, kind}`` for O(1) **self** look-up off the animation
                               notification. Rebuildable from the furniture files.
  * ``posed-<entity>.jsonl`` — append-only, one line per pose-change THIS avatar OBSERVED
                               (on self OR another). The "who was in what pose when" memory.

The daemon calls exactly one thing per observed change::

    payload = recognize(payload, entity="lyra")

``recognize`` is **reference-first + best-effort**: any missing file / lookup miss degrades
to an honest ``source="blind-freeform"`` or ``parent-only`` rather than a fabricated pose.

**The resolution is BIMODAL, never a confidence gradient.** Furniture positions come back
from Corrade *configured-exact* (verified Δ=0.0000), so a queried position either matches a
card entry within a representation-only ``EPS`` or it matches nothing. There is no "close
enough" to threshold: a no-match is a first-class ``blind-freeform`` value, and the matcher
**never snaps to nearest** — snapping would label a stillness as a pose that isn't happening.

Pure stdlib. No network. Unit-testable with a temp ``cache_dir``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
# haven/anchorage/senses/pose_cache.py → parents[2] == haven.
_CACHE_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "pose-cache"

# Representation-only tolerance for the configured-exact match (metres). Positions
# are configured, not physics-sampled, so this only absorbs float-repr wobble — it is
# NOT a confidence knob. A real different pose is centimetres away; freeform is arbitrary.
EPS = 0.02


def _cache_dir(base: str | Path | None = None) -> Path:
    d = Path(base) if base else _CACHE_DIR_DEFAULT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    """Local-timezone ISO-8601 to the second (matches the household clock)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Library I/O
# --------------------------------------------------------------------------- #
def load_furniture(key: str, cache_dir: str | Path | None = None) -> Optional[dict]:
    """Load one furniture reference file (``furniture/<key>.json``) or ``None``."""
    path = _cache_dir(cache_dir) / "furniture" / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_uuid_index(cache_dir: str | Path | None = None) -> dict:
    """Load the global ``anim_uuid -> meaning`` index (``{}`` if absent/broken)."""
    path = _cache_dir(cache_dir) / "uuid-index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def append_posed(entity: str, entry: dict, cache_dir: str | Path | None = None) -> None:
    """Append one line to ``posed-<entity>.jsonl`` (the per-avatar temporal log)."""
    d = _cache_dir(cache_dir)
    line = json.dumps(entry, ensure_ascii=False)
    with (d / f"posed-{entity}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# The bimodal matcher — configured-exact or nothing
# --------------------------------------------------------------------------- #
def _iter_pose_entries(furniture: dict):
    """Yield every pose entry across gender/menu in a furniture doc."""
    for gender, menus in (furniture.get("poses") or {}).items():
        for menu, entries in (menus or {}).items():
            for e in entries or []:
                yield e


def match_pose(
    furniture: dict,
    position,
    eps: float = EPS,
) -> tuple[Optional[dict], list[str]]:
    """Match a furniture-local ``position`` to a card entry, **bimodally**.

    Returns ``(entry, alternates)``:
      * ``(entry, [...])`` — an exact match within ``eps``. ``alternates`` lists the
        labels of any *other* entries also within ``eps`` (a genuine position-collision,
        e.g. two poses that share a sit position and differ only in the anim asset).
      * ``(None, [])`` — no card entry within ``eps``. This is ``blind-freeform``: the
        caller must NOT snap to nearest. Honest absence, not a guess.

    Gender is auto-resolved: male and female sit positions differ, so the exact match
    implicitly selects the right sitter without a gender hint.
    """
    if not furniture or position is None:
        return None, []
    px, py, pz = float(position[0]), float(position[1]), float(position[2])
    within: list[tuple[float, dict]] = []
    for e in _iter_pose_entries(furniture):
        p = e.get("position")
        if not p:
            continue
        d = math.dist((px, py, pz), (float(p[0]), float(p[1]), float(p[2])))
        if d <= eps:
            within.append((d, e))
    if not within:
        return None, []
    within.sort(key=lambda t: t[0])
    best = within[0][1]
    alternates = [e.get("label") for _, e in within[1:]]
    return best, alternates


# --------------------------------------------------------------------------- #
# The one public entry point the daemon calls, per observed pose-change
# --------------------------------------------------------------------------- #
def recognize(
    payload: dict,
    entity: str,
    *,
    cache_dir: str | Path | None = None,
    clock=_now_iso,
    log_it: bool = True,
) -> dict:
    """Resolve a raw pose observation against the reference library, set an honest
    ``source``, append to ``posed-<entity>.jsonl``, and return the augmented payload.

    Input ``payload`` shapes (produced by ``pose.py``), in resolution priority:
      * ``{subject, ..., uuid: <anim uuid>}``            → self-anim (exact, freeform-safe)
      * ``{subject, ..., furniture_key, position:[x,y,z]}`` → geometry (exact or blind)
      * ``{subject, ..., seated: True}`` (no furniture_key)  → parent-only (pose unknown)
      * ``{subject, ..., seated: False}``                    → not a pose; returned as-is

    Reference-first + best-effort: any lookup failure degrades to ``blind-freeform`` /
    ``parent-only`` — the sense must never break or invent a pose.
    """
    payload.setdefault("attribution", "agent")

    uuid = payload.get("uuid")
    fkey = payload.get("furniture_key")
    pos = payload.get("position")

    if uuid:
        idx = load_uuid_index(cache_dir).get(uuid)
        if idx:
            payload.update(
                source="self-anim", label=idx.get("label"), menu=idx.get("menu"),
                furniture_key=idx.get("furniture_key"), gender=idx.get("gender"),
                kind=idx.get("kind"),
            )
        else:
            # A UUID we've never carded (freeform dance, a foreign chair) — honest blind.
            payload.update(source="blind-freeform", label=None, menu=None)
    elif fkey and pos is not None:
        furniture = load_furniture(fkey, cache_dir)
        entry, alts = match_pose(furniture or {}, pos)
        if entry:
            payload.update(
                source="geometry-exact", label=entry.get("label"), menu=entry.get("menu"),
                gender=entry.get("gender"), kind=entry.get("kind"),
                anim_uuid=entry.get("anim_uuid"),
            )
            if alts:
                payload["ambiguous_with"] = alts
        else:
            payload.update(source="blind-freeform", label=None, menu=None)
    elif payload.get("seated"):
        # Seated on something we have no card for → we know they sit together, not the pose.
        payload.update(source="parent-only", label=None, menu=None)
    else:
        # Standing / not animating on furniture — not a pose event.
        payload.setdefault("source", "none")
        return payload

    if log_it:
        try:
            append_posed(entity, {
                "ts": clock(),
                "subject": payload.get("subject"),
                "subject_uuid": payload.get("subject_uuid"),
                "self": payload.get("self", False),
                "source": payload.get("source"),
                "label": payload.get("label"),
                "menu": payload.get("menu"),
                "furniture_key": payload.get("furniture_key"),
                "uuid": payload.get("anim_uuid") or uuid,
            }, cache_dir)
        except Exception:
            pass
    return payload
