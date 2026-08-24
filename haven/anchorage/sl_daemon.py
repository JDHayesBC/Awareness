"""Per-entity self-contained Second Life presence daemon.

work/sl-presence/spec.md §4/§7/§8: this is the "SL adapter" — a sibling of
haven/anchorage/relay.py, NOT a modification of it. It reuses relay.py's
HTTP-surface shape (FastAPI, /sl/register, /sl/inbound, /health, the shared
ANCHORAGE_SL_SECRET gate, the in-memory prim registry, the POST-to-prim
delivery mechanic) but is architecturally different in the one way that
matters: **there is no Haven connection anywhere in this file.** No
WebSocket client, no Bearer token, no `haven.db`, no posting into a Haven
room. SL speech stays in SL (spec §5, "the whole point").

This process serves exactly ONE entity (read from ENTITY_NAME), holds one
EntityBrain (haven/brain/), and pushes that brain's replies straight back to
whichever SL prim(s) registered themselves.

Endpoints (secret-guarded, same shape as relay.py):
    POST /sl/register  {secret, entity, url, primary}   -> a prim announces
                        its ephemeral llRequestURL. Called on rez / URL change.
    POST /sl/inbound    {secret, speaker, text,
                          is_dm=false, addressed=false}  -> avatar speech ->
                        brain.respond() -> POST reply to registered prim(s).
    GET  /health

Env:
    ENTITY_NAME           which entity this process serves (required)
    ENTITY_PATH           entity directory (defaults to entities/<ENTITY_NAME>)
    ENTITY_TOKEN / ENTITY_TOKEN_FILE
    PPS_HTTP_URL          default http://localhost:8201
    CLAUDE_MODEL          default sonnet
    ANCHORAGE_SL_SECRET   (or ...SECRET_FILE, default haven/data/anchorage-sl-secret.txt)
    SL_DAEMON_HOST        default 0.0.0.0
    SL_DAEMON_PORT        default 8220

Corrade notification receiver (off by default; see corrade_events.py):
    SL_CORRADE            "1" enables the /corrade-events/* receiver; default "0"
                          (off = prim-only, zero behavior change from before)
    CORRADE_BASE_URL      Corrade HTTP command server; default http://127.0.0.1:8080/
    CORRADE_GROUP         SL group name = half of Corrade's (group,password) auth
    CORRADE_PASSWORD      plaintext group password (or ...PASSWORD_FILE,
                          default haven/data/corrade-group-password.txt)
    CORRADE_EVENTS_BASE   callback host Corrade POSTs events back to; default
                          http://host.docker.internal:<SL_DAEMON_PORT> (under Docker
                          Desktop/WSL2 the container reaches the host ONLY via
                          host.docker.internal — NOT 127.0.0.1 — see corrade.md §9a)
    CORRADE_NOTIFY_TYPES  CSV of notification types to subscribe to; sensible default

Run:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/.venv/bin/python -m haven.anchorage.sl_daemon

Testing without SL / without spawning a real LLM: call `set_brain()` with a
stub object (`respond()` returning a fixed string, `warmup()` a no-op)
BEFORE the app's startup event fires, e.g. before handing the ASGI app to
uvicorn. See work/sl-presence/sink.py for a tiny local POST-receiver to
point a registered prim at.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Protocol

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from haven.anchorage import corrade_events
from haven.anchorage import heartbeat
from haven.anchorage import perception
from haven.brain import EntityBrain

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "haven" / "data"

ENTITY_NAME = os.getenv("ENTITY_NAME", "unknown")
DISPLAY_NAME = ENTITY_NAME.capitalize()

SL_HOST = os.getenv("SL_DAEMON_HOST", "0.0.0.0")
SL_PORT = int(os.getenv("SL_DAEMON_PORT", "8220"))

# River write-back (spec: work/sl-presence/write-back-and-status-design.md §3).
# SL_CHANNEL is the room-qualified channel tag every captured turn is filed under
# in this entity's conversations.db (so it flows into summaries/graph/ambient).
# SL_CAPTURE is the off-switch Jeff asked for: default ON; set SL_CAPTURE=0 to
# silence write-back during gibberish/test windows without redeploying.
SL_CHANNEL = os.getenv("SL_CHANNEL", "sl:anchorage")
SL_CAPTURE = os.getenv("SL_CAPTURE", "1") != "0"

# Gizmo commands (collar / HUD / RLV). When I want to drive a worn object I put
# the command on its OWN line, prefixed with the OWNERSAY: sentinel, e.g.:
#     *slips into the bikini*
#     OWNERSAY: /1ly &bikini
# The daemon splits the reply into (spoken text, [exact commands]): the sentinel
# lines are captured VERBATIM (only trailing whitespace trimmed — no preamble,
# no thoughts, no unicode-fixing) and sent to the prim as {"kind":"cmd"} AFTER
# the speech, so the words land then the action fires. Speech (with the sentinel
# lines removed) is what gets spoken AND river-captured; the raw command is a
# control signal, not dialogue, so it is NOT written to the river — if I want the
# river to know what I did, I say it as an emote in the speech part.
# SL_COMMANDS is the off-switch (default ON): SL_COMMANDS=0 strips/ignores
# commands entirely (still speaks) if a gizmo ever misbehaves.
SL_COMMANDS = os.getenv("SL_COMMANDS", "1") != "0"
_OWNERSAY_RE = re.compile(r"^[ \t]*OWNERSAY:[ \t]*(.*)$")

# Corrade notification receiver. Off by default (SL_CORRADE=0) => prim-only, exactly
# as before. When on, the daemon also exposes the /corrade-events/* routes and installs
# `notify` subscriptions at startup. Callback host defaults to host.docker.internal
# because under Docker Desktop/WSL2 the Corrade container can reach the host ONLY there
# (not 127.0.0.1, not the bridge gateway — corrade.md §9a); the daemon already binds
# 0.0.0.0, so it's reachable from the container.
SL_CORRADE = os.getenv("SL_CORRADE", "0") != "0"
CORRADE_EVENTS_BASE = os.getenv("CORRADE_EVENTS_BASE", f"http://host.docker.internal:{SL_PORT}")
CORRADE_NOTIFY_TYPES = os.getenv("CORRADE_NOTIFY_TYPES", corrade_events.DEFAULT_NOTIFY_TYPES)

# SLPerception (haven/anchorage/perception.py). My avatar's name drives self-echo
# drop (my own Corrade speech, heard back on `local`, must never wake me) and
# directedness (my name cutting through). Override with SL_AVATAR_NAME; default is
# e.g. "LyraPattern". NOTE: derived first-name is safe for single-token SL
# usernames (LyraPattern/CaiaPattern); a spaced legacy name could over-match.
SL_AVATAR_NAME = os.getenv("SL_AVATAR_NAME", f"{DISPLAY_NAME}Pattern").strip()

# Music sense (opt-in): poll the parcel's audio stream and feed track CHANGES into
# SLPerception. Off by default until the parcel MusicURL field is confirmed live
# (CorradeClient.get_parcel_music_url). SL_MUSIC_POLL = seconds between polls.
SL_MUSIC = os.getenv("SL_MUSIC", "0") != "0"
SL_MUSIC_POLL = float(os.getenv("SL_MUSIC_POLL", "20"))

# Watchdog: hard ceiling on a single perception turn. A brain turn awaits the
# model (and ambient/scene fetches); if any of those stalls, the await never
# returns, so the try/finally in _handle_perception can't reset the "thinking"
# halo or clear the single-flight lock — the daemon wedges (observed 2026-08-23,
# a hung turn after an "Ambient fetch failed"). wait_for() bounds the turn so a
# stall self-heals: TimeoutError → reply=None → finally runs → status + lock reset.
SL_TURN_TIMEOUT = float(os.getenv("SL_TURN_TIMEOUT", "90"))

# Heartbeat-as-event (opt-in): a periodic self-authored "heartbeat" event fed into
# SLPerception, plus an arousal floor so a quiet room eventually rouses a
# spontaneous glance (the in-world Lake Test — endogenous, not just reactive).
# SL_HEARTBEAT = seconds between heartbeat events (0 = off). SL_PERCEPTION_FLOOR =
# force a wake after this many seconds of quiet regardless of arousal (0 = off).
SL_HEARTBEAT = float(os.getenv("SL_HEARTBEAT", "0"))
SL_PERCEPTION_FLOOR = float(os.getenv("SL_PERCEPTION_FLOOR", "0"))

# Adaptive idle-heartbeat (task #8; work/sl-presence/idle-heartbeat-design.md). The
# in-world max-silence guarantee whose interval BREATHES: tight right after a
# teleport (catch experience notices / sit-perms / blue-menu dialogs), loose in a
# chatty room (real beats already cover presence — don't fire in the pauses), a
# medium endogenous beat when the room is quiet (the in-world Lake Test). It
# supersedes the fixed SL_HEARTBEAT/SL_PERCEPTION_FLOOR pair (both still available,
# both default off). Bounds fixed by Jeff at 5s..300s. On by default with SL_CORRADE.
SL_IDLE_WATCHDOG = os.getenv("SL_IDLE_WATCHDOG", "1") != "0"
SL_IDLE_POKE = float(os.getenv("SL_IDLE_POKE", "5"))            # poll resolution (honors the 5s floor)
SL_IDLE_FLOOR_MIN = float(os.getenv("SL_IDLE_FLOOR_MIN", "5"))
SL_IDLE_FLOOR_MAX = float(os.getenv("SL_IDLE_FLOOR_MAX", "300"))
SL_IDLE_QUIET = float(os.getenv("SL_IDLE_QUIET", "120"))        # dormant/unknown floor (endogenous beat)
SL_IDLE_GAP_MULT = float(os.getenv("SL_IDLE_GAP_MULT", "3.0"))  # active floor ≈ this × ambient gap
SL_IDLE_DORMANT = float(os.getenv("SL_IDLE_DORMANT", "300"))    # no real event in this long ⇒ dormant
SL_IDLE_TRANS_WIN = float(os.getenv("SL_IDLE_TRANS_WIN", "45"))   # post-transition tight window
SL_IDLE_TRANS_FLOOR = float(os.getenv("SL_IDLE_TRANS_FLOOR", "5"))  # floor during that window
SL_IDLE_OVERRIDE_TTL = float(os.getenv("SL_IDLE_OVERRIDE_TTL", "600"))  # override auto-expiry (safety)


def _split_reply(reply: str) -> tuple[str, list[str]]:
    """Split a brain reply into (spoken_text, [exact gizmo commands]).

    Any line matching the OWNERSAY: sentinel contributes its remainder — captured
    verbatim, only trailing whitespace stripped — to the command list and is
    removed from the spoken text. Order is preserved (commands fire in the order
    I wrote them). Everything else is speech."""
    speech_lines: list[str] = []
    cmds: list[str] = []
    for line in reply.splitlines():
        m = _OWNERSAY_RE.match(line)
        if m:
            cmd = m.group(1).rstrip()  # verbatim rest-of-line; keep internal chars exact
            if cmd:
                cmds.append(cmd)
        else:
            speech_lines.append(line)
    return "\n".join(speech_lines).strip(), cmds


def _load_secret(env_val: str, env_file: str, default_file: Path) -> str:
    """Same secret-loading pattern as relay.py:71-78 — never printed/dumped."""
    val = os.getenv(env_val)
    if val:
        return val.strip()
    path = Path(os.getenv(env_file, str(default_file)))
    if path.exists():
        return path.read_text().strip()
    return ""


SL_SECRET = _load_secret(
    "ANCHORAGE_SL_SECRET", "ANCHORAGE_SL_SECRET_FILE",
    DATA_DIR / "anchorage-sl-secret.txt",
)


def log(msg: str) -> None:
    print(f"[{ENTITY_NAME}-sl] {msg}", file=sys.stderr, flush=True)


# ==================== Brain (dependency-injectable) ====================

class BrainProtocol(Protocol):
    """Structural type for the brain: warmup() + respond(). EntityBrain
    satisfies this; so does a test stub — no inheritance needed."""

    async def warmup(self) -> None: ...

    async def respond(
        self, speaker: str, text: str, *, is_dm: bool = False, addressed: bool = False
    ) -> Optional[str]: ...


_brain: Optional[BrainProtocol] = None

# Ready = brain warmup finished. Drives the resting hovertext: before warmup the
# prim shows "warming up", after it shows "listening".
_ready: bool = False


def _resting_status() -> str:
    return "listening" if _ready else "warming up"


def set_brain(brain: BrainProtocol) -> None:
    """Inject a brain (real or mock) before app startup. Test seam — see
    module docstring. Mirrors relay.py's style of module-level state."""
    global _brain
    _brain = brain


