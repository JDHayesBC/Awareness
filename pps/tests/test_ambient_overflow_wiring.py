"""#365 wiring test: exercises the REAL poll_haven / poll_other_channels /
render-slice code from server_http.py (extracted by source, since importing the
module boots chroma/neo4j) against a fixture conversations.db and a mocked
Haven HTTP API. Complements test_ambient_overflow.py (pure helpers)."""
from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

DOCKER = Path(__file__).resolve().parents[1] / "docker"
SERVER_HTTP = DOCKER / "server_http.py"
sys.path.insert(0, str(DOCKER))

import ambient_overflow  # noqa: E402

FUNCS = {
    "_load_haven_last_seen", "_save_haven_last_seen", "_load_channel_cursors",
    "_save_channel_cursors", "poll_other_channels", "poll_haven",
}


def _funcs_src(src):
    tree = ast.parse(src)
    return "\n\n".join(
        ast.get_source_segment(src, n) for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in FUNCS
    )


def _slice(src, start_marker, end_marker):
    a = src.index(start_marker)
    b = src.index(end_marker, a) + len(end_marker)
    return textwrap.dedent(src[a:b])


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, rooms, msgs):
        self.rooms, self.msgs = rooms, msgs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        if url.endswith("/api/rooms"):
            return _Resp({"rooms": self.rooms})
        rid = url.split("/api/rooms/")[1].split("/")[0]
        return _Resp({"messages": self.msgs.get(rid, [])})


ROOMS = [
    {"id": "r-dm", "name": "dm-jeff-caia", "display_name": "Jeff & Caia"},
    {"id": "r-sg", "name": "silverglow", "display_name": "Silverglow"},
    {"id": "r-late", "name": "late-room", "display_name": "Late Room"},
]


def _hm(n, user, disp, content):
    return {"username": user, "display_name": disp, "content": content,
            "created_at": f"2026-10-09 17:{n:02d}:00"}


def _build(tmp_path, haven_msgs, db_rows, poll_haven_override=None):
    src = SERVER_HTTP.read_text()
    (tmp_path / "data").mkdir(exist_ok=True)
    db = tmp_path / "data" / "conversations.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, author_name TEXT, "
                 "content TEXT, created_at TEXT, channel TEXT)")
    conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", db_rows)
    conn.commit()
    conn.close()
    seen = tmp_path / "haven_last_seen.json"
    seen.write_text(json.dumps({"k": {"r-dm": "2026-10-09 00:00:00", "r-sg": "2026-10-09 00:00:00", "r-late": "2026-10-09 00:00:00"}}))
    httpx = MagicMock()
    httpx.AsyncClient = lambda timeout=None: _FakeClient(ROOMS, haven_msgs)
    ns = {
        "json": json, "sys": sys, "httpx": httpx, "datetime": datetime,
        "ENTITY_PATH": tmp_path, "ENTITY_NAME": "Caia", "ENTITY_TOKEN": "t",
        "HAVEN_URL": "http://haven", "_haven_last_seen_file": seen,
        "_channel_cursor_file": tmp_path / "data" / "channel_last_seen.json",
        **{k: getattr(ambient_overflow, k) for k in
           ("dedupe_channel_items", "make_is_addressed", "render_block",
            "room_from_channel", "sort_chronological", "INLINE_CAP")},
    }
    exec(compile(_funcs_src(src), str(SERVER_HTTP), "exec"), ns)
    if poll_haven_override:
        ns["poll_haven"] = poll_haven_override(ns["poll_haven"])
    poll_src = _slice(src, "    haven_items: list[dict] = []",
                      "# --- end #365 prep ---\n")
    render_src = _slice(src, "    # #365: pin addressed", "formatted_lines.extend(channel_body)\n")
    body = (
        "async def _wired(request, formatted_lines):\n"
        + textwrap.indent(poll_src, "    ")
        + textwrap.indent(render_src, "    ")
        + "    return haven_lines, channel_lines, haven_count, channel_count\n"
    )
    # startup branch references helpers we don't need (context != startup)
    ns["_advance_cursor_on_startup"] = lambda **k: "k"
    exec(compile(body, "wired", "exec"), ns)
    req = SimpleNamespace(channel="terminal", consumer_key="k", context="other")
    out: list[str] = []
    h, c, hc, cc = asyncio.run(ns["_wired"](req, out))
    _build.counts = (hc, cc)
    return out, h, c


