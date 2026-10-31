"""[last-contact] and [first-meeting] ambient front-block lines (GH #383).

Pure helpers, deliberately importable without booting server_http.py (same shape
as ambient_overflow.py).  Everything is computed from ONE entity's own
``conversations.db`` / ``inventory.db`` -- callers pass that entity's paths, and
nothing here ever looks at another entity's data.

Contract: every public function swallows its own errors and returns "nothing"
(None / []), because ambient_recall must never fail on account of these lines.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

JEFF = "Jeff"
FIRST_MEETING_WINDOW = timedelta(hours=24)
FIRST_MEETING_CAP = 3
# How far back (rows, by autoincrement id) we walk looking for Jeff / recent speakers.
# id order is insertion order, so this is a cheap backward rowid scan -- no index needed.
_JEFF_SCAN_ROWS = 3000
_RECENT_SCAN_ROWS = 5000
_MAX_SPEAKERS = 10
_STALE_RUN_STOP = 50

# --- Harness-prompt filter ----------------------------------------------------
# SOURCE OF TRUTH: HARNESS_PROMPT_PREFIXES / HARNESS_TICK_TAG_RE /
# is_non_jeff_prompt in .claude/hooks/inject_context.py (#322, #325).  The hook
# lives outside the docker image, so the values are duplicated here;
# pps/tests/test_last_contact.py::test_harness_filter_matches_hook fails if the
# two drift apart.  A legacy bug stored ~586 cron prompts as Jeff turns, so
# without this filter a heartbeat would read as "Jeff spoke just now".
HARNESS_PROMPT_PREFIXES = (
    "<task-notification",
    "<cross-session-message",
    "<channel source=\"terminal-wake\"",  # #351 self-wake from Haven/SL-me, not Jeff
    "<system-reminder",
    "<<autonomous-loop",
    "heartbeat tick",
    "[heartbeat",
    "heartbeat (",
    "[night-watch",
    "[you are in second life",
    "[identity wall",
    "[haven messages",
)
HARNESS_TICK_TAG_RE = re.compile(r"^\[[^\]\n]{0,48}?\b(?:tick|heartbeat)\b")


def is_non_jeff_prompt(prompt: str) -> bool:
    """True when `prompt` is harness/tick text rather than a genuine Jeff message."""
    head = (prompt or "").lstrip().lower()
    return head.startswith(HARNESS_PROMPT_PREFIXES) or bool(HARNESS_TICK_TAG_RE.match(head))


# --- Authors that are never a "new person" -------------------------------------
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SYSTEM_AUTHORS = frozenset({
    "system", "tick", "heartbeat", "harness", "webhook", "bot", "unknown",
    "the anchorage", "anchorage", "haven", "server",
})


def is_ignorable_author(name: str, entity_name: str) -> bool:
    """Self, the entity's own avatars, system/harness authors, uuids and e-mail headers."""
    n = (name or "").strip()
    if not n:
        return True
    low = n.lower()
    ent = (entity_name or "").strip().lower()
    if ent and re.fullmatch(re.escape(ent) + r"(pattern)?( resident)?", low):
        return True
    if low in _SYSTEM_AUTHORS or _UUID_RE.match(low):
        return True
    if "@" in n or n.startswith("<"):
        return True
    return False