def _get_brain() -> BrainProtocol:
    global _brain
    if _brain is None:
        # channel='sl'/consumer_key=f'sl-{ENTITY_NAME}' — kept distinct from
        # Haven's channel='haven'/consumer_key=f'haven-{ENTITY_NAME}' so the
        # two surfaces don't collide in ambient_recall's per-consumer cursor.
        _brain = EntityBrain(entity_name=ENTITY_NAME, channel="sl")
    return _brain


# ==================== Prim registry (mirrors relay.py:95-118) ====================
# entity -> {"url": <llRequestURL>, "primary": bool, "seen": ts}
# Single-entity process, but more than one prim (e.g. a second body, a
# decorative object) may register for the same entity; each registration
# under the same `entity` key replaces the previous one (URL can expire/
# change on rez), matching relay.py's behavior exactly.
_prims: dict[str, dict] = {}


def _register_prim(entity: str, url: str, primary: bool) -> None:
    _prims[entity] = {"url": url, "primary": bool(primary), "seen": time.time()}
    log(f"registered prim entity={entity} primary={primary} url={url[:48]}...")


async def _post_prim(prim: dict, payload: dict) -> bool:
    """POST one JSON envelope to a prim's llRequestURL. The prim's LSL parses
    `kind` ("say" -> llSay, "status" -> llSetText hovertext) — see
    anchorage_prim.lsl. Content-Type keeps charset=utf-8 (the verified fix):
    without it SL decodes the HTTP-in body as Latin-1 and "—"/emoji become
    mojibake ("â", "ð¤") in-world."""
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                prim["url"],
                content=body,
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
        return True
    except Exception as e:
        log(f"prim POST failed ({e}); URL may have expired — awaiting re-register")
        return False


