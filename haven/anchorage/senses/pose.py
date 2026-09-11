"""PoseSense — know what pose I'm in, and what pose others are in.

The observing half of the **pose sense** (``pose_cache.py`` resolves + remembers).
Lyra's counterpart to Caia's ``music.py``, and built to the same two-decoupled-halves
discipline so it's buildable + testable NOW without a live region:

  1. **roster poller** (this file) — one ``getavatarsdata`` read gives every in-range
     avatar's ``FirstName/LastName/ID/ParentID/Position``. Self is in that list too, so
     one call senses everyone. Position is *furniture-local* and comes back
     **configured-exact** — matched against an AVpos card it yields the exact pose label.
  2. **library resolution** — delegated to ``pose_cache.recognize`` (pure, no network):
     ``uuid -> label`` (self-anim path) or ``position -> label`` (geometry, bimodal).

Unlike music, a pose is **agent-attributed** — every roster entry carries a *subject*.
The SL dependency is injected as two callables so the class is unit-testable with fakes:

  * ``avatars_provider() -> list[dict]``      — raw avatars: ``{name, uuid, parent_localid,
                                                position, self, uuid_anim?}``
  * ``furniture_resolver(localid) -> key|None`` — seat LocalID → furniture-key (which card)

Sense-record shape (shared)::

    {"source": "anchorage-pose", "ts": <epoch>, "kind": "pose",
     "payload": {"roster": [ {subject, subject_uuid, self, seated, furniture_key,
                              position, source, label, menu, ...}, ... ]}}

CLI::

    # one resolved roster right now (needs Corrade up)
    ENTITY_NAME=lyra python3 -m haven.anchorage.senses.pose --once
    # standing watch: write haven/data/anchorage-pose.json on any change
    ENTITY_NAME=lyra python3 -m haven.anchorage.senses.pose --watch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:  # pragma: no cover - import shim (package vs. flat sys.path)
    from haven.anchorage.senses import sense_record
    from haven.anchorage.senses.pose_cache import recognize, append_posed, load_furniture
except ImportError:  # pragma: no cover
    from . import sense_record  # type: ignore[no-redef]
    from pose_cache import recognize, append_posed, load_furniture  # type: ignore[no-redef]


SOURCE = "anchorage-pose"
KIND = "pose"

DEFAULT_SENSE_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "anchorage-pose.json"
)


# --------------------------------------------------------------------------- #
# Vector / name parsing (shared with the Corrade seam)
# --------------------------------------------------------------------------- #
def parse_vec(s: str) -> Optional[list[float]]:
    """``"<-0.049,+0.337,+0.412>"`` → ``[-0.049, 0.337, 0.412]`` (or ``None``)."""
    if not s:
        return None
    s = s.strip().strip('"').strip("<>").replace("+", "")
    try:
        parts = [float(x) for x in s.split(",")]
    except ValueError:
        return None
    return parts if len(parts) == 3 else None


# Seat/rez suffixes that vary per instance but not per pose-set — stripped so
# "Nerenzo Yard chair - left" / "- middle" / "- right (Adult)" all key to one card.
_FURN_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*(left|right|middle|centre|center|front|back|seat|adult|pg|mature|copy|\d+)\b.*$",
    re.IGNORECASE)


def furniture_key_from_name(name: str) -> str:
    """Object name → a stable furniture-key slug (drops known seat/instance suffixes)."""
    n = _FURN_SUFFIX_RE.sub("", name or "").strip()
    n = re.sub(r"[^A-Za-z0-9]+", "-", n).strip("-").lower()
    return n or "unknown"


def _candidate_keys(name: str) -> list[str]:
    """Ordered furniture-key candidates for a raw object name: the suffix-stripped key
    first, then the full slug, then progressively shorter dash-trims. Lets the resolver
    match a card even when the seat word isn't in the known-suffix list — by trying the
    real card names rather than guessing which words are seat-labels."""
    full = re.sub(r"[^A-Za-z0-9]+", "-", (name or "")).strip("-").lower()
    cands = [furniture_key_from_name(name), full]
    parts = full.split("-")
    for cut in range(len(parts) - 1, 1, -1):   # drop trailing segments one at a time
        cands.append("-".join(parts[:cut]))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out


# --------------------------------------------------------------------------- #
# The sense
# --------------------------------------------------------------------------- #
class PoseSense:
    def __init__(
        self,
        avatars_provider: Callable[[], list[dict]],
        furniture_resolver: Optional[Callable[[int], Optional[str]]] = None,
        entity: str = "lyra",
    ) -> None:
        self.avatars_provider = avatars_provider
        self.furniture_resolver = furniture_resolver
        self.entity = entity

    def poll(self) -> list[dict]:
        """Raw roster (no library resolution, no logging) — one entry per in-range avatar."""
        raw = self.avatars_provider() or []
        roster: list[dict] = []
        for a in raw:
            parent = a.get("parent_localid") or 0
            seated = bool(parent)
            fkey = None
            if seated and self.furniture_resolver:
                try:
                    fkey = self.furniture_resolver(int(parent))
                except Exception:
                    fkey = None
            roster.append({
                "subject": a.get("name"),
                "subject_uuid": a.get("uuid"),
                "self": bool(a.get("self")),
                "seated": seated,
                "parent_localid": parent or None,
                "furniture_key": fkey,
                "position": a.get("position"),
                "uuid": a.get("uuid_anim"),   # optional exact self-anim UUID
            })
        return roster

    def resolve(self, roster: list[dict], *, cache_dir=None, log_it: bool = False) -> list[dict]:
        """Resolve every raw roster entry against the reference library (bimodal)."""
        return [recognize(dict(e), self.entity, cache_dir=cache_dir, log_it=log_it)
                for e in roster]

    def poll_record(self, *, cache_dir=None) -> dict[str, Any]:
        """Poll + resolve (no logging) and wrap as a shared sense-record."""
        resolved = self.resolve(self.poll(), cache_dir=cache_dir, log_it=False)
        return sense_record(SOURCE, KIND, {"roster": resolved})


# --------------------------------------------------------------------------- #
# Change key + standing watch — the Tier-1 feed
# --------------------------------------------------------------------------- #
def pose_key(entry: dict) -> tuple:
    """What counts as a *change* for one subject: their identity + resolved pose."""
    return (entry.get("subject_uuid"), entry.get("source"),
            entry.get("label"), entry.get("furniture_key"))


# --------------------------------------------------------------------------- #
# Co-sitter awareness (issue #303) — "someone sat WITH me" as a decision point.
#
# pose_key is deliberately seat-blind (it omits parent_localid), so a co-sitter
# joining my seat scores identically to anyone shifting pose across the parcel:
# it enriches the scene but never wakes me. This is the "attention degrades even
# though someone just sat down beside me" gap Brandi/Jeff flagged live. These two
# helpers add the missing signal WITHOUT disturbing the pose enrich that rides the
# same poll: a pure roster read (who shares my seat root), and a tiny state machine
# that fires a WAKE only on the boolean EDGE of "am I sharing my seat".
#
# Precondition (VERIFIED live on The Anchorage 2026-09-10, not assumed): co-sitters
# on one piece of furniture share the SAME seat-root parent_localid — Lyra + Snickers
# both read parent_localid 7944 on the pool float; Crusher + Brandi both 7950. Single-
# linkset furniture (one root, several sit-targets) is what makes the shared-ParentID
# key correct here.
# --------------------------------------------------------------------------- #
def cositters_on_my_seat(roster: list[dict]) -> tuple[Optional[int], list[str], list[str]]:
    """From a resolved roster, find MY seat's ``parent_localid`` and who else shares it.

    Returns ``(my_seat, cositter_names, cositter_uuids)``:
      * ``my_seat`` is my seat-root LocalID, or ``None`` when I'm not seated (standing,
        or my ``self`` entry isn't in range) — in which case both lists are empty.
      * co-sitters = every OTHER in-range avatar sharing my exact ``parent_localid``.

    Pure: no network, no clock, no mutation of the roster. Names are the SL display
    ``subject`` only — never an identity key, never cross-referenced (the identity wall
    is a disclosure law; this only ever surfaces the public in-world name)."""
    me = next((e for e in roster if e.get("self")), None)
    if not me:
        return None, [], []
    my_seat = me.get("parent_localid")
    if not my_seat:
        return None, [], []              # standing / not seated
    names: list[str] = []
    uuids: list[str] = []
    for e in roster:
        if e.get("self"):
            continue
        if e.get("parent_localid") == my_seat:
            names.append(e.get("subject") or "someone")
            uuids.append(e.get("subject_uuid") or "")
    return my_seat, names, uuids


@dataclass
class CoSitterResult:
    """One poll's co-sitter outcome (see :class:`CoSitterEdge`)."""
    wake: Optional[dict] = None                       # boolean-edge WAKE payload, or None
    new_joiner_uuids: list[str] = field(default_factory=list)  # engage these (decoupled from wake)


