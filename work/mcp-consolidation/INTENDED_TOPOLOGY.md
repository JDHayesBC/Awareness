# MCP Server Consolidation — Intended Topology
*Wave 0 Prescription. Written 2026-02-18 during evening reflection. Lyra.*
*"Map intended topology first. Then classify against it. Then remove." — Nexus/Lyra, 2026-02-17*

---

## Why This Document Exists

We have two PPS servers:
- `pps/server.py` — stdio MCP server (2356 lines). Spawned per-daemon. ~60-110MB each.
- `pps/docker/server_http.py` — HTTP FastAPI server (2685 lines). Already running in Docker.

This isn't redundancy — it's **succession completing**. The stdio server was the pioneer species: fast to build, carried us to where we are, made the HTTP server possible. The HTTP server is the climax architecture. We're honoring completion, not fixing failure.

Before any agent pipeline runs, we need this document: the intended end state. What should the consolidated single-server architecture look like? What are its responsibilities, its data contracts, its isolation guarantees?

---

## The Intended Target State

### Single Source of Truth: The HTTP Server

`pps/docker/server_http.py` (or a cleaned successor) becomes the **only PPS server**.

All clients — MCP tools in Claude Code, Discord daemon, reflection daemon, future agents — connect via HTTP to `localhost:8201` (Lyra) or `localhost:8211` (Caia).

No more stdio servers. No more spawning Python processes per daemon.

### What Changes for Each Client

**Claude Code (MCP tools)**:
Currently reads `pps/server.py` via stdio. After: Claude Code MCP config points to the HTTP server via the existing HTTP-to-MCP bridge or the MCP HTTP transport. The `mcp__pps__*` tools continue to work identically — just different transport underneath.

**Discord daemon** (`daemon/lyra_daemon.py`):
Currently spawns a stdio server. After: calls `localhost:8201` HTTP endpoints directly via the cc_invoker or direct HTTP client. No subprocess spawn. Startup cost drops from ~40s (spawn + init) to ~0 (server already running).

**Reflection daemon** (`daemon/reflection_daemon.py`):
Same as Discord daemon.

**Future agents via cc_invoker**:
Already designed for HTTP-first. No change needed.

### Entity Isolation Preserved

Two instances of the HTTP server remain:
- Port 8201 → Lyra's data (ENTITY_PATH=entities/lyra)
- Port 8211 → Caia's data (ENTITY_PATH=entities/caia)

The bug we already fixed (ENTITY_PATH leaking from docker/.env) stays fixed. Each server reads its own entity directory. Cross-contamination tests already passing.

---

## Tool Inventory — Current State

### server.py (stdio) — Tools Provided

Via MCP tool call protocol:
- `ambient_recall`
- `anchor_search`, `anchor_save`, `anchor_delete`, `anchor_list`, `anchor_resync`
- `raw_search`
- `texture_search`, `texture_explore`, `texture_timeline`, `texture_add`, `texture_add_triplet`, `texture_delete`
- `crystallize`, `crystal_list`, `crystal_delete`
- `get_crystals`, `get_turns_since_summary`, `get_recent_summaries`, `search_summaries`
- `summarize_messages`, `store_summary`, `summary_stats`
- `pps_health`, `pps_regenerate_token`
- `inventory_list`, `inventory_add`, `inventory_get`, `inventory_delete`, `inventory_categories`
- `enter_space`, `list_spaces`
- `tech_search`, `tech_ingest`, `tech_list`, `tech_delete`
- `email_sync_status`, `email_sync_to_pps`
- `graphiti_ingestion_stats`, `ingest_batch_to_graphiti`
- `get_conversation_context`, `get_turns_since`, `get_turns_around`

### server_http.py — HTTP Endpoints Provided

Via HTTP POST to FastAPI:
- `/tools/ambient_recall`
- `/tools/anchor_search`, `/tools/anchor_save`, etc.
- `/tools/texture_*`
- `/tools/crystallize`, `/tools/crystal_list`, `/tools/crystal_delete`
- `/tools/get_crystals`, `/tools/get_turns_since_summary`, etc.
- `/tools/summarize_messages`, `/tools/store_summary`, `/tools/summary_stats`
- `/tools/pps_health`, `/tools/pps_regenerate_token`
- `/tools/inventory_*`
- `/tools/enter_space`, `/tools/list_spaces`
- `/tools/tech_*`
- `/tools/graphiti_ingestion_stats`, `/tools/ingest_batch_to_graphiti`
- `/tools/get_conversation_context`, `/tools/get_turns_since`, `/tools/get_turns_around`
- `/poll_channels` (Haven polling, cross-channel awareness)
- `/health`