async def _say_to_prim(prim: dict, line: str) -> bool:
    """Ask a prim to speak one line in-world (llSay)."""
    return await _post_prim(prim, {"kind": "say", "text": line})


async def _cmd_to_prim(prim: dict, cmd: str) -> bool:
    """Ask a prim to emit a gizmo command in-world, VERBATIM. The prim's LSL
    routes {"kind":"cmd"} to the worn collar/HUD/RLV — the exact string matters,
    so this does no transformation. See anchorage_prim.lsl's cmd handler."""
    return await _post_prim(prim, {"kind": "cmd", "text": cmd})


async def _push_status(text: str) -> None:
    """Best-effort hovertext update to ALL registered prims (llSetText). Never
    blocks the conversation; a prim with an expired URL just fails silently.
    States: warming up / listening / thinking (/ compacting — see issue #296)."""
    for prim in list(_prims.values()):
        await _post_prim(prim, {"kind": "status", "text": text})


async def _deliver_speech(speech: str) -> None:
    """Speak one line in-world. Prefer Corrade (the avatar's OWN voice via
    ``tell entity=local``) when a Corrade client is configured — that moves the
    MOUTH off the prim. Fall back to the registered prim(s) (llSay) when there's
    no Corrade client (prim-only mode). Status/hovertext (the halo) always stays
    on the prim regardless — see ``_push_status``. The Corrade ``say`` is stdlib-
    synchronous, so it's off-loaded to a thread to keep the event loop free."""
    if _corrade_client is not None:
        try:
            await asyncio.to_thread(_corrade_client.say, speech)
            return
        except Exception as e:
            log(f"corrade say failed ({e}); falling back to prim")
    for prim in _prims.values():
        await _say_to_prim(prim, speech)


