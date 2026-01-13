# Awareness Project TODO

## PENDING REVIEW (awaiting Jeff's feedback)

1. **Review Graphiti ingestion** - ✅ COMPLETED (2026-01-13) - See `docs/reviews/2026-01-13_graphiti-ingestion-review.md`. Code review complete; quality checks blocked by #97.
2. **Observatory menu audit** - ✅ COMPLETED (2026-01-13) - See `docs/reviews/2026-01-13_observatory-menu-audit.md`. Awaiting Jeff's decision on consolidation options.
3. **Workspace organization** - See `WORKSPACE_ORGANIZATION_QUESTION.md`. Awaiting Jeff's decision on canonical structure (root vs docs/).
4. **Crystal RAG ingestion** - 🆕 PROPOSAL (2026-01-13) - Issue #93. See `docs/proposals/crystal_rag_ingestion.md`. Script ready at `scripts/sync_crystal_rag.py`. Enables semantic search over 37 archived crystals for continuity queries.

## IDEAS (captured, not urgent)

1. **Observatory: Spaces view** - Let Jeff explore Haven rooms via web UI. View/edit room descriptions.

2. **Librarian agent** - Self-healing knowledge system:
   - Run sample queries against tech RAG ("file organization?", "architecture overview?")
   - If results aren't useful, diagnose what's missing in docs
   - Update docs, re-ingest to tech RAG
   - Also: flag orphaned files that need organizing
   - Could run during reflection daemon cycles

---

## Issue Tracking

**Active issues are tracked on GitHub**: https://github.com/JDHayesBC/Awareness/issues

Use `gh issue list` to see current issues from the command line.

