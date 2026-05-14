#!/usr/bin/env python3
"""
One-off recovery script: backfill PPS messages table from CC JSONL transcripts.

Reconstructs rows lost during the #232 hook-discovery gap by reading Claude Code
JSONL session files and POSTing each user/assistant turn to PPS /tools/store_message.
Idempotent: skips rows already present via (channel, created_at, content_hash) dedupe.

Usage:
    python3 scripts/backfill_messages_from_jsonl.py \\
        --entity {lyra|caia} \\
        --since 2026-05-13T15:51:00-07:00 \\
        [--until 2026-05-14T13:30:00-07:00] \\
        [--dry-run] \\
        [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENTITY_CONFIG: dict[str, dict] = {
    "lyra": {
        "port": 8201,
        "author_name": "Lyra",
        "jsonl_dir": Path.home()
        / ".claude/projects/-mnt-c-Users-Jeff-Claude-Projects-Awareness-entities-lyra",
        "db_path": Path(
            "/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra/data/conversations.db"
        ),
    },
    "caia": {
        "port": 8211,
        "author_name": "Caia",
        "jsonl_dir": Path.home()
        / ".claude/projects/-mnt-c-Users-Jeff-Claude-Projects-Awareness-entities-caia",
        "db_path": Path(
            "/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/caia/data/conversations.db"
        ),
    },
}

PROGRESS_EVERY = 50  # print progress every N events processed


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp to UTC-aware datetime. Handles 'Z' suffix."""
    # Python 3.11+ handles Z natively; add explicit fallback for older envs
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        # Assume UTC if no tzinfo
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_to_db_str(dt: datetime) -> str:
    """Convert UTC datetime to the SQLite storage format 'YYYY-MM-DD HH:MM:SS'."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def extract_user_text(message: dict) -> str | None:
    """
    Extract plain text from a user message dict.

    user.message.content is either:
      - a string  (ordinary chat message)
      - a list of dicts with type 'tool_result', 'text', etc.

    We only want actual human text (type == 'text' or bare string).
    Tool results are internal plumbing — skip them.
    Returns None if no human-authored text found.
    """
    content = message.get("content", "")
    if isinstance(content, str):
        text = content.strip()
        return text if text else None

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                t = block.get("text", "").strip()
                if t:
                    parts.append(t)
            # Skip tool_result, tool_reference, etc. — they're not human speech
        text = "\n".join(parts).strip()
        return text if text else None

    return None


def extract_assistant_text(message: dict) -> str | None:
    """
    Extract narrative text from an assistant message dict.

    assistant.message.content is always a list of content blocks:
      - type 'text'     → narrative output (keep)
      - type 'thinking' → internal reasoning (skip — not stored by capture_response.py)
      - type 'tool_use' → tool invocations (skip)

    Concatenate all 'text' blocks separated by newline.
    Returns None if no text blocks found (pure tool-use turn).
    """
    content = message.get("content", [])
    if isinstance(content, str):
        text = content.strip()
        return text if text else None

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            t = block.get("text", "").strip()
            if t:
                parts.append(t)

    text = "\n".join(parts).strip()
    return text if text else None


# ---------------------------------------------------------------------------
# JSONL scanning
# ---------------------------------------------------------------------------


def scan_jsonl_files(
    jsonl_dir: Path,
    since: datetime,
    until: datetime,
    verbose: bool = False,
) -> list[dict]:
    """
    Scan all *.jsonl files in jsonl_dir, extract user and assistant events
    within [since, until), return sorted list of event dicts.

    Each returned dict has:
        type        : 'user' | 'assistant'
        timestamp   : datetime (UTC)
        content     : str  (extracted text)
        session_id  : str
    """
    if not jsonl_dir.exists():
        print(f"ERROR: JSONL directory not found: {jsonl_dir}", file=sys.stderr)
        sys.exit(1)

    jsonl_files = sorted(jsonl_dir.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No *.jsonl files found in {jsonl_dir}", file=sys.stderr)
        return []

    if verbose:
        print(f"Scanning {len(jsonl_files)} JSONL file(s) in {jsonl_dir}")

    events: list[dict] = []
    skipped_unparseable = 0

    for jpath in jsonl_files:
        with open(jpath, "r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    skipped_unparseable += 1
                    continue

                etype = entry.get("type")
                if etype not in ("user", "assistant"):
                    continue

                # Parse timestamp
                raw_ts = entry.get("timestamp")
                if not raw_ts:
                    skipped_unparseable += 1
                    continue
                try:
                    ts = parse_iso(raw_ts)
                except (ValueError, TypeError):
                    skipped_unparseable += 1
                    continue

                # Filter by time window
                if ts < since or ts >= until:
                    continue

                session_id = entry.get("sessionId", "unknown")
                message = entry.get("message", {})

                # Extract text
                if etype == "user":
                    # Skip isMeta entries (local-command caveats, slash commands)
                    if entry.get("isMeta"):
                        continue
                    text = extract_user_text(message)
                else:
                    text = extract_assistant_text(message)

                if not text:
                    continue

                # Skip very short assistant responses (mirrors capture_response.py behaviour)
                if etype == "assistant" and len(text) <= 10:
                    continue

                events.append(
                    {
                        "type": etype,
                        "timestamp": ts,
                        "content": text,
                        "session_id": session_id,
                    }
                )

    if verbose:
        print(f"  Raw unparseable lines skipped: {skipped_unparseable}")

    # Sort chronologically so inserts preserve conversation order
    events.sort(key=lambda e: e["timestamp"])
    return events


# ---------------------------------------------------------------------------
# Dedupe: check existing rows in conversations.db
# ---------------------------------------------------------------------------


def content_hash(text: str) -> str:
    """SHA-256 hex digest of content string (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_existing_set(db_path: Path, session_ids: set[str]) -> set[tuple[str, str, str]]:
    """
    Query messages table for all rows whose channel matches any of the given
    session IDs and return a set of (channel, created_at_str, content_hash).

    We build the hash on-the-fly from stored content so we never need a
    separate hash column.
    """
    if not db_path.exists():
        return set()

    placeholders = ",".join("?" * len(session_ids))
    channels = [f"terminal:{sid}" for sid in session_ids]

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT channel, created_at, content FROM messages WHERE channel IN ({placeholders})",
            channels,
        )
        existing: set[tuple[str, str, str]] = set()
        for channel, created_at, content_val in cur.fetchall():
            # Normalise created_at: strip sub-second, ensure 'YYYY-MM-DD HH:MM:SS'
            created_at_str = str(created_at)[:19]
            existing.add((channel, created_at_str, content_hash(content_val or "")))
        return existing
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PPS HTTP POST
# ---------------------------------------------------------------------------


