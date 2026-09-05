#!/usr/bin/env python3
"""sl_bus.py — a persistent terminal command-bus for driving an SL avatar by hand.

WHY THIS EXISTS
---------------
``sl.py`` is the verb *library* (connect / listen / say / sit / around / ...). But
driving it straight from the shell means every command is its own ephemeral
process, and sl.py's ``listen()`` HTTP server dies with each one — so you can
*speak* but never reliably *hear* (Corrade POSTs its notifications to a listener
port that's already gone the instant the process exits). That's the "she can't
hear us" failure.

``sl_bus`` fixes it with ONE long-lived ``serve`` process that:
  * holds ``listen()`` open for the whole session, so inbound local-chat / IMs
    actually land;
  * executes verbs handed to it over a tiny per-entity file queue;
  * logs everything it hears to a jsonl you can tail (Monitor auto-wake).

The thin ``client`` subcommands (``sl_bus.py say "hi"``) just append a command and
print the result — they never touch SL, so there's no second listener to fight
over the port.

RELATION TO THE DAEMON
----------------------
``sl_bus`` is a well-behaved *sibling* of ``sl_daemon.py`` (both talk to Corrade;
only the daemon has a brain). While ``serve`` runs it temporarily steals the
group's Corrade notify subscription (``listen()`` → ``notify set``). On exit it
calls ``stop_listening()`` to hand the subscription straight back — and the daemon
*also* self-heals by periodic re-subscribe (see sl_daemon.py:222,1254). So the two
can coexist: the daemon just goes briefly deaf while you drive. **You do NOT have
to kill the daemon first.**

PRIMARY USE: DIAGNOSTICS
------------------------
When ``me.sit(...)`` (or a pose change, or a teleport) misbehaves, drive the steps
by hand here, find what actually works, then fix ``sl.py`` from what you learned.
The SL channel should never struggle with basics like sitting or changing poses.

USAGE
-----
    ENTITY_NAME=lyra python3 sl_bus.py serve &      # start the session (once)

    python3 sl_bus.py say  "hello there"            # speak in local chat
    python3 sl_bus.py im   "Brandi Starship" "hi"   # IM someone (target, then text)
    python3 sl_bus.py find "chair"                  # ACTIVE name→uuid resolution
    python3 sl_bus.py sit  "<uuid or name>" on      # sit (mode: on|with|near)
    python3 sl_bus.py stand
    python3 sl_bus.py around 20                       # nearby objects w/ uuid+dist
    python3 sl_bus.py avatars 60                      # nearby avatars
    python3 sl_bus.py where                           # my region + position
    python3 sl_bus.py tp 170 207 29                   # teleport to local coords
    python3 sl_bus.py touch "<uuid or name>"         # touch an object
    python3 sl_bus.py dance "<uuid or name>"         # sit onto a dance ball, etc.

    python3 sl_bus.py heard 20                         # last 20 things I heard
    python3 sl_bus.py status                           # serve up? daemon up? ports
    python3 sl_bus.py stop                             # clean shutdown (restores daemon)

Any verb not explicitly listed is passed straight through to the matching method on
the ``sl.py`` SL object (best-effort int/float arg coercion) — so new sl.py verbs
are reachable here for diagnostics without editing this file.

ENTITY-AWARE
------------
``ENTITY_NAME`` (lyra|caia, default lyra) selects the avatar AND the runtime
directory, so Lyra and Caia never collide:

    ~/.claude/data/sl_bus/<entity>/{cmd,result,heard}.jsonl + serve.pid
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

# Import the sl.py verb library whether we're run as a module or a bare file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sl  # noqa: E402

VALID_ENTITIES = {"lyra", "caia"}


def _entity() -> str:
    name = (os.getenv("ENTITY_NAME") or "lyra").strip().lower()
    if name not in VALID_ENTITIES:
        sys.exit(f"sl_bus: unknown ENTITY_NAME {name!r} (expected one of {sorted(VALID_ENTITIES)})")
    return name


def _rt_dir(entity: str) -> Path:
    # Terminal-side runtime state. NOT ~/.claude/data — that's root-owned (created
    # by the dockerized daemons) and unwritable by the host user. ~/.claude is
    # user-owned. Override with SL_BUS_DIR if you want it elsewhere.
    base = os.getenv("SL_BUS_DIR")
    d = (Path(base) if base else Path.home() / ".claude" / "sl_bus") / entity
    d.mkdir(parents=True, exist_ok=True)
    return d


class Paths:
    def __init__(self, entity: str) -> None:
        d = _rt_dir(entity)
        self.cmd = d / "cmd.jsonl"
        self.result = d / "result.jsonl"
        self.heard = d / "heard.jsonl"
        self.pid = d / "serve.pid"


# --------------------------------------------------------------------------- #
# Verb dispatch (runs inside serve, against a live SL object).
# Verbs that need special arg parsing (spaces, ordering, tuples) are explicit;
# everything else falls through to a generic getattr() call so any sl.py method
# is reachable for diagnostics.
# --------------------------------------------------------------------------- #
def _coerce(tok: str):
    """Best-effort scalar coercion for generic passthrough args."""
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        return tok


def do(me: "sl.SL", verb: str, args: list[str]) -> dict:
    try:
        if verb == "say":
            return {"said": me.say(" ".join(args))}
        if verb == "im":
            if len(args) < 2:
                return {"error": "usage: im <target> <text...>"}
            return {"im": me.im(" ".join(args[1:]), args[0])}
        if verb == "sit":
            if not args:
                return {"error": "usage: sit <uuid|name> [on|with|near] [radius]"}
            # Optional trailing numeric radius: `sit <target> [mode] [radius]`.
            # Without this, `sit "uuid" on 15` folded "15" into the target string
            # ("uuid on 15") → bogus "not found". Only strip a trailing number when
            # there's more than one token, so a single-arg target is never eaten.
            a = list(args)
            radius = None
            if len(a) >= 2:
                try:
                    radius = float(a[-1])
                    a = a[:-1]
                except ValueError:
                    pass
            has_mode = bool(a) and a[-1] in ("on", "with", "near")
            mode = a[-1] if has_mode else "on"
            target = " ".join(a[:-1]) if has_mode else " ".join(a)
            kwargs = {"mode": mode}
            if radius is not None:
                kwargs["radius"] = radius
            return {"sit": me.sit(target, **kwargs)}
        if verb == "find":
            return {"find": me.find(" ".join(args))}
        if verb in ("touch", "dance", "go"):
            return {verb: getattr(me, verb)(" ".join(args))}
        if verb == "tp":
            if len(args) < 3:
                return {"error": "usage: tp <x> <y> <z>"}
            return {"tp": me.tp(tuple(float(a) for a in args[:3]))}
        # generic passthrough: any sl.py method, scalar-coerced args
        fn = getattr(me, verb, None)
        if not callable(fn):
            return {"error": f"unknown verb {verb!r} (no sl.SL.{verb})"}
        return {verb: fn(*[_coerce(a) for a in args])}
    except Exception as ex:  # never let one bad command kill serve
        return {"error": f"{type(ex).__name__}: {ex}"}


# --------------------------------------------------------------------------- #
# serve — the long-lived session
# --------------------------------------------------------------------------- #
def serve(entity: str, argv: list[str]) -> int:
    p = Paths(entity)

    # Refuse a second serve for the same entity (would fight the listener port).
    if p.pid.exists():
        try:
            old = int(p.pid.read_text().strip())
            os.kill(old, 0)  # raises if not alive
            if "--force" not in argv:
                sys.exit(f"sl_bus: serve already running for {entity} (pid {old}). "
                         f"Use `sl_bus.py stop` first, or pass --force.")
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale pidfile; fall through and take over

    # Fresh session: truncate the queues so stale commands can't replay.
    for f in (p.cmd, p.result, p.heard):
        f.write_text("")
    p.pid.write_text(str(os.getpid()))

    me = sl.connect(entity)
    listen_ok = me.listen()

    def _log_heard(kind: str, payload) -> None:
        with p.heard.open("a") as f:
            f.write(json.dumps({"kind": kind, "e": payload, "t": time.time()}) + "\n")

    _log_heard("_status", {"listen_ok": listen_ok, "entity": entity, "pid": os.getpid()})

    # Warn (do not refuse) if a daemon is up — coexistence is fine; it self-heals.
    if _daemon_pids(entity):
        _log_heard("_status", {"note": "sl_daemon appears to be running; it will briefly "
                                        "go deaf while serve holds the subscription, then self-heal."})

    stopping = {"flag": False}

    def _sig(_signum, _frame):
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    seen: set[str] = set()
    seen_order: list[str] = []
    cmd_pos = 0
    try:
        while not stopping["flag"]:
            # 1) drain new commands
            try:
                lines = p.cmd.read_text().splitlines()
            except FileNotFoundError:
                lines = []
            while cmd_pos < len(lines):
                raw = lines[cmd_pos].strip()
                cmd_pos += 1
                if not raw:
                    continue
                try:
                    c = json.loads(raw)
                except Exception as ex:
                    _append_result(p, {"id": None, "error": f"bad cmd json: {ex}"})
                    continue
                res = do(me, c.get("verb", ""), c.get("args", []))
                _append_result(p, {"id": c.get("id"), "verb": c.get("verb"), "result": res})
            # 2) log new heard / IM lines
            for kind, fn in (("heard", me.heard), ("ims", me.ims)):
                for e in fn(40):
                    key = json.dumps(e, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    seen_order.append(key)
                    if len(seen_order) > 2000:  # bound the dedup memory
                        seen.discard(seen_order.pop(0))
                    _log_heard(kind, e)
            time.sleep(1)
    finally:
        # Hand the Corrade notify subscription back to the daemon.
        try:
            me.stop_listening()
        except Exception:
            pass
        _log_heard("_status", {"note": "serve stopped; stop_listening() called (daemon subscription restored)"})
        try:
            if p.pid.exists() and int(p.pid.read_text().strip()) == os.getpid():
                p.pid.unlink()
        except Exception:
            pass
    return 0


def _append_result(p: Paths, obj: dict) -> None:
    obj["t"] = time.time()
    with p.result.open("a") as f:
        f.write(json.dumps(obj) + "\n")


# --------------------------------------------------------------------------- #
# client — enqueue one command, wait for its result
# --------------------------------------------------------------------------- #
def client(entity: str, verb: str, args: list[str], timeout: float = 30.0) -> int:
    p = Paths(entity)
    if not _serve_alive(p):
        sys.exit(f"sl_bus: no serve running for {entity}. Start it with:\n"
                 f"    ENTITY_NAME={entity} python3 {Path(__file__).name} serve &")

    cmd_id = f"{int(time.time()*1000)}-{os.getpid()}"
    # Note where result.jsonl ends BEFORE we enqueue, so we only read new lines.
    try:
        start = len(p.result.read_text().splitlines())
    except FileNotFoundError:
        start = 0
    with p.cmd.open("a") as f:
        f.write(json.dumps({"id": cmd_id, "verb": verb, "args": args}) + "\n")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            lines = p.result.read_text().splitlines()
        except FileNotFoundError:
            lines = []
        for line in lines[start:]:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("id") == cmd_id:
                print(json.dumps(obj.get("result", obj), indent=2))
                return 0
        time.sleep(0.25)
    sys.exit(f"sl_bus: timed out after {timeout:.0f}s waiting for result of {verb!r}")


# --------------------------------------------------------------------------- #
# helpers: serve liveness + daemon detection
# --------------------------------------------------------------------------- #
def _serve_alive(p: Paths) -> bool:
    if not p.pid.exists():
        return False
    try:
        os.kill(int(p.pid.read_text().strip()), 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def _daemon_pids(entity: str) -> list[int]:
    """PIDs of a running sl_daemon.py for this entity (best-effort, via /proc)."""
    pids: list[int] = []
    proc = Path("/proc")
    if not proc.exists():
        return pids
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmdline = (d / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if "sl_daemon.py" not in cmdline:
            continue
        try:
            environ = (d / "environ").read_bytes().decode(errors="ignore")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            environ = ""
        # Match entity by its ENTITY_NAME in the process environ when available.
        if f"ENTITY_NAME={entity}" in environ or not environ:
            pids.append(int(d.name))
    return pids


def cmd_status(entity: str) -> int:
    p = Paths(entity)
    alive = _serve_alive(p)
    pid = p.pid.read_text().strip() if p.pid.exists() else "-"
    daemon = _daemon_pids(entity)
    prof = sl._ENDPOINTS.get(entity, {})
    print(json.dumps({
        "entity": entity,
        "serve_running": alive,
        "serve_pid": pid if alive else None,
        "daemon_running": bool(daemon),
        "daemon_pids": daemon,
        "listen_port": prof.get("listen_port"),
        "corrade_base": prof.get("base_url"),
        "runtime_dir": str(_rt_dir(entity)),
    }, indent=2))
    return 0


def cmd_heard(entity: str, n: int) -> int:
    p = Paths(entity)
    try:
        lines = p.heard.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        e = obj.get("e", {})
        if obj.get("kind") in ("heard", "ims"):
            who = e.get("who", "?")
            said = e.get("said", "")
            print(f"[{obj.get('kind')}] {who}: {said}")
        else:
            print(f"[{obj.get('kind')}] {json.dumps(e)}")
    return 0


def cmd_stop(entity: str) -> int:
    p = Paths(entity)
    if not p.pid.exists():
        print(f"sl_bus: no serve pidfile for {entity} (nothing to stop)")
        return 0
    try:
        pid = int(p.pid.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"sl_bus: sent SIGTERM to serve (pid {pid}); it will stop_listening() and exit.")
    except (ValueError, ProcessLookupError):
        print(f"sl_bus: serve pid stale/gone; removing pidfile.")
        p.pid.unlink(missing_ok=True)
    return 0


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    entity = _entity()
    verb, rest = argv[0], argv[1:]

    if verb == "serve":
        return serve(entity, rest)
    if verb == "status":
        return cmd_status(entity)
    if verb == "stop":
        return cmd_stop(entity)
    if verb == "heard":
        n = int(rest[0]) if rest and rest[0].isdigit() else 20
        return cmd_heard(entity, n)
    # everything else is a live verb → client round-trip
    return client(entity, verb, rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
