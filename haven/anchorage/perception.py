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
    s_pose: float = 0.15        # a resolved pose change (mine or another's) — body-awareness
    # Motion churn (2026-08-24): a dancing avatar re-emits `animation` every ~10s,
    # plus `typing`/`appearance` bursts. At the old 0.15/0.10 these accumulated to
    # ~theta (steady-state ≈0.97) and woke the brain on ambient motion — over-firing
    # that both bloated the brain's context turn-over-turn AND made "a DM arrives
    # mid-turn" the common case (which tripped the reply-routing). Damped so motion
    # COLORS THE SCENE (still adds a delta) without triggering a turn on its own;
    # real speech (local 0.35 / directed-or-IM 1.20) still fires cleanly on top.
    s_animation: float = 0.04   # nearby avatar animation change (was 0.15)
    s_appearance: float = 0.04  # nearby avatar outfit change (was 0.15)
    s_typing: float = 0.02      # someone starts typing — early lean-in (was 0.10)
    s_low: float = 0.05         # region/balance/alert/collision/sit — routine
    s_heartbeat: float = 0.20   # endogenous "restlessness" tick (see floor_interval)
    s_drop: float = 0.0         # self-echo / ignore — never touches V


# Notification names we recognize (Corrade's, plus our synthetic "nowplaying").
_KNOWN_NOTIFS = frozenset({
    "local", "message", "dialog", "avatars", "collision", "sit", "animation",
    "appearance", "balance", "alert", "typing", "region", "permission",
    "nowplaying", "pose", "heartbeat",
})


def music_tail(payload: Optional[dict], *, include_ref: bool) -> str:
    """Compact enrichment suffix for a now-playing line (see ``senses/music_cache``).

    Genre/mood is always shown when known; a lyrics marker is appended when the
    song has words — with the cache ``lyrics_ref`` path on the persistent
    standing-state line (``include_ref=True``) and a bare ``♫ lyrics`` on the
    transient change delta. Returns ``""`` for a bare title, an un-enriched
    payload, or a non-song bumper — so an un-wired or degraded sense renders
    exactly as it did before (title only)."""
    if not isinstance(payload, dict) or payload.get("is_song") is False:
        return ""
    bits: list[str] = []
    desc = payload.get("description")
    if not desc:
        genres = payload.get("genres") or []
        desc = " · ".join(genres[:3]) if genres else None
    if desc:
        bits.append(desc)
    if payload.get("has_lyrics"):
        ref = payload.get("lyrics_ref")
        bits.append(f"♫ lyrics → {ref}" if (include_ref and ref) else "♫ lyrics")
    return ("  · " + "  · ".join(bits)) if bits else ""

def pose_delta_line(payload: Optional[dict]) -> Optional[str]:
    """Human one-liner for a resolved pose change (see ``senses/pose.py``).

    First-person for my own body ("I settled into…"), third-person for another
    avatar. Named when the pose resolved (geometry-exact / self-anim), honest and
    soft when it didn't (seated-but-uncarded → "sat down", off-card → "shifted").
    Returns ``None`` for a non-pose so it adds no delta line."""
    if not isinstance(payload, dict):
        return None
    src = payload.get("source")
    who_self = bool(payload.get("self"))
    who = "I" if who_self else (payload.get("subject") or "someone")
    label = payload.get("label")
    menu = payload.get("menu")
    tail = f" ({menu})" if (menu and menu.lower() not in (str(label or "").lower(),)) else ""
    if src in ("geometry-exact", "self-anim") and label:
        verb = "settled into" if who_self else "is now in"
        return f"⟡ {who} {verb} {label}{tail}"
    if src == "parent-only":
        return f"⟡ {who} sat down" + ("" if who_self else " (pose unnamed)")
    if src == "blind-freeform":
        return f"⟡ {who} shifted into a freeform pose"
    return None


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


def _display_name(event: dict) -> str:
    """The display/full name Corrade puts in a ``local`` event's ``name`` field.

    Corrade form-encodes spaces as ``+``; ``decode_kv`` now normalises that at
    the intake seam (``unquote_plus``, 2026-08-24), so the name arrives already
    spaced (``'LyraPattern Resident'``). We only ``strip`` here. This is a
    *display* concern — never an identity key (display names are mutable; use
    :func:`speaker_uuid`)."""
    return _get(event, "name").strip()


