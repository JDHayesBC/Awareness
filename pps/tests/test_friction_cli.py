"""CLI tests for scripts/friction.py (ENTITY_PATH pinned to tmp_path)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "friction.py"


def run(tmp_path, *args, stdin=None):
    env = {**os.environ, "ENTITY_PATH": str(tmp_path)}
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, input=stdin,
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_add_creates_db_and_table(tmp_path):
    out = run(tmp_path, "add", "false-room", "kitchen", "mention")
    assert out.strip() == "logged false-room (#1 in last 24h)"
    conn = sqlite3.connect(tmp_path / "data" / "friction.db")
    assert conn.execute("SELECT specimen, channel FROM irritants").fetchall() == [
        ("kitchen mention", "terminal")]


def test_add_reads_stdin(tmp_path):
    run(tmp_path, "add", "x", stdin="from stdin\n")
    assert "from stdin" in run(tmp_path, "list", "x")


def test_tally_window_and_resolved(tmp_path):
    for i in range(2):
        run(tmp_path, "add", "a", f"s{i}")
    run(tmp_path, "add", "b", "only")
    conn = sqlite3.connect(tmp_path / "data" / "friction.db")
    conn.execute("INSERT INTO irritants (ts, cls, specimen) VALUES ('2020-01-01T00:00:00.000000Z','a','old')")
    conn.commit()
    lines = run(tmp_path, "tally").strip().splitlines()
    assert lines[0].startswith("a ×2") and lines[1].startswith("b ×1")
    assert run(tmp_path, "tally", "--min", "2").strip().startswith("a ×2")
    run(tmp_path, "resolve", "b")
    assert "b ×" not in run(tmp_path, "tally")


def test_block_threshold_and_format(tmp_path):
    for i in range(2):
        run(tmp_path, "add", "false-room", f"s{i}")
    assert run(tmp_path, "block") == ""
    run(tmp_path, "add", "false-room", "third one")
    assert run(tmp_path, "block") == (
        '**[friction]** false-room ×3 today · "third one" — third time is a fix, '
        'not a clear; `python3 scripts/friction.py list false-room` for the specimens\n')


def test_list_oldest_first(tmp_path):
    for s in ("first", "second", "third"):
        run(tmp_path, "add", "c", s)
    out = run(tmp_path, "list", "c").strip().splitlines()
    assert [l.split()[-1] for l in out] == ["first", "second", "third"]
    assert out[0].startswith("#1 ")


def test_resolve_quiets_block(tmp_path):
    for i in range(3):
        run(tmp_path, "add", "c", f"s{i}")
    assert run(tmp_path, "block")
    assert run(tmp_path, "resolve", "c", "--note", "fixed").strip() == "resolved 3 c"
    assert run(tmp_path, "block") == ""


def test_block_caps_three_lines(tmp_path):
    for c in "abcd":
        for i in range(3):
            run(tmp_path, "add", c, "x")
    assert len(run(tmp_path, "block").strip().splitlines()) == 3