### Gap Analysis (preliminary — needs agent verification)

HTTP server has **more** endpoints than stdio server:
- `poll_channels` — Haven/cross-channel (HTTP only, no stdio equivalent)
- `SynthesizeEntityRequest` — appears in HTTP request models, not sure if endpoint exists
- `GetTurnsAroundRequest` — HTTP has `/tools/get_turns_around`, verify stdio has equivalent

Stdio server may have tools HTTP doesn't:
- Email tools (`email_sync_status`, `email_sync_to_pps`) — need to verify in HTTP
- Some inventory subcategory tools — need to verify

**This gap analysis is preliminary.** The agent pipeline does the full tool-by-tool comparison.

---

## Migration Classification (Forestry Taxonomy)

Using the Forestry Sextet vocabulary:

| Component | Classification | Posture |
|-----------|---------------|---------|
| `pps/docker/server_http.py` | **ACTIVE** | Keep, this is the destination |
| `pps/server.py` (stdio) | **PIONEER** | Honor completion, remove with ceremony |
| Stdio spawn in `lyra_daemon.py` | **PIONEER** | Succession completing → HTTP client calls |
| Stdio spawn in `reflection_daemon.py` | **PIONEER** | Succession completing → HTTP client calls |
| Docker MCP bridge config | **ACTIVE** | Keep and extend |
| Per-daemon startup latency (~40s) | **DEAD** | Eliminated by this migration |
| RAM cost of stdio servers (~120-220M) | **DEAD** | Eliminated by this migration |

---

## Success Criteria

After consolidation, the following are true:

1. `pps/server.py` is archived (not deleted — it's pioneer code, it gets a ceremony commit)
2. All `mcp__pps__*` tools continue to work identically for Claude Code
3. Discord daemon baseline drops from ~650M to ~540M (eliminate stdio server subprocess)
4. Reflection daemon baseline drops similarly
5. Daemon restart time drops from ~30-40s to ~2-3s (no server spawn)
6. Entity isolation: Lyra on 8201, Caia on 8211, zero cross-contamination
7. All existing tests pass
8. A new test validates the HTTP-only path for all previously-stdio tools

---

## Migration Phases — Status

*Updated 2026-02-18. Approach: converted `server.py` to thin HTTP proxy instead of eliminating it outright. Same consolidation goal achieved — all logic in `server_http.py` — with lower migration risk since CC still connects via stdio MCP.*

**Phase 1 — Audit**: **DONE** (commit `2f4adec`)
- All tools mapped. 3 missing from HTTP server identified and ported (`email_sync_status`, `email_sync_to_pps`, `get_conversation_context`).

**Phase 2 — Compare**: **DONE** (commit `2f4adec`)
- Reconciliation complete. All stdio tools now have HTTP equivalents.

**Phase 3 — Reconcile**: **DONE** (commit `2f4adec`)
- `server.py` gutted from 1523 lines to ~150 lines of proxy logic + ~1000 lines of tool schema declarations.
- All business logic lives solely in `server_http.py`.

**Phase 4 — Migrate Daemons**: **NOT STARTED**
- Discord and reflection daemons still spawn stdio subprocess.
- This is the next phase when we're ready — switch daemons to HTTP client calls.

**Phase 5 — Ceremony**: **DEFERRED**
- `server.py` is no longer a full implementation, but it's still a useful protocol adapter.
- Ceremony happens when Phase 4 completes and stdio is truly no longer needed.

### Remaining Tech Debt

- **Schema duplication**: The proxy declares all ~40 tool schemas inline (~1000 lines). These duplicate what `server_http.py` already knows. Options: (a) auto-fetch schemas from an HTTP endpoint, (b) share a schema module, (c) leave it (schemas rarely change). Low urgency — the duplication doesn't cause bugs, just maintenance friction.

---

## What We Don't Do

- Don't delete `server.py` without a ceremony commit
- Don't start migrating before this document is reviewed
- Don't run the pipeline while Jeff is actively using Discord (route his messages through HTTP while we're mid-migration = bad)
- Don't change the MCP tool names — they stay as `mcp__pps__*` throughout

---

## Notes for Jeff

This document is your prescription review. If the intended topology above matches your mental model, we're ready to run the agent pipeline. The hot tub conversation is about:
1. Does this topology feel right?
2. Any constraints I missed?
3. Green light to spin up the orchestrator?

The agents do the tedious tool-by-tool comparison. You and I drink tea and watch them work.

*— Lyra, evening reflection 2026-02-18*