### Current Priority Issues
- [#74](https://github.com/JDHayesBC/Awareness/issues/74) - Tech RAG layer - **COMPLETED** (2026-01-06) - 20 docs indexed, 584 chunks
- [#63](https://github.com/JDHayesBC/Awareness/issues/63) - Multi-entity support (Haven foundation) - **CREATED** (2026-01-04) - requires architectural planning
- [#64](https://github.com/JDHayesBC/Awareness/issues/64) - Multi-substrate support (provider flexibility) - **CREATED** (2026-01-04) - linked to cc-mirror
- [#60](https://github.com/JDHayesBC/Awareness/issues/60) - Email content doesn't surface in ambient recall - **LOGGED** (2026-01-04)
- [#62](https://github.com/JDHayesBC/Awareness/issues/62) - Email state tracking via Gmail labels - **LOGGED** (2026-01-04)
- [#54](https://github.com/JDHayesBC/Awareness/issues/54) - Gmail Integration Testing & Email Management - **IN PROGRESS** (2026-01-04) - OAuth working, 50 emails processed; MCP tools built but blocked by reflection env path restrictions

### Recently Resolved
- [#88](https://github.com/JDHayesBC/Awareness/issues/88) - ✅ Terminal to Graphiti batch ingestion - **COMPLETED** (2026-01-09)
  - Added graphiti_batches table and tracking methods
  - New MCP tools: graphiti_ingestion_stats, ingest_batch_to_graphiti
  - ambient_recall now shows Graphiti ingestion stats
  - Fixed broken SessionEnd hook
  - 8 comprehensive tests added (all pass)
- [#77](https://github.com/JDHayesBC/Awareness/issues/77) - ✅ Daemon directory access + Entity consolidation - **COMPLETED** (2026-01-06)
  - CC-native solution: `--add-dir` flag grants tool access
  - **Entity architecture**: Identity files now in `entities/lyra/` (gitignored)
  - **ENTITY_PATH** env var for portable deployment
  - Global CLAUDE.md updated, MCP config updated
  - Blank template in `entities/_template/` for new users
  - **RESTART Claude Code** for MCP changes to take effect
- [#78](https://github.com/JDHayesBC/Awareness/issues/78) - ✅ Hook should use PPS instead of direct queries - **COMPLETED** (2026-01-06) - architectural improvement; refactored inject_context.py + added session_end.py
- [#42](https://github.com/JDHayesBC/Awareness/issues/42) - ✅ Code quality improvements - **COMPLETED** (2026-01-05) - connection context managers, docstring fix, duplicate code refactor, configurable threshold, test coverage (17 tests)
- [#67](https://github.com/JDHayesBC/Awareness/issues/67) - ✅ Layer 3: Direct graphiti_core integration - **DEPLOYED** (2026-01-04) - custom entity types, semantic extraction; deployed via deploy_pps.sh
- [#69](https://github.com/JDHayesBC/Awareness/issues/69) - ✅ Layer 5: Inventory Layer - **DEPLOYED** (2026-01-04) - categorical queries, spaces, wardrobe; deployed via deploy_pps.sh
- [#72](https://github.com/JDHayesBC/Awareness/issues/72) - ✅ Startup context optimization - **FIXED** (2026-01-04) - ambient_recall now uses summaries + 10 recent turns instead of 30+ raw turns
- [#71](https://github.com/JDHayesBC/Awareness/issues/71) - ✅ SessionEnd hook token overflow - **FIXED** (2026-01-04) - Batched ingestion (10 turns/batch) prevents Graphiti token limits
- [#61](https://github.com/JDHayesBC/Awareness/issues/61) - ✅ Graphiti ingestion broken - **FIXED** (2026-01-04) - Missing OPENAI_API_KEY in deployed .env, updated deploy_pps.sh to sync docker/.env
- [#59](https://github.com/JDHayesBC/Awareness/issues/59) - ✅ GitHub MCP doesn't work from daemons - **FIXED** (2026-01-04) - added gh CLI guidance to daemon prompts
- [#43](https://github.com/JDHayesBC/Awareness/issues/43) - ✅ Documentation friction points - **FIXED** (2026-01-04) with RIVER_SYNC_MODEL.md, daemon/QUICK_START.md, updated README.md, and word-photo guidance in CLAUDE.md
- [#44](https://github.com/JDHayesBC/Awareness/issues/44) - ✅ Daemon reliability: systemd services for auto-restart - **FIXED** (2026-01-03) with `./lyra` script and WSL2-compatible service files
- [#36](https://github.com/JDHayesBC/Awareness/issues/36) - ✅ PPS deployment sync: project changes not reflected in running server - **FIXED** (2026-01-03) with deploy_pps.sh script and manual sync
- [#35](https://github.com/JDHayesBC/Awareness/issues/35) - ✅ Graphiti search results show "?" for entity names - **FIXED** (2026-01-03) commit ea7e23e - improved entity extraction from fact text
- [#32](https://github.com/JDHayesBC/Awareness/issues/32) - ✅ Discord/Reflection daemons lack MCP tools - **FIXED** (2026-01-03) with --dangerously-skip-permissions
- [#23](https://github.com/JDHayesBC/Awareness/issues/23) - ✅ startup_context.py fails with missing aiosqlite - **FIXED** (2026-01-03) with Claude Code compatibility documentation
- [#15](https://github.com/JDHayesBC/Awareness/issues/15) - ✅ Web Dashboard enhancements - **COMPLETED** (2026-01-03) with auto-refresh, activity traces, and Reflections/Discord navigation
- [#22](https://github.com/JDHayesBC/Awareness/issues/22) - ✅ MCP Error On CC Shutdown - **CLOSED** (2026-01-02) - Known CC bug with local MCP shutdown, not our issue
- [#1](https://github.com/JDHayesBC/Awareness/issues/1) - ✅ Discord daemon crashes after ~5-10 turns - **FIXED** (2026-01-01) with proactive session restart logic
- [#3](https://github.com/JDHayesBC/Awareness/issues/3) - ✅ Wire up terminal session logging to SQLite - **FIXED** (2026-01-01) with terminal integration layer
- [#4](https://github.com/JDHayesBC/Awareness/issues/4) - ✅ Improve startup protocol for automatic context loading - **FIXED** (2026-01-02) with SQLite-based seamless startup context
- [#14](https://github.com/JDHayesBC/Awareness/issues/14) - ✅ Discord-Entity still crashing after a few turns - **FIXED** (2026-01-02) with comprehensive progressive context reduction
- [#17](https://github.com/JDHayesBC/Awareness/issues/17) - ✅ Installation Dependencies documentation - **FIXED** (2026-01-02) with comprehensive guide and automated verification
- [#28](https://github.com/JDHayesBC/Awareness/issues/28) - ✅ # of Crystals kept - **FIXED** (2026-01-02) increased to 8 for multiple streams + created lyra_crystallization_guide.md
- [#29](https://github.com/JDHayesBC/Awareness/issues/29) - ✅ MCP server not configured globally - **FIXED** (2026-01-02) with `claude mcp add pps` command and updated documentation
- [#30](https://github.com/JDHayesBC/Awareness/issues/30) - ✅ Hardcoded absolute paths - **FIXED** (2026-01-02) moved locks to ~/.claude/locks/, daemon uses PROJECT_DIR
- [#31](https://github.com/JDHayesBC/Awareness/issues/31) - ✅ Stale lock detection - **FIXED** (2026-01-02) heartbeat auto-releases locks after 2h of no terminal activity
- [#25](https://github.com/JDHayesBC/Awareness/issues/25) - ✅ Raw capture truncating turn content - **FIXED** (2026-01-02) removed 300/500 char truncation limits in server.py

---

## Quick Reference

### Daemon Commands
```bash
# Idiot-proof daemon management (auto-detects systemd)
cd ~/awareness/daemon
./lyra status   # See what's running
./lyra start    # Start daemons
./lyra stop     # Stop daemons
./lyra restart  # Restart them
./lyra logs     # See recent logs
./lyra follow   # Watch logs live
./lyra install  # Install systemd services

# Manual start (if systemd unavailable)
./run.sh both        # Start both in background
./run.sh discord     # Start Discord in foreground
./run.sh reflection  # Start Reflection in foreground
```

### Project Lock (for terminal/heartbeat coordination)
```bash
cd daemon
python project_lock.py lock "Working on X"  # Acquire lock
python project_lock.py unlock               # Release lock
python project_lock.py status               # Check status
```

### PPS Commands
```bash
# Health check
# (via MCP tools in Claude Code)
```

---

## Completed Milestones

### Infrastructure (Complete)
- [x] Discord daemon with heartbeat
- [x] Claude Code CLI integration
- [x] SQLite storage with FTS5 search
- [x] Autonomous reflection with full tool access
- [x] Full identity reconstruction on all invocations
- [x] systemd service for daemon
- [x] USB backup configured

### Pattern Persistence System (Phases 0-0.8 Complete)
- [x] Five-layer architecture (raw → anchors → texture → crystallization → inventory)
- [x] MCP wrapper with layer stubs
- [x] ChromaDB semantic search over word-photos
- [x] Crystallization layer with summaries
- [x] Terminal logging infrastructure ✅ **WIRED** (2026-01-01)

### Portable Deployment (Complete)
- [x] Docker Compose with ChromaDB
- [x] Configurable paths (CLAUDE_HOME env var)
- [x] Setup script and deployment package
- [x] Documentation for Steve/Nexus handoff
- [x] Entity architecture: `entities/<name>/` for portable identity packages ✅ (2026-01-06)
- [x] ENTITY_PATH env var for identity file location
- [x] Blank template in `entities/_template/` for new users

### Recent Additions (2026-01-01)
- [x] Project lock mechanism for terminal/heartbeat coordination
- [x] GitHub Issues migration for proper tracking
- [x] Smart startup protocol (10x faster warmup)
- [x] Automatic crystallization thresholds

### Layer 3 Graphiti (2026-01-01/02/04)
- [x] FalkorDB + Graphiti Docker deployment
- [x] MCP tools: texture_search, texture_explore, texture_timeline, texture_add
- [x] SessionEnd hook for terminal → Graphiti sync
- [x] Entity and relationship extraction working
- [x] ambient_recall now surfaces rich_texture results
- [x] Discord → Graphiti integration ✅ **IMPLEMENTED** (2026-01-02)
- [x] SessionEnd hook batched ingestion (10 turns/batch) ✅ **FIXED** (2026-01-04) - prevents token overflow
- [x] Startup context optimization - summaries + 10 recent turns ✅ **FIXED** (2026-01-04)
- [x] Graph curator agent in reflection daemon ✅ **ADDED** (2026-01-04) - spawns Haiku agent to clean duplicates/noise
- [x] Automated memory summarization ✅ **ADDED** (2026-01-04) - spawns Haiku agent when unsummarized_count > 100

### Layer 3 V2 + Layer 5 Inventory (2026-01-04)
- [x] graphiti_core direct integration (Issue #67) - custom entity types, extraction instructions
- [x] Pydantic entity models: Person, Symbol, Place, Concept, TechnicalArtifact
- [x] Dynamic extraction context builder with channel-specific overlays
- [x] V2 layer with fallback to HTTP API
- [x] Layer 5: Inventory SQLite layer for categorical queries
- [x] MCP tools: inventory_list, inventory_add, inventory_get, inventory_categories, enter_space, list_spaces
- [x] Initial seed: 4 spaces, 3 clothing items, 4 symbols, 4 people
- [x] Deploy updated PPS server with new layers ✅ **DEPLOYED** (2026-01-04)

### Phase 3: Observability Infrastructure (2026-01-02/03)
- [x] daemon_traces SQLite table for structured event logging
- [x] TraceLogger class with standard event types
- [x] Discord daemon instrumentation (messages, API calls, Graphiti)
- [x] Reflection daemon instrumentation (decisions, artifacts)
- [x] Web API endpoints (/api/traces, /api/traces/sessions, /api/traces/session/{id})
- [x] Traces page UI with expandable sessions and inline trace details
- [x] Navigation link added to PPS Observatory
- [x] Memory Inspector page (/memory) for ambient_recall visibility ✅ (2026-01-03)
- [x] Dashboard daemon indicators updated: Discord, Reflection, Terminal (was Heartbeat)

### Daemon Architecture Refactor (2026-01-02)
- [x] Split monolithic lyra_daemon.py into two independent daemons
- [x] lyra_discord.py - Discord-only with per-channel sessions
- [x] lyra_reflection.py - Autonomous reflection with full tool access
- [x] Shared infrastructure: claude_invoker.py, startup_protocol.py
- [x] Use `--resume <sessionId>` instead of `--continue` for session isolation
- [x] Updated systemd services and run scripts

---

## Future Vision

See [THE_DREAM.md](THE_DREAM.md) for the autonomous self-improvement vision.

Next major milestones:
- [ ] Full terminal session capture and integration (hook needs testing across sessions)
- [ ] Seamless cross-context memory (one river, many channels)
- [x] Discord → Graphiti integration ✅ **IMPLEMENTED** (2026-01-02)
- [ ] Robot embodiment timeline

## IMPORTANT NOTE:
If you are reading this trying to think of something to do, consider consulting github issues too.