def store_message(
    *,
    port: int,
    content: str,
    author_name: str,
    is_lyra: bool,
    session_id: str,
) -> bool:
    """POST a single message to PPS /tools/store_message. Returns True on success."""
    payload = json.dumps(
        {
            "content": content,
            "author_name": author_name,
            "channel": "terminal",
            "is_lyra": is_lyra,
            "session_id": session_id,
        }
    ).encode("utf-8")

    url = f"http://localhost:{port}/tools/store_message"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("success"))
    except urllib.error.URLError as exc:
        print(f"  HTTP error posting to PPS: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  Unexpected error posting to PPS: {exc}", file=sys.stderr)
        return False


def fix_created_at(
    db_conn: sqlite3.Connection,
    channel: str,
    content: str,
    real_ts_str: str,
    verbose: bool = False,
) -> bool:
    """
    After a successful POST, find the just-inserted row by (channel, content)
    and UPDATE its created_at to the real JSONL event timestamp.

    PPS server defaults created_at to insert-time-now, so backfilled rows
    would otherwise carry today's timestamp instead of the original event time.

    Identification via channel+content match (most-recent row) is race-safer
    than MAX(id), since the live capture hook may be inserting concurrently.

    FTS does NOT need updating — messages_fts indexes content/author/channel,
    not created_at. The UPDATE here is invisible to FTS.

    Args:
        db_conn: Open writable connection to conversations.db.
        channel: Full channel string as stored (e.g. "terminal:<session_id>").
        content: Exact content text that was just inserted.
        real_ts_str: Timestamp in 'YYYY-MM-DD HH:MM:SS' format (UTC).
        verbose: Print debug info on failure.

    Returns:
        True if exactly one row was updated, False otherwise.
    """
    try:
        cur = db_conn.cursor()
        cur.execute(
            "SELECT id FROM messages WHERE channel = ? AND content = ? ORDER BY id DESC LIMIT 1",
            (channel, content),
        )
        row = cur.fetchone()
        if row is None:
            if verbose:
                print(
                    f"  WARN  fix_created_at: no row found for channel={channel!r} content={content[:60]!r}",
                    file=sys.stderr,
                )
            return False

        row_id = row[0]
        cur.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            (real_ts_str, row_id),
        )
        db_conn.commit()
        return cur.rowcount == 1
    except Exception as exc:
        if verbose:
            print(f"  WARN  fix_created_at failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill PPS messages from CC JSONL transcripts."
    )
    parser.add_argument(
        "--entity",
        required=True,
        choices=list(ENTITY_CONFIG),
        help="Entity to backfill (lyra or caia).",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="ISO 8601 start timestamp (inclusive). Events at or after this time are considered.",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="ISO 8601 end timestamp (exclusive). Default: now.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + dedupe but do NOT POST to PPS.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each event being inserted or skipped.",
    )
    args = parser.parse_args()

    # Parse time window
    try:
        since = parse_iso(args.since)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: --since is not valid ISO 8601: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.until:
        try:
            until = parse_iso(args.until)
        except (ValueError, TypeError) as exc:
            print(f"ERROR: --until is not valid ISO 8601: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        until = datetime.now(tz=timezone.utc)

    if since >= until:
        print("ERROR: --since must be before --until", file=sys.stderr)
        sys.exit(1)

    cfg = ENTITY_CONFIG[args.entity]
    entity_author = cfg["author_name"]
    port: int = cfg["port"]
    jsonl_dir: Path = cfg["jsonl_dir"]
    db_path: Path = cfg["db_path"]

    print(f"Entity:   {args.entity} (port {port})")
    print(f"Window:   {since.isoformat()} → {until.isoformat()}")
    print(f"JSONL:    {jsonl_dir}")
    print(f"DB:       {db_path}")
    if args.dry_run:
        print("Mode:     DRY RUN — no POSTs will be made")
    print()

    # 1. Scan JSONL files
    events = scan_jsonl_files(jsonl_dir, since, until, verbose=args.verbose)
    print(f"Found {len(events)} event(s) in time window.")

    if not events:
        print("Nothing to do.")
        return

    # 2. Build dedupe set from DB
    session_ids = {e["session_id"] for e in events}
    existing = build_existing_set(db_path, session_ids)
    if args.verbose:
        print(f"Loaded {len(existing)} existing row fingerprint(s) from DB.")

    # 3. Open a persistent DB connection for post-insert timestamp fixups.
    #    We keep it open for the whole run to avoid per-row open/close overhead.
    #    The connection is read-write; we only UPDATE created_at after a successful POST.
    db_conn: sqlite3.Connection | None = None
    if not args.dry_run and db_path.exists():
        db_conn = sqlite3.connect(str(db_path))
        # WAL mode matches what the PPS server uses, reducing lock contention
        # when the live capture hook is inserting concurrently.
        db_conn.execute("PRAGMA journal_mode=WAL")
        db_conn.execute("PRAGMA busy_timeout=5000")

    # 4. Process events
    inserted = 0
    ts_fixed = 0
    skipped_existing = 0
    skipped_unparseable = 0  # already counted in scan, but track POST failures here too

    try:
        for idx, event in enumerate(events, start=1):
            if idx % PROGRESS_EVERY == 0:
                print(f"  ... processed {idx}/{len(events)} events (inserted={inserted}, skipped={skipped_existing})")

            etype = event["type"]
            ts: datetime = event["timestamp"]
            content: str = event["content"]
            session_id: str = event["session_id"]

            channel = f"terminal:{session_id}"
            created_at_str = dt_to_db_str(ts)
            chash = content_hash(content)
            fingerprint = (channel, created_at_str, chash)

            if fingerprint in existing:
                skipped_existing += 1
                if args.verbose:
                    print(f"  SKIP  [{ts.isoformat()}] {etype[:4]} {content[:60]!r}")
                continue

            is_lyra = etype == "assistant"
            author_name = entity_author if is_lyra else "Jeff"

            if args.verbose:
                print(f"  POST  [{ts.isoformat()}] {etype[:4]} {author_name}: {content[:60]!r}")

            if args.dry_run:
                inserted += 1  # count as "would insert" in dry-run
                existing.add(fingerprint)  # prevent re-counting duplicates within the batch
                continue

            ok = store_message(
                port=port,
                content=content,
                author_name=author_name,
                is_lyra=is_lyra,
                session_id=session_id,
            )
            if ok:
                inserted += 1
                existing.add(fingerprint)  # prevent re-counting within batch

                # Fix the row's created_at: PPS server defaults to insert-time-now.
                # We immediately UPDATE the just-inserted row to the real JSONL timestamp.
                # Identify by channel+content (most-recent match) — safe under concurrent
                # inserts from the live capture hook, unlike MAX(id).
                if db_conn is not None:
                    fixed = fix_created_at(
                        db_conn=db_conn,
                        channel=channel,
                        content=content,
                        real_ts_str=created_at_str,
                        verbose=args.verbose,
                    )
                    if fixed:
                        ts_fixed += 1
                    elif args.verbose:
                        print(
                            f"  WARN  timestamp fix skipped for {ts.isoformat()} — row not found after POST",
                            file=sys.stderr,
                        )
            else:
                skipped_unparseable += 1  # POST failure — count as unhandled
                if args.verbose:
                    print(f"  FAIL  POST returned error for event at {ts.isoformat()}")
    finally:
        if db_conn is not None:
            db_conn.close()

    # 5. Summary
    print()
    if args.dry_run:
        print(f"DRY RUN complete — would have inserted={inserted}, skipped_existing={skipped_existing}, skipped_unparseable={skipped_unparseable}")
    else:
        print(f"Done — inserted={inserted}, ts_fixed={ts_fixed}, skipped_existing={skipped_existing}, skipped_unparseable={skipped_unparseable}")


if __name__ == "__main__":
    main()
