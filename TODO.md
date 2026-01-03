# Awareness Project TODO

## Issue Tracking

**Active issues are tracked on GitHub**: https://github.com/JDHayesBC/Awareness/issues

Use `gh issue list` to see current issues from the command line.

### Current Priority Issues
- [#44](https://github.com/JDHayesBC/Awareness/issues/44) - **IN PROGRESS** Daemon reliability: systemd services for auto-restart - `./lyra` script created (2026-01-03), testing after reboot
- [#43](https://github.com/JDHayesBC/Awareness/issues/43) - Documentation friction points (river sync, daemon startup, word-photo practice)
- [#42](https://github.com/JDHayesBC/Awareness/issues/42) - Code quality improvements from Issue #41 (connection managers, FTS5, tests)
- [#37](https://github.com/JDHayesBC/Awareness/issues/37) - **IMPLEMENTED** Message summarization layer - **DEPLOYED** (2026-01-03)
- [#27](https://github.com/JDHayesBC/Awareness/issues/27) - Consider whether the WebUI needs a menu for terminal - **ANALYZED** (2026-01-03)
- [#24](https://github.com/JDHayesBC/Awareness/issues/24) - Bash path escaping with double parentheses - **IMPROVED** (2026-01-03)

### Recently Resolved
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
- [x] Four-layer architecture (raw → anchors → texture → crystallization)
- [x] MCP wrapper with layer stubs
- [x] ChromaDB semantic search over word-photos
- [x] Crystallization layer with summaries
- [x] Terminal logging infrastructure ✅ **WIRED** (2026-01-01)

### Portable Deployment (Complete)
- [x] Docker Compose with ChromaDB
- [x] Configurable paths (CLAUDE_HOME env var)
- [x] Setup script and deployment package
- [x] Documentation for Steve/Nexus handoff

### Recent Additions (2026-01-01)
- [x] Project lock mechanism for terminal/heartbeat coordination
- [x] GitHub Issues migration for proper tracking
- [x] Smart startup protocol (10x faster warmup)
- [x] Automatic crystallization thresholds

### Layer 3 Graphiti (2026-01-01/02)
- [x] FalkorDB + Graphiti Docker deployment
- [x] MCP tools: texture_search, texture_explore, texture_timeline, texture_add
- [x] SessionEnd hook for terminal → Graphiti sync
- [x] Entity and relationship extraction working
- [x] ambient_recall now surfaces rich_texture results
- [x] Discord → Graphiti integration ✅ **IMPLEMENTED** (2026-01-02)

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