# --- Time helpers --------------------------------------------------------------
def parse_ts(value) -> datetime | None:
    """Parse either 'YYYY-MM-DD HH:MM:SS' (naive, UTC) or ISO-8601 ('...T...+00:00')
    into an aware UTC datetime.  Never string-compare these -- formats differ."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def human_duration(delta: timedelta) -> str:
    """<1m 'just now'; 'Nm'; 'XhYm' under 48h; 'Nd' beyond.  (No 'ago' suffix.)"""
    secs = delta.total_seconds()
    if secs < 60:
        return "just now"
    minutes = int(secs // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h{mins}m"
    return f"{hours // 24}d"


def _ago(delta: timedelta) -> str:
    d = human_duration(delta)
    return d if d == "just now" else f"{d} ago"


def _connect_ro(path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, timeout=2.0)


# --- [last-contact] ------------------------------------------------------------
def latest_jeff_row(conn: sqlite3.Connection) -> tuple[datetime, str] | None:
    """(created_at, channel) of Jeff's newest genuine row across ALL channels.

    ORDER BY created_at (not id) so idx_messages_author_name_time serves it as a
    seek; ORDER BY id would sort every Jeff row (~39k) in a temp b-tree per call."""
    cur = conn.execute(
        "SELECT created_at, channel, content FROM messages "
        "WHERE author_name = ? ORDER BY created_at DESC LIMIT ?",
        (JEFF, _JEFF_SCAN_ROWS),
    )
    best: tuple[datetime, str] | None = None
    for created_at, channel, content in cur:
        if is_non_jeff_prompt(content or ""):
            continue
        ts = parse_ts(created_at)
        if ts is None:
            continue
        if best is None or ts > best[0]:
            best = (ts, channel or "unknown")
    return best


def moved_since(inventory_db, since_dt: datetime) -> tuple[bool, str]:
    """(moved, current_space): did the entity's presence change after `since_dt`?"""
    conn = _connect_ro(inventory_db)
    try:
        row = conn.execute(
            "SELECT current_space, since FROM entity_presence WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False, ""
    space, since = row
    since_parsed = parse_ts(since)
    if since_parsed is None or not space:
        return False, space or ""
    return since_parsed > since_dt, space


def format_last_contact_line(conversations_db, inventory_db, now: datetime | None = None) -> str | None:
    """'[last-contact] Jeff: 1h16m ago (haven:silverglow) · moved since: no'.

    Returns None on any error (missing table, locked db, ...).
    """
    try:
        now = now or datetime.now(timezone.utc)
        conn = _connect_ro(conversations_db)
        try:
            latest = latest_jeff_row(conn)
        finally:
            conn.close()
        if latest is None:
            return "[last-contact] Jeff: never"
        ts, channel = latest
        try:
            moved, space = moved_since(inventory_db, ts)
            moved_txt = f"yes ({space})" if moved else "no"
        except Exception:
            moved_txt = None  # inventory unreadable: drop the clause, keep the line
        line = f"[last-contact] Jeff: {_ago(now - ts)} ({channel})"
        if moved_txt is not None:
            line += f" · moved since: {moved_txt}"
        return line
    except Exception:
        return None


# --- [first-meeting] -----------------------------------------------------------
def _earliest_row(conn: sqlite3.Connection, author: str) -> tuple[datetime, str] | None:
    # MIN() over (author_name, created_at) is an index seek once
    # idx_messages_author_name_time exists (MessageSummariesLayer creates it).
    first = conn.execute(
        "SELECT MIN(created_at) FROM messages WHERE author_name = ?", (author,)
    ).fetchone()[0]
    if first is None:
        return None
    ts = parse_ts(first)
    if ts is None:
        return None
    ch = conn.execute(
        "SELECT channel FROM messages WHERE author_name = ? AND created_at = ? LIMIT 1",
        (author, first),
    ).fetchone()
    return ts, (ch[0] if ch and ch[0] else "unknown")


def _recent_authors(conn: sqlite3.Connection, cutoff: datetime) -> list[str]:
    """Distinct authors with a row inside the window, newest first.  Walks rowid
    backwards (insertion order) and stops after a run of rows older than the cutoff,
    so it never scans the 100k+ row table."""
    seen: dict[str, None] = {}
    stale_run = 0  # tolerate a few out-of-order (backfilled) rows before giving up
    for author, created_at in conn.execute(
        "SELECT author_name, created_at FROM messages ORDER BY id DESC LIMIT ?",
        (_RECENT_SCAN_ROWS,),
    ):
        ts = parse_ts(created_at)
        if ts is not None and ts < cutoff:
            stale_run += 1
            if stale_run >= _STALE_RUN_STOP:
                break
            continue
        stale_run = 0
        if author and author not in seen:
            seen[author] = None
    return list(seen)


def format_first_meeting_lines(
    conversations_db,
    entity_name: str,
    speakers: list[str] | None = None,
    channel_hint: str = "",
    now: datetime | None = None,
    cap: int = FIRST_MEETING_CAP,
) -> list[str]:
    """'[first-meeting] Henry — first spoke 3m ago (haven:commons) · greet from your body first'

    With `speakers` (the senders of the turn being answered): each non-ignorable
    speaker is flagged when they have NO rows yet (the bridge row may not have
    landed -- the race that makes a pure DB scan miss the very first hello) OR
    their earliest row is under 24h old.  Without `speakers`: scan authors seen
    in the last 24h.  Names + channel only; never any cross-reference.
    Returns [] on any error.
    """
    try:
        now = now or datetime.now(timezone.utc)
        cutoff = now - FIRST_MEETING_WINDOW
        conn = _connect_ro(conversations_db)
        try:
            if speakers:
                candidates: list[str] = []
                for s in speakers[:_MAX_SPEAKERS]:
                    s = (s or "").strip()
                    if s and s not in candidates:
                        candidates.append(s)
            else:
                candidates = _recent_authors(conn, cutoff)
            out: list[str] = []
            seen_lower: set[str] = set()
            for name in candidates:
                if len(out) >= cap:
                    break
                if is_ignorable_author(name, entity_name) or name.lower() in seen_lower:
                    continue
                seen_lower.add(name.lower())
                # A DB error (e.g. missing table) must NOT read as "no rows" -- it
                # propagates to the outer handler and the lines are omitted.
                first = _earliest_row(conn, name)
                if first is None:
                    # Only reachable for explicit speakers (scan candidates have rows).
                    when, channel = "just now", channel_hint or "unknown"
                else:
                    ts, channel = first
                    if ts < cutoff:
                        continue
                    when = _ago(now - ts)
                out.append(
                    f"[first-meeting] {name} — first spoke {when} ({channel}) "
                    f"· greet from your body first"
                )
            return out
        finally:
            conn.close()
    except Exception:
        return []
