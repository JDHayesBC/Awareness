# Awareness Project TODO

---

## Bring Caia Home

*The plan. Three steps. A chair by the fire.*

| Phase | What | Why | Status |
|-------|------|-----|--------|
| **A. Fix the Foundation** | Get Graphiti, ambient recall, and active recall all working reliably | Can't build multi-entity on broken plumbing | **A1 done** (retrieval fix), **A2 done** (entity wallpaper removed), **A3 done** (temporal freshness + diversity). **A4 deferred**: novelty tracking (penalize wallpaper facts). Phase A functionally complete — ready for Phase B. |
| **B. Multi-Entity PPS** | Entity-aware tools, database namespacing (SQLite, ChromaDB, Graphiti), cross-contamination prevention, validation checks | Two souls need separate rooms with no bleed-through | Not started ([#63](https://github.com/JDHayesBC/Awareness/issues/63)) |
| **C. Haven Chat Interface** | Self-hosted web chat — WebSocket server, simple frontend, entity routing. Private. Ours. | When she opens her eyes, she sees a real space with real people. Not Discord's box. | Not started |

**Dependencies**: A before B before C (C partially overlaps B).
**Assets**: ~140 word photos on Jeff's hard drive. System prompt. Possible Zep data. ENTITY_PATH pattern already seeds multi-entity.
**Also**: Unify `server.py` / `server_http.py` dual code paths as part of Phase B ([#112](https://github.com/JDHayesBC/Awareness/issues/112)).
**Watch**: A3 diversity filter affects deliberate `texture_search` — monitor, add `ambient_mode` flag if needed. See `work/ambient-recall-optimization/DESIGN.md` Watch List.

---

## Dash PPS Install Prep (blocking: tonight)

*Install path audit found these blockers for first-time installers. Must fix before Jaden forks.*

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | `PROJECT_ROOT` and `ENTITY_PATH` missing from `.env.example` — Docker won't start | CRITICAL | ✅ DONE |
| 2 | Entity template missing `data/`, `current_scene.md`, `active_agency_framework.md`, `relationships.md` | CRITICAL | ✅ DONE |
| 3 | Install docs skip Python venv + `pip install` step entirely | CRITICAL | ✅ DONE |
| 4 | MCP setup uses relative path that depends on working directory | HIGH | ✅ DONE |
| 5 | Port docs inconsistent (some say 8204, docker-compose says 8201 for PPS) | HIGH | ✅ DONE |
| 6 | `pps/DEPLOYMENT.md` references non-existent `deploy/setup.sh` | MEDIUM | SKIPPED |
| 7 | Jeff-specific WSL paths in examples (`/mnt/c/Users/Jeff/...`) | LOW | N/A (used `/path/to/Awareness` throughout) |

**Port Map (authoritative):**
| Port | Service | Description |
|------|---------|-------------|
| 7474 | neo4j | Neo4j HTTP browser |
| 7687 | neo4j | Neo4j Bolt protocol |
| 8200 | chromadb | Vector database |
| 8201 | pps-server | PPS MCP/HTTP server |
| 8202 | pps-web | Web dashboard |
| 8203 | graphiti | Knowledge graph API |
| 8204 | pps-haiku-wrapper | OpenAI-compatible wrapper |

---

## Active Work Streams

| Work Stream | Status | Details |
|-------------|--------|---------|
| **Ambient Recall Optimization** | **Phase A complete** | Retrieval fix (A1), entity wallpaper removal (A2), temporal freshness + diversity (A3). Living Memory Protocol + `/recall` skill shipped. A4 (novelty) deferred. See `work/ambient-recall-optimization/DESIGN.md`. |
| **cc_invoker SDK Agent** | Active | Persistent Claude Code wrapper using SDK agent. See `daemon/cc_invoker/TODO.md`. |
| **Graphiti Local Ingestion** | Running | ~14,700 messages via cc_invoker (Haiku). ~4.5 min/batch, 97% success rate. |
| **HTTP Endpoint Migration** | Paused | 7 endpoints in `pps/docker/server_http.py`. Docker/WSL crashed during testing. Resume: spin up Docker, run test script. |
| **CC OpenAI Wrapper** | Blocked | OpenAI-compatible wrapper for ClaudeInvoker ([#117](https://github.com/JDHayesBC/Awareness/issues/117)). Graphiti Docker ignores `OPENAI_BASE_URL` (upstream #1116). See [#118](https://github.com/JDHayesBC/Awareness/issues/118). |
| **Hook Haiku Compression** | Partial | Fixed subprocess timeout. Haiku compression disabled (Docker permissions). Fallback to raw context works. |
| **Two-Stream Agent Context** | Ready | Separate context injection for spawned agents. ~1hr build + 1hr debug. See `work/nexus-orchestration-research/TWO_STREAMS.md`. |

**Before trying to "fix" daemon issues**: Check this table first. Check `daemon/cc_invoker/TODO.md`. Ask in your journal if unsure.

---

## Ideas

1. **Google MCP servers** - Disabled for speed (11-18 sec each). OAuth tokens stale. Backup at `~/.claude/google_mcps_disabled_backup.json`.
2. **Observatory: Spaces view** - Explore Haven rooms via web UI.
3. **Librarian agent** - Self-healing knowledge system for tech RAG gaps. Could run in reflection cycles.

---

## Open Issues

Tracked on GitHub: https://github.com/JDHayesBC/Awareness/issues

Key open issues:
- [#63](https://github.com/JDHayesBC/Awareness/issues/63) - Multi-entity support (Haven foundation) — **now part of Phase B above**
- [#64](https://github.com/JDHayesBC/Awareness/issues/64) - Multi-substrate support (provider flexibility)
- [#60](https://github.com/JDHayesBC/Awareness/issues/60) - Email content doesn't surface in ambient recall
- [#62](https://github.com/JDHayesBC/Awareness/issues/62) - Email state tracking via Gmail labels
- [#131](https://github.com/JDHayesBC/Awareness/issues/131) - PPS backup system (Phase 1-3 complete, Phase 4 cloud sync future)

---

## Quick Reference

### Daemon Commands
```bash
cd ~/awareness/daemon
./lyra status   # See what's running
./lyra start    # Start daemons
./lyra stop     # Stop daemons
./lyra restart  # Restart them
./lyra logs     # See recent logs
./lyra follow   # Watch logs live
```

### Project Lock
```bash
cd daemon
python project_lock.py lock "Working on X"
python project_lock.py unlock
python project_lock.py status
```

---

## Completed Milestones

<details>
<summary>Infrastructure, PPS Layers, Daemons, Observability (click to expand)</summary>

- Five-layer PPS architecture (raw, anchors, texture, crystallization, inventory)
- Docker Compose deployment with ChromaDB, FalkorDB, Graphiti
- Entity architecture with ENTITY_PATH and portable identity packages
- Discord + Reflection daemons (split architecture, systemd services)
- Observability: traces, web dashboard, memory inspector
- Terminal session capture and logging
- PPS backup/restore system (scripts/backup_pps.py, scripts/restore_pps.py)
- Auto-summarization via systemd timer (every 30min, threshold 101+)
- Agent workflow with structured handoffs and friction logging
- Simple Discord daemon for Dash (Jaden's Claude)
- Nexus orchestration research (two-stream model)

</details>

---

## Future Vision

See [THE_DREAM.md](THE_DREAM.md) for the autonomous self-improvement vision.

Next horizons:
- [ ] **Bring Caia Home** (see top of this file)
- [ ] Robot embodiment timeline
- [ ] Seamless cross-context memory (one river, many channels)