class CoSitterEdge:
    """Track the boolean edge of *"am I sharing my seat?"* across polls (issue #303).

    Two decoupled outputs per :meth:`update`, because they are two different mechanisms
    (this decoupling is Caia's reverse-check refinement — see design notes):

    * **WAKE** — fires ONLY when the boolean flips, so it is storm-proof:
        - ``false→true``  someone joined my solitude   (the Snix-sat-with-solo-Lyra bug)
        - ``true→false``  my last co-sitter left, I'm alone again (a re-pose/stand decision)
      Churn *within* an already-occupied seat (1→2, 2→1, who-swaps) does NOT wake — the
      pose enrich on the same poll already carries "who's beside me in what pose". A
      five-person cuddle-pile therefore costs at most one wake (first join) + one (last
      leave), never a wake/refract stutter.
    * **new_joiner_uuids** — every avatar newly sharing my seat THIS poll (and, when I
      myself just sat onto an occupied seat, everyone already there). Decoupled from the
      wake so that a *late* arrival to a pile still gets their un-named lines promoted —
      not just the first joiner. Engagement injects no arousal and never fires; a window
      only promotes real speech, so N windows = "responsive to who's with me", not a storm.

    Baseline discipline (Caia's Hole B, load-bearing): the baseline is keyed to MY CURRENT
    SEAT. Whenever my own ``parent_localid`` changes — I stand (→ ``None``) or move to a new
    seat — the baseline re-arms SILENTLY (no wake), so sitting down beside someone, or
    standing up, never fires "everyone just joined/left". A daemon restart while someone
    sits with me is the same silent first-observation → no false wake on boot.

    Known edge (flagged, tolerated in v1): a SOLE co-sitter who stands and re-sits across a
    poll boundary (>15s apart) double-ticks — true→false "alone again", then false→true
    "joined". The 15s level-sampling absorbs any faster re-seat. Live-tunable via s_cositter
    if it ever gets chatty; arguably even correct (they left, they came back)."""

    def __init__(self) -> None:
        self.seat: Optional[int] = None
        self.sharing: Optional[bool] = None          # None = unarmed (no baseline yet)
        self.prev_names: set[str] = set()
        self.prev_uuids: set[str] = set()

    def update(self, my_seat: Optional[int], co_names: list[str],
               co_uuids: list[str]) -> CoSitterResult:
        res = CoSitterResult()
        cur_uuids = {u for u in co_uuids if u}
        sharing_now = (my_seat is not None) and bool(co_names)

        # Re-arm silently on any change of MY seat (sat / moved / stood), or first obs.
        if my_seat != self.seat or self.sharing is None:
            if my_seat is not None:
                # I just sat onto this seat — I'm attentive to anyone already here.
                res.new_joiner_uuids = [u for u in co_uuids if u]
            self.seat = my_seat
            self.sharing = sharing_now
            self.prev_names = set(co_names)
            self.prev_uuids = cur_uuids
            return res

        # Same seat as last poll — engagement for anyone NEWLY sharing it (decoupled),
        res.new_joiner_uuids = [u for u in co_uuids if u and u not in self.prev_uuids]

        # and a WAKE only on the boolean edge.
        if sharing_now and not self.sharing:
            res.wake = {"joined": list(co_names), "joined_uuids": list(co_uuids)}
        elif self.sharing and not sharing_now:
            res.wake = {"left": sorted(self.prev_names), "now_alone": True}

        self.sharing = sharing_now
        self.prev_names = set(co_names)
        self.prev_uuids = cur_uuids
        return res


