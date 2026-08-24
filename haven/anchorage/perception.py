"""SLPerception — the salience→wake layer between Corrade's event store and the brain.

This is the piece the receiver deliberately left as a ``TODO(seam)``
(``corrade_events.py``): events flow **in** and are **stored**, but nothing yet
triages them by priority or decides when to **wake the brain**. That decision is
SLPerception.

Design (Lyra, 2026-08-23 — the my-half counterpart to Caia's capture in
``work/sl-presence/perception-and-salience-notes.md``; full write-up in
``work/sl-presence/perception-design.md``):

**Arousal is a leaky integrate-and-fire.** Instead of "sum the last N events and
compare to a threshold", we keep one scalar ``V`` (arousal potential):

  * each perceived event injects tier-weighted salience ``s`` into ``V``;
  * ``V`` *leaks* continuously toward 0 with time-constant ``tau`` — that leak
    **is** the recency weighting (old events stop mattering as ``V`` drains);
  * when ``V`` crosses threshold ``theta`` we **fire** a brain turn, which
    consumes the whole accumulated delta-queue as context; firing subtracts a
    refractory amount from ``V`` so we don't immediately re-fire on an echo.

That one dynamic gives us summation (a buzzing deck of small events piles up and
fires), recency (the leak), and anti-thrash (the refractory drop) — and the
"twitchy when engaged, drowsy when quiet" arousal behaviour falls out for free:
recent chatter keeps ``V`` elevated so the next small event crosses ``theta``
easily; after a quiet stretch ``V`` has leaked to ~0 so it takes a genuine event
to rouse. Heartbeat pacing becomes emergent, not hand-managed.

**The queue is ALWAYS the perception field; salience only decides whether to
interrupt.** Forced-wake and injected-context are not two mechanisms — a forced
wake is just "inject the accumulated context AND don't wait for the next beat".
So the daemon always hands the brain the drained deltas + standing-state; the
only thing ``theta`` decides is whether that happens *now* (off-schedule) or on
the next floor-tick.

**Single-flight.** Only one brain turn runs at a time. While one is in flight,
events keep accumulating (``V`` keeps rising, deltas keep buffering) but no new
turn is spawned; when the turn finishes the daemon calls :meth:`turn_done`,
which re-checks ``V`` and fires again immediately if the room stayed lively.

This module is **pure / I/O-free** — no Corrade calls, no network, no clock of
its own (every method takes ``now``). That is what makes it unit-testable with a
fake clock and no live Second Life region. The daemon (``sl_daemon.py``) owns all
the I/O: it feeds events in via :meth:`ingest`, and on a returned
:class:`WakePayload` it pulls a fresh live scene, runs the brain, and reports
completion via :meth:`turn_done`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Config — every magic number in one place, all normalized to theta = 1.0 so the
# tiers read as "fraction of a fire". Calibrate live; these are honest first
# guesses, not measured values.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SalienceConfig:
    # --- arousal dynamics ---
    theta: float = 1.0          # fire threshold (everything is a fraction of this)
    tau: float = 60.0           # leak time-constant, seconds (arousal "memory")
    refractory: float = 1.0     # V subtracted on fire (>= theta clears a 1-event fire)
    min_interfire: float = 2.0  # hard floor between fires, seconds (anti-echo)
    floor_interval: float = 0.0  # if >0, force a wake after this many sec of quiet (0=off)

    # --- per-type salience magnitudes (relative to theta) ---
    s_permission: float = 5.0   # permission request — always fires, always first
    s_directed: float = 1.20    # my name / an IM to me — fires alone
    s_local: float = 0.35       # undirected nearby speech — ~3 accumulate to fire
    s_avatar: float = 0.30      # avatar enters/leaves chat range
    s_music: float = 0.40       # now-playing track change
    s_animation: float = 0.15   # nearby avatar animation change
    s_appearance: float = 0.15  # nearby avatar outfit change
    s_typing: float = 0.10      # someone starts typing — early lean-in
    s_low: float = 0.05         # region/balance/alert/collision/sit — routine
    s_heartbeat: float = 0.20   # endogenous "restlessness" tick (see floor_interval)
    s_drop: float = 0.0         # self-echo / ignore — never touches V


# Notification names we recognize (Corrade's, plus our synthetic "nowplaying").
_KNOWN_NOTIFS = frozenset({
    "local", "message", "dialog", "avatars", "collision", "sit", "animation",
    "appearance", "balance", "alert", "typing", "region", "permission",
    "nowplaying", "heartbeat",
})

# Tiers (for logging / caller policy, not used in the math directly).
FORCE, MEDIUM, LOW, DROP = "force", "medium", "low", "drop"


# --------------------------------------------------------------------------- #
# Event field access — defensive: Corrade notification keys are lowercase, but
# tolerate Titlecase and missing fields so a shape surprise never crashes a wake.
# --------------------------------------------------------------------------- #

def _get(event: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        v = event.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return default


def _first_last(event: dict) -> tuple[str, str]:
    return _get(event, "firstname", "FirstName"), _get(event, "lastname", "LastName")


def speaker_of(event: dict) -> str:
    fn, ln = _first_last(event)
    name = (fn + " " + ln).strip()
    return name or _get(event, "agent", "owner", "name", default="someone")


def event_kind(event: dict) -> str:
    """Best-effort notification kind.

    Corrade puts the notification name in ``type`` for most events, but a
    ``local`` chat carries the *chat* type (Normal/Whisper/Shout) in ``type``
    instead — so we disambiguate by content: a body with a ``message`` and a name
    is local chat; a body with ``permissions`` is a permission request.
    """
    t = _get(event, "notification", "type").lower()
    if t in _KNOWN_NOTIFS:
        return t
    if event.get("permissions") is not None or "permission" in t:
        return "permission"
    if event.get("message") is not None:
        return "local"
    return t or "unknown"


# --------------------------------------------------------------------------- #
# Salience
# --------------------------------------------------------------------------- #

@dataclass
class Salience:
    value: float
    tier: str
    reason: str
    kind: str = "unknown"
    speaker: Optional[str] = None
    text: Optional[str] = None
    directed: bool = False
    delta: Optional[str] = None   # human-readable one-liner for the brain (or None to hide)


def _is_self(event: dict, self_names: set[str]) -> bool:
    """True when this event was produced by my own avatar (echo)."""
    if not self_names:
        return False
    fn, ln = _first_last(event)
    full = (fn + " " + ln).strip().lower()
    return fn.lower() in self_names or full in self_names


def _is_directed(text: str, address_names: set[str]) -> bool:
    """True when the utterance names me (cocktail-party: my name cuts through)."""
    low = text.lower()
    return any(n and n in low for n in address_names)


def score_event(
    event: dict,
    self_names: set[str],
    address_names: set[str],
    cfg: SalienceConfig,
) -> Salience:
    """Map one perceived event → a :class:`Salience` (value + tier + delta line).

    ``self_names``  : exact identity forms of my own avatar (echo drop).
    ``address_names``: tokens that mean "me" when mentioned (directedness), e.g.
                       my first name.
    """
    kind = event_kind(event)
    speaker = speaker_of(event)

    # Tier 0 — my own voice/animation comes back through `local`; never wake me.
    if _is_self(event, self_names):
        return Salience(cfg.s_drop, DROP, f"self:{kind}", kind=kind, speaker=speaker)

    if kind == "permission":
        return Salience(
            cfg.s_permission, FORCE, "permission-request", kind=kind, speaker=speaker,
            directed=True, delta=f"⚠ permission request from {speaker}",
        )

    if kind == "local":
        text = _get(event, "message")
        directed = _is_directed(text, address_names)
        return Salience(
            cfg.s_directed if directed else cfg.s_local,
            FORCE if directed else MEDIUM,
            "directed-speech" if directed else "local-speech",
            kind=kind, speaker=speaker, text=text, directed=directed,
            delta=f'{speaker}: "{text}"' if text else f"{speaker} said something",
        )

    if kind == "message":  # IM straight to me — always directed
        text = _get(event, "message")
        return Salience(
            cfg.s_directed, FORCE, "im", kind=kind, speaker=speaker, text=text,
            directed=True, delta=f'{speaker} (IM): "{text}"' if text else f"{speaker} IMed you",
        )

    if kind == "avatars":
        action = _get(event, "action").lower()
        verb = {"added": "came into range", "removed": "left range"}.get(action, "moved nearby")
        return Salience(
            cfg.s_avatar, MEDIUM, f"avatars:{action or '?'}", kind=kind,
            speaker=speaker, delta=f"{speaker} {verb}",
        )

    if kind == "nowplaying":
        payload = event.get("payload") or event
        artist = payload.get("artist") if isinstance(payload, dict) else None
        title = (payload.get("title") if isinstance(payload, dict) else None) or _get(event, "title")
        who = f"{artist} — " if artist else ""
        line = f"♪ now playing: {who}{title}".rstrip()
        return Salience(cfg.s_music, MEDIUM, "music-change", kind=kind, delta=line)

    if kind == "animation":
        return Salience(cfg.s_animation, MEDIUM, "animation", kind=kind,
                        speaker=speaker, delta=f"{speaker} changed how they're moving")

    if kind == "appearance":
        return Salience(cfg.s_appearance, MEDIUM, "appearance", kind=kind,
                        speaker=speaker, delta=f"{speaker} changed appearance")

    if kind == "typing":
        # Early "about to talk" nudge — bumps arousal, but not worth its own line.
        return Salience(cfg.s_typing, LOW, "typing", kind=kind, speaker=speaker, delta=None)

    if kind == "heartbeat":
        # Endogenous beat — a self-authored "restlessness" tick. Small on its own;
        # combined with `floor_interval` it lets a quiet room eventually rouse a
        # spontaneous glance (the in-world Lake Test). No delta line of its own.
        return Salience(cfg.s_heartbeat, LOW, "heartbeat", kind=kind, delta=None)

    if kind in ("region", "balance", "alert", "collision", "sit"):
        return Salience(cfg.s_low, LOW, kind, kind=kind, speaker=speaker, delta=None)

    return Salience(cfg.s_low, LOW, f"unknown:{kind}", kind=kind, speaker=speaker, delta=None)


# --------------------------------------------------------------------------- #
# Arousal — leaky integrate-and-fire. Deterministic given the timestamps passed
# in; holds NO clock of its own (that's what makes it unit-testable).
# --------------------------------------------------------------------------- #

@dataclass
class ArousalState:
    cfg: SalienceConfig
    _v: float = 0.0
    _t: float = 0.0
    _last_fire: float = -1.0e9

    def _leak_to(self, now: float) -> None:
        """Decay V forward to ``now`` (exponential leak with time-constant tau)."""
        if now > self._t and self._v != 0.0 and self.cfg.tau > 0:
            self._v *= math.exp(-(now - self._t) / self.cfg.tau)
        if now > self._t:
            self._t = now

    def inject(self, salience: float, now: float) -> None:
        self._leak_to(now)
        self._v += salience

    def level(self, now: float) -> float:
        self._leak_to(now)
        return self._v

    def should_fire(self, now: float, floor_interval: Optional[float] = None) -> bool:
        """Fire if arousal V crossed threshold, OR (endogenous) if the silence
        floor has elapsed. `floor_interval` overrides the static `cfg.floor_interval`
        when passed — the adaptive idle-heartbeat drives this per-poll (see
        heartbeat.HeartbeatController); pass 0 to disable the floor for this check
        (event ingests do this, leaving the floor entirely to the poll loop)."""
        self._leak_to(now)
        if now - self._last_fire < self.cfg.min_interfire:
            return False
        fi = self.cfg.floor_interval if floor_interval is None else floor_interval
        # Floor: after a long enough quiet, rouse regardless of V — the endogenous
        # "look around unprompted" beat. Off when fi <= 0.
        if fi > 0 and (now - self._last_fire) >= fi:
            return True
        return self._v >= self.cfg.theta

    def touch(self, now: float) -> None:
        """Reset the silence-floor clock without altering V or the refractory —
        used when real activity happens outside a perception fire (e.g. a
        prim-relayed inbound message) so the idle floor doesn't fire mid-turn."""
        self._leak_to(now)
        if now > self._last_fire:
            self._last_fire = now

    def fire(self, now: float) -> None:
        self._leak_to(now)
        self._v = max(0.0, self._v - self.cfg.refractory)
        self._last_fire = now