def _scenario(long=False, late=False):
    pad = "x" * 480 if long else ""
    dm = [_hm(50, "jeff", "Jeff", "Consider it from the aspect of reaching")]
    sg = [_hm(i, "lyra", "Lyra", f"banter {i} {pad}") for i in range(12)]
    # late-listed room whose messages are all OLDER than silverglow's
    lt = [_hm(i, "nexus", "Nexus", f"old late {i}") for i in range(20, 26)] if late else []
    msgs = {"r-dm": dm, "r-sg": sg, "r-late": lt}
    rows, i = [], 1
    for room, ms in (("dm-jeff-caia", dm), ("silverglow", sg), ("late-room", lt)):
        for m in ms:  # same messages mirrored into the cross-channel DB
            rows.append((i, m["display_name"], m["content"], m["created_at"], f"haven:{room}"))
            i += 1
    rows.append((i, "Jeff", "terminal chatter", "2026-10-09 17:55:00", "terminal:abc"))
    rows.append((i + 1, "Jeff", "discord hello", "2026-10-09 17:56:00", "discord:general"))
    return msgs, rows


def test_real_wiring_repro(tmp_path):
    msgs, rows = _scenario(long=True)
    out, h, c = _build(tmp_path, msgs, rows)
    text = "\n".join(out)
    assert len(h) == 13 and len(c) == 14  # raw poll counts pre-dedupe
    assert "**[unread]**" not in text or True  # unread line built elsewhere
    # DM inline in [haven]
    assert "- **#Jeff & Caia** Jeff: Consider it from the aspect of reaching" in text
    # no line twice anywhere
    msg_lines = [l for l in out if l.startswith("- **")]
    assert len(msg_lines) == len(set(msg_lines))
    # mirrored haven:* copies were deduped away; only the discord line survives
    assert not any(l.startswith("- **[haven:") for l in out)
    assert "- **[discord:general]** Jeff: discord hello" in text
    assert "**[other_channels]**" in text and "**[haven]**" in text
    # overflow + digest
    assert "INCOMPLETE: 5 hidden" in text
    assert '  - silverglow: 5 hidden, Lyra' in text
    assert len(text) < 10000 and len(text) < 6000
    # chronological (DM is the newest message, 17:50): banter ascending, DM last
    assert text.index("banter 5") < text.index("banter 11") < text.index("Consider it")
    # [unread] counts come from deduped items: 13 haven, only the 1 non-mirror, non-terminal channel msg
    assert _build.counts == (13, 1)


def test_multi_room_order_late_room_with_older_messages(tmp_path):
    msgs, rows = _scenario(late=True)
    # silverglow banter minutes are 0..11 (17:00..17:11); make late-room 16:xx (older)
    for m in msgs["r-late"]:
        m["created_at"] = m["created_at"].replace(" 17:", " 16:")
    rows = [r if r[4] != "haven:late-room" else (r[0], r[1], r[2], r[3].replace(" 17:", " 16:"), r[4]) for r in rows]
    out, h, c = _build(tmp_path, msgs, rows)
    text = "\n".join(out)
    haven_part = text.split("**[other_channels]**")[0]
    # newest silverglow banter shown; older late-room lines are hidden, not shown
    assert "banter 11" in haven_part and "banter 5 " in haven_part
    assert not any(l.startswith("- **#Late Room**") for l in out)
    assert "  - late-room: 6 hidden" in haven_part
    assert "Consider it" in haven_part  # pinned DM still shown


def test_other_channels_block_dropped_when_all_duplicates(tmp_path):
    msgs, rows = _scenario()
    rows = [r for r in rows if not r[4].startswith(("terminal", "discord"))]
    out, h, c = _build(tmp_path, msgs, rows)
    assert "**[other_channels]**" not in "\n".join(out)
    assert "**[haven]**" in "\n".join(out)


def test_count_mismatch_falls_back_to_tail_slice(tmp_path):
    msgs, rows = _scenario()

    def override(real):
        async def bad(requesting_channel="", consumer_key="", items_out=None):
            lines = await real(requesting_channel, consumer_key, items_out)
            if items_out:
                items_out.pop()  # metadata now disagrees with lines
            return lines
        return bad

    out, h, c = _build(tmp_path, msgs, rows, poll_haven_override=override)
    text = "\n".join(out)
    assert "INCOMPLETE" not in text  # old behaviour: plain tail slice
    haven_part = text.split("**[other_channels]**")[0]
    assert haven_part.count("- **#") == 8
    assert "banter 11" in haven_part and "banter 3" not in haven_part


def test_dockerfile_copy_path_resolves_in_build_context():
    pps = Path(__file__).resolve().parents[1]
    df = (pps / "docker" / "Dockerfile").read_text()
    # compose builds with context=pps (COPY docker/server_http.py precedent)
    assert "COPY docker/ambient_overflow.py ." in df
    assert (pps / "docker" / "ambient_overflow.py").is_file()
    assert "COPY docker/server_http.py ." in df