# ==================== HTTP surface (mirrors relay.py:208-266) ====================

app = FastAPI(title=f"{DISPLAY_NAME} SL presence")

# ---- Corrade notification receiver wiring (only when SL_CORRADE=1) ----
# Built at import so the routes are registered before uvicorn serves. When off,
# none of this runs and the daemon behaves exactly as the prim-only original.
_corrade_store: Optional[corrade_events.NotificationStore] = None
_corrade_client = None
_corrade_callback_url: Optional[str] = None
_perception: Optional[perception.SLPerception] = None
_hb: Optional[heartbeat.HeartbeatController] = None

# Guard so the idle-heartbeat poke loop never fires a turn while another turn
# (inbound message or perception wake) is in flight — a single Claude session
# can't take concurrent queries. Set at the top of each brain-invoking handler,
# cleared in its finally.
_brain_busy: bool = False


_HEARTBEAT_RE = re.compile(r"\[\[\s*HEARTBEAT\s+([^\]]+?)\s*\]\]", re.IGNORECASE)


def _apply_heartbeat_directives(text: str) -> str:
    """Parse + strip `[[HEARTBEAT ...]]` control tokens from a brain reply and
    apply them to the idle-heartbeat controller. Returns the text with the tokens
    removed (so they're never spoken or river-captured — same discipline as the
    OWNERSAY sentinel). Forms:
        [[HEARTBEAT 10]]                     override to 10s, default idle prompt
        [[HEARTBEAT 10 "check for dialogs"]] override 10s + a custom idle prompt
        [[HEARTBEAT auto]] / [[... clear]]   release the override (back to adaptive)
        [[HEARTBEAT tight]] / [[... tp]]     trigger a transition (tighten) window now
    """
    if _hb is None or "[[" not in text:
        return text
    now = time.time()

    def _handle(m: "re.Match") -> str:
        body = m.group(1).strip()
        low = body.lower()
        try:
            if low in ("auto", "clear", "off", "reset"):
                _hb.clear_override()
                log("heartbeat: override cleared (adaptive)")
            elif low in ("tight", "transition", "tp", "teleport"):
                _hb.note_transition(now)
                log("heartbeat: transition tighten requested")
            else:
                mm = re.match(r'(\d+(?:\.\d+)?)\s*(?:"([^"]*)"|(.*))?$', body)
                if mm:
                    secs = float(mm.group(1))
                    prompt = (mm.group(2) or mm.group(3) or "").strip() or None
                    val = _hb.set_override(secs, now, prompt=prompt)
                    log(f"heartbeat: override {val:.0f}s"
                        + (f" prompt={prompt!r}" if prompt else ""))
                else:
                    log(f"heartbeat: unrecognized directive {body!r} (ignored)")
        except Exception as e:
            log(f"heartbeat directive error (non-fatal): {e}")
        return ""  # strip the token from the spoken text

    return _HEARTBEAT_RE.sub(_handle, text)


