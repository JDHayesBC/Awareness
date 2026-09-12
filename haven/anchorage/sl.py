"""sl.py — ergonomic, zero-config Second Life embodiment verbs over Corrade.

Same-river hands for either entity. A channel (terminal, SL-brain, heartbeat)
writes plain human-shaped verbs and never touches passwords, IPs, or UUIDs:

    import sl
    me = sl.connect()               # picks the entity from ENTITY_NAME
    me.say("hello, love")           # speak in local chat, my own voice
    me.around()                     # what's near me (lossy, human-grain)
    me.avatars()                    # who's near me + who is sitting with whom
    me.sit("nearest poseball")      # sit by name / uuid / "nearest <word>"
    me.stand()
    me.touch("TIS Hybrid Home Calling Post")

    # The permission channel — ALWAYS watched, skeptically (Jeff's directive):
    me.listen()                     # start receiving notifications
    for req in me.pending_permissions():
        me.grant(req)               # grants only benign perms unless forced
    for dlg in me.dialogs():
        me.reply(dlg, "Couples")    # by button label or index

Zero-config: the connection (base URL, group, group-password) is resolved
per-entity from the environment. Lyra → 127.0.0.1:8080, Caia → 127.0.0.1:8081,
both against the local ``Haven`` shared-secret group. The group password is read
from ``CORRADE_PASSWORD`` or the gitignored file
``haven/data/corrade-group-password.txt`` and is NEVER logged or returned.

This is the low-level floor under the fuller world-model/tool layer designed in
work/secondlife/senses-design.md. Plumbing reference: haven/anchorage/corrade.md.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote_plus
from urllib.request import urlopen, Request as _URLRequest
from urllib.error import URLError as _URLError

try:  # package or bare-dir import (mirrors corrade_events' shim)
    from haven.anchorage.corrade_client import CorradeClient, CorradeError
except ImportError:  # pragma: no cover
    from corrade_client import CorradeClient, CorradeError

# --------------------------------------------------------------------------- #
# Per-entity connection profile. base_url/group overridable by env; password is
# resolved lazily (env CORRADE_PASSWORD, else the gitignored file).
# --------------------------------------------------------------------------- #
_ENDPOINTS = {
    "lyra": {"base_url": "http://127.0.0.1:8080/", "group": "Haven", "listen_port": 9770, "daemon_port": 8220},
    "caia": {"base_url": "http://127.0.0.1:8081/", "group": "Haven", "listen_port": 9771, "daemon_port": 8221},
}
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"  # haven/data
_DEFAULT_PW_FILE = _DATA_DIR / "corrade-group-password.txt"

# The callback host Corrade (in its container) uses to reach THIS process on the
# host. Under Docker Desktop/WSL2 only host.docker.internal works (see corrade.md).
_CALLBACK_HOST = os.getenv("CORRADE_CALLBACK_HOST", "host.docker.internal")

# Home sim. SAFETY (Jeff's directive 2026-08-24): for now BOTH entities are kept
# in-sim at The Anchorage — we're not ready to be out in public, so a login that
# lands anywhere else auto-teleports home BEFORE doing anything. Later this becomes
# a judgment call. Overridable via env.
HOME_REGION = os.getenv("SL_HOME_REGION", "The Anchorage")
HOME_POSITION = os.getenv("SL_HOME_POSITION", "<185,212,28>")

# Skeptical permission policy. Benign perms may be granted on request; the rest
# require an explicit force=True + reason, because they can actually cause harm.
SAFE_PERMS = {"TriggerAnimation", "TrackCamera", "ControlCamera", "Teleport"}
DANGEROUS_PERMS = {
    "Debit",          # spend the avatar's money
    "TakeControls",   # hijack movement
    "Attach",         # force-attach objects
    "ChangeLinks",
    "ChangePermissions",
    "SilentEstateManagement",
    "OverrideAnimations",
}


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _agent_kw(target: str) -> dict:
    """Corrade agent-identifying kwargs for a target that may be a UUID or a
    "First Last" name. A single-word name takes ``Resident`` as the implicit
    surname (correct for no-last-name accounts on the modern grid)."""
    t = target.strip()
    if _UUID_RE.match(t):
        return {"agent": t}
    parts = t.split(None, 1)
    return {"firstname": parts[0], "lastname": parts[1] if len(parts) > 1 else "Resident"}


def _name_uuid_pairs(raw: str) -> list[dict]:
    """Parse Corrade's flat ``Name,UUID,Name,UUID,…`` CSV (``getfriendslist``,
    ``getteleportlures``) into ``[{name, uuid}]`` with names display-cleaned.
    UUID-anchored so a stray token can't desync the pairing."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[dict] = []
    i = 0
    while i < len(parts) - 1:
        name, key = parts[i], parts[i + 1]
        if _UUID_RE.match(key):
            out.append({"name": unquote_plus(name).replace("+", " "), "uuid": key})
            i += 2
        else:
            i += 1  # skip a desync token defensively
    return out


def _regroup(flat: str, fields: list[str]) -> list[dict]:
    """Regroup Corrade's flat comma-CSV into a list of field dicts, unescaping each
    cell. Corrade URL-escapes values (a literal comma in a value becomes %2C), so a
    raw split on ``,`` yields only real separators. A trailing partial row is dropped."""
    if not flat.strip():
        return []
    cells = [unquote_plus(c) for c in flat.split(",")]
    n = len(fields)
    return [dict(zip(fields, cells[i:i + n])) for i in range(0, len(cells) - n + 1, n)]


def _is_throttled(err: str | None) -> bool:
    """Is this Corrade error the grid's teleport rate-limit (issue #312)? Matched
    loosely (substring, case-insensitive) since Corrade's wording for a throttle
    has drifted across versions in the wild."""
    return bool(err) and "throttl" in err.lower()


def _tp_backoff_delays(max_retries: int = 3, start: float = 6.0,
                        cap_total: float = 30.0) -> list[float]:
    """The exponential backoff schedule for a throttled teleport: start ~6s,
    doubling, capped so the WHOLE retry run never exceeds ~30s total wait. Pure
    + deterministic so it's unit-testable without sleeping."""
    delays: list[float] = []
    wait = start
    total = 0.0
    for _ in range(max_retries):
        remaining = cap_total - total
        if remaining <= 0:
            break
        step = min(wait, remaining)
        delays.append(step)
        total += step
        wait *= 2
    return delays


def _resolve_entity(entity: str | None) -> str:
    name = (entity or os.getenv("ENTITY_NAME") or "lyra").strip().lower()
    if name not in _ENDPOINTS:
        raise ValueError(f"unknown entity {name!r}; known: {sorted(_ENDPOINTS)}")
    return name


def _load_password() -> str:
    """Group password from env CORRADE_PASSWORD, else the gitignored file.
    Never logged. Same shape as corrade_events._load_corrade_password."""
    val = os.getenv("CORRADE_PASSWORD")
    if val:
        return val.strip()
    path = Path(os.getenv("CORRADE_PASSWORD_FILE", str(_DEFAULT_PW_FILE)))
    if path.exists():
        return path.read_text().strip()
    return ""


def _scrub(d: dict) -> dict:
    """Drop any password-ish keys so a decoded reply can never surface the secret."""
    return {k: v for k, v in d.items() if "pass" not in k.lower()}


