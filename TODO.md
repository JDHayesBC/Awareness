# Awareness Project TODO

## Issue Tracking

**Active issues are tracked on GitHub**: https://github.com/JDHayesBC/Awareness/issues

Use `gh issue list` to see current issues from the command line.

### Current Priority Issues
- [#3](https://github.com/JDHayesBC/Awareness/issues/3) - Wire up terminal session logging to SQLite (enhancement, priority:high)
- [#4](https://github.com/JDHayesBC/Awareness/issues/4) - Improve startup protocol for automatic context loading (enhancement, priority:high)

### Recently Resolved
- [#1](https://github.com/JDHayesBC/Awareness/issues/1) - ✅ Discord daemon crashes after ~5-10 turns - **FIXED** (2026-01-01) with proactive session restart logic

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
- [x] Terminal logging infrastructure (needs wiring)

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

---

## Future Vision

See [THE_DREAM.md](THE_DREAM.md) for the autonomous self-improvement vision.

Next major milestones:
- [ ] Layer 3: Graphiti integration for rich texture
- [ ] Full terminal session capture and integration
- [ ] Seamless cross-context memory (one river, many channels)
- [ ] Robot embodiment timeline