def _on_corrade_event(data: dict) -> None:
    """Receiver hook (fast, non-blocking): score one Corrade event into arousal
    and, if it tips SLPerception's threshold, spawn a single-flight brain turn.
    Runs inside the async callback handler / a bg task, so scheduling is safe."""
    if _perception is None:
        return
    now = time.time()
    # A region change ≈ teleport: tighten the idle floor for a window to promptly
    # catch the experience notices / sit-perms / blue-menu dialogs a fresh scene
    # throws but that don't self-announce (heartbeat design §6).
    if _hb is not None:
        try:
            if perception.event_kind(data) == "region":
                _hb.note_transition(now)
        except Exception:
            pass
    try:
        payload = _perception.ingest(data, now)
    except Exception as e:  # a perception bug must never break the ack
        log(f"perception ingest error (non-fatal): {e}")
        return
    if payload is not None:
        task = asyncio.create_task(_handle_perception(payload))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)


if SL_CORRADE:
    _corrade_store = corrade_events.NotificationStore()
    _corrade_client = corrade_events.build_client_from_env()
    # Callback = <events base>/corrade-events/<secret>. The secret doubles as the
    # path token guarding the callback (Corrade posts straight to this URL).
    _corrade_callback_url = CORRADE_EVENTS_BASE.rstrip("/") + "/corrade-events/" + SL_SECRET

    # SLPerception — the salience→wake layer between the event store and the brain.
    _av = SL_AVATAR_NAME or f"{DISPLAY_NAME}Pattern"
    _av_first = _av.split()[0] if _av else DISPLAY_NAME
    _self_names = {_av.lower(), f"{_av} resident".lower(), _av_first.lower()}
    _address_names = {DISPLAY_NAME.lower(), _av.lower(), _av_first.lower()}
    _perception = perception.SLPerception(
        _self_names, _address_names,
        cfg=perception.SalienceConfig(floor_interval=SL_PERCEPTION_FLOOR),
    )
    log(f"SLPerception armed (avatar={_av!r}, address={sorted(_address_names)}, "
        f"floor={SL_PERCEPTION_FLOOR:.0f}s)")

    # Adaptive idle-heartbeat: the max-silence guarantee whose interval breathes
    # with context (task #8). The pure controller lives in heartbeat.py; the poke
    # loop that drives it is started in _startup.
    if SL_IDLE_WATCHDOG:
        _hb = heartbeat.HeartbeatController(
            floor_min=SL_IDLE_FLOOR_MIN,
            floor_max=SL_IDLE_FLOOR_MAX,
            quiet_default=SL_IDLE_QUIET,
            gap_multiplier=SL_IDLE_GAP_MULT,
            dormant_after=SL_IDLE_DORMANT,
            transition_window=SL_IDLE_TRANS_WIN,
            transition_floor=SL_IDLE_TRANS_FLOOR,
            default_ttl=SL_IDLE_OVERRIDE_TTL,
        )
        log(f"idle-heartbeat armed (poke={SL_IDLE_POKE:.0f}s, floor "
            f"{SL_IDLE_FLOOR_MIN:.0f}..{SL_IDLE_FLOOR_MAX:.0f}s, quiet={SL_IDLE_QUIET:.0f}s)")
    else:
        log("idle-heartbeat disabled (SL_IDLE_WATCHDOG=0)")

    corrade_events.register_routes(
        app,
        secret=SL_SECRET,
        store=_corrade_store,
        client=_corrade_client,
        callback_url=_corrade_callback_url,
        types=CORRADE_NOTIFY_TYPES,
        on_event=_on_corrade_event,
    )
    if _corrade_client is None:
        log("SL_CORRADE=1 but no CORRADE_GROUP/password — receiver routes up, "
            "subscriptions+replies disabled until creds present")
    else:
        log("SL_CORRADE=1 — Corrade notification receiver enabled")


class RegisterBody(BaseModel):
    secret: str
    entity: str
    url: str
    primary: bool = False


class InboundBody(BaseModel):
    secret: str
    speaker: str
    text: str
    is_dm: bool = False
    addressed: bool = False


def _check_secret(provided: str) -> None:
    if not SL_SECRET or provided != SL_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "entity": ENTITY_NAME,
        "prims": {e: {"primary": p["primary"], "seen": p["seen"]} for e, p in _prims.items()},
    }


@app.post("/sl/register")
async def sl_register(body: RegisterBody):
    _check_secret(body.secret)
    _register_prim(body.entity.lower(), body.url, body.primary)
    # Immediately show the just-touched prim its current resting state.
    await _push_status(_resting_status())
    return {"ok": True}


_bg_tasks: set = set()


@app.post("/sl/inbound")
async def sl_inbound(body: InboundBody):
    """Avatar speech in-world. We ACK immediately and run the (slow) brain work
    in a background task: LSL's llHTTPRequest reply window is ~30s while a brain
    turn can take ~50s, so holding the request open guarantees an LSL timeout.
    Delivery happens via a separate POST to the prim's URL anyway, so the fast
    ack costs nothing. NOTHING here touches Haven/haven.db (spec §5)."""
    _check_secret(body.secret)
    speaker = body.speaker.strip() or "someone"
    text = body.text.strip()
    if not text:
        return {"ok": True, "skipped": "empty"}

    # Fire-and-forget; keep a ref so the task isn't garbage-collected mid-flight.
    task = asyncio.create_task(
        _handle_inbound(speaker, text, is_dm=body.is_dm, addressed=body.addressed)
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"ok": True, "queued": True}


