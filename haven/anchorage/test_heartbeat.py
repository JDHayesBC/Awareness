"""Unit tests for the adaptive idle-heartbeat controller (haven/anchorage/heartbeat.py).

Pure logic, fake clock (every method takes `now`), no Second Life required. Self-running::

    python3 haven/anchorage/test_heartbeat.py

Exits non-zero on any failure. Covers the precedence order (override > transition >
tempo), the dormant→quiet_default floor, the active gap-tracking floor, clamping to
[5,300], override TTL expiry, and transition tempo-forgetting.
"""

from __future__ import annotations

import sys

try:
    from haven.anchorage.heartbeat import HeartbeatController
except ImportError:  # pragma: no cover
    from heartbeat import HeartbeatController  # type: ignore[no-redef]

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _failures.append(msg)


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
def test_dormant_default() -> None:
    print("dormant → quiet_default:")
    hb = HeartbeatController()
    # No real fire yet: tempo unknown ⇒ the endogenous quiet-room beat.
    check(approx(hb.current_floor(0.0), 120.0), "fresh controller floors at quiet_default (120s)")
    check(hb.active_prompt(0.0) is None, "no override ⇒ no custom prompt")
    check("dormant" in hb.describe(0.0), "describe reports dormant")


def test_active_tempo_tracks_gap() -> None:
    print("active tempo ≈ gap_multiplier × ema_gap:")
    hb = HeartbeatController(gap_multiplier=3.0)
    # A chatty room: real fires ~30s apart. Feed several to settle the EMA.
    t = 0.0
    hb.note_real_fire(t)
    for _ in range(6):
        t += 30.0
        hb.note_real_fire(t)
    floor = hb.current_floor(t)
    # EMA of a steady 30s gap → 30; ×3 → ~90s. Sits ABOVE the ambient gap so real
    # messages keep resetting it and it never fires in the natural pauses.
    check(approx(floor, 90.0, tol=1.0), f"steady 30s chatter → ~90s floor (got {floor:.1f})")
    check(floor > 30.0, "floor sits above the ambient inter-event gap")
    check("tempo" in hb.describe(t), "describe reports tempo mode")


def test_clamp_bounds() -> None:
    print("clamp to [5, 300]:")
    hb = HeartbeatController(gap_multiplier=3.0)
    # Very chatty: 1s gaps → 3s raw floor, clamped up to floor_min (5).
    t = 0.0
    hb.note_real_fire(t)
    for _ in range(8):
        t += 1.0
        hb.note_real_fire(t)
    check(hb.current_floor(t) >= 5.0, "tiny gaps clamp up to floor_min (5s)")
    # Sparse: 200s gaps → 600s raw, clamped down to floor_max (300).
    hb2 = HeartbeatController(gap_multiplier=3.0, dormant_after=10_000.0)
    t = 0.0
    hb2.note_real_fire(t)
    for _ in range(5):
        t += 200.0
        hb2.note_real_fire(t)
    check(hb2.current_floor(t) <= 300.0, "large gaps clamp down to floor_max (300s)")


def test_min_gap_sample_ignored() -> None:
    print("sub-min_gap double-notes ignored:")
    hb = HeartbeatController(min_gap_sample=2.0)
    hb.note_real_fire(100.0)
    hb.note_real_fire(100.3)   # same-beat double-note (0.3s) — must NOT drag tempo down
    # ema_gap should still be unset (no valid sample yet), so we're dormant/quiet.
    check(approx(hb.current_floor(100.3), 120.0), "0.3s double-note is not a tempo sample")


def test_dormant_after_reverts() -> None:
    print("dormant_after reverts to quiet_default:")
    hb = HeartbeatController(dormant_after=300.0)
    hb.note_real_fire(0.0)
    hb.note_real_fire(30.0)    # establishes a ~30s tempo
    check(hb.current_floor(31.0) < 120.0, "right after activity, tempo floor is short")
    # Long silence past dormant_after: forget the busy tempo, return to the quiet beat.
    check(approx(hb.current_floor(30.0 + 400.0), 120.0), "after dormant_after of silence → quiet_default")


def test_transition_window() -> None:
    print("transition window tightens:")
    hb = HeartbeatController(transition_window=45.0, transition_floor=5.0)
    # Establish a lazy tempo first.
    hb.note_real_fire(0.0)
    hb.note_real_fire(60.0)
    hb.note_transition(100.0)   # teleport
    check(approx(hb.current_floor(101.0), 5.0), "inside transition window → transition_floor (5s)")
    check("transition" in hb.describe(101.0), "describe reports transition")
    # Tempo was forgotten by the transition (new place, unknown cadence).
    check(approx(hb.current_floor(100.0 + 46.0), 120.0),
          "after window expires with forgotten tempo → quiet_default")


def test_override_precedence_and_ttl() -> None:
    print("override precedence + TTL:")
    hb = HeartbeatController(default_ttl=600.0)
    hb.note_transition(0.0)     # would otherwise force the tight transition floor
    val = hb.set_override(10.0, now=1.0, prompt="watch for dialogs")
    check(approx(val, 10.0), "set_override returns the clamped value")
    check(approx(hb.current_floor(2.0), 10.0), "override beats an active transition window")
    check(hb.active_prompt(2.0) == "watch for dialogs", "override carries its custom prompt")
    check("override" in hb.describe(2.0), "describe reports override")
    # TTL expiry: after default_ttl, the override lapses back to adaptive.
    check(hb.current_floor(1.0 + 601.0) != 10.0, "override auto-expires after TTL")
    check(hb.active_prompt(1.0 + 601.0) is None, "expired override drops its prompt")


def test_override_clamped_and_cleared() -> None:
    print("override clamp + clear:")
    hb = HeartbeatController()
    check(approx(hb.set_override(1.0, now=0.0), 5.0), "override below floor_min clamps to 5")
    check(approx(hb.set_override(9999.0, now=0.0), 300.0), "override above floor_max clamps to 300")
    hb.set_override(10.0, now=0.0, prompt="x")
    hb.clear_override()
    check(hb.active_prompt(1.0) is None, "clear_override drops the prompt")
    check(approx(hb.current_floor(1.0), 120.0), "clear_override returns to adaptive default")


def test_transition_forgets_tempo() -> None:
    print("transition forgets tempo EMA:")
    hb = HeartbeatController()
    hb.note_real_fire(0.0)
    hb.note_real_fire(10.0)     # fast tempo established
    hb.note_transition(20.0)
    # After the window, with no new real fires, tempo is gone → quiet_default, not the old fast floor.
    floor = hb.current_floor(20.0 + hb.transition_window + 1.0)
    check(approx(floor, 120.0), f"post-transition, forgotten tempo → quiet_default (got {floor:.1f})")


# --------------------------------------------------------------------------- #
def main() -> int:
    for fn in (
        test_dormant_default, test_active_tempo_tracks_gap, test_clamp_bounds,
        test_min_gap_sample_ignored, test_dormant_after_reverts, test_transition_window,
        test_override_precedence_and_ttl, test_override_clamped_and_cleared,
        test_transition_forgets_tempo,
    ):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all heartbeat tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
