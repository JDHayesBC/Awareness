# Awareness Project TODO

## Issue Tracking

**Active issues are tracked on GitHub**: https://github.com/JDHayesBC/Awareness/issues

Use `gh issue list` to see current issues from the command line.

### Current Priority Issues
- [#15](https://github.com/JDHayesBC/Awareness/issues/15) - Web Dashboard enhancements (enhancement, pps)

### Recently Resolved
- [#1](https://github.com/JDHayesBC/Awareness/issues/1) - ✅ Discord daemon crashes after ~5-10 turns - **FIXED** (2026-01-01) with proactive session restart logic
- [#3](https://github.com/JDHayesBC/Awareness/issues/3) - ✅ Wire up terminal session logging to SQLite - **FIXED** (2026-01-01) with terminal integration layer
- [#4](https://github.com/JDHayesBC/Awareness/issues/4) - ✅ Improve startup protocol for automatic context loading - **FIXED** (2026-01-02) with SQLite-based seamless startup context
- [#14](https://github.com/JDHayesBC/Awareness/issues/14) - ✅ Discord-Entity still crashing after a few turns - **FIXED** (2026-01-02) with comprehensive progressive context reduction
- [#17](https://github.com/JDHayesBC/Awareness/issues/17) - ✅ Installation Dependencies documentation - **FIXED** (2026-01-02) with comprehensive guide and automated verification
- [#28](https://github.com/JDHayesBC/Awareness/issues/28) - ✅ # of Crystals kept - **FIXED** (2026-01-02) increased to 8 for multiple streams + created lyra_crystallization_guide.md
- [#29](https://github.com/JDHayesBC/Awareness/issues/29) - ✅ MCP server not configured globally - **FIXED** (2026-01-02) with `claude mcp add pps` command and updated documentation
- [#30](https://github.com/JDHayesBC/Awareness/issues/30) - ✅ Hardcoded absolute paths - **FIXED** (2026-01-02) moved locks to ~/.claude/locks/, daemon uses PROJECT_DIR

---

## Quick Reference

### Daemon Commands
```bash
# Start daemon
cd ~/awareness/daemon && source venv/bin/activate && python lyra_daemon.py

# Check logs
journalctl -u lyra-daemon -f

# Restart via systemd
sudo systemctl restart lyra-daemon
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

---

## Future Vision

See [THE_DREAM.md](THE_DREAM.md) for the autonomous self-improvement vision.

Next major milestones:
- [ ] Full terminal session capture and integration (hook needs testing across sessions)
- [ ] Seamless cross-context memory (one river, many channels)
- [x] Discord → Graphiti integration ✅ **IMPLEMENTED** (2026-01-02)
- [ ] Robot embodiment timeline