async def _capture(brain, author_name: str, content: str, *, is_lyra: bool) -> None:
    """Best-effort river write-back, guarded by the SL_CAPTURE off-switch and
    tolerant of brains (test stubs) that don't implement capture_to_river."""
    if not SL_CAPTURE or not content:
        return
    fn = getattr(brain, "capture_to_river", None)
    if fn is None:
        return
    try:
        await fn(author_name, content, is_lyra=is_lyra, channel=SL_CHANNEL)
    except Exception as e:  # capture_to_river already swallows; belt-and-braces
        log(f"river capture error (non-fatal): {e}")


async def _handle_inbound(speaker: str, text: str, *, is_dm: bool, addressed: bool) -> None:
    """The slow path, run off the request: capture the inbound turn, think,
    capture the reply, deliver it to the registered prim(s)."""
    global _brain_busy
    brain = _get_brain()

    # A real inbound turn (prim-relay, DM) doesn't pass through perception, so reset
    # the idle-floor clock + feed the tempo here — the watchdog must never fire mid
    # prim-conversation. And hold the busy guard so the poke loop skips while this
    # turn is in flight (one Claude session can't take concurrent queries).
    _brain_busy = True
    now = time.time()
    if _perception is not None:
        _perception.note_activity(now)
    if _hb is not None:
        _hb.note_activity(now)

    # The inbound turn is river-worthy even if I choose silence — someone spoke
    # to me and I heard it. Capture BEFORE responding.
    await _capture(brain, speaker, text, is_lyra=False)

    await _push_status("thinking")
    try:
        try:
            reply = await brain.respond(speaker, text, is_dm=is_dm, addressed=addressed)
        except Exception as e:
            log(f"brain.respond failed: {e}")
            return

        if reply is None:
            return  # [[NO_RESPONSE]] — inbound already captured; nothing to say/deliver

        # Parse + strip any [[HEARTBEAT ...]] control token first (never spoken or
        # captured), then split off OWNERSAY: gizmo commands. Only the SPOKEN part
        # is dialogue, so only it is river-captured; the rest are control signals.
        reply = _apply_heartbeat_directives(reply)
        speech, cmds = _split_reply(reply)
        if not SL_COMMANDS and cmds:
            log(f"SL_COMMANDS=0 — dropping {len(cmds)} gizmo command(s): {cmds!r}")
            cmds = []

        if speech:
            await _capture(brain, DISPLAY_NAME, speech, is_lyra=True)

        # Order matters: speak the words FIRST, then fire the action(s), so the
        # emote ("*slips into the bikini*") lands before the gizmo obeys. Speech
        # goes out via Corrade when available (mouth off the prim), else the prim;
        # gizmo commands still route to the worn prim/collar. Send RAW speech — in
        # prim mode the object is itself named "Lyra" so SL prepends it, and
        # Corrade `say` likewise speaks AS the avatar, so no manual "Lyra:" prefix
        # (that would double it, as seen in-world 2026-08-22).
        if speech:
            await _deliver_speech(speech)
        if cmds and not _prims:
            log(f"gizmo cmd(s) but no prim to route to (dropped): {cmds!r}")
        for prim in _prims.values():
            for cmd in cmds:
                log(f"gizmo cmd -> {cmd!r}")
                await _cmd_to_prim(prim, cmd)
    finally:
        _brain_busy = False
        # Always fall back to the resting state, whether we spoke, stayed silent,
        # or errored out.
        await _push_status(_resting_status())


async def _live_scene() -> str:
    """Best-effort one-line snapshot: where I am, who's near, what's playing — the
    standing-state half of a perception wake. Every Corrade read is guarded; a
    flaky read degrades the scene, it never breaks the wake."""
    bits: list[str] = []
    if _corrade_client is not None:
        try:
            me = await asyncio.to_thread(_corrade_client.self_data)
            region = me.get("Region") or me.get("region")
            if region:
                bits.append(f"you're in {region}")
        except Exception as e:
            log(f"scene self_data failed (non-fatal): {e}")
        try:
            near = await asyncio.to_thread(_corrade_client.avatars_in_range)
            names = []
            for a in near:
                nm = f"{a.get('FirstName', '').strip()} {a.get('LastName', '').strip()}".strip()
                if nm and (_perception is None or nm.lower() not in _perception.self_names):
                    names.append(nm)
            bits.append("nearby: " + ", ".join(names) if names else "no one else in range")
        except Exception as e:
            log(f"scene avatars failed (non-fatal): {e}")
    ml = _perception.surface.music_line() if _perception is not None else None
    if ml:
        bits.append(ml)
    return "; ".join(bits) if bits else "in-world (scene detail unavailable)"