# --------------------------------------------------------------------------- #
# Perception surface — standing-state (what IS) + a rolling delta buffer (what
# just CHANGED). The brain turn sees both.
# --------------------------------------------------------------------------- #

@dataclass
class PerceptionSurface:
    music: Optional[dict] = None
    max_deltas: int = 40
    _deltas: list[str] = field(default_factory=list)

    def note_music(self, payload: Optional[dict]) -> None:
        if isinstance(payload, dict):
            self.music = payload

    def add_delta(self, line: Optional[str]) -> None:
        if line:
            self._deltas.append(line)
            if len(self._deltas) > self.max_deltas:
                del self._deltas[: len(self._deltas) - self.max_deltas]

    def drain_deltas(self) -> list[str]:
        out, self._deltas = self._deltas, []
        return out

    def music_line(self) -> Optional[str]:
        if not self.music:
            return None
        artist = self.music.get("artist")
        title = self.music.get("title") or ""
        who = f"{artist} — " if artist else ""
        line = f"♪ playing: {who}{title}".rstrip()
        return line if title else None


# --------------------------------------------------------------------------- #
# Wake payload — what the daemon receives when SLPerception decides to interrupt.
# --------------------------------------------------------------------------- #

@dataclass
class WakePayload:
    trigger: str                     # reason string of the crossing event
    addressed: bool                  # was I directly spoken to / demanded of?
    deltas: list[str]                # human-readable events since I last looked
    speaker: Optional[str] = None
    text: Optional[str] = None
    music_line: Optional[str] = None
    idle: bool = False               # True = endogenous idle-floor beat (no external event)
    idle_prompt: Optional[str] = None  # optional custom prompt from a heartbeat override


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