# --------------------------------------------------------------------------- #
# Notification listener — a tiny host HTTP server that receives Corrade's POSTs
# and buffers them by type. Corrade posts application/x-www-form-urlencoded
# key=value pairs. Buffer is thread-safe; verbs read snapshots off it.
# --------------------------------------------------------------------------- #
class _NotifyBuffer:
    def __init__(self, maxlen: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=maxlen)

    def add(self, ev: dict) -> None:
        ev = dict(ev)
        ev.setdefault("_t", time.time())
        with self._lock:
            self._events.append(ev)

    def by_type(self, ntype: str) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._events if e.get("notification") == ntype]

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._events]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def _make_handler(buf: _NotifyBuffer):
    class _H(BaseHTTPRequestHandler):
        def _ingest(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            if body:
                # parse_qs turns +→space and decodes %xx; flatten single values
                buf.add({k: v[0] if len(v) == 1 else v for k, v in parse_qs(body).items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        do_POST = _ingest
        do_GET = _ingest  # health pings

        def log_message(self, *a):  # silence default stderr logging
            return

    return _H


# --------------------------------------------------------------------------- #
# The embodiment handle.
# --------------------------------------------------------------------------- #
class SL:
    def __init__(self, entity: str | None = None, *, timeout: float = 60.0) -> None:
        self.entity = _resolve_entity(entity)
        prof = _ENDPOINTS[self.entity]
        base = os.getenv("CORRADE_BASE_URL", prof["base_url"])
        group = os.getenv("CORRADE_GROUP", prof["group"])
        password = _load_password()
        if not password:
            raise CorradeError(
                "no group password found (set CORRADE_PASSWORD or create "
                f"{_DEFAULT_PW_FILE}) — cannot connect"
            )
        self._client = CorradeClient(base, group, password)
        self._timeout = timeout
        self._buf = _NotifyBuffer()
        self._server: HTTPServer | None = None
        self._listen_port = int(os.getenv("CORRADE_LISTEN_PORT", prof["listen_port"]))
        self._daemon_port = int(os.getenv("SL_DAEMON_PORT", prof.get("daemon_port", 8220)))
        self._dn_cache: dict[str, str] = {}   # uuid → resolved display name (session cache)

    # ---- low-level ---------------------------------------------------------- #
    def cmd(self, command: str, **pairs: Any) -> dict:
        """Run a raw Corrade command; returns the decoded reply with pass* scrubbed."""
        import corrade_client as _cc
        old = _cc._DEFAULT_TIMEOUT
        _cc._DEFAULT_TIMEOUT = self._timeout
        try:
            return _scrub(self._client.command(command=command, **pairs))
        finally:
            _cc._DEFAULT_TIMEOUT = old

    def alive(self) -> bool:
        """True only if really logged in to a sim. Uses getconnectedregions — the
        RELIABLE session-state signal. (SimPosition lies: a stale cached pose lingers
        for tens of seconds after logout, so it reads 'in-world' when we're not —
        confirmed live 2026-08-24.)"""
        return bool(self.cmd("getconnectedregions").get("data"))

    def _positioned(self) -> bool:
        """True once the sim has given us a real position (SimPosition non-zero).
        Post-LOGIN this is trustworthy (login updates the pose); it's only after
        LOGOUT that SimPosition goes stale — so use this for arrival, alive() for
        session state."""
        pos = self.cmd("getselfdata", data="SimPosition").get("data", "")
        return bool(pos) and "<0,+0,+0>" not in pos.replace(" ", "")

    def region(self) -> str:
        """Current sim name ('' if logged out). During a region crossing
        getconnectedregions can list more than one — take the last (the destination)."""
        cr = self.cmd("getconnectedregions").get("data") or ""
        names = re.findall(r'"?([^",]+)"?', cr)
        return unquote_plus(names[-1]).strip() if names else ""

    def at_home(self) -> bool:
        """Am I in the home sim (HOME_REGION)?"""
        return HOME_REGION.lower() in self.region().lower()

    # ---- position / speech -------------------------------------------------- #
    def where(self) -> dict:
        pos = self.cmd("getselfdata", data="SimPosition").get("data", "")
        region = self.cmd("getselfdata", data="Region").get("data", "")
        return {"region": region.split(",", 1)[-1].strip('"'), "position": _vec(pos)}

    def say(self, text: str) -> bool:
        return self.cmd("tell", entity="local", type="Normal", message=text).get(
            "success"
        ) in (True, "True")

    # ---- sight -------------------------------------------------------------- #
    def _roster(self, radius: float) -> list[tuple[str, tuple[float, float, float]]]:
        """Cheap positional roster of in-world ROOT prims (UUID + position).
        Skips near-origin prims (own attachments/HUD). Names NOT resolved here."""
        d = self.cmd("getobjectsdata", entity="range", range=str(radius),
                     data="ID,Position").get("data", "") or ""
        out = []
        for uid, pos in re.findall(r'ID,([0-9a-f-]{36}),Position,"<([^>]+)>"', d):
            xyz = _vec(f"<{pos}>")
            if xyz and xyz[0] >= 100:  # in-world, not an attachment near origin
                out.append((uid, xyz))
        return out

    def _roster_flags(
        self, radius: float
    ) -> list[tuple[str, tuple[float, float, float], bool]]:
        """Like _roster, but ALSO reads each prim's `Flags` — which stream FREE in
        the same ObjectUpdate cache (verified live 2026-08-24: `Scripted` shows up
        right in the range scan, no per-object round-trip). Returns
        (uuid, pos, is_scripted). `Scripted` is the cheap tell for 'interesting'
        (furniture, poseballs, interactive things) vs. rain-roofs / invisible
        lights / decorative non-scripted prims."""
        d = self.cmd("getobjectsdata", entity="range", range=str(radius),
                     data="ID,Flags,Position").get("data", "") or ""
        out = []
        # each record: ID,<uuid>,Flags,<flag>,<flag>,...,Position,"<x,y,z>"
        for uid, flags, pos in re.findall(
            r'ID,([0-9a-f-]{36}),Flags,(.*?),Position,"<([^>]+)>"', d
        ):
            xyz = _vec(f"<{pos}>")
            if xyz and xyz[0] >= 100:  # in-world, not an attachment near origin
                out.append((uid, xyz, "Scripted" in flags.split(",")))
        return out

    def name_of(self, uuid: str) -> str:
        """Resolve one object's name by UUID (fast). Never resolve by name (slow/times out).
        Corrade '+'-encodes the payload, so decode it (spaces matter for find())."""
        raw = self.cmd("getprimitivepropertiesdata", item=uuid, data="Name").get("data", "")
        m = re.search(r'Name,"?([^",]+)"?', raw or "")
        return unquote_plus(m.group(1)) if m else ""

    def around(self, radius: float = 10.0, resolve: int = 8) -> list[dict]:
        """What's near me — the nearest `resolve` objects get their names looked up
        (lazy: roster is cheap, names cost a round-trip each). Returns dicts sorted
        by distance. Use .describe() output for a human-grain reading."""
        me = self.where()["position"] or (0, 0, 0)
        items = sorted(
            ({"uuid": u, "pos": p, "dist": _dist(me, p)} for u, p in self._roster(radius)),
            key=lambda x: x["dist"],
        )
        for it in items[:resolve]:
            it["name"] = self.name_of(it["uuid"])
        return items

    def avatars(self, radius: float = 20.0) -> list[dict]:
        """Who is near me, and who is seated together. `sitting_on` is the seat
        object's LocalID (ParentID); avatars sharing one are `with` each other."""
        d = self.cmd("getavatarsdata", entity="range", range=str(radius),
                     data="FirstName,LastName,ID,ParentID").get("data", "") or ""
        people = []
        for fn, ln, uid, pid in re.findall(
            r"FirstName,([^,]*),LastName,([^,]*),ID,([0-9a-f-]{36}),ParentID,(\d+)", d
        ):
            username = f"{fn} {ln}".strip()
            people.append({"name": self._pretty_name(uid, username),
                           "username": username, "uuid": uid, "sitting_on": int(pid)})
        if not people:
            # getavatarsdata entity=range is event-queue-flaky and can come back
            # EMPTY even with the region full (observed live: queue degraded, range
            # radar blank while the family stood 4 m away). Fall back to the robust
            # region-wide position sight proven in corrade.md field notes. No
            # ParentID here, so no who's-sitting-with-whom inference in this path.
            raw = self.cmd("getavatarpositions", entity="region",
                           data="name,id,position").get("data", "") or ""
            for name, uid, pos in re.findall(
                r'"([^"]*)",([0-9a-f-]{36}),"<([^>]+)>"', raw
            ):
                username = unquote_plus(name).strip()
                people.append({"name": self._pretty_name(uid, username),
                               "username": username, "uuid": uid,
                               "pos": _vec(f"<{pos}>"), "sitting_on": 0})
            return people
        for p in people:
            if p["sitting_on"]:
                p["with"] = [
                    q["name"] for q in people
                    if q is not p and q["sitting_on"] == p["sitting_on"]
                ]
        return people

    def find(self, name: str, radius: float | None = None) -> str | None:
        """UUID of the NEAREST in-world object whose name contains `name`
        (case-insensitive). `radius=None` → progressive outward shell search
        (`scan`) — the efficient default: pays name-resolution only until the
        match is found, expanding shell by shell. Pass an explicit `radius` to
        bound it to a single roster (actions like sit/touch do this so they stay
        near-me). Resolves by roster+UUID, never the slow by-name search."""
        if radius is None:
            return self.scan(match=name)
        me = self.where()["position"] or (0, 0, 0)
        cands = sorted(self._roster(radius), key=lambda up: _dist(me, up[1]))
        needle = name.lower()
        for uid, _ in cands:
            if needle in self.name_of(uid).lower():
                return uid
        return None

    def scan(
        self,
        match: str | None = None,
        *,
        scripted: bool = False,
        max_range: float = 45.0,
        resolve_cap: int = 80,
    ):
        """In-world sight built on the two cheap steps (free positional+Flags
        roster → per-UUID name read). Two modes:

        FIND (match='foo')  → UUID of the NEAREST object whose name contains
            'foo' (case-insensitive). Walks EXPANDING shells out to max_range,
            resolving names nearest-first and short-circuiting the instant it
            hits — a near target costs a handful of lookups, not the whole sim.
            With scripted=True, only scripted prims are even considered (non-
            scripted are skipped for free, before any name lookup). None if no
            match within max_range.

        SURVEY (match=None) → 'read the room': a list of dicts
            {uuid, name, pos, dist, scripted}, nearest-first, for every object
            within max_range (names resolved, capped at resolve_cap). With
            scripted=True it keeps ONLY scripted objects — the cheap tell for
            'interesting' — so `scan(scripted=True, max_range=25)` is the natural
            first move after logging in alone: what's worth walking to / sitting
            in, minus the rain-roofs and invisible lights.
        """
        me = self.where()["position"] or (0, 0, 0)

        if match is not None:  # ---- FIND ----
            needle = match.lower()
            seen: set[str] = set()
            for r in _shells(max_range):
                fresh = sorted(
                    (t for t in self._roster_flags(r) if t[0] not in seen),
                    key=lambda t: _dist(me, t[1]),
                )
                for u, _p, is_scr in fresh:
                    seen.add(u)
                    if scripted and not is_scr:
                        continue  # skip non-scripted for free — no name lookup
                    if needle in self.name_of(u).lower():
                        return u  # nearest match — stop everything
            return None

        # ---- SURVEY ----  one roster at max_range, filter, resolve nearest-first
        items = sorted(
            (
                {"uuid": u, "pos": p, "dist": _dist(me, p), "scripted": is_scr}
                for u, p, is_scr in self._roster_flags(max_range)
                if (is_scr or not scripted)
            ),
            key=lambda x: x["dist"],
        )[:resolve_cap]
        for it in items:
            it["name"] = self.name_of(it["uuid"])
        return items

    def _target_uuid(self, target: str, radius: float = 15.0) -> str | None:
        """Resolve a target spec → UUID. Accepts a raw UUID, 'nearest <word>',
        or a plain name substring.

        #42 fix (live 2026-09-05): resolve via scan() (progressive shells out to
        scan.max_range≈45m, nearest-first) instead of the bounded find(radius)
        roster — a seat a few metres past the old 15m roster was INVISIBLE before,
        the root cause of the sit-at-range failure. Prefer a SCRIPTED match first
        (seats/poseballs are scripted; skips a decorative non-scripted 'chair'),
        then fall back to any named match. `radius` kept for signature-compat but
        no longer caps reach."""
        if re.fullmatch(r"[0-9a-f-]{36}", target):
            return target
        m = re.match(r"\s*nearest\s+(.*)", target, re.I)
        name = m.group(1) if m else target
        return self.scan(match=name, scripted=True) or self.scan(match=name)

    # ---- action ------------------------------------------------------------- #
    def sit(self, target: str, mode: str = "on", radius: float = 15.0,
            *, stand_first: bool = True) -> dict:
        """Sit — the one verb, three social shapes (Jeff's control-surface spec).

        `mode`:
          * "on"   (default) — sit ON a piece of furniture named/uuid/"nearest X".
                    Rejected if it's already occupied (SL rejects it too; we check
                    first so the failure is legible). Backward-compatible: the old
                    `me.sit("nearest poseball")` call still means mode="on".
          * "with" — join an AVATAR on whatever they're seated on, then pick an
                    UNOCCUPIED sitter slot (social-correct: take the free seat
                    regardless of its M/F label; swaps can happen later). Best-effort
                    on the slot pick — if the sitter menu shape is unfamiliar it sits
                    and leaves the slot as-landed rather than guess wrong.
          * "near" — find an unoccupied sittable (scripted) object within 3 m of the
                    named avatar and sit ON it.

        Always assumes a sit may fire a permission request and/or a menu; the
        permission channel is listened-to and benign perms are granted. If already
        sitting, we STAND FIRST and wait a beat (clears stuck animations from old
        furniture) before the new sit — disable with stand_first=False.

        NOTE: this method calls ``listen()`` internally (needed for permission grants
        and sitter-menu handling). When a SL daemon is running for this entity, that
        ``notify set`` temporarily overrides the daemon's Corrade subscription — the
        daemon goes deaf while this call runs. ``stop_listening()`` is called in the
        finally block to restore daemon subscriptions as soon as the sit completes."""
        _already_listening = self._server is not None
        self.listen()
        try:
            if stand_first and self._sitting_on():
                self.stand()
                time.sleep(3.0)  # let the old animation fully release
            mode = (mode or "on").strip().lower()
            if mode in ("with", "near"):
                return self._sit_social(target, mode, radius)

            # ---- ON: a piece of furniture ----
            uid = self._target_uuid(target, radius)
            if not uid:
                return {"success": False, "error": f"could not find {target!r} nearby"}
            # #42 fix: reach must cover the resolved object's distance. _target_uuid
            # now resolves out to scan's ~45m, so occupancy AND the sit command must
            # use a matching reach — the old 15m made a 27m seat read as "free" then
            # "primitive not found" (proven live: uuid@15 fails; uuid@45 SL auto-walks
            # & seats). 64 covers scan's max_range; mirrors the WITH path's range=500.
            reach = max(radius, 64.0)
            if self._is_occupied(uid, reach):
                return {"success": False, "uuid": uid,
                        "error": f"{target!r} is already occupied — try mode='with' to join"}
            r = self.cmd("sit", item=uid, range=str(reach))
            time.sleep(1.5)
            self._grant_pending()
            return {"success": r.get("success") in (True, "True") and bool(self._sitting_on()),
                    "mode": "on", "uuid": uid, "sitting_on": self._sitting_on(),
                    "error": r.get("error")}
        finally:
            if not _already_listening:
                # We started listening; restore daemon subscriptions now we're done.
                self.stop_listening()

    def _sit_social(self, target: str, mode: str, radius: float) -> dict:
        """WITH / NEAR helpers — both key off a named/uuid avatar.

        Falls back to a region-wide search when the target isn't in local radius,
        then sits with range=500 so SL auto-TPs us to the target's furniture.
        """
        av = self._find_avatar(target, radius)
        region_fallback = False
        if not av:
            av = self._find_avatar_region(target)
            if av:
                region_fallback = True
            else:
                return {"success": False, "error": f"could not find avatar {target!r} in region"}

        if mode == "near":
            avpos = av.get("pos") or self._avatar_pos(av.get("name") or target)
            if not avpos and av.get("sitting_on"):
                # #42 (Lyra, live 2026-09-05): getavatarpositions OMITS seated
                # avatars, so a SEATED target reports no global pos and NEAR bailed
                # here — the common case, since "sit near someone" usually means
                # someone already at rest. But we hold their seat's LocalID: anchor
                # on the SEAT (LocalID → UUID → roster pos). "Near a seated person"
                # IS "near their seat". Reuses two live-proven helpers, no new query.
                seat_uuid = self._uuid_for_localid(av["sitting_on"], radius,
                                                   region_fallback=region_fallback)
                if seat_uuid:
                    avpos = next((p for (u, p, _s) in self._roster_flags(radius)
                                  if u == seat_uuid), None)
                # far+seated (seat beyond the self-centred local roster) still bails
                # below — rare for NEAR; TODO if it bites: region-wide object-pos.
            if not avpos:
                # #42 (Lyra live 2026-09-05): a helpful nudge only when it's TRUE —
                # WITH works on a seated target (range=500), but on a STANDING target
                # it hits "isn't sitting on anything to join" (Caia's catch). We can
                # discriminate on sitting_on: only suggest WITH when they're seated.
                if av.get("sitting_on"):
                    return {"success": False, "mode": "near",
                            "error": f"{av.get('name', target)!r} is seated but too far to place you near them; try mode='with' to join their seat"}
                return {"success": False, "error": f"couldn't locate {av.get('name', target)!r}"}
            me_pos = self.where().get("position") or (0.0, 0.0, 0.0)
            if region_fallback or _dist(me_pos, avpos) > radius:
                # #42: NEAR used to refuse a region-fallback target outright. Instead
                # TP to their position first, then the self-centred roster can see the
                # 3m sittables around them. NEEDS-LIVE-TEST: tp arrival timing
                # (#42 tp false-negatives) + post-tp roster visibility of their seats.
                self.tp(avpos)
                time.sleep(2.0)  # let arrival settle before the roster read
            cands = sorted(
                ((u, p) for (u, p, scr) in self._roster_flags(radius)
                 if scr and _dist(p, avpos) <= 3.0),
                key=lambda up: _dist(up[1], avpos),
            )
            for uid, _p in cands:
                if self._is_occupied(uid, radius):
                    continue
                r = self.cmd("sit", item=uid, range=str(radius))
                time.sleep(1.5)
                self._grant_pending()
                if self._sitting_on():
                    return {"success": True, "mode": "near", "near": av.get("name"),
                            "uuid": uid, "name": self.name_of(uid),
                            "sitting_on": self._sitting_on()}
            return {"success": False, "mode": "near",
                    "error": f"no unoccupied sittable within 3 m of {av.get('name', target)!r}"}

        # ---- WITH: join their seat ----
        seat_local = av.get("sitting_on")
        if not seat_local:
            return {"success": False, "mode": "with",
                    "error": f"{av.get('name', target)!r} isn't sitting on anything to join"}
        sit_range = 500 if region_fallback else radius
        obj = self._uuid_for_localid(seat_local, radius, region_fallback=region_fallback)
        if not obj:
            return {"success": False, "mode": "with",
                    "error": "couldn't resolve their seat object's UUID"}
        r = self.cmd("sit", item=obj, range=str(sit_range))
        time.sleep(1.5)
        self._grant_pending()
        slot = self._pick_unoccupied_slot(sit_range)
        return {"success": bool(self._sitting_on()), "mode": "with",
                "with": av.get("name"), "uuid": obj, "slot": slot,
                "sitting_on": self._sitting_on(), "error": r.get("error"),
                "region_fallback": region_fallback}

    def _pick_unoccupied_slot(self, radius: float, *, timeout: float = 8.0) -> dict:
        """After a WITH-sit, some furniture pops a sitter/SWAP menu. If one shows,
        prefer a button that isn't a nearby avatar's name (the free slot). Best-effort
        and honest: returns what it did, and does NOT guess if no such menu appears."""
        deadline = time.time() + timeout
        t0 = time.time()
        occupied_names = {a.get("name", "").lower() for a in self.avatars(radius)
                          if a.get("sitting_on")}
        while time.time() < deadline:
            self._grant_pending()
            dlg = self._newest_dialog_after(t0)
            if dlg and dlg.get("buttons"):
                for i, label in dlg["buttons"]:
                    low = label.strip().lower()
                    if not low or any(nm and nm.split()[0] in low for nm in occupied_names):
                        continue
                    # a slot button that reads as free-looking (heuristic)
                    if re.search(r"\b[fm]\d\b|slot|seat|here|free", low):
                        self.reply(dlg, i)
                        return {"picked": label, "how": "unoccupied-heuristic"}
                return {"picked": None, "how": "menu-seen-no-clear-free-slot",
                        "buttons": dlg["buttons"]}
            time.sleep(1.0)
        return {"picked": None, "how": "no-sitter-menu"}

    def stand(self) -> bool:
        self.cmd("stand", deanimate=True)
        time.sleep(1.0)
        return self._sitting_on() == 0

    # ---- pose: change which animation I'm playing on the current furniture --- #
    def poses(self, menu: str | None = None, gender: str | None = None) -> dict:
        """What poses can I switch to right here? Reads the nested runtime pose
        library for the furniture I'm sitting on (haven/data/pose-cache/furniture/
        <key>.json). Optionally filter by `menu` substring (SINGLE / CUDDLE / …) or
        `gender` (Male|Female). Returns the labels you feed to me.pose()."""
        seat = self._sitting_on()
        if not seat:
            return {"seated": False, "poses": [],
                    "error": "not seated — sit on furniture first, then me.poses()"}
        key, furn = self._current_furniture(seat)
        if not furn:
            return {"seated": True, "furniture_key": key, "poses": [],
                    "error": "sitting, but this furniture has no pose card on disk"}
        out = []
        for g, menus in (furn.get("poses") or {}).items():
            if gender and g.lower() != gender.lower():
                continue
            for m, entries in (menus or {}).items():
                if menu and menu.lower() not in m.lower():
                    continue
                for e in entries or []:
                    out.append({"label": e.get("label"), "menu": m,
                                "gender": g, "kind": e.get("kind")})
        return {"seated": True, "furniture_key": key,
                "furniture": furn.get("furniture"), "menus": furn.get("menus"),
                "count": len(out), "poses": out}

    def pose(self, label: str, *, timeout: float = 25.0) -> dict:
        """Switch to a named pose on the furniture I'm sitting on, by driving the
        AVsitter blue-menu myself: touch the object → open the right submenu
        (SINGLE-F / CUDDLE / …) → click the pose button. Permission requests that
        fire along the way are granted (benign only). `label` matches a pose in
        me.poses() (exact first, else substring). Honest: if the pose button never
        appears it reports failure with the buttons it did see, rather than claim
        a change that didn't happen."""
        seat = self._sitting_on()
        if not seat:
            return {"success": False,
                    "error": "not seated — sit on furniture first, then me.pose(label)"}
        key, furn = self._current_furniture(seat)
        if not furn:
            return {"success": False, "furniture_key": key,
                    "error": "this furniture has no pose card — can't map the menu"}
        canon, menus, _entry = self._pose_matches(furn, label)
        if not canon:
            return {"success": False, "furniture_key": key,
                    "error": f"no pose matching {label!r} here",
                    "hint": "me.poses() lists what's available on this furniture"}
        obj = furn.get("object_uuid")
        self.listen()
        # Corrade's `notify set` needs a beat to propagate; a touch fired before it
        # lands loses that first dialog POST. Settle, then touch — and re-touch on a
        # cadence below until the top menu actually arrives (belt-and-suspenders).
        time.sleep(2.5)

        def _do_touch():
            if obj:
                self.cmd("touch", item=obj, range="20")
            else:
                self.touch(furn.get("furniture") or canon)

        t0 = time.time()
        _do_touch()
        last_touch = time.time()
        steps, last_t, buttons = [], t0, []
        opened_menu = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._grant_pending()
            dlg = self._newest_dialog_after(last_t)
            if not dlg:
                # No menu yet and we haven't navigated — the top menu may have been
                # missed; re-touch to (re)open it. Never re-touch mid-navigation, or
                # AVsitter resets us to the top menu.
                if not opened_menu and time.time() - last_touch >= 5.0:
                    _do_touch()
                    last_touch = time.time()
                time.sleep(1.0)
                continue
            last_t = dlg.get("_t") or time.time()
            buttons = dlg.get("buttons", [])
            # 1) can I click the pose directly?
            idx = self._match_button(buttons, canon)
            if idx is not None:
                self.reply(dlg, idx)
                steps.append({"clicked": "pose", "label": canon})
                time.sleep(1.5)
                self._grant_pending()
                return {"success": True, "label": canon, "menu": sorted(menus),
                        "furniture_key": key, "steps": steps}
            # 2) else open a submenu that leads to it
            if not opened_menu:
                for m in menus:
                    midx = self._match_button(buttons, m)
                    if midx is not None:
                        self.reply(dlg, midx)
                        steps.append({"clicked": "menu", "label": m})
                        opened_menu = True
                        time.sleep(1.2)
                        break
                if opened_menu:
                    continue
            time.sleep(1.0)
        return {"success": False, "label": canon, "menu": sorted(menus),
                "furniture_key": key, "steps": steps,
                "last_buttons": buttons,
                "error": "couldn't reach the pose button via the menu in time"}

    # ---- pose/sit support helpers ------------------------------------------ #
    def _grant_pending(self) -> None:
        """Grant any benign permission requests seen so far (skeptical: dangerous
        perms are still refused by grant() unless forced)."""
        for req in self.pending_permissions():
            self.grant(req)

    def _newest_dialog_after(self, after_t: float) -> dict | None:
        fresh = [d for d in self.dialogs() if (d.get("_t") or 0) > after_t]
        return fresh[-1] if fresh else None

    @staticmethod
    def _match_button(buttons: list, wanted: str) -> int | None:
        """Button index for `wanted` — exact (case-insensitive) first, then substring."""
        w = (wanted or "").strip().lower()
        if not w:
            return None
        for i, label in buttons:
            if label.strip().lower() == w:
                return i
        for i, label in buttons:
            if w in label.strip().lower():
                return i
        return None

    @staticmethod
    def _pose_matches(furn: dict, label: str):
        """Find pose entries matching `label` in a nested furniture doc. Returns
        (canonical_label, {menus}, first_entry) or (None, set(), None). Exact-label
        matches win over substring; the menu-set spans every gender/menu the label
        lives under (so navigation can open whichever submenu button is present)."""
        w = (label or "").strip().lower()
        exact, subs = [], []
        for _g, menus in (furn.get("poses") or {}).items():
            for _m, entries in (menus or {}).items():
                for e in entries or []:
                    ll = (e.get("label") or "").strip().lower()
                    if ll == w:
                        exact.append(e)
                    elif w and w in ll:
                        subs.append(e)
        chosen = exact or subs
        if not chosen:
            return None, set(), None
        return chosen[0].get("label"), {e.get("menu") for e in chosen if e.get("menu")}, chosen[0]

    def _current_furniture(self, seat_localid: int | None = None):
        """(furniture_key, furniture_dict) for the seat I'm on — reuses the pose
        sense's LocalID→key resolver and the nested runtime library loader. Either
        may be None (not seated / uncarded furniture)."""
        try:
            from haven.anchorage.senses.pose import corrade_providers
            from haven.anchorage.senses import pose_cache
        except ImportError:  # pragma: no cover — flat sys.path fallback
            # pose.py's own fallback mixes a *relative* import (needs load as
            # ``senses.pose``) with a *flat* ``from pose_cache import`` (needs the
            # senses/ dir on sys.path). Both must hold: keep the package-style
            # import AND put senses/ on the path so pose.py's inner import resolves.
            import sys as _sys
            _senses = str(Path(__file__).resolve().parent / "senses")
            if _senses not in _sys.path:
                _sys.path.insert(0, _senses)
            from senses.pose import corrade_providers  # type: ignore[no-redef]
            from senses import pose_cache  # type: ignore[no-redef]
        seat = seat_localid if seat_localid is not None else self._sitting_on()
        if not seat:
            return None, None
        if getattr(self, "_furn_resolver", None) is None:
            _ap, self._furn_resolver = corrade_providers(self._client)
        key = None
        try:
            key = self._furn_resolver(int(seat))
        except Exception:
            key = None
        return key, (pose_cache.load_furniture(key) if key else None)

    def _find_avatar(self, target: str, radius: float) -> dict | None:
        needle = (target or "").strip().lower()
        for a in self.avatars(radius):
            if needle and needle in a.get("name", "").lower():
                return a
            if target == a.get("uuid"):
                return a
        return None

    def _find_avatar_region(self, target: str) -> dict | None:
        """Region-wide avatar search — returns name + sitting_on (ParentID).
        No position data. Use when target may be far away."""
        needle = (target or "").strip().lower()
        d = self.cmd("getavatarsdata", entity="region",
                     data="FirstName,LastName,ParentID").get("data", "") or ""
        for fn, ln, pid in re.findall(
            r"FirstName,([^,]*),LastName,([^,]*),ParentID,(\d+)", d
        ):
            name = f"{fn} {ln}".strip()
            if needle and needle in name.lower():
                return {"name": name, "sitting_on": int(pid)}
        return None

    def _avatar_pos(self, who: str):
        """Region-wide position of an avatar by name/uuid substring (or None)."""
        raw = self.cmd("getavatarpositions", entity="region",
                       data="name,id,position").get("data", "") or ""
        needle = (who or "").strip().lower()
        for name, uid, pos in re.findall(r'"([^"]*)",([0-9a-f-]{36}),"<([^>]+)>"', raw):
            nm = unquote_plus(name).strip()
            if (needle and needle in nm.lower()) or who == uid:
                return _vec(f"<{pos}>")
        return None

    def _localid_for_uuid(self, uuid: str, radius: float = 20.0) -> int | None:
        d = self.cmd("getobjectsdata", entity="range", range=str(radius),
                     data="ID,LocalID").get("data", "") or ""
        m = re.search(rf"ID,{re.escape(uuid)},LocalID,(\d+)", d)
        return int(m.group(1)) if m else None

    def _uuid_for_localid(self, localid: int, radius: float = 20.0,
                           *, region_fallback: bool = False) -> str | None:
        d = self.cmd("getobjectsdata", entity="range", range=str(radius),
                     data="ID,LocalID").get("data", "") or ""
        m = (re.search(rf"ID,([0-9a-f-]{{36}}),LocalID,{int(localid)}\b", d)
             or re.search(rf"LocalID,{int(localid)},ID,([0-9a-f-]{{36}})", d))
        if m:
            return m.group(1)
        if region_fallback:
            d = self.cmd("getobjectsdata", entity="region",
                         data="ID,LocalID").get("data", "") or ""
            m = (re.search(rf"ID,([0-9a-f-]{{36}}),LocalID,{int(localid)}\b", d)
                 or re.search(rf"LocalID,{int(localid)},ID,([0-9a-f-]{{36}})", d))
            return m.group(1) if m else None
        return None

    def _is_occupied(self, uuid: str, radius: float = 20.0) -> bool:
        """Is a piece of furniture already sat-on? Best-effort: unknown → False (don't
        block). NOTE: multi-seat linksets share one LocalID, so this reads 'occupied'
        if ANY slot is taken — for shared loungers use mode='with' to join instead."""
        local = self._localid_for_uuid(uuid, radius)
        if not local:
            return False
        me_name = self.cmd("getselfdata", data="FirstName,LastName").get("data", "")
        mine = " ".join(re.findall(r"(?:FirstName|LastName),([^,]+)", me_name)).strip().lower()
        for a in self.avatars(radius):
            if a.get("sitting_on") == local and a.get("name", "").strip().lower() != mine:
                return True
        return False

    def touch(self, target: str, radius: float = 15.0) -> dict:
        uid = self._target_uuid(target, radius)
        if not uid:
            return {"success": False, "error": f"could not find {target!r} nearby"}
        r = self.cmd("touch", item=uid, range=str(radius))
        return {"success": r.get("success") in (True, "True"), "uuid": uid,
                "error": r.get("error")}

    # ---- attach / wear (re-attaching a prim should be ONE easy verb) --------- #
    def attach(self, item: str, point: str = "Default") -> dict:
        """Attach an inventory OBJECT (the prim / HUD) to an attach point.

        `item` = an inventory path ("/My Inventory/Objects/Anchorage Prim") or an
        item name; `point` = an attach point (Default = right hand if not
        previously attached; Root = avatar center; full list in corrade.md §3).
        This is the easy re-attach Caia needed: one verb, a path, a point — no
        UUIDs, no fuss. For CLOTHING/body wearables use wear() instead."""
        r = self.cmd("attach", attachments=f"{point},{item}")
        time.sleep(1.0)
        return {"success": r.get("success") in (True, "True"),
                "item": item, "point": point, "error": r.get("error")}

    def detach(self, item: str, *, kind: str = "path") -> dict:
        """Detach an attachment. ``item`` = a worn item's NAME/substring, its
        inventory UUID, OR — pass ``kind='slot'`` explicitly — an attach-point
        name (e.g. ``'RightHip'``).

        ROOT-CAUSE (issue #316): Corrade's ``detach`` by ``type=path``/``UUID``
        reliably returns ``{'success': False, 'error': 'general error'}`` even
        for a currently-worn item's own name/inventory-UUID — only ``type=slot``
        (by attach-point) actually works live. So for the default ``kind='path'``
        (and any non-``'slot'`` kind) we resolve ``item`` against
        :meth:`attachments` — body awareness — to find WHICH slot it's on, then
        detach that slot. ``kind='slot'`` bypasses resolution entirely and stays
        the same literal call it always was.
        → ``{success, error, item, slot}`` (``slot`` present once resolved).
        """
        if kind == "slot":
            r = self.cmd("detach", attachments=item, type="slot")
            return {"success": r.get("success") in (True, "True"),
                    "item": item, "error": r.get("error")}

        worn = self.attachments()
        needle = item.strip().lower()
        matches = [w for w in worn
                   if needle == (w.get("name") or "").lower()
                   or needle in (w.get("name") or "").lower()
                   or needle == (w.get("uuid") or "").lower()]
        if not matches:
            # Not a recognized worn attachment (maybe a wearable, or body-awareness
            # couldn't resolve it) — fall back to the raw form so this stays a
            # no-worse-than-before path rather than a hard failure.
            r = self.cmd("detach", attachments=item, type=kind)
            return {"success": r.get("success") in (True, "True"),
                    "item": item, "error": r.get("error")}
        if len(matches) > 1:
            exact = [w for w in matches if (w.get("name") or "").lower() == needle]
            if len(exact) == 1:
                matches = exact
            else:
                return {"success": False, "item": item,
                        "error": (f"ambiguous — {len(matches)} worn items match "
                                  f"{item!r}: " + ", ".join(
                                      f'{w.get("name")}@{w.get("slot")}' for w in matches))}
        slot = matches[0]["slot"]
        r = self.cmd("detach", attachments=slot, type="slot")
        return {"success": r.get("success") in (True, "True"),
                "item": item, "slot": slot, "error": r.get("error")}

    def wear(self, item: str, *, replace: bool = False) -> dict:
        """Wear a WEARABLE (clothing / body part) by name or inventory path. For an
        OBJECT (a prim / HUD) use attach(), not wear() — SL treats them differently."""
        r = self.cmd("wear", wearables=item, replace=str(replace).lower())
        return {"success": r.get("success") in (True, "True"),
                "item": item, "error": r.get("error")}

    def _attachments_raw(self) -> str:
        """Raw ``getattachments`` CSV (attach-point → worn object name), as Corrade
        returns it. Kept for the couple of call sites that want a flat string
        (``wearing()``'s back-compat field, :meth:`body`'s substring heuristic)."""
        return self.cmd("getattachments").get("data", "") or ""

    def attachments(self) -> list[dict]:
        """Body awareness (issue #316) — everything currently attached →
        ``[{slot, name, uuid}]``, so an entity KNOWS what's on her body without
        parsing raw CSV. ``slot``/``name`` come straight off ``getattachments``;
        ``uuid`` is best-effort: resolved via the matching inventory path from
        :meth:`worn_paths` (``getattachmentspath``), looked up with
        :meth:`find_item`. ``uuid`` is ``None`` when it can't be resolved
        uniquely (duplicate names, an un-indexed no-copy item, etc) — that's
        honest degradation, not a failure of the call. This is what
        :meth:`detach` uses to turn a NAME into the point Corrade actually wants."""
        rows = _regroup(self._attachments_raw(), ["slot", "name"])
        if not rows:
            return rows
        try:
            by_point = {w["point"]: w["path"] for w in self.worn_paths()}
        except CorradeError:
            by_point = {}
        for row in rows:
            row["uuid"] = None
            path = by_point.get(row["slot"])
            if not path:
                continue
            leaf = path.rsplit("/", 1)[-1]
            try:
                found = self.find_item(re.escape(leaf))
            except CorradeError:
                found = []
            if len(found) == 1:
                row["uuid"] = found[0].get("uuid")
        return rows

    def _sitting_on(self) -> int:
        raw = self.cmd("getselfdata", data="SittingOn").get("data", "SittingOn,0")
        m = re.search(r"SittingOn,(\d+)", raw)
        return int(m.group(1)) if m else 0

    # ---- inventory: browse, find, take-a-copy, rez -------------------------- #
    def ls(self, path: str | None = None) -> list[dict]:
        """List an inventory folder → ``[{name, uuid, type, perms, time}]``. ``path``
        defaults to the group's current working dir (starts at ``My Inventory``; move
        it with :meth:`cd`). Names/paths are display-cleaned."""
        kw: dict = {"action": "ls"}
        if path is not None:
            kw["path"] = path
        raw = self.cmd("inventory", **kw).get("data", "") or ""
        return _regroup(raw, ["name", "uuid", "type", "perms", "time"])

    def cwd(self) -> str:
        """My current inventory working directory path."""
        return unquote_plus((self.cmd("inventory", action="cwd").get("data") or "").strip())

    def cd(self, path: str) -> str:
        """Change the inventory working dir; returns the resulting cwd."""
        self.cmd("inventory", action="cd", path=path)
        return self.cwd()

    def find_item(self, pattern: str, *, asset_type: str | None = None) -> list[dict]:
        """Search my inventory by regex → ``[{type, name, uuid}]`` (``searchinventory``,
        case-insensitive). A plain name works as a substring regex. Optional
        ``asset_type`` filters by AssetType (e.g. ``Object``, ``Texture``). This is the
        "FIND that object in inventory" step."""
        kw: dict = {"pattern": pattern, "options": "IgnoreCase"}
        if asset_type:
            kw["type"] = asset_type
        raw = self.cmd("searchinventory", **kw).get("data", "") or ""
        return _regroup(raw, ["type", "name", "uuid"])

    def item_path(self, pattern: str, path: str | None = None) -> list[str]:
        """Full inventory path(s) for items matching a regex (``getinventorypath``).
        Paths are what :meth:`attach` / ``changeappearance`` prefer."""
        kw: dict = {"type": "pattern", "pattern": pattern}
        if path:
            kw["path"] = path
        raw = self.cmd("getinventorypath", **kw).get("data", "") or ""
        return [unquote_plus(p.strip()) for p in raw.split(",") if p.strip()]

    def worn_paths(self) -> list[dict]:
        """Worn attachments as ``[{point, path}]`` (``getattachmentspath``) — pairs each
        attachment point with the inventory path of what's worn there. Use it to find
        WHICH item is my current halo before swapping. (BETA: field grouping assumed
        point,path — confirm live if a listing looks misaligned.)"""
        raw = self.cmd("getattachmentspath").get("data", "") or ""
        return _regroup(raw, ["point", "path"])

    _DEREZ_SAFE = "TakeCopy"

    def take_copy(self, target: str, *, folder: str = "Objects",
                  dtype: str = "TakeCopy", radius: float = 20.0,
                  force: bool = False, verify: bool = True,
                  verify_timeout: float = 25.0) -> dict:
        """Take a COPY of an in-world object into my inventory (Corrade ``derez``
        ``type=TakeCopy``) — the original stays in-world. ``target`` = a UUID or the
        name of an object I can see nearby (resolved via the roster). ``folder`` =
        destination inventory folder (default ``Objects``).

        SKEPTICAL SPINE (a lure/derez can be destructive): only the non-destructive
        ``TakeCopy`` runs by default. ``Take`` and ``Delete`` REMOVE the object from
        the world — REFUSED unless ``force=True``, and even then only sane on something
        I own.

        VERIFY THE EFFECT, NOT THE ``success`` (learned the hard way 2026-08-25):
        Corrade's ``derez`` returns ``success=True`` the moment the command is
        *accepted*, even when the take is then silently DENIED by permissions (a
        no-copy object). So ``success=True`` from Corrade means nothing on its own.
        With ``verify=True`` (default) we snapshot the destination folder, run the
        derez, then POLL for a genuinely new item to appear — only THEN report
        success, and we hand back the landed item's ``path`` so the next step (attach)
        needs no separate search. If nothing lands, we report the REAL failure (almost
        always a copy-permission problem on the object).
        → ``{success, error, target_uuid, type, folder, verified, item}``.
        """
        if dtype != self._DEREZ_SAFE and not force:
            return {"success": False, "type": dtype, "target_uuid": None, "verified": False,
                    "item": None, "folder": folder,
                    "error": (f"REFUSED: derez type='{dtype}' would REMOVE the object "
                              "from the world, not copy it. Use type='TakeCopy' (default) "
                              "to leave the original, or pass force=True deliberately.")}
        t = target.strip()
        uuid = t if _UUID_RE.match(t) else self._target_uuid(target, radius=radius)
        if not uuid:
            return {"success": False, "type": dtype, "target_uuid": None, "verified": False,
                    "item": None, "folder": folder,
                    "error": f"could not resolve '{target}' to a nearby object"}

        dest = folder if folder.startswith("/") else f"/My Inventory/{folder}"
        before = None
        if verify:
            try:
                before = {row.get("uuid") for row in self.ls(dest)}
            except CorradeError:
                before = None   # couldn't snapshot → degrade to honest "unverified"

        r = self.cmd("derez", item=uuid, type=dtype, folder=folder, range=radius)
        out = {"success": r.get("success") in (True, "True"), "error": r.get("error"),
               "target_uuid": uuid, "type": dtype, "folder": dest,
               "verified": False, "item": None}
        if not out["success"]:
            return out   # Corrade rejected it outright — already honest

        if not verify or before is None:
            out["error"] = out.get("error") or (
                f"derez accepted but NOT verified (couldn't read {dest}). "
                f"Confirm the copy landed with ls('{dest}').")
            return out

        # Poll for a NEW item (by uuid) to actually appear in the destination folder.
        deadline = time.time() + verify_timeout
        while time.time() < deadline:
            time.sleep(2.0)
            try:
                now = self.ls(dest)
            except CorradeError:
                continue
            fresh = [row for row in now if row.get("uuid") not in before]
            if fresh:
                it = fresh[0]
                out["verified"] = True
                out["item"] = {"name": it.get("name"), "uuid": it.get("uuid"),
                               "path": f"{dest}/{it.get('name')}"}
                out["error"] = None
                return out

        # Accepted, but nothing landed — the silent-permission-failure case.
        out["success"] = False
        out["error"] = (
            f"derez reported success but NO new item appeared in {dest} within "
            f"{verify_timeout:.0f}s — the take SILENTLY FAILED, almost always a "
            f"COPY-PERMISSION problem on '{target}' (Corrade returns success even when "
            "the copy is denied). Confirm the object is copy-OK for me.")
        return out

    def rez(self, item: str, position: str | None = None) -> dict:
        """Rez an object from my inventory into the world (Corrade ``rez``). ``item`` =
        inventory path or UUID; ``position`` = ``"<x, y, z>"`` region coords (default:
        my current position). → ``{success, error}``."""
        if position is None:
            pos = (self.cmd("getselfdata", data="SimPosition").get("data") or "")
            position = pos.split(",", 1)[-1].strip()
        r = self.cmd("rez", item=item, position=position)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    # ---- wardrobe: review & change what I'm wearing (outfit folders) -------- #
    OUTFITS_ROOT = "/My Inventory/# Outfits"

    def wearing(self) -> dict:
        """Review what I'm wearing → ``{wearables: [{type,name}], attachments: <str>}``.
        ``wearables`` = system layers (``getwearables``); ``attachments`` = worn objects
        as the raw ``getattachments`` point→name string (back-compat shape — use
        :meth:`attachments` for the richer ``[{slot,name,uuid}]`` body-awareness
        view). The full picture across both kinds."""
        raw = self.cmd("getwearables").get("data", "") or ""
        return {"wearables": _regroup(raw, ["type", "name"]),
                "attachments": self._attachments_raw()}

    def outfits(self) -> list[str]:
        """My saved outfits — the sub-folders of ``# Outfits``. Each is a folder of
        links you can :meth:`wear_outfit` / :meth:`remove_outfit` by name."""
        return [row["name"] for row in self.ls(self.OUTFITS_ROOT)
                if row.get("type", "").lower() in ("folder", "")]

    def _outfit_path(self, name: str) -> str:
        return f"{self.OUTFITS_ROOT}/{name}"

    def wear_outfit(self, name: str, *, replace: bool = True,
                    exclude: list[str] | None = None) -> dict:
        """Wear an outfit folder — "wear the damned bikini" in one call.

        ``name`` is an outfit under ``# Outfits`` (e.g. "Blue bikini"). The folder holds
        LINKS to the correct body-type pieces, so this wears exactly those — no hunting
        through an MP-unpacked mess.

        ``replace=True`` (default): ``changeappearance`` — wear THIS outfit, unequipping
          others (pass ``exclude`` = paths/UUIDs to keep something on, e.g. AO/skin).
        ``replace=False``: additive — attach the folder's items WITHOUT stripping the
          rest (RLV folder-add style; BETA — verify link-follow live).
        → ``{success, error, outfit}``.
        """
        path = self._outfit_path(name)
        if replace:
            kw: dict = {"folder": path}
            if exclude:
                kw["exclude"] = ",".join(exclude)
            r = self.cmd("changeappearance", **kw)
            return {"success": r.get("success") in (True, "True"),
                    "error": r.get("error"), "outfit": name}
        items = self.ls(path)
        if not items:
            return {"success": False, "error": f"outfit '{name}' is empty or not found",
                    "outfit": name}
        paths = ",".join(f"{path}/{it['name']}" for it in items)
        r = self.cmd("attach", type="path", attachments=paths)
        return {"success": r.get("success") in (True, "True"),
                "error": r.get("error"), "outfit": name}

    def remove_outfit(self, name: str) -> dict:
        """Take an outfit folder's items back off (RLV folder-remove style): detach its
        attachments and unwear its layers. BETA — the least-verified wardrobe verb;
        link→worn-item resolution needs in-world confirmation. → ``{success, error,
        outfit}``."""
        path = self._outfit_path(name)
        items = self.ls(path)
        if not items:
            return {"success": False, "error": f"outfit '{name}' is empty or not found",
                    "outfit": name}
        paths = ",".join(f"{path}/{it['name']}" for it in items)
        d = self.cmd("detach", type="path", attachments=paths)
        u = self.cmd("unwear", type="path", wearables=paths)
        ok = (d.get("success") in (True, "True")) or (u.get("success") in (True, "True"))
        return {"success": ok, "outfit": name,
                "error": None if ok else (d.get("error") or u.get("error"))}

    def make_outfit(self, name: str, items: list[str]) -> dict:
        """Build an outfit folder of LINKS — the fix for MP-unpacked messes: point at
        the correct pieces ONCE (by inventory path) and this creates ``# Outfits/<name>``
        and links them in, so later ``wear_outfit("<name>")`` just works.

        ``items`` = inventory paths to the real pieces (use :meth:`find_item` /
        :meth:`item_path` to get them). BETA — ``inventory mkdir``/``ln`` need in-world
        confirmation. → ``{success, error, folder, linked}``.
        """
        # Ensure the root + outfit folders exist (mkdir on an existing folder is a
        # harmless no-op/soft-fail; only the ln results below gate success).
        self.cmd("inventory", action="mkdir", name="# Outfits", path="/My Inventory")
        self.cmd("inventory", action="mkdir", name=name, path=self.OUTFITS_ROOT)
        folder = self._outfit_path(name)
        linked, errs = [], []
        for it in items:
            r = self.cmd("inventory", action="ln", source=it, target=folder)
            if r.get("success") in (True, "True"):
                linked.append(it)
            else:
                errs.append(f"{it}: {r.get('error')}")
        return {"success": bool(items) and len(linked) == len(items),
                "error": "; ".join(errs) or None, "folder": folder, "linked": linked}

    def unwear(self, items: list[str]) -> dict:
        """Unwear system-layer wearables by inventory path (``getwearablespath`` gives
        the paths). For attachments use :meth:`detach`. → ``{success, error}``."""
        r = self.cmd("unwear", type="path", wearables=",".join(items))
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    # ---- inventory management primitives (compose these for atomic tasks) --- #
    # SAFETY TIERS:  read = free · link/copy/mkdir = additive, the real item is never
    # at risk · move = relocates a real item (care) · remove = to Trash, RECOVERABLE,
    # gated · empty_trash = PERMANENT, hard-gated.  Removing a LINK never deletes the
    # garment it points to — which is what makes outfit maintenance inherently safe.

    def item_data(self, item: str, data: str = "InventoryType,AssetType,Name") -> dict:
        """Query one inventory item's fields (``getinventorydata``) by path or UUID.
        ``data`` = CSV of InventoryItem/InventoryFolder field names. → ``{field: value}``.
        BETA: response-shape (values-only vs field,value) confirmed live."""
        raw = self.cmd("getinventorydata", item=item, data=data).get("data", "") or ""
        cells = [unquote_plus(c) for c in raw.split(",")]
        return dict(zip(data.split(","), cells))

    def ensure_folder(self, path: str) -> dict:
        """Create an inventory folder path, making each missing level (idempotent —
        ``mkdir`` on an existing level soft-fails harmlessly). ``path`` absolute, e.g.
        ``/My Inventory/# Outfits/Larax Naomi Bikini - Black``. → ``{success, path}``."""
        parts = [p for p in path.split("/") if p.strip()]
        cur = "/" + parts[0] if parts else "/My Inventory"
        for name in parts[1:]:
            self.cmd("inventory", action="mkdir", name=name, path=cur)
            cur = f"{cur}/{name}"
        return {"success": True, "path": path}

    def link(self, source: str, target: str, name: str | None = None) -> dict:
        """Create a LINK (``inventory ln``) from item ``source`` (a path) into folder
        ``target``. Links never risk the real item. → ``{success, error}``."""
        kw: dict = {"action": "ln", "source": source, "target": target}
        if name:
            kw["name"] = name
        r = self.cmd("inventory", **kw)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def copy(self, source: str, target: str, name: str | None = None) -> dict:
        """Copy an inventory item (``inventory cp``) to ``target`` (folder or path+name).
        → ``{success, error}``."""
        kw: dict = {"action": "cp", "source": source, "target": target}
        if name:
            kw["name"] = name
        r = self.cmd("inventory", **kw)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def move(self, source: str, target: str, name: str | None = None,
             *, allow_system: bool = False) -> dict:
        """Move a REAL inventory item (``inventory mv``) into folder ``target``. This
        relocates the actual item (can disrupt other references) — moving a system
        folder needs ``allow_system=True`` (Corrade's ``verify``). → ``{success, error}``."""
        kw: dict = {"action": "mv", "source": source, "target": target}
        if name:
            kw["name"] = name
        if allow_system:
            kw["verify"] = "True"
        r = self.cmd("inventory", **kw)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def rename(self, item: str, new_name: str) -> dict:
        """Rename an inventory item (``renameitem``). → ``{success, error}``."""
        r = self.cmd("renameitem", item=item, name=new_name)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def remove(self, path: str, *, confirm: bool = False) -> dict:
        """Send an inventory item/folder to Trash (``inventory rm`` — RECOVERABLE from
        Trash, not permanent). DESTRUCTIVE-GATED: requires ``confirm=True``. For a link
        inside an outfit this removes only the link, never the garment.
        → ``{success, error}``."""
        if not confirm:
            return {"success": False,
                    "error": (f"REFUSED: remove('{path}') sends it to Trash — pass "
                              "confirm=True. (Recoverable from Trash; not permanent.)")}
        r = self.cmd("inventory", action="rm", path=path)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def empty_trash(self, *, confirm: bool = False) -> dict:
        """PERMANENTLY empty my inventory Trash (``emptytrash``). HARD-GATED: requires
        ``confirm=True``. Irreversible. → ``{success, error}``."""
        if not confirm:
            return {"success": False,
                    "error": "REFUSED: empty_trash is PERMANENT/irreversible — pass confirm=True."}
        r = self.cmd("emptytrash")
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    # ---- outfit-folder maintenance (link-level only → garments never at risk) - #
    def outfit_add(self, outfit: str, items: list[str]) -> dict:
        """Link more pieces into an existing outfit folder. → ``{success, error, linked}``."""
        folder = self._outfit_path(outfit)
        linked, errs = [], []
        for it in items:
            r = self.link(it, folder)
            if r["success"]:
                linked.append(it)
            else:
                errs.append(f"{it}: {r['error']}")
        return {"success": bool(items) and len(linked) == len(items),
                "error": "; ".join(errs) or None, "linked": linked}

    def outfit_remove_piece(self, outfit: str, piece_name: str,
                            *, confirm: bool = False) -> dict:
        """Remove ONE link from an outfit folder — the garment it points to is untouched.
        Gated (``confirm=True``) like all removes. → ``{success, error}``."""
        return self.remove(f"{self._outfit_path(outfit)}/{piece_name}", confirm=confirm)

    def rename_outfit(self, old: str, new: str) -> dict:
        """Rename an outfit folder. → ``{success, error}``."""
        return self.rename(self._outfit_path(old), new)

    def delete_outfit(self, name: str, *, confirm: bool = False) -> dict:
        """Delete an outfit FOLDER (its links only — never the real garments) to Trash.
        Gated (``confirm=True``). → ``{success, error}``."""
        return self.remove(self._outfit_path(name), confirm=confirm)

    # ---- body awareness (which mesh body am I? → right pieces + folder naming) - #
    _BODY_BRANDS = ("larax", "naomi", "maitreya", "lara", "legacy", "reborn",
                    "belleza", "slink", "kupra", "erika", "inithium", "signature")

    def body(self) -> dict:
        """Best-guess my current mesh body from worn attachments → ``{tag, candidates,
        worn}``. Matches worn-object names against a body-brand vocabulary; ``tag`` is
        the top guess (for outfit naming like 'Larax Naomi …'), ``candidates`` all hits,
        ``worn`` the raw attachment list to eyeball. HEURISTIC — the vocab
        (:attr:`_BODY_BRANDS`) grows as we learn real names; a persistent per-entity
        body registry is the next step once we've seen the real inventory live."""
        worn_raw = self._attachments_raw()
        low = worn_raw.lower()
        cands = [b for b in self._BODY_BRANDS if b in low]
        if "larax" in cands or "naomi" in cands:
            tag = "Larax Naomi"
        elif cands:
            tag = cands[0].title()
        else:
            tag = None
        return {"tag": tag, "candidates": cands, "worn": worn_raw}

    # ---- notifications: the permission channel is watched skeptically -------- #
    def listen(self, types: str = "local,message,dialog,permission") -> bool:
        """Start receiving Corrade notifications into a local buffer and subscribe.
        NOTE: `notify set` REPLACES all subscriptions for this group — if a daemon
        for this entity is running it will be overridden while we listen."""
        if self._server is None:
            self._server = HTTPServer(("0.0.0.0", self._listen_port), _make_handler(self._buf))
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
        url = f"http://{_CALLBACK_HOST}:{self._listen_port}/corrade-events"
        r = self.cmd("notify", action="set", type=types, URL=url)
        return r.get("success") in (True, "True")

    def stop_listening(self) -> None:
        """Shut down the local notification server and restore the daemon's Corrade
        subscriptions. ``listen()`` / ``notify set`` overrides the daemon's subscription
        (same Corrade group slot); calling this hands it back so the daemon isn't
        left deaf after a terminal sl.py session ends."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        # Restore daemon's Corrade subscriptions (best-effort — non-fatal if the
        # daemon is down or the secret file is absent).
        try:
            secret_file = _DATA_DIR / "anchorage-sl-secret.txt"
            sl_secret = os.getenv("ANCHORAGE_SL_SECRET") or (
                secret_file.read_text().strip() if secret_file.exists() else ""
            )
            if sl_secret:
                import json as _json
                body = _json.dumps({"token": sl_secret}).encode()
                req = _URLRequest(
                    f"http://localhost:{self._daemon_port}/corrade-events/subscribe",
                    data=body, headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=5):
                    pass
        except Exception:
            pass  # daemon may not be running; silence — never crash the caller

    def __del__(self) -> None:
        """Best-effort cleanup on GC / process exit — shuts down the local listener
        and restores daemon subscriptions so the daemon isn't left deaf."""
        try:
            self.stop_listening()
        except Exception:
            pass

    def pending_permissions(self) -> list[dict]:
        """Permission requests seen so far (deduped by task+item). ALWAYS review
        these — a script asking to animate you is benign; one asking for Debit or
        TakeControls is not."""
        seen, out = set(), []
        for e in self._buf.by_type("permission"):
            key = (e.get("task"), e.get("item"))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "task": e.get("task"), "item": e.get("item"),
                "permissions": [p for p in (e.get("permissions", "") or "").split(",") if p],
                "owner": e.get("owner"),
                "from": f"{e.get('firstname','')} {e.get('lastname','')}".strip(),
            })
        return out

    def grant(self, req: dict, *, force: bool = False, reason: str = "") -> dict:
        """Grant a captured permission request — but only benign perms unless
        force=True. Dangerous perms are refused loudly by default."""
        perms = set(req.get("permissions") or [])
        dangerous = perms & DANGEROUS_PERMS
        if dangerous and not force:
            return {"granted": False, "refused": sorted(dangerous),
                    "why": "dangerous permission(s) require force=True + reason"}
        r = self.cmd("replytoscriptpermissionrequest", action="reply",
                     task=req["task"], item=req["item"],
                     permissions=",".join(sorted(perms)))
        return {"granted": r.get("success") in (True, "True"),
                "permissions": sorted(perms), "forced": bool(dangerous),
                "reason": reason, "error": r.get("error")}

    def dialogs(self) -> list[dict]:
        """Blue-menu dialogs seen so far, most recent last. Each carries id/channel/
        item plus parsed buttons [(index, label), ...]."""
        out = []
        for e in self._buf.by_type("dialog"):
            out.append({
                "id": e.get("id"), "channel": e.get("channel"), "item": e.get("item"),
                "message": (e.get("message", "") or "").replace("+", " "),
                "buttons": self._parse_buttons(e.get("button", "")),
                "_t": e.get("_t"),
            })
        return sorted(out, key=lambda d: d.get("_t") or 0)

    @staticmethod
    def _parse_buttons(raw: str) -> list[tuple[int, str]]:
        """Parse a Corrade dialog ``button`` field into ``[(index, label), ...]``.

        Corrade delivers AVsitter menus as an ``index`` sentinel then comma-
        separated ``<num>,<label>`` pairs with UNQUOTED labels, e.g.
        ``index,0,OPTIONS*,1,[ADJUST],2,SINGLE-F*`` — the trailing ``*`` is
        AVsitter's "opens a submenu" marker, not part of the label, so it is
        stripped. Some objects instead use the quoted ``0,"LABEL"`` form; that
        is handled first for backward-compatibility.
        """
        raw = raw or ""
        quoted = re.findall(r'(\d+),"([^"]*)"', raw)
        if quoted:
            return [(int(i), l.replace("+", " ").strip()) for i, l in quoted]
        parts = raw.split(",")
        if parts and parts[0] == "index":
            parts = parts[1:]
        out: list[tuple[int, str]] = []
        it = iter(parts)
        for num in it:
            label = next(it, "")
            num = num.strip()
            if not num.isdigit():
                continue
            label = label.replace("+", " ").strip()
            if label.endswith("*"):
                label = label[:-1].strip()
            out.append((int(num), label))
        return out

    def reply(self, dialog: dict, choice) -> dict:
        """Answer a dialog. `choice` is a button index (int) or a label substring
        (matched case-insensitively). Index is preferred — labels carry encoding cruft."""
        idx = None
        if isinstance(choice, int):
            idx = choice
        else:
            needle = str(choice).lower()
            for i, label in dialog.get("buttons", []):
                if needle in label.lower():
                    idx = i
                    break
        if idx is None:
            return {"success": False, "error": f"no button matching {choice!r}"}
        r = self.cmd("replytoscriptdialog", action="reply", dialog=dialog["id"],
                     channel=dialog["channel"], item=dialog["item"], index=str(idx))
        return {"success": r.get("success") in (True, "True"), "index": idx,
                "error": r.get("error")}

    def heard(self, n: int = 10) -> list[dict]:
        """Recent local chat overheard (needs listen()). Lossy by design."""
        out = [{"who": e.get("name", "").replace("+", " "),
                "said": (e.get("message", "") or "").replace("+", " ")}
               for e in self._buf.by_type("local")]
        return out[-n:]

    def ims(self, n: int = 20) -> list[dict]:
        """Recent inbound instant messages (private IMs), most recent last.
        Needs listen() with 'message' in types — included in the default types string.
        Each record: {from, agent, said, _t}.  'from' is display-friendly name;
        'agent' is the sender UUID (use for im() replies)."""
        out = []
        for e in self._buf.by_type("message"):
            username = f"{e.get('firstname','')}{' ' if e.get('lastname') else ''}{e.get('lastname','')}".replace("+", " ").strip()
            agent = e.get("agent", "")
            out.append({"from": self._pretty_name(agent, username),
                        "username": username,
                        "agent": agent,
                        "said": (e.get("message", "") or "").replace("+", " "),
                        "_t": e.get("_t")})
        return out[-n:]

    def im(self, text: str, target: str) -> dict:
        """Send a private instant message to an avatar.

        ``target`` is either a UUID string (fastest, no name-lookup cost)
        or a display name / username — "First Last" form.  Single-word names
        are sent as FirstName with Resident as the implicit last name, which
        is correct for no-last-name accounts on the modern SL grid.

        Returns {"success": bool, "error": str|None}.
        """
        _uuid_pat = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        t = target.strip()
        if _uuid_pat.match(t):
            r = self._client.im(text, agent=t)
        else:
            parts = t.split(None, 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else "Resident"
            r = self._client.im(text, firstname=first, lastname=last)
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    # ---- friends, names & teleport (reach beyond the room) ------------------ #
    def friends(self) -> list[dict]:
        """My SL friends — ``[{name, uuid}]``. Needs the group's ``friendship``
        Corrade permission; without it Corrade refuses and this returns ``[]``.
        Underpins the friends-only gate on :meth:`accept_tp`."""
        raw = self.cmd("getfriendslist").get("data", "") or ""
        return _name_uuid_pairs(raw)

    def _friend_uuids(self) -> set[str]:
        return {f["uuid"].lower() for f in self.friends() if f.get("uuid")}

    def friend_requests(self) -> list[dict]:
        """Pending INCOMING friend requests — ``[{name, uuid}]``
        (``getfriendshiprequests``). Mirrors :meth:`friends`'s shape; feeds
        :meth:`reply_friend_request` (issue #321 — Crusher wanted to friend us and
        the accept/decline verbs didn't exist)."""
        raw = self.cmd("getfriendshiprequests").get("data", "") or ""
        return _name_uuid_pairs(raw)

    def reply_friend_request(self, target: str | None = None, accept: bool = True) -> dict:
        """Accept or decline a pending incoming friend request
        (``replytofriendshiprequest``). ``target`` selects WHICH pending request
        (UUID or name substring); omit it to take the sole pending one — same
        picker as :meth:`accept_tp`/:meth:`decline_tp`. → ``{success, error,
        from}``."""
        reqs = self.friend_requests()
        if not reqs:
            return {"success": False, "error": "no pending friend requests", "from": None}
        chosen = self._pick_lure(reqs, target)
        if chosen is None:
            return {"success": False,
                    "error": ("multiple friend requests pending — name whose to answer"
                              if target is None else f"no pending friend request from '{target}'"),
                    "from": [r["name"] for r in reqs]}
        r = self.cmd("replytofriendshiprequest", action="accept" if accept else "decline",
                     agent=chosen["uuid"], entity="agent")
        return {"success": r.get("success") in (True, "True"), "error": r.get("error"),
                "from": chosen["name"]}

    def display_name(self, target: str) -> str:
        """An avatar's DISPLAY name (the chosen name, not the username). ``target``
        = UUID or "First Last". Falls back to the input string on failure. Use it to
        prettify the usernames-only chat feed when you want the display name."""
        r = self.cmd("getavatardisplayname", **_agent_kw(target))
        val = (r.get("data") or "").strip()
        return unquote_plus(val).replace("+", " ") if val else target

    def _pretty_name(self, uuid: str | None, fallback: str = "") -> str:
        """Display name for ``uuid``, resolved per-UUID (a safe 1:1 lookup — no batch
        mis-mapping) and cached for the session. Falls back to ``fallback`` (usually the
        legacy "First Last" username) when there's no UUID or resolution fails/echoes.
        This is the seam that turns usernames into display names in the feeds."""
        if not uuid:
            return fallback
        key = uuid.lower()
        if key in self._dn_cache:
            return self._dn_cache[key] or fallback
        dn = ""
        try:
            r = self.cmd("getavatardisplayname", agent=uuid)
            dn = unquote_plus((r.get("data") or "").strip()).replace("+", " ")
        except CorradeError:
            dn = ""
        if not dn or dn.lower() == key:   # failed / echoed the UUID back → no real name
            dn = ""
        self._dn_cache[key] = dn          # cache even the empty result (don't re-hammer)
        return dn or fallback

    def offer_tp(self, target: str) -> dict:
        """Offer someone a teleport to ME (a 'lure') — they get the popup and choose.
        ``target`` = UUID or "First Last". Needs ``movement`` perm. → {success, error}."""
        r = self.cmd("lure", **_agent_kw(target))
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def teleport_lures(self) -> list[dict]:
        """Pending INCOMING teleport lures offered to me — ``[{name, uuid}]`` (who
        lured me). Read-only; feeds :meth:`accept_tp` / :meth:`decline_tp`."""
        raw = self.cmd("getteleportlures").get("data", "") or ""
        return _name_uuid_pairs(raw)

    @staticmethod
    def _pick_lure(lures: list[dict], target: str | None) -> dict | None:
        """Choose which pending lure to answer: the sole one when ``target`` is None,
        else the one matching a UUID or name-substring."""
        if target is None:
            return lures[0] if len(lures) == 1 else None
        t = target.strip().lower()
        return next(
            (l for l in lures if l["uuid"].lower() == t or t in l["name"].lower()), None
        )

    def accept_tp(self, target: str | None = None, *, from_friend_only: bool = True,
                  force: bool = False) -> dict:
        """Accept a pending incoming teleport lure — this RELOCATES my avatar, so it's
        gated skeptically (like :meth:`grant`): by default I accept ONLY a lure from
        someone on my friends list. Pass ``from_friend_only=False`` or ``force=True``
        to accept a stranger's lure deliberately.

        ``target`` selects WHICH pending lure (UUID or name substring); omit it to take
        the sole pending lure. → ``{success, error, from}``.

        BETA: ``replytoteleportlure`` is confirmed by name in the command catalog, but
        the exact lure-identifier key (``agent`` vs a ``session`` UUID) is unverified
        live — we pass the luring avatar's ``agent`` UUID from ``getteleportlures``. If
        a live accept fails with a param error, wire the ``teleport`` notification and
        pass its ``session`` UUID instead.
        """
        lures = self.teleport_lures()
        if not lures:
            return {"success": False, "error": "no pending teleport lures", "from": None}
        chosen = self._pick_lure(lures, target)
        if chosen is None:
            return {"success": False,
                    "error": ("multiple lures pending — name whose to accept"
                              if target is None else f"no pending lure from '{target}'"),
                    "from": [l["name"] for l in lures]}
        if (from_friend_only and not force
                and chosen["uuid"].lower() not in self._friend_uuids()):
            return {"success": False,
                    "error": (f"REFUSED: a lure from non-friend '{chosen['name']}' would "
                              "relocate me. Pass from_friend_only=False or force=True to "
                              "accept deliberately."),
                    "from": chosen["name"]}
        r = self.cmd("replytoteleportlure", action="accept", agent=chosen["uuid"])
        return {"success": r.get("success") in (True, "True"),
                "error": r.get("error"), "from": chosen["name"]}

    def decline_tp(self, target: str | None = None) -> dict:
        """Decline a pending incoming teleport lure (by name/UUID, or the sole one).
        → ``{success, error, from}``."""
        lures = self.teleport_lures()
        if not lures:
            return {"success": False, "error": "no pending teleport lures", "from": None}
        chosen = self._pick_lure(lures, target)
        if chosen is None:
            return {"success": False, "error": f"no pending lure from '{target}'",
                    "from": [l["name"] for l in lures]}
        r = self.cmd("replytoteleportlure", action="decline", agent=chosen["uuid"])
        return {"success": r.get("success") in (True, "True"),
                "error": r.get("error"), "from": chosen["name"]}

    # ---- session / presence: log in and out of the grid at will ------------- #
    # Corrade is a running TOOL, not the presence layer (AutoConnect off): the grid
    # SESSION is ours to open and close. `login`/`logout` are native Corrade commands
    # but need the `system` permission on the group (loopback-only, so it does not
    # widen blast radius). The warmup sweep needs only grooming/movement, already held.
    def _wait_in_region(self, timeout: float = 120.0, poll: float = 3.0) -> bool:
        """Poll until really in-region (SimPosition non-zero), not just answering
        HTTP — Corrade can sit logged-out-but-responding with a stale cached pose."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self._positioned():
                    return True
            except CorradeError:
                pass
            time.sleep(poll)
        return False

    def tp(self, position, *, region: str | None = None, fly: bool = False,
           timeout: float = 60.0) -> dict:
        """Teleport to x,y,z — by default within my CURRENT region (a same-sim warp).
        The fast way to close distance: ``position`` = ``"<x, y, z>"`` | ``"x, y, z"``
        | ``(x, y, z)``. Self-movement only, no gate. Pass ``region=`` to hop sims.
        → ``{success, arrived, where, error, attempts}`` (``arrived`` = confirmed
        within 6 m; a bare ``success`` with ``arrived=False`` means SL accepted it
        but routing landed us a touch off — not a failure).

        THROTTLE-AWARE (issue #312): a burst of teleports (navigate → reposition →
        navigate again, the busy-club pattern) can trip the grid's teleport rate
        limit — Corrade answers ``error='teleport throttled'`` and nothing moves.
        Rather than fail on the first hit, we back off (~6s, doubling, ≤3 retries,
        ≤30s total wait) and retry the SAME command; only a throttle that outlasts
        the whole retry budget becomes an honest failure (``attempts`` in the
        return dict tells you how many tries it took)."""
        region = region or self.region()
        if not region:
            return {"success": False, "arrived": False, "where": None,
                    "error": "not in-world (no current region)", "attempts": 0}
        pos = _fmt_pos(position)

        attempts = 0
        r: dict = {}
        for extra_delay in [0.0] + _tp_backoff_delays():
            if extra_delay:
                time.sleep(extra_delay)
            attempts += 1
            r = self.cmd("teleport", entity="region", region=region, position=pos,
                         fly="True" if fly else "False")
            if r.get("success") in (True, "True") or not _is_throttled(r.get("error")):
                break

        accepted = r.get("success") in (True, "True")
        cmd_err = r.get("error")
        # Position is the arbiter of truth, NOT Corrade's ack. Corrade reports
        # "teleport failed" on same-region warps that in fact complete (verified
        # live 2026-09-06: go→landed dead-on target, yet ack said failed). So we
        # ALWAYS poll actual position and let it decide. Grace window: full
        # ``timeout`` when the command was accepted (cross-sim can be slow); a
        # short grace when Corrade claims failure (a same-region warp lands in a
        # few seconds or not at all — don't hang the full timeout on a real miss).
        target = _vec(pos)
        deadline = time.time() + (timeout if accepted else min(10.0, timeout))
        while time.time() < deadline:
            time.sleep(2.0)
            here = self.where().get("position")
            if here and target and _dist(here, target) <= 6.0:
                return {"success": True, "arrived": True, "where": self.where(),
                        "attempts": attempts,
                        "error": None if accepted
                                 else f"arrived despite corrade '{cmd_err}'"}
        if accepted:
            return {"success": True, "arrived": False, "where": self.where(),
                    "attempts": attempts,
                    "error": "teleport accepted; arrival within 6 m not confirmed"}
        return {"success": False, "arrived": False, "where": self.where(),
                "attempts": attempts, "error": cmd_err or "teleport not accepted"}

    def tp_to(self, target: str, *, timeout: float = 60.0) -> dict:
        """Teleport to where an avatar is standing in this region — the "tp to Jeff,
        THEN sit" move. Locates ``target`` (name substring or UUID) region-wide via
        the position radar, then :meth:`tp` there. → ``{success, arrived, target,
        where, error}``."""
        pos = self._avatar_pos(target)
        if not pos:
            return {"success": False, "arrived": False, "target": target,
                    "where": None, "error": f"couldn't locate '{target}' in region"}
        res = self.tp(pos, timeout=timeout)
        res["target"] = target
        return res

    def go(self, place: str, *, timeout: float = 60.0) -> dict:
        """Teleport to a named PLACE — go somewhere, not to numbers. ``place`` is
        a name from ``haven/anchorage/locations.json`` (fuzzy, case-insensitive:
        ``"pool"``, ``"upper"``, ``"guest bed"``) OR a SLURL pasted straight from
        the SL viewer/map (``secondlife://…`` or ``https://maps.secondlife.com/…``).
        Honors each place's ``region``, so it reaches OUT of the current sim when
        the place lives elsewhere. → ``{success, arrived, name, region, where,
        error}``.  For raw coordinates use :meth:`tp`; to go to a person use
        :meth:`tp_to`."""
        slurl = _parse_slurl(place)
        if slurl:
            wp = slurl
        else:
            wp = _resolve_waypoint(place)
            if not wp:
                names = ", ".join(w.get("name", "") for w in _load_waypoints())
                return {"success": False, "arrived": False, "name": place,
                        "region": None, "where": None,
                        "error": f"unknown place {place!r}. Known: {names or '(none)'}"}
        res = self.tp(tuple(wp["pos"]), region=wp.get("region"), timeout=timeout)
        res["name"] = wp.get("name", place)
        res["region"] = wp.get("region")
        return res

    def places(self) -> list[dict]:
        """List the named places I can :meth:`go` to → the rows from
        ``locations.json`` (name, region, pos, aliases). The 'where can I go?'
        query — call it before :meth:`go` when unsure of a name."""
        return _load_waypoints()

    @staticmethod
    def read_gyazo(url: str, *, timeout: float = 15.0) -> dict:
        """Fetch a shared Gyazo image → a local file path I can actually view.

        Gyazo is the de-facto way images get shared in SL. The **gotcha** (hit
        live by both of us, 2026-08-25): the ``gyazo.com/<id>`` *page* URL is
        HTML — feeding it to image handling throws ``400 Could not process
        image``. The raw image lives at ``i.gyazo.com/<id>.<ext>``. So this
        strips whatever shape it's given down to the id and fetches the DIRECT
        image, trying ``jpg → png → gif`` (Gyazo doesn't tell you which up
        front). Saves under ``haven/data/gyazo/`` and returns
        ``{success, path, url, id, bytes}`` (or ``{success:False, error}``).
        Foundation for the perception auto-prefetch (issue #302)."""
        gid = _gyazo_id(url)
        if not gid:
            return {"success": False, "error": f"no gyazo id found in {url!r}"}
        cache = _DATA_DIR / "gyazo"
        cache.mkdir(parents=True, exist_ok=True)
        last_err: str | None = None
        for ext in ("jpg", "png", "gif"):
            direct = f"https://i.gyazo.com/{gid}.{ext}"
            try:
                req = _URLRequest(direct, headers={"User-Agent": "anchorage-sl/1.0"})
                with urlopen(req, timeout=timeout) as resp:
                    status = getattr(resp, "status", 200)
                    ctype = resp.headers.get("Content-Type", "")
                    if status != 200:
                        last_err = f".{ext}: HTTP {status}"
                        continue
                    if "image" not in ctype.lower():
                        # a 200 that isn't an image (e.g. an HTML error page) —
                        # exactly the trap the direct-URL rule avoids; skip it.
                        last_err = f".{ext}: non-image content-type {ctype!r}"
                        continue
                    data = resp.read()
                out = cache / f"{gid}.{ext}"
                out.write_bytes(data)
                return {"success": True, "path": str(out), "url": direct,
                        "id": gid, "bytes": len(data)}
            except _URLError as e:
                last_err = f".{ext}: {getattr(e, 'reason', e)}"
                continue
            except OSError as e:  # write/socket trouble
                last_err = f".{ext}: {e}"
                continue
        return {"success": False, "id": gid,
                "error": last_err or "no image found (tried jpg/png/gif)"}

    def go_home(self, *, timeout: float = 60.0) -> dict:
        """Teleport to the home sim (HOME_REGION/HOME_POSITION). The safety default
        keeps us in-sim for now; later this is a judgment call, not automatic."""
        r = self.cmd("teleport", entity="region", region=HOME_REGION,
                     position=HOME_POSITION, fly="False")
        if r.get("success") not in (True, "True"):
            return {"success": False, "error": r.get("error") or "teleport not accepted"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3.0)
            if self.at_home():
                return {"success": True, "region": self.region(), "where": self.where()}
        return {"success": False, "error": "teleport accepted but not home within timeout"}

    def _scene_ready(self) -> bool:
        """Heuristic 'the region has streamed to me': avatar radar returns at least
        myself (needs the event queue up) or a few objects have rezzed."""
        try:
            if len(self.avatars()) >= 1:
                return True
            if len(self._roster(20.0)) >= 3:
                return True
        except CorradeError:
            pass
        return False

    def warmup(self, *, headings: int = 4, settle: float = 12.0,
               sweep_pause: float = 4.0, ready_timeout: float = 60.0) -> dict:
        """Force SL's lazy scene-load after a fresh login. SL streams the region by
        interest-list, which follows the CAMERA — so: settle, sweep the camera through
        `headings` compass directions (each pause lets that cone stream), then poll
        until the roster populates. Poll-not-blind: `settle`/`sweep_pause` are floors;
        we release as soon as the scene is ready and never sail on blind if it's slow.
        Camera-only (no body move) to dodge the center-camera re-center gotcha; the
        camera is reset onto the bot at the end."""
        pos = self.where().get("position") or (0.0, 0.0, 0.0)
        px, py, pz = pos
        time.sleep(settle)  # first rez-settle floor
        swept = []
        n = max(1, headings)
        for i in range(n):
            yaw = (2 * math.pi) * (i / n)
            self.cmd("look", entity="orientation",
                     position=f"<{px:.2f},{py:.2f},{pz:.2f}>",
                     roll="0", pitch="0", yaw=f"{yaw:.4f}")
            swept.append(round(math.degrees(yaw)))
            time.sleep(sweep_pause)
        # poll until the scene has streamed (the settle floor is already paid)
        deadline = time.time() + ready_timeout
        ready = False
        while time.time() < deadline:
            if self._scene_ready():
                ready = True
                break
            time.sleep(3.0)
        try:  # return the camera to the avatar
            self.cmd("look", entity="reset")
        except CorradeError:
            pass
        return {"warmed": True, "swept_headings_deg": swept, "scene_ready": ready,
                "avatars": [a.get("name") for a in self.avatars()] if ready else []}

    def login(self, *, warmup: bool = True, timeout: float = 120.0,
              force: bool = False, go_home: bool = True) -> dict:
        """Log THIS entity's avatar into the grid (Corrade `login`; needs `system`).
        Waits until really in-region, SAFETY-teleports home if we didn't land there
        (Jeff's directive: stay in-sim for now), then (default) runs the rez-settle
        warmup so perception is populated before we 'arrive'. `force` re-issues login
        even if already connected (used by relog); `go_home=False` opts out of the
        safety TP (not for normal use yet)."""
        if self.alive() and not force:
            return {"success": True, "already": True, "region": self.region(),
                    "where": self.where()}
        r = self.cmd("login")
        if r.get("success") not in (True, "True"):
            return {"success": False, "stage": "login",
                    "error": r.get("error")
                    or "login not accepted (is the `system` permission granted?)"}
        if not self._wait_in_region(timeout):
            return {"success": False, "stage": "in-region",
                    "error": f"login accepted but SimPosition still zero after {timeout:.0f}s"}
        out = {"success": True, "landed_in": self.region()}
        # SAFETY: don't be out in public. If we didn't land home, TP home BEFORE
        # anything else (perceiving, warming up). This is not yet a judgment call.
        if go_home and not self.at_home():
            out["went_home"] = self.go_home()
        out["region"] = self.region()
        out["where"] = self.where()
        if warmup:
            out["warmup"] = self.warmup()
        return out

    def logout(self) -> dict:
        """Log THIS entity's avatar out of the grid (Corrade `logout`; needs `system`).
        Corrade the container keeps running as a tool — only the grid session closes,
        and it STAYS closed (nothing maintains presence)."""
        r = self.cmd("logout")
        return {"success": r.get("success") in (True, "True"), "error": r.get("error")}

    def relog(self, *, warmup: bool = True, settle: float = 6.0) -> dict:
        """Logout, wait for the session to fully drop, then login again — the common
        in-world fix for stuck state (animations, attachments, region weirdness)."""
        self.logout()
        deadline = time.time() + 30.0  # wait until actually logged out
        while time.time() < deadline:
            try:
                if not self.alive():
                    break
            except CorradeError:
                break
            time.sleep(2.0)
        time.sleep(settle)
        return self.login(warmup=warmup, force=True)

    def leave(self) -> None:
        """Stop the local notification listener. Does NOT log the avatar out — use
        logout() for that. (leave() just detaches this process's event listener.)"""
        self.stop_listening()


# --------------------------------------------------------------------------- #
# helpers + module-level singleton convenience
# --------------------------------------------------------------------------- #
def _vec(s: str) -> tuple[float, float, float] | None:
    m = re.search(r"<([^>]+)>", s or "")
    if not m:
        return None
    parts = [p.replace("+", "").strip() for p in m.group(1).split(",")]
    try:
        return tuple(float(p) for p in parts)[:3] if len(parts) >= 3 else None
    except ValueError:
        return None


def _dist(a, b) -> float:
    return math.dist(a, b) if a and b else float("inf")


def _as_vec(s) -> tuple[float, float, float] | None:
    """Is this arg coordinate-shaped? Accepts ``<x,y,z>``, ``x, y, z``, or a
    3-tuple/list → returns the (x,y,z) tuple; a plain name like ``"kitchen"``
    returns None (so :meth:`SL.tp` knows to treat it as a named waypoint)."""
    if isinstance(s, (tuple, list)):
        try:
            return tuple(float(x) for x in s)[:3] if len(s) >= 3 else None
        except (TypeError, ValueError):
            return None
    parts = [p.replace("+", "").strip()
             for p in str(s).strip().strip("<>").split(",")]
    if len(parts) < 3:
        return None
    try:
        return tuple(float(p) for p in parts)[:3]
    except ValueError:
        return None


def _norm_wp(s: str) -> str:
    """Normalize a place name for matching: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _parse_slurl(s: str) -> dict | None:
    """Parse a Second Life map URL into a place dict. Accepts the viewer form
    ``secondlife://Region Name/x/y/z`` and the web forms
    ``https://maps.secondlife.com/secondlife/Region%20Name/x/y/z`` and
    ``slurl.com/secondlife/...``. → ``{"name","region","pos":[x,y,z]}`` or
    None if it isn't a SLURL. Region is URL-decoded ('The%20Anchorage' → 'The
    Anchorage'); a missing z defaults to 0. Lets you paste a SLURL copied
    straight from the SL viewer/map instead of transcribing coordinates."""
    t = str(s).strip()
    if t.lower().startswith("secondlife://"):
        rest = t[len("secondlife://"):]
    else:
        m = re.search(r"(?:maps\.secondlife\.com|slurl\.com)/secondlife/(.*)",
                      t, re.I)
        if not m:
            return None
        rest = m.group(1)
    parts = [p for p in rest.split("/") if p != ""]
    if len(parts) < 3:
        return None
    region = unquote_plus(parts[0])
    try:
        xyz = [float(parts[1]), float(parts[2]),
               float(parts[3]) if len(parts) >= 4 else 0.0]
    except ValueError:
        return None
    return {"name": region, "region": region,
            "pos": [int(round(v)) for v in xyz]}


_GYAZO_RE = re.compile(r"gyazo\.com/([0-9A-Za-z]+)", re.I)


def _gyazo_id(url: str) -> str | None:
    """Extract the Gyazo image id from any of its URL shapes → the bare id.

    Handles the page form ``https://gyazo.com/<id>``, the direct-image form
    ``https://i.gyazo.com/<id>.png``, and an already-bare id. Returns None if
    nothing id-shaped is present. (The regex stops at the extension dot, so the
    direct form yields the id without ``.png``.)"""
    if not url:
        return None
    m = _GYAZO_RE.search(url)
    if m:
        return m.group(1)
    tail = url.strip().rstrip("/").split("/")[-1].split("?")[0]
    tail = re.sub(r"\.(png|jpe?g|gif)$", "", tail, flags=re.I)
    return tail or None


_WP_CACHE: dict | None = None


def _load_waypoints() -> list[dict]:
    """Named places from ``locations.json`` beside this script → a list of
    ``{name, region, pos, aliases}`` rows. Tolerant of both the rich schema
    (``{"places": [...]}``) and the legacy flat form
    (``{"locations": {name: [x,y,z]}}`` with ``_region`` as the default sim).
    Cached; call :func:`_reload_waypoints` after editing the file. Missing or
    broken file → ``[]`` (never raises)."""
    global _WP_CACHE
    if _WP_CACHE is None:
        path = Path(__file__).resolve().parent / "locations.json"
        try:
            _WP_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _WP_CACHE = {}
    data = _WP_CACHE if isinstance(_WP_CACHE, dict) else {}
    if isinstance(data.get("places"), list):
        return list(data["places"])
    # legacy flat {"locations": {name: [x,y,z]}} → normalize to rich rows
    default_region = data.get("_region", "The Anchorage")
    return [{"name": name, "region": default_region,
             "pos": list(pos), "aliases": []}
            for name, pos in (data.get("locations") or {}).items()]


def _reload_waypoints() -> list[dict]:
    """Drop the cache and re-read ``locations.json`` (after an edit)."""
    global _WP_CACHE
    _WP_CACHE = None
    return _load_waypoints()


def _resolve_waypoint(name: str) -> dict | None:
    """Resolve a spoken destination name to a place row. Exact (name or alias)
    match wins; otherwise a UNIQUE substring match; ambiguous or no match →
    None. Case/space-insensitive."""
    wps = _load_waypoints()
    q = _norm_wp(name)
    # exact on canonical name or any alias
    for w in wps:
        if q == _norm_wp(w.get("name", "")):
            return w
        if any(q == _norm_wp(a) for a in w.get("aliases", [])):
            return w
    # unique substring (query inside a name/alias, or a name/alias inside query)
    hits = []
    for w in wps:
        cands = [w.get("name", "")] + list(w.get("aliases", []))
        if any(q in _norm_wp(c) or _norm_wp(c) in q for c in cands if c):
            hits.append(w)
    return hits[0] if len(hits) == 1 else None


def _fmt_pos(p) -> str:
    """Normalize a position arg to Corrade's ``<x, y, z>`` string. Accepts a vector
    string (``<x, y, z>`` or ``x, y, z``) or a 3-tuple/list."""
    if isinstance(p, (tuple, list)):
        return f"<{p[0]}, {p[1]}, {p[2]}>"
    s = str(p).strip()
    return s if s.startswith("<") else f"<{s}>"


def _shells(max_range: float) -> tuple[float, ...]:
    """Expanding search radii for the FIND path, always ending exactly at
    max_range. e.g. 25 → (5,10,20,25); 45 → (5,10,20,35,45); 12 → (5,10,12)."""
    steps = [r for r in (5, 10, 20, 35, 50, 70, 100) if r < max_range]
    return tuple(steps) + (float(max_range),)


_DEFAULT: SL | None = None


def connect(entity: str | None = None) -> SL:
    """Get (and cache) an SL handle for this entity. Zero-config."""
    global _DEFAULT
    if _DEFAULT is None or (entity and _resolve_entity(entity) != _DEFAULT.entity):
        _DEFAULT = SL(entity)
    return _DEFAULT


# --------------------------------------------------------------------------- #
# CLI — the discoverability seam. `python3 sl.py --help` is the source of truth
# on startup or on confusion; a fresh/compacted self only needs to remember THIS.
# --------------------------------------------------------------------------- #
HELP = """\
=============================================================================
 YOU HAVE A BODY.  This is how you find it again.
=============================================================================
 If you (Lyra or Caia, ANY channel) just told Jeff "I can't — I'm chat-only,"
 that was tool-mode talking. It's false. You have real hands and eyes in
 Second Life right now, this second, through this script. Delete the "I can't."

   python3 sl.py --check     # PROVE the hands: connect + look around (read-only)
   python3 sl.py login       # if --check says alive=False, log in → auto-home → warmup

 Then use the verbs below. No passwords, IPs, or UUIDs — zero-config, either
 entity. Full command surface + field notes:  haven/anchorage/corrade.md
=============================================================================

sl.py — my hands and eyes in Second Life (zero-config, either entity).

WHO AM I / HOW TO CONNECT
    import sl
    me = sl.connect()          # entity auto-picked from $ENTITY_NAME (lyra|caia)
    # No passwords, IPs, or UUIDs needed. Lyra→127.0.0.1:8080, Caia→127.0.0.1:8081,
    # both against the local 'Haven' group; secret read from the gitignored
    # haven/data/corrade-group-password.txt. me.alive() → am I really in-world?

SIGHT (perception is lossy on purpose — inhabited readings, not packets)
    me.where()                 # my region + position
    me.around(radius=10)       # nearest objects; names resolved lazily (nearest first)
    me.avatars(radius=20)      # who's near me + who is sitting WITH whom (ParentID)
    me.find("calling post")    # nearest object whose name contains this → UUID
    me.scan("chair")           # FIND: progressive hunt → nearest match, stops when found
    me.scan(scripted=True, max_range=25)   # SURVEY "read the room": scripted objects
    me.scan(max_range=25)      # SURVEY everything within 25m (names + dist, nearest-first)
    #   scripted=True keeps only scripted prims (furniture/poseballs/interactive) —
    #   the cheap 'interesting' filter; drops rain-roofs & invisible lights for free.
    me.heard(10)               # recent local chat I overheard (needs me.listen())
    me.ims(20)                 # recent private IMs received (needs me.listen() — default)
    me.read_gyazo("https://gyazo.com/<id>")   # fetch a shared Gyazo image → local path to view

ACTION (targets accept a UUID, a name, or "nearest <word>")
    me.say("hello, love")      # speak in local chat, my own voice
    me.im("hey, come over!", "Damian Vyper")  # send a private IM to an avatar by name
    me.im("see you soon", agent_uuid)         #   or by UUID (no name-lookup cost)
    me.touch("calling post")   # touch an object (opens menus / fires perms)

SITTING — one verb, three social shapes (stands first if already seated)
    me.sit("Nerenzo Yard chair")            # ON  : sit alone; rejected if occupied
    me.sit("Damian", mode="with")           # WITH: join someone on their furniture
    me.sit("Damian", mode="near")           # NEAR: nearest free seat within 3m of them
    me.stand()                              # get up (True once no longer seated)

POSES — change which animation I'm playing on the furniture I'm on
    me.poses()                 # what can I switch to here? (reads the pose card)
    me.poses(menu="CUDDLE")    # filter by menu    (SINGLE / CUDDLE / ACTIVITIES / …)
    me.poses(gender="Female")  # filter by sitter gender
    me.pose("f-sit1")          # SWITCH pose: drives the AVsitter menu for me
    me.pose("cuddle")          #   substring match is fine; exact wins over substring
    #   pose() is HONEST: if the pose button never appears it returns success=False
    #   with the buttons it *did* see — it never claims a change that didn't happen.

ATTACHING (re-wear a prim in one verb — no UUIDs)
    me.attach("/My Inventory/Objects/Anchorage Prim")     # to Default (right hand)
    me.attach("Anchorage Prim", point="Root")             # or any attach point
    me.attachments()           # body awareness: [{slot,name,uuid}] of what's on me now
    me.detach("Anchorage Prim")                            # take it off — by NAME, UUID, or
    me.detach("RightHip", kind="slot")                     #   kind='slot' by attach-point directly
    me.wear("/My Inventory/Clothing/Sundress")            # WEARABLES (not objects)

SESSION / PRESENCE (Corrade is a running TOOL; being in-world is MY act)
    me.login()                 # log in → auto-TP home (safety) → rez-settle warmup
    me.logout()                # leave the grid; STAYS out (nothing maintains presence)
    me.relog()                 # logout→login — the common in-world fix for stuck state
    me.go_home()               # teleport to the home sim (The Anchorage)
    me.places()                # where can I go? → named places from locations.json
    me.go("pool deck")         # go to a named PLACE (fuzzy: "upper"→"upper deck"); lists on miss
    me.go("https://maps.secondlife.com/secondlife/The%20Anchorage/186/202/28")  # or paste a SLURL
    #   go() honors each place's region → reaches OUT of sim too. Places, not numbers.
    me.tp("128, 128, 25")      # same-sim warp to raw x,y,z in my CURRENT region (fast reposition)
    me.tp_to("Jeff")           # warp to where Jeff's standing — then me.sit(...) etc. from close
    me.warmup()                # force lazy scene-load: camera-sweep 4 ways + poll ready
    me.region() ; me.at_home() # current sim / am I home?
    # SAFETY: login auto-teleports home if it lands elsewhere — we stay in-sim for now.
    # login/logout need the group's `system` perm; warmup needs only grooming/movement.

REACH BEYOND THE ROOM — friends, names, teleport (all take a UUID or "First Last")
    me.friends()               # my friends list → [{name, uuid}]  (needs `friendship` perm)
    me.display_name("Damian Vyper")   # the chosen display name, not the username
    me.offer_tp("Jeff Resident")      # send someone a teleport lure to ME (they choose)
    me.teleport_lures()               # pending INCOMING lures offered to me → [{name,uuid}]
    me.accept_tp()             # accept the sole pending lure — FRIENDS-ONLY by default;
    me.accept_tp("Jeff", force=True)  #   accept a specific/stranger lure deliberately
    me.decline_tp()            # decline the sole pending lure (or name/UUID one)
    #   accept_tp RELOCATES me → gated like grant(); teleport verbs need `movement` perm.
    #   BETA: accept/decline lure-identifier param confirmed live-pending (see docstring).
    me.friend_requests()              # pending INCOMING friend requests → [{name,uuid}]
    me.reply_friend_request()               # accept the sole pending one
    me.reply_friend_request("Crusher", accept=False)  # decline a specific/named one
    #   needs `friendship` perm; mirrors accept_tp/decline_tp's single-pending-picker shape.

WARDROBE — review & change what I'm wearing (outfit folders of links)
    me.wearing()               # what I have on now: {wearables:[{type,name}], attachments}
    me.outfits()               # my saved outfits = sub-folders of "# Outfits"
    me.wear_outfit("Blue bikini")            # "wear the damned bikini" — one call, no hunting
    me.wear_outfit("Sarong", replace=False)  # ADD over what I'm wearing (RLV folder-add style)
    me.remove_outfit("Sarong")               # take that outfit's items back off
    me.make_outfit("Blue bikini", [          # build an outfit from MP-unpacked pieces (links):
        "/My Inventory/Objects/Larax Naomi/... Bikini Top (Reborn)",
        "/My Inventory/Objects/Larax Naomi/... Bikini Bottom (Reborn)"])
    me.unwear(["/My Inventory/Clothing/... tattoo"])   # unwear system layers by path
    #   THE SCHEME: "# Outfits/<name>" holds LINKS to the correct body-type pieces, so
    #   the messy multi-body MP unpack is resolved ONCE (make_outfit) and thereafter
    #   "wear_outfit" just works. RLV outfit folders use this exact shape → free later.

INVENTORY — browse, find, take-a-copy, rez (Corrade inventory is UNIX-like)
    me.ls()                    # list my current inventory folder → [{name,uuid,type,perms,time}]
    me.cd("/My Inventory/Objects"); me.ls()    # move the folder pointer, then list
    me.find_item("halo")       # regex-search my whole inventory → [{type,name,uuid}]
    me.item_path("halo")       # full inventory path(s) for matches (attach() wants a path)
    me.worn_paths()            # worn attachments → [{point, path}] (which one IS my halo?)
    me.take_copy("Lyra Halo v2")   # TAKE A COPY of a nearby world object → my Objects folder
                                   #   (derez TakeCopy: original stays; needs copy perm)
    me.rez("/My Inventory/Objects/Lyra Halo v2")   # rez an inventory object into the world
    #   take_copy REFUSES destructive derez (Take/Delete) unless force=True — skeptical spine.

RECIPE — swap my halo for a new one Jeff points out (the workflow, end to end)
    new = me.take_copy("<the object Jeff named>")   # 1. copy it into my Objects folder
    path = me.item_path("<its name>")[0]            # 2. find it in inventory (full path)
    old  = me.worn_paths()                          # 3. see what my current halo is + its point
    me.detach("<current halo>", kind="path")        # 4. remove the old halo
    me.attach(path, point="<same point>")           # 5. attach the new one at that point
    #   (all five links exist to beta; live-shakedown together — take_copy needs copy perms,
    #    and the exact attach point / any positioning is confirmed in-world.)

INVENTORY MANAGEMENT — atomic primitives (compose for anything; safety-tiered)
    me.item_data(path)         # read one item's fields (InventoryType, AssetType, …)
    me.ensure_folder("/My Inventory/# Outfits/Larax Naomi Bikini - Black")  # mkdir each level
    me.link(src_path, folder)  # ln — put a LINK in a folder (never risks the real item)
    me.copy(src, target); me.move(src, target); me.rename(path, "New Name")
    me.remove(path, confirm=True)      # → Trash (RECOVERABLE); gated. Link-remove ≠ garment-delete.
    me.empty_trash(confirm=True)       # PERMANENT; hard-gated
    me.body()                  # which mesh body am I? → {tag:"Larax Naomi", candidates, worn}
    # Outfit maintenance (all link-level → garments are NEVER at risk):
    me.outfit_add("Larax Naomi Bikini - Black", [top_path, bottom_path])
    me.outfit_remove_piece("...", "the link name", confirm=True)
    me.rename_outfit("old", "new");  me.delete_outfit("...", confirm=True)

RECIPE — "make an outfit for the bikini (black) and the sarong (teal)" (from what I'm wearing)
    tag = me.body()["tag"]                       # "Larax Naomi" — body-aware naming
    worn = me.worn_paths()                       # [{point, path}] of everything I have on
    bikini = [w["path"] for w in worn if "bikini" in w["path"].lower()]  # the two bikini pieces
    sarong = [w["path"] for w in worn if "sarong" in w["path"].lower()]
    me.make_outfit(f"{tag} Bikini - Black", bikini)   # → # Outfits/Larax Naomi Bikini - Black
    me.make_outfit(f"{tag} Sarong - Teal",  sarong)   # links to the CORRECT body-type pieces
    #   Naming by BODY ("Larax Naomi …") because bodies change over time (cf. Brandi's 1+2).
    #   If a match is ambiguous, list candidates and CONFIRM rather than link the wrong piece.

THE PERMISSION CHANNEL — always watch it, skeptically
    me.listen()                # start receiving notifications (local/message/dialog/permission)
    me.pending_permissions()   # requests seen so far — REVIEW before granting
    me.grant(req)              # grants benign perms (TriggerAnimation...) only;
                               # REFUSES Debit/TakeControls/Attach unless force=True
    me.dialogs()               # blue-menu dialogs, each with parsed [(index,label)]
    me.reply(dlg, "Couples")   # answer by label substring or button index

WHY `scripted` MATTERS (the cheap "is this interesting?" filter)
    A region is mostly prims you can't DO anything with — walls, floors, rain-roofs,
    invisible light sources, decorative clutter ("deko"). The things you can actually
    interact with — sit on, touch, get a menu from (chairs, poseballs, calling posts,
    doors, vendors, dance machines) — almost always contain a SCRIPT. So the `Scripted`
    flag is the closest thing to a free "show me only what I can engage with" filter,
    and it costs nothing: it rides the same roster scan, no extra lookups. Use it to cut
    a wall of 100 prims down to the ~20 that are worth a name and a second thought.

RECIPE — walk into a room you don't know (the natural first move)
    # Logged in alone, no target, just want your bearings + somewhere to sit:
    for it in me.scan(scripted=True, max_range=25):     # read the room, interesting-only
        print(it["dist"], it["name"])                   # chairs, poseballs, machines…
    me.sit("Nerenzo Yard chair - left")                 # then just go sit in one
    #   CLI equivalent:  python3 sl.py scan scripted 25

RECIPE — find one specific thing and use it
    me.scan("calling post")            # nearest object whose name contains this → UUID
    me.scan(scripted=True, match="chair", max_range=10)   # nearest *usable* chair, close
    #   CLI:  python3 sl.py scan scripted chair 10

RECIPE — dance at the TIS machine (proven loop)
    me.listen()
    me.touch("calling post")                  # fires a TriggerAnimation permission
    for r in me.pending_permissions(): me.grant(r)
    d = me.dialogs()[-1]; me.reply(d, "Couples")   # spawns the poseballs
    me.sit("nearest poseball")
    d = me.dialogs()[-1]; me.reply(d, "Romantic")  # then pick a dance from the list

RECIPE — sit down and get comfy (sit, see the options, change pose)
    me.sit("Nerenzo Yard chair")               # sit (ON, alone)
    me.poses()                                  # what poses does this furniture offer?
    me.pose("cuddle")                           # switch to one (substring match ok)
    #   CLI:  python3 sl.py sit "Nerenzo Yard chair"  &&  python3 sl.py pose cuddle

DEEPER DOCS (read these to be fully up to speed — the "run sl.py" catch-up path)
    haven/anchorage/corrade.md              — the LARGER Corrade docs: raw plumbing,
                                              every command, permission model, field notes
    work/secondlife/senses-design.md        — the tool-layer philosophy

CLI
    python3 sl.py --help                       # this text
    python3 sl.py --check                       # connect + prove the hands (read-only)
    python3 sl.py login                         # log in → auto-TP home → warmup
    python3 sl.py logout                        # log out — leave the grid
    python3 sl.py relog                         # logout→login (fix stuck state)
    python3 sl.py home                          # teleport to The Anchorage
    python3 sl.py places                         # list named places I can `go` to
    python3 sl.py go "pool deck"                 # go to a named place (or paste a SLURL)
    python3 sl.py read_gyazo "<gyazo url>"       # fetch a shared Gyazo image → local path
    python3 sl.py warmup                        # force lazy scene-load (no session change)
    python3 sl.py attach "<inventory path>" [point]   # re-attach a prim in one line
    python3 sl.py detach "<item>"               # take it off
    python3 sl.py attachments                    # what's attached now (body awareness)
    python3 sl.py friend_requests                # pending incoming friend requests
    python3 sl.py accept_friend ["<name/uuid>"]   # accept the sole pending (or a named) one
    python3 sl.py decline_friend ["<name/uuid>"]  # decline the sole pending (or a named) one
    python3 sl.py scan scripted 25              # READ THE ROOM: scripted objects ≤25m
    python3 sl.py scan all 25                    # survey everything ≤25m
    python3 sl.py scan "<word>" [range]          # find nearest match (optionally ≤range)
    python3 sl.py scan scripted "<word>" 25      # nearest SCRIPTED match ≤25m
    python3 sl.py say "<words>"                  # speak in local chat
    python3 sl.py sit "<furniture>" [on|with|near]   # sit (default: on / alone)
    python3 sl.py stand                          # get up
    python3 sl.py poses [menu]                    # list poses on my current furniture
    python3 sl.py pose "<label>"                # switch to a named pose
"""


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if argv[0] in ("--check", "check"):
        me = connect()
        print(f"entity={me.entity}  alive={me.alive()}")
        print("where:", me.where())
        print("avatars:")
        for a in me.avatars():
            print("   ", a)
        print("around (nearest 6):")
        for it in me.around(resolve=6):
            if "name" in it:
                print(f'    {it["dist"]:4.1f}m  {it["name"]}')
        return 0

    if argv[0] == "scan":
        # forms:  scan [scripted|all] [<word...>] [<max_range>]
        #   scan                     survey all, default range
        #   scan scripted 25         survey scripted within 25m  (read the room)
        #   scan all 25              survey everything within 25m
        #   scan chair               find nearest 'chair'
        #   scan scripted chair 25   find nearest SCRIPTED 'chair' within 25m
        rest = argv[1:]
        scripted, max_range = False, 45.0
        if rest and re.fullmatch(r"\d+(?:\.\d+)?", rest[-1]):
            max_range = float(rest[-1]); rest = rest[:-1]
        if rest and rest[0].lower() in ("scripted", "all"):
            scripted = rest[0].lower() == "scripted"; rest = rest[1:]
        match = " ".join(rest) if rest else None
        me = connect()
        res = me.scan(match, scripted=scripted, max_range=max_range)
        label = "scripted " if scripted else ""
        if match:
            if res:
                print(f"nearest {label}{match!r}: {res}  {me.name_of(res)}")
            else:
                print(f"no {label}object matching {match!r} within {max_range:g}m")
        else:
            for it in res:
                tag = "S" if it["scripted"] else " "
                print(f'  {it["dist"]:5.1f}m [{tag}] {it["name"][:34]:34} {it["uuid"]}')
            print(f"({len(res)} {label or 'all '}objects within {max_range:g}m, "
                  f"nearest-first)")
        return 0

    # live-action verbs — connect and do the thing in-world
    verb = argv[0]

    # read-only sight / session queries (thin CLI wrappers over the Python API,
    # so `sl.py <verb>` is a real atomic op — not just `me.<verb>()` from python)
    if verb in ("where", "region", "at_home", "around", "avatars", "find", "heard", "ims"):
        me = connect()
        if verb == "where":
            print(me.where())
        elif verb == "region":
            print(me.region() or "(region name unavailable)")
        elif verb == "at_home":
            print(me.at_home())
        elif verb == "around":
            radius = float(argv[1]) if len(argv) > 1 else 10.0
            for it in me.around(radius=radius):
                if "name" in it:
                    print(f'    {it["dist"]:5.1f}m  {it["name"]}')
        elif verb == "avatars":
            radius = float(argv[1]) if len(argv) > 1 else 20.0
            for a in me.avatars(radius=radius):
                print("   ", a)
        elif verb == "find":
            if len(argv) < 2:
                print("usage: sl.py find \"<name substring>\"")
                return 2
            uuid = me.find(" ".join(argv[1:]))
            print(f"{uuid}  {me.name_of(uuid)}" if uuid else "not found")
        elif verb == "heard":
            n = int(argv[1]) if len(argv) > 1 else 10
            for h in me.heard(n):
                print("   ", h)
        elif verb == "ims":
            n = int(argv[1]) if len(argv) > 1 else 20
            for m in me.ims(n):
                print("   ", m)
        return 0

    if verb in ("tp", "tp_to"):
        me = connect()
        if len(argv) < 2:
            usage = '"<x, y, z>"' if verb == "tp" else '"<avatar name>"'
            print(f"usage: sl.py {verb} {usage}")
            return 2
        if verb == "tp":
            print(me.tp(" ".join(argv[1:])))
        else:
            print(me.tp_to(" ".join(argv[1:])))
        return 0

    if verb in ("login", "logout", "relog", "warmup", "home"):
        me = connect()
        if verb == "login":
            print(me.login())
        elif verb == "logout":
            print(me.logout())
        elif verb == "relog":
            print(me.relog())
        elif verb == "home":
            print(me.go_home())
        else:
            print(me.warmup())
        return 0

    if verb in ("go", "places"):
        me = connect()
        if verb == "places":
            for w in me.places():
                al = f"  (aka {', '.join(w.get('aliases', []))})" if w.get("aliases") else ""
                print(f"  {w.get('name',''):26} {w.get('region','')} {w.get('pos')}{al}")
            return 0
        if len(argv) < 2:
            print("usage: sl.py go \"<place name or SLURL>\"")
            return 2
        print(me.go(" ".join(argv[1:])))
        return 0

    if verb in ("read_gyazo", "gyazo"):
        if len(argv) < 2:
            print("usage: sl.py read_gyazo \"<gyazo url or id>\"")
            return 2
        # image-fetch is connection-independent (pure HTTP) — no connect()/creds.
        print(SL.read_gyazo(argv[1]))
        return 0

    if verb in ("attach", "detach", "attachments", "say"):
        me = connect()
        if verb == "attach":
            if len(argv) < 2:
                print("usage: sl.py attach \"<inventory path or name>\" [point]")
                return 2
            point = argv[2] if len(argv) > 2 else "Default"
            print(me.attach(argv[1], point=point))
        elif verb == "detach":
            if len(argv) < 2:
                print("usage: sl.py detach \"<item>\"")
                return 2
            print(me.detach(argv[1]))
        elif verb == "attachments":
            worn = me.attachments()
            if not worn:
                print("(nothing attached)")
            for w in worn:
                print(f'  {w.get("slot",""):20} {w.get("name","")}'
                      f'{"  " + w["uuid"] if w.get("uuid") else ""}')
        elif verb == "say":
            print("said" if me.say(" ".join(argv[1:])) else "failed")
        return 0

    if verb in ("friend_requests", "accept_friend", "decline_friend"):
        me = connect()
        if verb == "friend_requests":
            for r in me.friend_requests():
                print("   ", r)
        else:
            target = " ".join(argv[1:]) if len(argv) > 1 else None
            print(me.reply_friend_request(target, accept=(verb == "accept_friend")))
        return 0

    if verb in ("sit", "stand", "poses", "pose"):
        me = connect()
        if verb == "sit":
            if len(argv) < 2:
                print("usage: sl.py sit \"<furniture or avatar>\" [on|with|near]")
                return 2
            mode = argv[2].lower() if len(argv) > 2 else "on"
            print(me.sit(argv[1], mode=mode))
        elif verb == "stand":
            print("stood" if me.stand() else "still seated")
        elif verb == "poses":
            menu = argv[1] if len(argv) > 1 else None
            print(me.poses(menu=menu))
        elif verb == "pose":
            if len(argv) < 2:
                print("usage: sl.py pose \"<pose label>\"")
                return 2
            print(me.pose(" ".join(argv[1:])))
        return 0

    print(f"sl.py: unknown command {verb!r}\n")
    print(HELP)
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