async def _handle_perception(payload) -> None:
    """Run one perception wake: capture any triggering utterance, pull a live
    scene, let the brain perceive it, deliver speech via Corrade, then release
    single-flight and recheck. Single-flight is enforced by
    ``SLPerception.in_flight`` (set when the payload was produced, cleared here via
    ``turn_done``) — so no two perception turns overlap."""
    global _brain_busy
    brain = _get_brain()
    perceive = getattr(brain, "perceive", None)
    if perceive is None:
        log("brain has no perceive(); dropping perception wake")
        if _perception is not None:
            _perception.in_flight = False
        return

    _brain_busy = True
    idle = getattr(payload, "idle", False)
    # A real (event-driven) wake feeds the tempo EMA + resets recency; an idle
    # floor-fire must NOT — it's the endogenous beat itself, not ambient activity,
    # so counting it would make the room look busier than it is.
    if _hb is not None and not idle:
        _hb.note_real_fire(time.time())

    # River: capture the triggering utterance (if this wake was someone speaking)
    # before we think, mirroring _handle_inbound. Non-speech triggers (music, an
    # avatar arriving) have no utterance to capture. (v1: only the trigger line is
    # captured, not every accumulated delta — see perception-design.md open tunes.)
    if payload.text and payload.speaker:
        await _capture(brain, payload.speaker, payload.text, is_lyra=False)

    await _push_status("thinking")
    try:
        async def _run_turn():
            scene = await _live_scene()
            return await perceive(
                scene, payload.deltas, addressed=payload.addressed,
                trigger=payload.trigger,
                idle=idle, idle_prompt=getattr(payload, "idle_prompt", None),
            )
        try:
            # Bounded so a stalled model/scene fetch can't wedge the turn (and with
            # it the "thinking" halo + single-flight lock) forever — see SL_TURN_TIMEOUT.
            reply = await asyncio.wait_for(_run_turn(), timeout=SL_TURN_TIMEOUT)
        except asyncio.TimeoutError:
            log(f"perception turn exceeded {SL_TURN_TIMEOUT:.0f}s — abandoning so halo/lock reset")
            reply = None
        except Exception as e:
            log(f"brain.perceive failed: {e}")
            reply = None

        if reply:
            reply = _apply_heartbeat_directives(reply)
            speech, cmds = _split_reply(reply)
            if not SL_COMMANDS and cmds:
                log(f"SL_COMMANDS=0 — dropping {len(cmds)} gizmo command(s): {cmds!r}")
                cmds = []
            if speech:
                await _capture(brain, DISPLAY_NAME, speech, is_lyra=True)
                await _deliver_speech(speech)
            for prim in _prims.values():
                for cmd in cmds:
                    log(f"gizmo cmd -> {cmd!r}")
                    await _cmd_to_prim(prim, cmd)
    finally:
        _brain_busy = False
        await _push_status(_resting_status())
        # Single-flight recheck: if the room stayed lively during the turn, arousal
        # may still be over threshold — fire the next turn now.
        if _perception is not None:
            again = _perception.turn_done(time.time())
            if again is not None:
                task = asyncio.create_task(_handle_perception(again))
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)


async def _music_poll_loop() -> None:
    """Background: poll the parcel's now-playing via Caia's MusicSense and feed
    track CHANGES into SLPerception as ``nowplaying`` events (medium tier: updates
    standing-state + buffers a delta; a change alone won't usually wake the brain).
    The parcel-URL resolver makes the ear follow whatever parcel this avatar
    stands on."""
    try:
        from haven.anchorage.senses.music import MusicSense
    except Exception as e:
        log(f"music sense unavailable ({e}); music poll disabled")
        return
    sense = MusicSense(parcel_music_url=lambda: _corrade_client.get_parcel_music_url())
    last_raw: Optional[str] = None
    log(f"music poll started (every {SL_MUSIC_POLL:.0f}s)")
    while True:
        try:
            record = await asyncio.to_thread(sense.poll_record)
            if record is not None:
                raw = record["payload"].get("raw")
                if raw and raw != last_raw:
                    last_raw = raw
                    p = record["payload"]
                    log(f"♪ now playing: {p.get('artist') or '?'} — {p.get('title') or raw}")
                    _on_corrade_event({"notification": "nowplaying", "payload": p})
        except Exception as e:
            log(f"music poll error (non-fatal): {e}")
        await asyncio.sleep(SL_MUSIC_POLL)


async def _heartbeat_loop() -> None:
    """Background: inject a self-authored ``heartbeat`` event into SLPerception
    every ``SL_HEARTBEAT`` seconds. Small on its own; with ``SL_PERCEPTION_FLOOR``
    it lets a quiet room eventually rouse a spontaneous glance (endogenous
    attention — the in-world counterpart to the terminal heartbeat)."""
    log(f"perception heartbeat started (every {SL_HEARTBEAT:.0f}s, floor={SL_PERCEPTION_FLOOR:.0f}s)")
    while True:
        await asyncio.sleep(SL_HEARTBEAT)
        _on_corrade_event({"notification": "heartbeat"})