def speaker_of(event: dict) -> str:
    """A human-readable label for the speaker (logs / stored author_name).

    Display concern → prefer a name, fall back to the agent UUID only when no name
    rode along. Identity comparison must use :func:`speaker_uuid`, not this."""
    fn, ln = _first_last(event)
    name = (fn + " " + ln).strip()
    return name or _display_name(event) or _get(
        event, "agent", "owner", "item", "id", default="someone"
    )


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


def speaker_uuid(event: dict) -> str:
    """The speaking agent's UUID — SL's ONE invariant identity key.

    SL is UUID-native: display names are mutable ("Jeff Mills"↔"Damian Mills" is
    one UUID) and ``local`` chat carries NO firstname/lastname at all — only the
    speaker's agent UUID (verified against real Corrade wire data 2026-08-24). So
    identity/echo comparison keys on the UUID, never the name.

    Per event kind:
      * ``local`` chat by an avatar (``entity=Agent``): ``owner`` == ``item`` both
        hold the speaking agent's UUID.
      * ``local`` chat by an *object* (``entity=Object``): ``item`` is the object
        (never my avatar); ``owner`` is the object's owner — we return ``item`` so
        an object I happen to own can't be mistaken for my own echo.
      * IM / friendship / teleport etc.: ``agent``.
      * ``avatars`` roster: ``id``.
    Returns a lowercased UUID string, or "" when the event carries no agent UUID.
    """
    if event_kind(event) == "local" and _get(event, "entity").lower() == "object":
        return _get(event, "item").lower()
    return _get(event, "agent", "owner", "item", "id").lower()


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
    speaker_uuid: Optional[str] = None  # invariant reply target (SL is UUID-native)
    text: Optional[str] = None
    directed: bool = False
    delta: Optional[str] = None   # human-readable one-liner for the brain (or None to hide)


def _is_self(
    event: dict, self_names: set[str], self_uuids: "set[str] | frozenset[str]" = frozenset()
) -> bool:
    """True when this event was produced by my own avatar (echo).

    UUID-first (the invariant): if the event's agent UUID is one of mine, it's my
    echo — no matter what display name rode along. This is what actually stops the
    replay storm: real ``local`` echoes carry my UUID in ``owner``/``item`` but
    NO firstname/lastname, so the old name-only check never matched them and every
    line I spoke got re-ingested as a foreign turn (bug confirmed 2026-08-24).

    Name matching stays as a defensive fallback — it covers events with no UUID,
    and the window before the UUID seed loads. It checks first/last, the joined
    full name, AND the ``+``-decoded ``name`` field against self_names (the last of
    which is what catches a ``local`` echo when no UUID seed is configured).
    """
    uid = speaker_uuid(event)
    if uid and uid in self_uuids:
        return True
    if self_names:
        fn, ln = _first_last(event)
        full = (fn + " " + ln).strip().lower()
        disp = _display_name(event).lower()
        if fn and fn.lower() in self_names:
            return True
        if full and full in self_names:
            return True
        if disp and disp in self_names:
            return True
    return False


def _is_directed(text: str, address_names: set[str]) -> bool:
    """True when the utterance names me (cocktail-party: my name cuts through)."""
    low = text.lower()
    return any(n and n in low for n in address_names)


