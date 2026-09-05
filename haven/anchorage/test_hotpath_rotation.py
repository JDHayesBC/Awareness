"""Regression guards for the SL-brain hot-path rotation ceiling (issue #20).

Context: in a busy-but-succeeding room NEITHER old rotation path fired — the
proactive path is gated on an idle beat that a lively room never yields (`again`
stays non-None through a burst), and the repeated-timeout backstop needs
back-to-back timeouts that sporadic single timeouts never produce. The session
grew unbounded (observed 44/40 turns, 59k tok) until a turn was dropped at the
40s timeout — the felt "beat of lag". Fix (2026-08-30, Lyra+Caia): add a HOT-PATH
ceiling guard that fires the EXISTING `rotate_if_approaching` at a tighter 0.95
threshold regardless of idle/again, so it rotates at ~38 turns (0.95 * 40) —
below the ~44-turn degradation zone — eating one honest "warming up" stall.

IMPORTANT — what this file is and is NOT:
  - These are SOURCE-INSPECTION revert-guards. They prove the fix's *shape*
    survives future edits (the hot-path branch exists, is reachable when NOT idle,
    and the preferred free idle path is retained). They do NOT prove the runtime
    behavior — that a saturated session actually rotates at 0.95.
  - The CORRECTNESS proof is the LIVE post-deploy check: drive a busy room past
    ~38 turns and confirm the journal logs "rotated on hot path (room saturated,
    no idle beat)" with turn_count resetting — verify against real data, not this.

Run:
    PYTHONPATH=<repo> pps/venv/bin/python3 haven/anchorage/test_hotpath_rotation.py
"""

from __future__ import annotations

import inspect
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


_src = inspect.getsource(d._handle_perception)

# --- the preferred (free) idle path is retained --------------------------------
check("if idle and again is None:" in _src,
      "idle-beat path retained (preferred, off-hot-path rotation)")

# --- the hot-path ceiling guard exists and fires at the tighter 0.95 threshold --
check("threshold=0.95" in _src,
      "hot-path rotation fires rotate_if_approaching at the 0.95 ceiling threshold")

# --- it is REACHABLE when the room is busy: it must be an `elif` sibling of the --
# idle branch, NOT nested inside `if idle ...` (the original bug). Guard the exact
# regression: re-nesting under the idle gate would make it unreachable in a burst.
check("elif rotate is not None:" in _src,
      "hot-path rotation is an elif sibling of the idle branch (reachable when again is non-None)")

# the elif must appear AFTER the idle `if` (structural sanity: it's the alternative)
_idle_at = _src.find("if idle and again is None:")
_elif_at = _src.find("elif rotate is not None:")
check(_idle_at != -1 and _elif_at != -1 and _elif_at > _idle_at,
      "elif hot-path branch follows the idle branch")

# --- visibility: both rotations log distinctly so live behavior is observable ----
check("rotated on hot path (room saturated, no idle beat)" in _src,
      "hot-path rotation logs a distinct line (journal visibility)")
check("rotated proactively (quiet moment, off hot path)" in _src,
      "idle rotation still logs its distinct line")

# --- the shared rotate handle is resolved once, before the branch ---------------
# (both branches use it; resolving inside the idle-only block would NameError the elif)
check("rotate = getattr(brain, \"rotate_if_approaching\", None)" in _src,
      "rotate handle resolved once before the if/elif (both branches can use it)")


if _failures:
    print(f"\n{len(_failures)} hot-path-rotation guard(s) FAILED")
    raise SystemExit(1)
print("\nall hot-path-rotation guards passed")