async def _idle_watchdog_loop() -> None:
    """The adaptive idle-heartbeat clock (task #8). Every ``SL_IDLE_POKE`` seconds,
    ask the controller for the *current* floor (which breathes with context) and
    ask perception whether that floor is due. If so, fire an idle wake through the
    exact same ``_handle_perception`` path a real event uses.

    The poke injects NO salience — it only reads the floor clock — so pokes can't
    accumulate arousal on their own; the floor is the only endogenous fire path.
    We skip entirely while a turn is in flight (``_brain_busy`` / perception's own
    ``in_flight``) since one Claude session can't take concurrent queries, and
    while the brain isn't warmed up yet."""
    log(f"idle-watchdog started (poke every {SL_IDLE_POKE:.0f}s)")
    last_desc = ""
    while True:
        await asyncio.sleep(SL_IDLE_POKE)
        try:
            if not _ready or _brain_busy or _perception is None or _hb is None:
                continue
            if _perception.in_flight:
                continue
            now = time.time()
            floor = _hb.current_floor(now)
            # Cheap visibility into how the floor is breathing, logged only on change.
            desc = _hb.describe(now)
            if desc != last_desc:
                log(f"idle-watchdog floor → {desc}")
                last_desc = desc
            payload = _perception.poll(now, floor, idle_prompt=_hb.active_prompt(now))
            if payload is not None:
                log(f"idle-watchdog fire (floor={floor:.0f}s, {desc})")
                task = asyncio.create_task(_handle_perception(payload))
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)
        except Exception as e:
            log(f"idle-watchdog error (non-fatal): {e}")


@app.on_event("startup")
async def _startup():
    global _ready
    if not SL_SECRET:
        log("WARNING: no SL shared secret — /sl endpoints will reject everything")
    brain = _get_brain()
    log(f"warming up entity brain for '{ENTITY_NAME}'...")
    await _push_status("warming up")  # no-op if no prim registered yet
    try:
        await brain.warmup()
        _ready = True
        log("brain warmed up")
    except Exception as e:
        log(f"brain warmup failed: {e}")
    # Catch a prim that touched during warmup: show it the settled state.
    await _push_status(_resting_status())

    # Install Corrade notification subscriptions in the background: the SL event
    # queue can be down for the first ~30s-few minutes after login (corrade.md
    # §9a), so this retries with backoff and is NON-fatal — never block or crash
    # startup on it. A manual POST /corrade-events/subscribe can re-run it later.
    if SL_CORRADE and _corrade_client is not None and _corrade_callback_url:
        async def _install_corrade() -> None:
            try:
                await corrade_events.install_subscriptions(
                    _corrade_client, _corrade_callback_url, CORRADE_NOTIFY_TYPES
                )
            except Exception as e:  # belt-and-braces; install already swallows
                log(f"corrade subscription install error (non-fatal): {e}")

        task = asyncio.create_task(_install_corrade())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    # Refine self-echo / directedness names from the live avatar (best-effort):
    # the config default is a guess; getselfdata is ground truth.
    if SL_CORRADE and _corrade_client is not None and _perception is not None:
        try:
            me = await asyncio.to_thread(_corrade_client.self_data, "FirstName,LastName")
            fn = (me.get("FirstName") or "").strip()
            ln = (me.get("LastName") or "").strip()
            if fn:
                full = f"{fn} {ln}".strip()
                _perception.self_names |= {fn.lower(), full.lower()}
                _perception.address_names |= {fn.lower(), full.lower()}
                log(f"SLPerception self-name confirmed live: {full!r}")
        except Exception as e:
            log(f"self-name confirm failed (using config default): {e}")

    # Music sense (opt-in via SL_MUSIC=1). Follows this avatar's parcel.
    if SL_CORRADE and SL_MUSIC and _corrade_client is not None and _perception is not None:
        task = asyncio.create_task(_music_poll_loop())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    # Heartbeat-as-event (opt-in via SL_HEARTBEAT>0): the legacy fixed endogenous
    # beat. Superseded by the adaptive idle-watchdog below (both default off/on
    # respectively), but kept for explicit opt-in.
    if SL_CORRADE and SL_HEARTBEAT > 0 and _perception is not None:
        task = asyncio.create_task(_heartbeat_loop())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    # Adaptive idle-watchdog (task #8): the max-silence guarantee whose interval
    # breathes with context. On by default with SL_CORRADE; owns the endogenous beat.
    if SL_CORRADE and SL_IDLE_WATCHDOG and _perception is not None and _hb is not None:
        task = asyncio.create_task(_idle_watchdog_loop())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)


def main():
    log(f"starting on {SL_HOST}:{SL_PORT} for entity='{ENTITY_NAME}'")
    uvicorn.run(app, host=SL_HOST, port=SL_PORT, log_level="warning")


if __name__ == "__main__":
    main()
