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

import inspect
import os

os.environ.setdefault("SL_CORRADE", "0")  # skip Corrade client build at import
os.environ.setdefault("ENTITY_NAME", "lyra")

from haven.anchorage import perception  # noqa: E402
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
for state in ("warming up", "listening", "dozing", "thinking"):
    p = d._status_payload(state)
    check(p.get("kind") == "status", f"{state!r}: kind is 'status'")
    check("text" in p and isinstance(p["text"], str) and p["text"] != "",
          f"{state!r}: has non-empty text")
    check(_is_vec_string(p.get("color", "")), f"{state!r}: carries a valid <r,g,b> color")

# distinct colors per state — a human must be able to tell them apart
_colors = {s: d._status_payload(s)["color"]
           for s in ("warming up", "listening", "dozing", "thinking")}
check(len(set(_colors.values())) == 4, "the four states have four distinct colors")

# dozing (#299) must tell the human what to do — say my name
check("name" in d._status_payload("dozing")["text"].lower(),
      "dozing text tells the human to say my name")

# ---- backward-compat / fallback ------------------------------------------
clear = d._status_payload("")
check(clear["text"] == "", "empty status clears the halo (text == '')")
check(_is_vec_string(clear["color"]), "cleared payload still carries a color field")

adhoc = d._status_payload("brb — kettle")
check(adhoc["text"] == "brb — kettle", "unknown key renders verbatim as text (backward-compat)")
check(adhoc["color"] == d._HALO_DEFAULT_COLOR, "unknown key uses the v6 default blue-white color")

# A fake perception whose attentiveness we control (used across the status tests).
class _FakePerc:
    def __init__(self, attentive: bool) -> None:
        self._a = attentive
    def is_attentive(self, now: float) -> bool:
        return self._a

# ---- _current_status: single source of truth, by priority ----------------
_saved = (d._ready, d._brain_busy, d._perception)
try:
    d._ready = False
    d._brain_busy = False
    d._perception = _FakePerc(True)
    check(d._current_status() == "warming up", "not ready -> 'warming up' (even if not busy)")

    d._ready = False
    d._brain_busy = True
    check(d._current_status() == "warming up", "not ready wins over busy -> 'warming up'")

    d._ready = True
    d._brain_busy = True
    check(d._current_status() == "thinking", "ready + busy -> 'thinking'")

    # idle branch DELEGATES to the resting sub-state — attentive -> listening,
    # not-attentive -> dozing. Hardcoding "listening" here reintroduced the stomp
    # (Caia's pre-deploy catch); pin both directions so it can't silently regress.
    d._ready = True
    d._brain_busy = False
    d._perception = _FakePerc(True)
    check(d._current_status() == "listening", "ready + idle + attentive -> 'listening'")
    d._perception = _FakePerc(False)
    check(d._current_status() == "dozing",
          "ready + idle + NOT attentive -> 'dozing' (the re-register stomp bug)")

    # The honest-state guarantee: a turn in flight NEVER reads as 'listening'.
    d._ready = True
    d._brain_busy = True
    check(d._current_status() != "listening",
          "in-flight turn never shows 'listening' (kills the #309 bug)")
finally:
    d._ready, d._brain_busy, d._perception = _saved


# ---- is_attentive: the honest attentive/dozing signal (#299) --------------
_p = perception.SLPerception(self_names={"lyra"}, address_names={"lyra"})
NOW = 1000.0
UID = "beadfeed-0000-1111-2222-333344445555"
check(_p.is_attentive(NOW) is False, "fresh perception: not attentive (dozing)")
_p._note_engagement(UID, NOW)
check(_p.is_attentive(NOW + 1) is True, "attentive while an engagement window is open")
check(_p.is_attentive(NOW + _p.cfg.engage_window + 1) is False,
      "not attentive once the window lapses")
check(UID not in _p._engaged, "is_attentive prunes the lapsed window (no stale attention)")

# ---- _resting_status: reflects attentive/dozing when ready ----------------
_saved2 = (d._ready, d._perception)
try:
    d._ready = True
    d._perception = _FakePerc(True)
    check(d._resting_status() == "listening", "ready + engaged -> 'listening'")
    d._perception = _FakePerc(False)
    check(d._resting_status() == "dozing", "ready + not engaged -> 'dozing' (#299)")
    d._perception = None
    check(d._resting_status() == "listening", "prim-only (no perception) keeps 'listening'")
    d._ready = False
    d._perception = _FakePerc(True)
    check(d._resting_status() == "warming up", "not ready -> 'warming up' regardless of engagement")
finally:
    d._ready, d._perception = _saved2

# ---- regression guard (Caia's note): the register path must push _current_status
# so a re-register can't stomp a live 'thinking' — a future revert to
# _resting_status() would be silent without this.
_src = inspect.getsource(d.sl_register)
check("_current_status" in _src,
      "sl_register pushes _current_status() (not _resting_status()) — re-register honest-state guard")


if _failures:
    print(f"\n{len(_failures)} halo-status test(s) FAILED")
    raise SystemExit(1)
print("\nall halo-status tests passed")