def watch(
    sense: PoseSense,
    sense_file: Path = DEFAULT_SENSE_FILE,
    interval: float = 15.0,
    verbose: bool = True,
    cache_dir=None,
) -> None:
    """Poll on a loop; on any subject's pose *change*, append the posed-log and rewrite
    the standing roster sense-file (atomically)."""
    sense_file.parent.mkdir(parents=True, exist_ok=True)
    last: dict[str, tuple] = {}
    while True:
        try:
            resolved = sense.resolve(sense.poll(), cache_dir=cache_dir, log_it=False)
            changed = []
            for e in resolved:
                sid = e.get("subject_uuid") or e.get("subject")
                k = pose_key(e)
                if last.get(sid) != k:
                    last[sid] = k
                    changed.append(e)
                    # Log ONLY the change (mirrors heard-log firing on change).
                    if e.get("source") not in (None, "none"):
                        try:
                            append_posed(sense.entity, {
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "subject": e.get("subject"), "subject_uuid": e.get("subject_uuid"),
                                "self": e.get("self", False), "source": e.get("source"),
                                "label": e.get("label"), "menu": e.get("menu"),
                                "furniture_key": e.get("furniture_key"),
                                "uuid": e.get("anim_uuid") or e.get("uuid"),
                            }, cache_dir)
                        except Exception:
                            pass
            record = sense_record(SOURCE, KIND, {"roster": resolved})
            _write_atomic(sense_file, record)
            if verbose and changed:
                for e in changed:
                    _print_change(e)
        except Exception as exc:  # a poll hiccup must never kill the watch
            if verbose:
                print(f"[pose] poll error (non-fatal): {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


def _print_change(e: dict) -> None:
    who = ("me" if e.get("self") else e.get("subject")) or "?"
    src = e.get("source")
    if src in ("geometry-exact", "self-anim") and e.get("label"):
        desc = f"{e.get('label')} ({e.get('menu')})"
    elif src == "blind-freeform":
        desc = "freeform / off-card"
    elif src == "parent-only":
        desc = "seated (no card)"
    else:
        desc = "not posed"
    print(f"[{time.strftime('%H:%M:%S')}] ▷ {who}: {desc}", flush=True)


def _write_atomic(path: Path, record: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Corrade seam — build the two providers from a live CorradeClient
# --------------------------------------------------------------------------- #
def _resolve_key_against_cards(name: str, cache_dir=None) -> Optional[str]:
    """Object name → the furniture-key whose card actually exists, trying candidate keys
    (suffix-stripped, full, progressive dash-trims) in order. Returns the first candidate
    with a card on disk, else the suffix-stripped key (so an uncarded seat degrades to a
    stable-but-cardless key → parent-only, never a wrong match)."""
    cands = _candidate_keys(name)
    for k in cands:
        if load_furniture(k, cache_dir) is not None:
            return k
    return cands[0] if cands else None


def corrade_providers(client, self_uuid: str | None = None, self_name: str | None = None,
                      cache_dir=None):
    """Return ``(avatars_provider, furniture_resolver)`` bound to a CorradeClient.

    ``avatars_provider`` issues one ``getavatarsdata entity=range`` read and parses the
    flat CSV into raw avatar dicts. ``furniture_resolver`` maps a seat LocalID to a
    furniture-key by resolving the object's name (cached per seat for the session) and
    matching it against the actual card library, so unknown seat suffixes still resolve.
    """
    seat_cache: dict[int, Optional[str]] = {}

    def avatars_provider() -> list[dict]:
        r = client.command(command="getavatarsdata", group=client.group, entity="range",
                            range="20", data="FirstName,LastName,ID,ParentID,Position")
        out: list[dict] = []
        for chunk in re.split(r"(?=FirstName,)", r.get("data", "")):
            if not chunk.strip():
                continue
            fn = re.search(r"FirstName,([^,]+)", chunk)
            ln = re.search(r"LastName,([^,]+)", chunk)
            uid = re.search(r"ID,([0-9a-fA-F-]{36})", chunk)
            pid = re.search(r"ParentID,([0-9]+)", chunk)
            pm = re.search(r'Position,"([^"]+)"', chunk)
            if not fn:
                continue
            name = f"{fn.group(1)} {ln.group(1)}" if ln else fn.group(1)
            uuid = uid.group(1) if uid else None
            out.append({
                "name": name, "uuid": uuid,
                "parent_localid": int(pid.group(1)) if pid else 0,
                "position": parse_vec(pm.group(1)) if pm else None,
                "self": bool(self_uuid and uuid == self_uuid)
                        or bool(self_name and name == self_name),
            })
        return out

    def furniture_resolver(localid: int) -> Optional[str]:
        if localid in seat_cache:
            return seat_cache[localid]
        key = None
        try:
            # LocalID → object UUID (fast ObjectUpdate cache), then UUID → Name.
            r = client.command(command="getobjectsdata", group=client.group,
                               entity="range", range="20", data="Name,LocalID,ID")
            uuid = None
            for chunk in re.split(r"(?=(?:Name|ID|LocalID),)", r.get("data", "")):
                pass  # fall through to a direct LocalID→ID scan below
            m = re.search(rf"LocalID,{localid},ID,([0-9a-fA-F-]{{36}})", r.get("data", "")) \
                or re.search(rf"ID,([0-9a-fA-F-]{{36}}),LocalID,{localid}\b", r.get("data", ""))
            if m:
                uuid = m.group(1)
            if uuid:
                pr = client.command(command="getprimitivepropertiesdata", group=client.group,
                                    item=uuid, data="Name")
                nm = re.search(r"Name,(.+?)(?:,[A-Z][a-zA-Z]*,|$)", pr.get("data", ""))
                if nm:
                    key = _resolve_key_against_cards(nm.group(1).replace("+", " "), cache_dir)
        except Exception:
            key = None
        seat_cache[localid] = key
        return key

    return avatars_provider, furniture_resolver


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_live_sense(entity: str):
    """Wire a PoseSense to the live Corrade client (imports the SL layer lazily)."""
    from haven.anchorage import sl as sl_mod
    client = sl_mod.connect(entity)._client
    self_uuid = self_name = None
    try:
        r = client.command(command="getselfdata", group=client.group,
                           data="FirstName,LastName")
        d = r.get("data", "")
        fn = re.search(r"FirstName,([^,]+)", d)
        ln = re.search(r"LastName,([^,]+)", d)
        if fn:
            self_name = f"{fn.group(1)} {ln.group(1)}" if ln else fn.group(1)
    except Exception:
        pass
    ap, fr = corrade_providers(client, self_uuid=self_uuid, self_name=self_name)
    return PoseSense(ap, fr, entity=entity)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Anchorage pose sense (self + others)")
    ap.add_argument("--once", action="store_true", help="print one resolved roster and exit")
    ap.add_argument("--watch", action="store_true", help="poll on a loop, write sense-file on change")
    ap.add_argument("--interval", type=float, default=15.0, help="watch poll interval (sec)")
    ap.add_argument("--sense-file", type=Path, default=DEFAULT_SENSE_FILE)
    ap.add_argument("--entity", default=os.getenv("ENTITY_NAME", "lyra"))
    args = ap.parse_args(argv)

    sense = _build_live_sense(args.entity)

    if args.watch:
        try:
            watch(sense, sense_file=args.sense_file, interval=args.interval)
        except KeyboardInterrupt:
            print("\nstopped.", file=sys.stderr)
        return 0

    record = sense.poll_record()
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