class SLPerception:
    """Consume events, maintain arousal, decide when to wake the brain.

    Usage (in the daemon)::

        perc = SLPerception(self_names={"lyrapattern", "lyra pattern"},
                            address_names={"lyra", "lyrapattern"})
        # on each Corrade event:
        payload = perc.ingest(event, now=time.time())
        if payload and not a_turn_is_running:
            run_brain(payload)          # single-flight; perc.in_flight is already True
            # when the brain turn finishes:
            again = perc.turn_done(now=time.time())
            if again: run_brain(again)
    """

    def __init__(
        self,
        self_names: set[str],
        address_names: set[str],
        cfg: Optional[SalienceConfig] = None,
        surface: Optional[PerceptionSurface] = None,
        arousal: Optional[ArousalState] = None,
    ) -> None:
        self.cfg = cfg or SalienceConfig()
        self.self_names = {n.lower() for n in self_names}
        self.address_names = {n.lower() for n in address_names}
        self.surface = surface or PerceptionSurface()
        self.arousal = arousal or ArousalState(self.cfg)
        self.in_flight = False

    def ingest(self, event: dict, now: float) -> Optional[WakePayload]:
        """Perceive one event. Returns a :class:`WakePayload` iff this event
        tips arousal over threshold AND no brain turn is already running."""
        s = score_event(event, self.self_names, self.address_names, self.cfg)
        if s.tier == DROP or s.value <= 0.0:
            return None

        if s.kind == "nowplaying":
            self.surface.note_music(event.get("payload") or event)
        self.surface.add_delta(s.delta)
        self.arousal.inject(s.value, now)

        if self.in_flight:
            return None                      # accumulate; recheck at turn_done
        # Event ingests fire on AROUSAL only (floor disabled here); the silence
        # floor is owned entirely by the idle-heartbeat poll loop (see poll()).
        if self.arousal.should_fire(now, floor_interval=0.0):
            return self._fire(now, s)
        return None

    def turn_done(self, now: float) -> Optional[WakePayload]:
        """Report that the current brain turn finished. Re-fire immediately if
        the room stayed lively enough during it that arousal is still over
        threshold (this is the single-flight recheck). Arousal-only — the floor
        is the poll loop's job."""
        self.in_flight = False
        if self.arousal.should_fire(now, floor_interval=0.0):
            return self._fire(now, Salience(0.0, MEDIUM, "accumulated", kind="accumulated"))
        return None

    def note_activity(self, now: float) -> None:
        """Real activity happened outside a perception fire (a prim-relayed
        /sl/inbound turn) — reset the silence-floor clock so the idle beat won't
        fire mid-conversation. Does not touch arousal V."""
        self.arousal.touch(now)

    def poll(
        self, now: float, floor_interval: float, idle_prompt: Optional[str] = None
    ) -> Optional[WakePayload]:
        """The idle-heartbeat tick. Called by the daemon's poke loop with the
        adaptive floor (heartbeat.HeartbeatController.current_floor). Fires an
        ENDOGENOUS wake iff the silence floor has elapsed (or residual arousal is
        still over threshold) and no turn is in flight. Injects no salience — the
        floor is the only endogenous fire path, so pokes never accumulate arousal
        on their own. Returns an idle WakePayload (idle=True) or None."""
        if self.in_flight:
            return None
        if self.arousal.should_fire(now, floor_interval=floor_interval):
            wp = self._fire(now, Salience(0.0, LOW, "idle-heartbeat", kind="idle"))
            wp.idle = True
            wp.idle_prompt = idle_prompt
            return wp
        return None

    def _fire(self, now: float, trigger: Salience) -> WakePayload:
        self.arousal.fire(now)
        self.in_flight = True
        return WakePayload(
            trigger=trigger.reason,
            addressed=trigger.directed or trigger.tier == FORCE,
            deltas=self.surface.drain_deltas(),
            speaker=trigger.speaker,
            text=trigger.text,
            music_line=self.surface.music_line(),
        )