def score_event(
    event: dict,
    self_names: set[str],
    address_names: set[str],
    cfg: SalienceConfig,
    self_uuids: "set[str] | frozenset[str]" = frozenset(),
) -> Salience:
    """Map one perceived event → a :class:`Salience` (value + tier + delta line).

    ``self_names``  : display-name forms of my own avatar (echo drop, fallback).
    ``self_uuids``  : my own avatar UUID(s) — the *invariant* echo key (primary).
    ``address_names``: tokens that mean "me" when mentioned (directedness), e.g.
                       my first name.
    """
    kind = event_kind(event)
    speaker = speaker_of(event)

    # Tier 0 — my own voice/animation comes back through `local`; never wake me.
    if _is_self(event, self_names, self_uuids):
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
            kind=kind, speaker=speaker, speaker_uuid=speaker_uuid(event),
            text=text, directed=directed,
            delta=f'{speaker}: "{text}"' if text else f"{speaker} said something",
        )

    if kind == "message":  # IM straight to me — always directed
        text = _get(event, "message")
        return Salience(
            cfg.s_directed, FORCE, "im", kind=kind, speaker=speaker,
            speaker_uuid=speaker_uuid(event), text=text,
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
        line = f"♪ now playing: {who}{title}".rstrip() + music_tail(payload, include_ref=False)
        return Salience(cfg.s_music, MEDIUM, "music-change", kind=kind, delta=line)

    if kind == "pose":
        # A resolved pose change from the pose sense (senses/pose.py). Enriches the
        # generic `animation` notification with the actual named pose — mine or
        # another's — so the brain sees "who is in what pose", the embodied scene.
        payload = event.get("payload") or event
        line = pose_delta_line(payload)
        return Salience(cfg.s_pose, MEDIUM, "pose-change", kind=kind,
                        speaker=payload.get("subject") if isinstance(payload, dict) else None,
                        delta=line)

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
        if not title:
            return None
        return line + music_tail(self.music, include_ref=True)


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
    # Reply routing — where the answer should go back (SL is UUID-native).
    # "im"  -> IM the sender privately (reply_to_uuid is their agent UUID);
    # "local" (default) -> speak in local chat. Local speech, idle beats, and
    # accumulated re-fires all stay "local"; only a direct IM trigger routes "im".
    reply_via: str = "local"
    reply_to_uuid: Optional[str] = None


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
        self_uuids: Optional[set[str]] = None,
    ) -> None:
        self.cfg = cfg or SalienceConfig()
        self.self_names = {n.lower() for n in self_names}
        # Invariant echo key (SL is UUID-native). Kept mutable so the daemon can
        # confirm/extend it live once the avatar is in-world.
        self.self_uuids = {u.lower() for u in (self_uuids or set())}
        self.address_names = {n.lower() for n in address_names}
        self.surface = surface or PerceptionSurface()
        self.arousal = arousal or ArousalState(self.cfg)
        self.in_flight = False
        # A directed IM's reply target (speaker, uuid, text), remembered across the
        # in-flight window so a DM that lands mid-turn is still answered privately
        # when the turn wraps — the accumulated re-fire would otherwise lose it.
        self._pending_im: "tuple[Optional[str], str, Optional[str]] | None" = None

    def ingest(self, event: dict, now: float) -> Optional[WakePayload]:
        """Perceive one event. Returns a :class:`WakePayload` iff this event
        tips arousal over threshold AND no brain turn is already running."""
        s = score_event(event, self.self_names, self.address_names, self.cfg, self.self_uuids)
        if s.tier == DROP or s.value <= 0.0:
            return None

        # Remember a directed IM's reply target for the whole in-flight window (set
        # here so it's captured whether this IM fires its own turn or merely
        # accumulates behind a running one). Consumed + cleared by the next _fire.
        if s.kind == "message" and s.speaker_uuid:
            self._pending_im = (s.speaker, s.speaker_uuid, s.text)

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
        speaker, text = trigger.speaker, trigger.text
        # Reply routing (SL is UUID-native). Prefer the trigger if it's itself an IM;
        # otherwise fall back to a DM captured during the in-flight accumulation
        # window (a mid-turn IM) so a private message is ALWAYS answered privately —
        # this is the fix for "answered my DM in public": the accumulated re-fire
        # used to lose the target and fall back to local. Every other trigger (local
        # speech, idle beat, non-IM re-fire) stays local. Guarded on a real UUID so
        # a nameless IM can't route into a blank im(agent="").
        if trigger.kind == "message" and trigger.speaker_uuid:
            reply_via, reply_to_uuid = "im", trigger.speaker_uuid
        elif self._pending_im:
            p_speaker, p_uuid, p_text = self._pending_im
            reply_via, reply_to_uuid = "im", p_uuid
            # Surface the IM's speaker/text to the brain when the trigger (an
            # "accumulated" re-fire) carries none — so it can answer + capture it.
            speaker = speaker or p_speaker
            text = text or p_text
        else:
            reply_via, reply_to_uuid = "local", None
        self._pending_im = None  # consumed — never carries beyond one fire cycle
        return WakePayload(
            trigger=trigger.reason,
            addressed=trigger.directed or trigger.tier == FORCE or reply_via == "im",
            deltas=self.surface.drain_deltas(),
            speaker=speaker,
            text=text,
            music_line=self.surface.music_line(),
            reply_via=reply_via,
            reply_to_uuid=reply_to_uuid,
        )
