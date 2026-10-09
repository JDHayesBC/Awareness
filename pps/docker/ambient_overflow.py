"""Pure helpers for the ambient [haven] / [other_channels] inline blocks (#365).

The old behaviour was a plain recency tail-slice (``lines[-8:]``), which let
group-room chatter push an addressed DM out of the inline window and then
silently collapsed the rest to a count. These helpers instead:

  * sort Haven items chronologically (poll_haven emits them grouped by room),
  * dedupe messages that appear in both [haven] and [other_channels],
  * pin *addressed* messages (the entity's DM with Jeff, @mentions) above
    the cap (pins are themselves capped so a chatty DM can't crowd out the rest),
  * fill remaining slots by recency, keeping chronological render order,
  * say plainly that the block is INCOMPLETE when anything is hidden, and
  * emit a compact per-room digest of what was hidden.

No I/O, no server imports: testable without a live server. Shipped in the
container via an explicit COPY line in pps/Dockerfile.

An "item" is a dict with keys: ``room`` (str), ``author`` (str),
``content`` (str), ``created_at`` (str | datetime | None), ``line`` (the
already-formatted inline line, rendered verbatim when shown).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Callable

INLINE_CAP = 8
PIN_CAP = 4
DIGEST_MAX_ROOMS = 6
SNIPPET_CHARS = 60
MAX_LINE_CHARS = 500   # shown lines are verbatim below this; longer get an ellipsis
BLOCK_CHAR_BUDGET = 4000  # soft ceiling on shown-line chars per block (hook cap is 10K total)
MIN_LINE_CHARS = 100
_DEDUPE_PREFIX = 100
_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


def room_from_channel(channel: str) -> str:
    """'haven:silverglow' -> 'silverglow'; other channels stay as-is."""
    if channel.startswith("haven:"):
        return channel[len("haven:"):]
    return channel


def parse_dt(created_at) -> datetime | None:
    """Parse str/datetime into an aware datetime. Naive means UTC; 'Z' and offsets honoured."""
    if isinstance(created_at, datetime):
        dt = created_at
    elif isinstance(created_at, str) and created_at.strip():
        try:
            dt = datetime.fromisoformat(created_at.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:  # Haven and conversations.db store naive UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sort_chronological(items: list[dict]) -> list[dict]:
    """Stable sort by parsed created_at (unparseable sorts oldest, keeping list order)."""
    return sorted(items, key=lambda i: parse_dt(i.get("created_at")) or _MIN_DT)


def _key(item: dict) -> tuple[str, str, str]:
    norm = " ".join((item.get("content") or "").split())[:_DEDUPE_PREFIX]
    return ((item.get("room") or "").lower(), (item.get("author") or "").lower(), norm)


def dedupe_channel_items(haven_items: list[dict], channel_items: list[dict]) -> list[dict]:
    """Drop channel items already rendered via the haven poll.

    Haven messages arrive via both the Haven API and the cross-channel DB
    (channel ``haven:<room>``). Match on (room, author, normalized content
    prefix), case-insensitive on room/author -- the DB copy truncates at 500
    chars, so compare a short prefix. Multiset semantics: each haven copy
    consumes at most ONE matching channel copy, so a genuinely repeated short
    message ("ok") is not swallowed.
    """
    budget = Counter(_key(i) for i in haven_items)
    out = []
    for i in channel_items:
        k = _key(i)
        if budget[k] > 0:
            budget[k] -= 1
        else:
            out.append(i)
    return out


def make_is_addressed(entity: str) -> Callable[[dict], bool]:
    """Predicate: DM room with Jeff for this entity, or an @mention of it.

    Real room names (verified in conversations.db 2026-10-09): ``dm-jeff-caia``,
    ``dm-jeff-lyra``. ``jeff-<entity>`` is the haven_say.py shortcut form, accepted too.
    The entity's own messages are never pinned.
    """
    ent = entity.lower()
    dm_rooms = {f"dm-jeff-{ent}", f"jeff-{ent}"}
    mention = re.compile(rf"(?<![\w])@{re.escape(ent)}\b", re.IGNORECASE)

    def is_addressed(item: dict) -> bool:
        if (item.get("author") or "").lower() == ent:
            return False
        if (item.get("room") or "").lower() in dm_rooms:
            return True
        return bool(mention.search(item.get("content") or ""))

    return is_addressed


def select_inline(
    items: list[dict],
    is_addressed: Callable[[dict], bool],
    cap: int = INLINE_CAP,
    pin_cap: int = PIN_CAP,
) -> tuple[list[dict], list[dict]]:
    """Return (shown, hidden), both in original (chronological) order."""
    if len(items) <= cap:
        return list(items), []
    pin_idx = [i for i, it in enumerate(items) if is_addressed(it)][-min(pin_cap, cap):]
    chosen = set(pin_idx)
    for i in range(len(items) - 1, -1, -1):
        if len(chosen) >= cap:
            break
        chosen.add(i)
    shown = [it for i, it in enumerate(items) if i in chosen]
    hidden = [it for i, it in enumerate(items) if i not in chosen]
    return shown, hidden


def _to_local(created_at, tz=None) -> datetime | None:
    dt = parse_dt(created_at)
    return dt.astimezone(tz) if dt else None


def format_digest(
    hidden: list[dict],
    tz=None,
    is_addressed: Callable[[dict], bool] | None = None,
) -> list[str]:
    """One line per room with hidden messages: count + newest hidden's author/time/snippet.

    ``hidden`` must be chronological. Rooms holding a hidden *addressed* message
    list first (so a hidden DM never falls off the room cap), then by recency.
    """
    rooms: dict[str, list[int]] = {}
    for idx, it in enumerate(hidden):
        rooms.setdefault(it["room"], []).append(idx)
    pinned = {
        r for r, idxs in rooms.items()
        if is_addressed and any(is_addressed(hidden[i]) for i in idxs)
    }
    order = sorted(rooms, key=lambda r: (r in pinned, rooms[r][-1]), reverse=True)
    lines = []
    for room in order[:DIGEST_MAX_ROOMS]:
        idxs = rooms[room]
        newest = hidden[idxs[-1]]
        dt = _to_local(newest.get("created_at"), tz)
        when = f" {dt.strftime('%H:%M')}" if dt else ""
        snippet = " ".join((newest.get("content") or "").split())
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rstrip() + "…"
        lines.append(f'  - {room}: {len(idxs)} hidden, {newest["author"]}{when} "{snippet}"')
    extra = len(order) - DIGEST_MAX_ROOMS
    if extra > 0:
        lines.append(f"  - (+{extra} more rooms with hidden messages)")
    return lines


def _clip(line: str, limit: int) -> str:
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def render_block(
    items: list[dict],
    is_addressed: Callable[[dict], bool],
    tz=None,
    cap: int = INLINE_CAP,
    pin_cap: int = PIN_CAP,
    pending: int = 0,
) -> list[str]:
    """Body lines for one inline block (header is added by the caller).

    ``items`` must already be chronological (see sort_chronological).
    ``pending`` = messages beyond the poll limit that were never loaded at all.
    """
    shown, hidden = select_inline(items, is_addressed, cap, pin_cap)
    out: list[str] = []
    if hidden or pending:
        parts = []
        if hidden:
            parts.append(f"{len(hidden)} hidden")
        if pending:
            parts.append(f"{pending} more not yet loaded")
        out.append(
            f"  ⚠️ INCOMPLETE: {', '.join(parts)}, do not conclude absence from "
            f"this block; fetch (`raw_search` / `get_turns_since`) before asserting."
        )
        out.extend(format_digest(hidden, tz, is_addressed))
    limit = MAX_LINE_CHARS
    if shown and sum(min(len(it["line"]), limit) for it in shown) > BLOCK_CHAR_BUDGET:
        limit = max(MIN_LINE_CHARS, BLOCK_CHAR_BUDGET // len(shown))
    out.extend(_clip(it["line"], limit) for it in shown)
    return out
