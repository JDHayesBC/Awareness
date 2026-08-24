"""Adaptive idle-heartbeat controller — the breathing floor under the in-world
brain's max-silence guarantee (task #8; design: work/sl-presence/idle-heartbeat-design.md).

The in-world counterpart to the terminal heartbeat. `SLPerception` already owns
the *mechanism* of a silence-floor (`floor_interval`: fire a wake after N seconds
of quiet; `_last_fire` resets on every wake — so "reset on any tick" is intrinsic).
This controller supplies the one thing that was fixed: the **value** of that floor,
recomputed each poll so the interval *breathes* with context.

Precedence, highest first:
  1. explicit override  — the brain said `[[HEARTBEAT 10]]`; wins, with a safety TTL.
  2. transition window  — just teleported / region changed; tighten to catch the
                          experience-notices / sit-perms / blue-menu dialogs that
                          a fresh scene throws but that don't self-announce.
  3. tempo default      — EMA of the gap between *real* (event-driven) wakes:
       · dormant/unknown → `quiet_default` (endogenous "look around" beat; the
         in-world Lake Test — a quiet room still rouses periodically);
       · active          → `gap_multiplier × ema_gap`, so the floor sits just
         ABOVE the ambient chatter gap — real messages keep resetting it and it
         never fires in the natural pauses; only a genuine lull does.

All outputs clamped to [floor_min, floor_max] (Jeff's spec: 5s .. 300s).

Pure / clock-free: every method takes `now`. No I/O, no timer of its own — that
is what makes it unit-testable with a fake clock (see test_heartbeat.py). The
daemon (`sl_daemon.py`) owns the wall clock and the poke loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_NEVER = -1.0e9  # sentinel "long ago / not set" timestamp


@dataclass
class HeartbeatController:
    # --- bounds (Jeff's spec) ---
    floor_min: float = 5.0
    floor_max: float = 300.0
    # --- tempo default ---
    quiet_default: float = 120.0    # floor when dormant / tempo unknown (endogenous beat)
    gap_multiplier: float = 3.0     # active floor ≈ this × the ambient inter-event gap
    dormant_after: float = 300.0    # no real event in this long ⇒ treat as dormant
    ema_alpha: float = 0.4          # EMA weight on each new gap sample (0..1; higher = faster)
    min_gap_sample: float = 2.0     # ignore sub-this gaps as EMA samples (same-beat double-notes)
    # --- transition (post-teleport tighten) ---
    transition_window: float = 45.0  # how long the tight window lasts after a transition
    transition_floor: float = 5.0    # floor while inside that window
    # --- explicit override ---
    default_ttl: float = 600.0       # override auto-expires after this many seconds (safety)

    # --- mutable state ---
    _ema_gap: Optional[float] = field(default=None)
    _last_real_fire: float = field(default=_NEVER)
    _transition_until: float = field(default=_NEVER)
    _override_val: Optional[float] = field(default=None)
    _override_prompt: Optional[str] = field(default=None)
    _override_until: float = field(default=_NEVER)

    # ------------------------------------------------------------------ #
    def _clamp(self, v: float) -> float:
        return max(self.floor_min, min(self.floor_max, v))

    # ---- observations fed in by the daemon -------------------------------- #
    def note_real_fire(self, now: float) -> None:
        """A real (event-driven) brain wake happened — update the tempo EMA + recency.

        Near-simultaneous double-notes (the same utterance seen via both the
        perception and prim paths) produce a ~0 gap; those are ignored as EMA
        samples (< min_gap_sample) so they can't drag the tempo toward the floor,
        but they still refresh recency."""
        if self._last_real_fire > _NEVER / 2:
            gap = now - self._last_real_fire
            if gap >= self.min_gap_sample:
                gap = min(gap, self.floor_max)  # cap so one long lull can't blow up the EMA
                self._ema_gap = gap if self._ema_gap is None else (
                    self.ema_alpha * gap + (1.0 - self.ema_alpha) * self._ema_gap
                )
        self._last_real_fire = now

    # Real activity outside the perception path (e.g. a prim-relayed /sl/inbound
    # message) should also count toward tempo + recency, so the idle floor never
    # fires mid-conversation. Same effect as a real fire.
    note_activity = note_real_fire

    def note_transition(self, now: float) -> None:
        """A teleport / region-change / scene shift — tighten for a window so we
        promptly catch experience notices, sit-perms, blue-menu dialogs. A new
        place has an unknown tempo, so forget the old room's cadence."""
        self._transition_until = now + self.transition_window
        self._ema_gap = None

    def set_override(
        self, interval: float, now: float, *, prompt: Optional[str] = None,
        ttl: Optional[float] = None,
    ) -> float:
        """Brain-commanded override: pin the floor to `interval` (clamped) with an
        optional custom idle prompt, until `ttl` seconds elapse. Returns the
        clamped value actually set."""
        iv = self._clamp(float(interval))
        self._override_val = iv
        self._override_prompt = prompt
        self._override_until = now + (self.default_ttl if ttl is None else ttl)
        return iv

    def clear_override(self) -> None:
        """Release an override; return to fully adaptive behaviour."""
        self._override_val = None
        self._override_prompt = None
        self._override_until = _NEVER

    # ---- the value / prompt the daemon polls with ------------------------ #
    def _override_active(self, now: float) -> bool:
        return self._override_val is not None and now < self._override_until

    def current_floor(self, now: float) -> float:
        """The floor interval (seconds) to poll the arousal model with right now."""
        if self._override_active(now):
            return self._override_val  # already clamped at set time
        if now < self._transition_until:
            return self._clamp(self.transition_floor)
        if self._ema_gap is None or (now - self._last_real_fire) > self.dormant_after:
            return self._clamp(self.quiet_default)
        return self._clamp(self.gap_multiplier * self._ema_gap)

    def active_prompt(self, now: float) -> Optional[str]:
        """The custom idle prompt to carry on the next floor fire, if an override
        set one; None otherwise (perceive() then uses its default idle framing)."""
        return self._override_prompt if self._override_active(now) else None

    # ---- introspection (logging / status) -------------------------------- #
    def describe(self, now: float) -> str:
        floor = self.current_floor(now)
        if self._override_active(now):
            mode = f"override({floor:.0f}s"
            mode += f', "{self._override_prompt}"' if self._override_prompt else ""
            mode += ")"
        elif now < self._transition_until:
            mode = f"transition({floor:.0f}s, {self._transition_until - now:.0f}s left)"
        elif self._ema_gap is None or (now - self._last_real_fire) > self.dormant_after:
            mode = f"dormant({floor:.0f}s)"
        else:
            mode = f"tempo({floor:.0f}s, gap≈{self._ema_gap:.0f}s)"
        return mode
