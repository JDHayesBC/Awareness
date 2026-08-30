"""Unit tests for the halo-v2 dumb-display status layer (issue #309).

The v7 prim is a dumb display: the daemon owns ALL status wording + color and
sends both in the "status" envelope. These tests pin the Python side that the
LSL now trusts:

  - _status_payload(): every payload carries text AND a "<r,g,b>" color (the v7
    protocol), known states map to their vocabulary, and an unknown key (incl.
    "" = clear) falls back to (key-as-text, default color) — the backward-compat
    contract that lets an old v5/v6 prim still render text.
  - _current_status(): the single source of truth, by priority
    (not-ready -> "warming up"; busy -> "thinking"; else -> "listening") — the
    honest-state fix that stops a mid-turn re-register showing "listening" while
    a reply is actually being generated.

No live grid / no brain: pure functions driven directly. Run:
    PYTHONPATH=<repo> pps/venv/bin/python3 haven/anchorage/test_halo_status.py
"""

from __future__ import annotations

import os

os.environ.setdefault("SL_CORRADE", "0")  # skip Corrade client build at import
os.environ.setdefault("ENTITY_NAME", "lyra")

from haven.anchorage import sl_daemon as d  # noqa: E402

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _failures.append(msg)


def _is_vec_string(s: str) -> bool:
    """Loosely: an LSL vector literal "<a, b, c>" the prim can cast to a vector."""
    return isinstance(s, str) and s.startswith("<") and s.endswith(">") and s.count(",") == 2


# ---- _status_payload: protocol shape -------------------------------------
for state in ("warming up", "listening", "thinking"):
    p = d._status_payload(state)
    check(p.get("kind") == "status", f"{state!r}: kind is 'status'")
    check("text" in p and isinstance(p["text"], str) and p["text"] != "",
          f"{state!r}: has non-empty text")
    check(_is_vec_string(p.get("color", "")), f"{state!r}: carries a valid <r,g,b> color")

# distinct colors per state — a human must be able to tell them apart
_colors = {s: d._status_payload(s)["color"] for s in ("warming up", "listening", "thinking")}
check(len(set(_colors.values())) == 3, "the three states have three distinct colors")

# ---- backward-compat / fallback ------------------------------------------
clear = d._status_payload("")
check(clear["text"] == "", "empty status clears the halo (text == '')")
check(_is_vec_string(clear["color"]), "cleared payload still carries a color field")

adhoc = d._status_payload("brb — kettle")
check(adhoc["text"] == "brb — kettle", "unknown key renders verbatim as text (backward-compat)")
check(adhoc["color"] == d._HALO_DEFAULT_COLOR, "unknown key uses the v6 default blue-white color")

# ---- _current_status: single source of truth, by priority ----------------
_saved = (d._ready, d._brain_busy)
try:
    d._ready = False
    d._brain_busy = False
    check(d._current_status() == "warming up", "not ready -> 'warming up' (even if not busy)")

    d._ready = False
    d._brain_busy = True
    check(d._current_status() == "warming up", "not ready wins over busy -> 'warming up'")

    d._ready = True
    d._brain_busy = True
    check(d._current_status() == "thinking", "ready + busy -> 'thinking'")

    d._ready = True
    d._brain_busy = False
    check(d._current_status() == "listening", "ready + idle -> 'listening'")

    # The honest-state guarantee: a turn in flight NEVER reads as 'listening'.
    d._ready = True
    d._brain_busy = True
    check(d._current_status() != "listening",
          "in-flight turn never shows 'listening' (kills the #309 bug)")
finally:
    d._ready, d._brain_busy = _saved


if _failures:
    print(f"\n{len(_failures)} halo-status test(s) FAILED")
    raise SystemExit(1)
print("\nall halo-status tests passed")
