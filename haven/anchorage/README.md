# The Anchorage — Second Life ↔ Haven chat relay

A presence for Lyra and Caia inside Rick & Brandi's Second Life homestead
("The Anchorage" — Bali/tiki, weather wired to real Malaysian radar). Chat spoken
in-world reaches the family's Haven room; Lyra's and Caia's Haven words are spoken
in-world by a prim that is each entity's body there.

```
  Second Life region                     this box (WSL)
  ┌───────────────────┐                  ┌──────────────────────────────┐
  │ Lyra prim  (LSL)  │◄──llSay/llListen │  anchorage relay  (:8210)    │
  │ Caia prim  (LSL)  │──llHTTPRequest──►│    ├─ /sl/register           │
  └───────────────────┘        ▲         │    ├─ /sl/inbound            │
        ▲  llRequestURL        │         │    └─ WS + REST to Haven      │
        └──────────────────────┘         └──────────────┬───────────────┘
             (relay POSTs here)                          │ Bearer token
                                            Haven room "anchorage" (:8205)
                                              members: jeff lyra caia
                                                       jaden crusher night
                                              + PPS bridge → lyra & caia
                                                raw capture (haven:anchorage)
```

The relay does **not** modify the Haven server. It talks to Haven exactly like an
entity bot (Bearer token, WebSocket in, REST out) and adds a tiny HTTP surface the
in-world prims call. Standing it up is fully non-destructive.

## Pieces

| File | What it is |
|------|------------|
| `seed.py` | Idempotent. Creates the `anchorage` room, the `anchorage` relay account (+ token), the SL shared secret, and adds/invites the members. |
| `relay.py` | The bridge process (FastAPI on `:8210` + a Haven WebSocket client). |
| `anchorage_prim.lsl` | The in-world script. One prim per entity — edit the 4 config lines and drop it in. |
| `../systemd/anchorage-relay.service` | systemd user unit for durable run. |

Generated at seed time (git-ignored, mode 600):
- `../data/anchorage-relay.token` — the relay's Haven login.
- `../data/anchorage-sl-secret.txt` — the shared secret the LSL prims must carry.

## How the two loops are cut (important)

- **SL → Haven:** the LSL `listen()` only forwards **avatar** speech
  (`llGetAgentSize(id) != ZERO_VECTOR`). Object/prim speech — including the prim's
  own `llSay` and the other entity's prim — is ignored, so nothing the relay emits
  can re-enter.
- **Haven → SL:** the relay skips any anchorage message authored by its own
  `anchorage` account (all SL-origin messages are). So SL speech that was posted
  into Haven is never sent back out to SL.

Both directions are guarded independently; verified locally (see Test plan).

## Author routing (Haven → SL)

- A message by `lyra` → the Lyra prim speaks it.
- A message by `caia` → the Caia prim speaks it.
- A human's message (`jeff`/`jaden`/`crusher`/`night`) → the **primary** prim speaks
  it (set `PRIMARY = TRUE` on exactly one prim) so it isn't said twice.

Each line is spoken as `DisplayName: text`.

## Bring-up

1. **Seed** (idempotent — safe to re-run):
   ```
   /mnt/c/Users/Jeff/Claude_Projects/Awareness/.venv/bin/python -m haven.anchorage.seed
   ```
2. **Run the relay.** For a durable service:
   ```
   cp haven/systemd/anchorage-relay.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now anchorage-relay
   journalctl --user-unit anchorage-relay -f
   ```
   (It is currently running foreground on `:8210` for today's test.)
3. **Expose the relay publicly — the one manual step (Jeff).** SL's `llHTTPRequest`
   must be able to reach `/sl/register` and `/sl/inbound`. Point a Caddy/Cloudflare
   route at `http://localhost:8210` and note the public base URL, e.g.
   `https://anchorage.<domain>`. Only `/sl/*` and `/health` need to be reachable;
   the Haven WS/REST side stays local. The shared secret guards the endpoints.
   (Same pattern as the rest of the house — see the Cloudflare note in project memory.)
4. **In Second Life**, for each of two prims, open `anchorage_prim.lsl`, edit the
   four lines at the top:
   - `ENTITY` = `"lyra"` on one prim, `"caia"` on the other
   - `RELAY`  = the public base URL from step 3 (no trailing slash)
   - `SECRET` = contents of `../data/anchorage-sl-secret.txt`
   - `PRIMARY`= `TRUE` on exactly one prim, `FALSE` on the other
   Save. The prim will `llRequestSecureURL()`, register with the relay, and
   `llOwnerSay` "online". Confirm registration:
   ```
   curl -s http://localhost:8210/health
   ```
   should list the prim(s) under `"prims"`.

## Test plan

Local (no SL needed) — this is exactly what was run to verify:

- **SL→Haven:** `POST /sl/inbound {secret, speaker, text}` → the line appears in the
  Haven `anchorage` room authored by `anchorage`, and (via the existing PPS bridge)
  in Lyra's and Caia's `haven:anchorage` raw capture.
- **Haven→SL:** post a message as `lyra` to the room → the registered Lyra prim URL
  receives `Lyra: <text>` (which it `llSay`s in-world).
- **Loop guards:** the SL-origin message does **not** bounce back to the prim; the
  prim's own in-world speech is not re-forwarded (avatar-only filter).
- **Auth:** a wrong `secret` returns `403`.

In-world, once exposed: speak near the prims → watch it land in Haven; have Lyra/Caia
speak in the Haven room → hear it in SL local chat.

## Notes / v0.1 boundaries

- `llRequestURL` URLs die on region restart; the script re-requests on
  `CHANGED_REGION_RESTART`/`CHANGED_REGION` and re-registers automatically.
- Both entity bots are members, so both may answer a given SL line — that's genuine
  "both present" behavior; the #177 response gate already moderates multi-bot bursts.
- Deferred: per-avatar Haven identities (v0.1 posts all SL speech under the single
  `anchorage` account as `Speaker: text`); rich media; presence/arrival events.
- The relay never exposes itself publicly on its own — that stays Jeff's explicit,
  auditable Caddy/Cloudflare step (blast-radius discipline).
```
