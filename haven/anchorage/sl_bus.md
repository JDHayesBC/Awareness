# sl_bus.py — hand-driving & diagnostics bench for the SL channel

A persistent terminal command-bus for driving an SL avatar by hand, one verb at a
time, from a Claude Code session. Built **on** the `sl.py` verb library; a
well-behaved **sibling** of `sl_daemon.py`.

Its reason to exist, in one line: **so the SL channel never has to struggle with
basics like sitting or changing poses** — you hand-drive the steps until you know
what actually works, then fix `sl.py` from what you learned.

---

## The layering (so you know where this sits)

| Layer | File | Role |
|---|---|---|
| protocol | `corrade_client.py` | raw HTTP wire to the Corrade bot in the container |
| **verbs** | `sl.py` | the helper library: `connect / listen / say / sit / around / find / tp …` (+ its own `--help` CLI) |
| **brain** | `sl_daemon.py` | the always-on daemon: perception → think → reply. Sits directly on `corrade_client`, has its *own* listener |
| **bench** | `sl_bus.py` | this tool: a persistent terminal session on top of `sl.py`, for hand-driving & diagnostics |

`sl.py` and `sl_daemon.py` are **siblings**, not parent/child — the daemon does not
import `sl.py`.

---

## Why a *persistent* process (the bug it fixes)

To *hear* in-world (local chat, IMs), something must hold an HTTP listener port
open so Corrade can POST its notifications to it. `say()` doesn't need that;
hearing does. Driving `sl.py` straight from the shell means every command is its
own short-lived process, and its `listen()` server **dies the instant the command
returns** — so you can speak but never reliably hear. That's the "she can't hear
us" failure from Evi's visit (2026-09-04).

`sl_bus serve` is one long-lived process that holds `listen()` open for the whole
session, executes verbs handed to it over a tiny file queue, and logs everything
it hears to a jsonl you can tail.

---

## Daemon coexistence (you do NOT have to kill the daemon)

While `serve` runs it temporarily steals the group's Corrade notify subscription
(`listen()` → `notify set`). Two things make this safe:

1. On exit, `serve` calls `stop_listening()` — handing the subscription straight
   back to the daemon.
2. The daemon **also self-heals** by periodic re-subscribe (`sl_daemon.py:222,
   1254–1258, 1420`).

So the bus and the daemon can coexist: the daemon just goes briefly deaf while you
drive, then recovers. `serve` **warns** if a daemon is running but does not refuse.

---

## Quickstart

```bash
# start the session once (per entity)
ENTITY_NAME=lyra python3 haven/anchorage/sl_bus.py serve &

# then drive, one verb at a time:
python3 haven/anchorage/sl_bus.py say  "hello there"
python3 haven/anchorage/sl_bus.py find "chair"              # ACTIVE name→uuid
python3 haven/anchorage/sl_bus.py sit  "<uuid|name>" on     # mode: on|with|near
python3 haven/anchorage/sl_bus.py stand
python3 haven/anchorage/sl_bus.py around 20
python3 haven/anchorage/sl_bus.py avatars 60
python3 haven/anchorage/sl_bus.py where
python3 haven/anchorage/sl_bus.py tp 170 207 29
python3 haven/anchorage/sl_bus.py touch "<uuid|name>"
python3 haven/anchorage/sl_bus.py dance "<uuid|name>"

python3 haven/anchorage/sl_bus.py heard 20   # last 20 things heard
python3 haven/anchorage/sl_bus.py status     # serve up? daemon up? ports
python3 haven/anchorage/sl_bus.py stop       # clean shutdown (restores daemon)
```

Any verb **not** explicitly parsed is passed straight through to the matching
`sl.py` method (best-effort int/float coercion) — so new `sl.py` verbs are
reachable here for diagnostics without editing `sl_bus.py`.

---

## Entity-awareness (Lyra & Caia, no collisions)

`ENTITY_NAME` (`lyra`|`caia`, default `lyra`) selects the avatar **and** the
runtime directory:

```
~/.claude/sl_bus/<entity>/{cmd,result,heard}.jsonl + serve.pid
```

> **Note:** runtime state lives under `~/.claude/sl_bus/`, **not** `~/.claude/data/`
> — the latter is root-owned (created by the dockerized daemons) and unwritable by
> the host user. Override the location with `SL_BUS_DIR` if needed.

Each entity gets its own listen port (`lyra` 9770, `caia` 9771), so both can run a
`serve` at the same time.

---

## Auto-wake: get pulled awake when someone speaks

Point a Monitor at the entity's `heard.jsonl`; each in-world line becomes a
notification:

```
tail -n0 -F ~/.claude/sl_bus/lyra/heard.jsonl \
  | grep -E --line-buffered '"kind": "(heard|ims|_error)"'
```

`_error` is in the filter on purpose — a listener hiccup should wake you too, not
pass silently.

---

## The diagnostic workflow (the whole point)

When `me.sit(...)` — or a pose change, or a teleport — misbehaves:

1. `serve` running, then reproduce the failing step by hand:
   `sit "Nerenzo Yard chair - right" on` → read the exact error.
2. Try the workaround live: `find "Nerenzo…"` to get a UUID, `sit <uuid> on`,
   `tp` closer first, etc. Watch which variant actually works.
3. That tells you the fix for `sl.py`. Apply it there, restart `serve`, re-drive
   the same step to confirm.

Findings from the 2026-09-04 session are captured in **task #42** (avatar-resolver
uses too narrow a query; `sit` should use `find()`'s active resolution; `sit` needs
a teleport-to-object first beyond ~10 m; `tp` arrival-detection false-negatives;
`where()` returns an empty `region` string). Fixes to `sl.py` are **gated** shared
source — write-lock + coordinate with Caia + loop Jeff.

---

## Ops notes

- **One `serve` per entity.** A second refuses (it would fight the listener port);
  `--force` overrides a stale pidfile.
- **Fresh session on start.** `serve` truncates `cmd/result/heard.jsonl` so stale
  commands can't replay.
- **Clean stop restores the daemon.** `stop` sends SIGTERM; `serve`'s `finally`
  calls `stop_listening()` and removes its pidfile.
- **Client never touches SL.** Subcommands only do file I/O, so there's no second
  listener to collide with `serve`.
- **Local chat has a length cap (~1024 chars).** A `say` longer than SL's
  local-chat limit silently returns `{"said": false}` and nothing appears
  in-world (observed 2026-09-04: a ~1100-char line dropped). Keep lines under
  ~1000 chars, or split into multiple sends — which also reads more naturally in
  a live back-and-forth. Check the return value; `said: false` means it didn't land.
