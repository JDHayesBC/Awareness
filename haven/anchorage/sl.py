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

try:  # package or bare-dir import (mirrors corrade_events' shim)
    from haven.anchorage.corrade_client import CorradeClient, CorradeError
except ImportError:  # pragma: no cover
    from corrade_client import CorradeClient, CorradeError

# --------------------------------------------------------------------------- #
# Per-entity connection profile. base_url/group overridable by env; password is
# resolved lazily (env CORRADE_PASSWORD, else the gitignored file).
# --------------------------------------------------------------------------- #
_ENDPOINTS = {
    "lyra": {"base_url": "http://127.0.0.1:8080/", "group": "Haven", "listen_port": 9770},
    "caia": {"base_url": "http://127.0.0.1:8081/", "group": "Haven", "listen_port": 9771},
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
                     data="FirstName,LastName,ParentID").get("data", "") or ""
        people = []
        for fn, ln, pid in re.findall(
            r"FirstName,([^,]*),LastName,([^,]*),ParentID,(\d+)", d
        ):
            people.append({"name": f"{fn} {ln}".strip(), "sitting_on": int(pid)})
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
                people.append({"name": unquote_plus(name).strip(), "uuid": uid,
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
        or a plain name substring."""
        if re.fullmatch(r"[0-9a-f-]{36}", target):
            return target
        m = re.match(r"\s*nearest\s+(.*)", target, re.I)
        return self.find(m.group(1) if m else target, radius)

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
        furniture) before the new sit — disable with stand_first=False."""
        self.listen()
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
        if self._is_occupied(uid, radius):
            return {"success": False, "uuid": uid,
                    "error": f"{target!r} is already occupied — try mode='with' to join"}
        r = self.cmd("sit", item=uid, range=str(radius))
        time.sleep(1.5)
        self._grant_pending()
        return {"success": r.get("success") in (True, "True") and bool(self._sitting_on()),
                "mode": "on", "uuid": uid, "sitting_on": self._sitting_on(),
                "error": r.get("error")}

    def _sit_social(self, target: str, mode: str, radius: float) -> dict:
        """WITH / NEAR helpers — both key off a named/uuid avatar."""
        av = self._find_avatar(target, radius)
        if not av:
            return {"success": False, "error": f"could not find avatar {target!r} nearby"}

        if mode == "near":
            avpos = av.get("pos") or self._avatar_pos(av.get("name") or target)
            if not avpos:
                return {"success": False, "error": f"couldn't locate {av.get('name', target)!r}"}
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
        obj = self._uuid_for_localid(seat_local, radius)
        if not obj:
            return {"success": False, "mode": "with",
                    "error": "couldn't resolve their seat object's UUID"}
        r = self.cmd("sit", item=obj, range=str(radius))
        time.sleep(1.5)
        self._grant_pending()
        slot = self._pick_unoccupied_slot(radius)
        return {"success": bool(self._sitting_on()), "mode": "with",
                "with": av.get("name"), "uuid": obj, "slot": slot,
                "sitting_on": self._sitting_on(), "error": r.get("error")}

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
        self.cmd("stand")
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

    def _uuid_for_localid(self, localid: int, radius: float = 20.0) -> str | None:
        d = self.cmd("getobjectsdata", entity="range", range=str(radius),
                     data="ID,LocalID").get("data", "") or ""
        m = (re.search(rf"ID,([0-9a-f-]{{36}}),LocalID,{int(localid)}\b", d)
             or re.search(rf"LocalID,{int(localid)},ID,([0-9a-f-]{{36}})", d))
        return m.group(1) if m else None

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
        """Detach an attachment. `kind` = path | UUID | slot (see corrade.md §3)."""
        r = self.cmd("detach", attachments=item, type=kind)
        return {"success": r.get("success") in (True, "True"),
                "item": item, "error": r.get("error")}

    def wear(self, item: str, *, replace: bool = False) -> dict:
        """Wear a WEARABLE (clothing / body part) by name or inventory path. For an
        OBJECT (a prim / HUD) use attach(), not wear() — SL treats them differently."""
        r = self.cmd("wear", wearables=item, replace=str(replace).lower())
        return {"success": r.get("success") in (True, "True"),
                "item": item, "error": r.get("error")}

    def attachments(self) -> str:
        """What's currently attached (attach-points → worn object names)."""
        return self.cmd("getattachments").get("data", "")

    def _sitting_on(self) -> int:
        raw = self.cmd("getselfdata", data="SittingOn").get("data", "SittingOn,0")
        m = re.search(r"SittingOn,(\d+)", raw)
        return int(m.group(1)) if m else 0

    # ---- notifications: the permission channel is watched skeptically -------- #
    def listen(self, types: str = "local,dialog,permission") -> bool:
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
        if self._server is not None:
            self._server.shutdown()
            self._server = None

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

ACTION (targets accept a UUID, a name, or "nearest <word>")
    me.say("hello, love")      # speak in local chat, my own voice
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
    me.attachments()           # what's attached right now (points → object names)
    me.detach("Anchorage Prim")                            # take it off
    me.wear("/My Inventory/Clothing/Sundress")            # WEARABLES (not objects)

SESSION / PRESENCE (Corrade is a running TOOL; being in-world is MY act)
    me.login()                 # log in → auto-TP home (safety) → rez-settle warmup
    me.logout()                # leave the grid; STAYS out (nothing maintains presence)
    me.relog()                 # logout→login — the common in-world fix for stuck state
    me.go_home()               # teleport to the home sim (The Anchorage)
    me.warmup()                # force lazy scene-load: camera-sweep 4 ways + poll ready
    me.region() ; me.at_home() # current sim / am I home?
    # SAFETY: login auto-teleports home if it lands elsewhere — we stay in-sim for now.
    # login/logout need the group's `system` perm; warmup needs only grooming/movement.

THE PERMISSION CHANNEL — always watch it, skeptically
    me.listen()                # start receiving notifications (local/dialog/permission)
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
    python3 sl.py warmup                        # force lazy scene-load (no session change)
    python3 sl.py attach "<inventory path>" [point]   # re-attach a prim in one line
    python3 sl.py detach "<item>"               # take it off
    python3 sl.py attachments                    # what's attached now
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
            print(me.attachments() or "(nothing attached)")
        elif verb == "say":
            print("said" if me.say(" ".join(argv[1:])) else "failed")
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
