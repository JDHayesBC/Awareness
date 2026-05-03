#!/usr/bin/env python3
"""Haven flow observer — passive field-notebook for bot-flow analysis.

Tails lyra-haven and caia-haven systemd journals, polls haven.db for new
messages, and emits one JSONL event per observation to data/haven_flow.jsonl.

Captured event types:
  message       — new row appeared in messages table
  debounce      — bot started/processed a batch
  typing_emit   — bot POSTed typing indicator
  decision      — bot reached NO_RESPONSE / response with timing
  human_typing  — human typing signal received
  raw           — anything else interesting that didn't parse

Run in background; tail data/haven_flow.jsonl to watch live. Layer 2 (LLM
reviewer) reads this file later — observer itself does no analysis.
"""

import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
DB_PATH = ROOT / "haven" / "data" / "haven.db"
OUT_PATH = ROOT / "data" / "haven_flow.jsonl"
ENTITIES = ["lyra", "caia"]
POLL_INTERVAL_S = 2.0

OUT_LOCK = threading.Lock()


def emit(event: dict) -> None:
    event["observed_at"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(event, ensure_ascii=False)
    with OUT_LOCK:
        with OUT_PATH.open("a") as f:
            f.write(line + "\n")


# ---------- journal tailers ----------

# All known patterns; regex on the trailing-content portion of a journal line.
# Each entry: (compiled_regex, builder(entity, match_dict) -> dict_of_event_fields)
LOG_PATTERNS = [
    # [lyra] NO_RESPONSE from=caia bot=True query=4.4s ambient=0.9s total=5.3s topology=3p human-mix
    (
        re.compile(
            r"\[(?P<entity>\w+)\] NO_RESPONSE from=(?P<from>\S+) bot=(?P<bot>\S+) "
            r"query=(?P<query_s>[\d.]+)s ambient=(?P<ambient_s>[\d.]+)s "
            r"total=(?P<total_s>[\d.]+)s topology=(?P<topology>\S+)(?: (?P<topo_kind>\S+))?"
        ),
        lambda m: {
            "event": "decision",
            "decision": "NO_RESPONSE",
            "from": m["from"],
            "from_is_bot": m["bot"] == "True",
            "query_s": float(m["query_s"]),
            "ambient_s": float(m["ambient_s"]),
            "total_s": float(m["total_s"]),
            "topology": m["topology"],
            "topology_kind": m.get("topo_kind"),
        },
    ),
    # [lyra] [DEBOUNCE] New batch in 39d8d930 (15.0s wait, 3p human-mix)
    (
        re.compile(
            r"\[(?P<entity>\w+)\] \[DEBOUNCE\] New batch in (?P<room>\S+) "
            r"\((?P<wait_s>[\d.]+)s wait, (?P<topology>\S+) (?P<topology_kind>\S+)\)"
        ),
        lambda m: {
            "event": "debounce",
            "phase": "new_batch",
            "room_prefix": m["room"],
            "wait_s": float(m["wait_s"]),
            "topology": m["topology"],
            "topology_kind": m["topology_kind"],
        },
    ),
    # [lyra] [DEBOUNCE] Processing 1 msg(s) in 39d8d930 (waited 15.0s)
    (
        re.compile(
            r"\[(?P<entity>\w+)\] \[DEBOUNCE\] Processing (?P<count>\d+) msg\(s\) "
            r"in (?P<room>\S+) \(waited (?P<waited_s>[\d.]+)s\)"
        ),
        lambda m: {
            "event": "debounce",
            "phase": "processing",
            "msg_count": int(m["count"]),
            "room_prefix": m["room"],
            "waited_s": float(m["waited_s"]),
        },
    ),
    # [lyra] [DEBOUNCE] Bot-msg fast path: 4.0s typing check window
    (
        re.compile(r"\[(?P<entity>\w+)\] \[DEBOUNCE\] Bot-msg fast path:"),
        lambda m: {"event": "debounce", "phase": "bot_fast_path"},
    ),
    # [lyra] [TYPING] Human 'jeff' typing in 39d8d930 (hold until +5.0s)
    (
        re.compile(
            r"\[(?P<entity>\w+)\] \[TYPING\] Human '(?P<who>\S+)' typing in (?P<room>\S+)"
        ),
        lambda m: {"event": "human_typing", "who": m["who"], "room_prefix": m["room"]},
    ),
    # POST .../api/rooms/<id>/typing — bot-side typing indicator emit
    (
        re.compile(
            r"HTTP Request: POST http://[^/]+/api/rooms/(?P<room>[^/]+)/typing"
        ),
        lambda m: {"event": "typing_emit", "room": m["room"]},
    ),
]


def tail_journal(entity: str) -> None:
    unit = f"{entity}-haven"
    cmd = ["journalctl", "--user-unit", unit, "-f", "-n", "0", "--output=short-iso", "--no-pager"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        emit({"event": "raw", "level": "error", "entity": entity, "msg": f"journalctl spawn failed: {e}"})
        return
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        # Strip timestamp/host/unit prefix to get the trailing content
        # Example: "2026-05-03T09:38:01-0700 host lyra-haven[194725]: [lyra] NO_RESPONSE..."
        content = line
        m = re.match(r"^(\S+)\s+\S+\s+\S+:\s*(.*)$", line)
        if m:
            content = m.group(2)
        matched = False
        for pat, build in LOG_PATTERNS:
            mm = pat.search(content)
            if mm:
                fields = build(mm.groupdict())
                fields["entity"] = entity
                fields["raw_line"] = content[:300]
                emit(fields)
                matched = True
                break
        # We don't emit unmatched lines by default — too noisy. Toggle if needed:
        # if not matched: emit({"event": "raw", "entity": entity, "line": content[:300]})


# ---------- DB poller ----------

def poll_messages() -> None:
    last_id = None
    # Initialize: pick up current max so we only emit truly new rows
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
            cur = conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages")
            last_id = cur.fetchone()[0]
    except Exception as e:
        emit({"event": "raw", "level": "error", "msg": f"db init failed: {e}"})
        last_id = 0

    while True:
        time.sleep(POLL_INTERVAL_S)
        try:
            with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    """
                    SELECT m.id, m.room_id, r.name AS room_name, u.username AS sender,
                           u.is_bot, m.content, m.image_url, m.created_at
                    FROM messages m
                    LEFT JOIN users u ON u.id = m.user_id
                    LEFT JOIN rooms r ON r.id = m.room_id
                    WHERE m.id > ? ORDER BY m.id ASC LIMIT 100
                    """,
                    (last_id,),
                )
                rows = cur.fetchall()
            for r in rows:
                content = r["content"] or ""
                emit(
                    {
                        "event": "message",
                        "msg_id": r["id"],
                        "room_id": r["room_id"],
                        "room_name": r["room_name"],
                        "sender": r["sender"],
                        "is_bot": bool(r["is_bot"]),
                        "preview": content[:160],
                        "len": len(content),
                        "has_image": bool(r["image_url"]),
                        "created_at": r["created_at"],
                    }
                )
                last_id = r["id"]
        except Exception as e:
            emit({"event": "raw", "level": "error", "msg": f"db poll failed: {e}"})


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    emit({"event": "observer_start", "version": 1, "entities": ENTITIES, "out_path": str(OUT_PATH)})

    threads = []
    for ent in ENTITIES:
        t = threading.Thread(target=tail_journal, args=(ent,), daemon=True, name=f"tail-{ent}")
        t.start()
        threads.append(t)

    poll_thread = threading.Thread(target=poll_messages, daemon=True, name="db-poll")
    poll_thread.start()
    threads.append(poll_thread)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        emit({"event": "observer_stop", "reason": "keyboard_interrupt"})
        return 0


if __name__ == "__main__":
    sys.exit(main())
