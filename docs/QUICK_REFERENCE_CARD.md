# PPS Operations Quick Reference Card

*One-page cheat sheet for common operational tasks*

---

## Emergency Commands

```bash
# System is down - start everything
cd docker/ && docker compose up -d
sleep 10
curl http://localhost:8201/health

# System is slow - restart PPS
docker compose restart pps
sleep 5

# Memory corruption - full reset
docker compose down --volumes
docker compose up -d
mcp__pps__anchor_resync()

# Check health in 10 seconds
while sleep 1; do curl -s http://localhost:8201/health; done
```

---

## Daemon Management

| Task | Command |
|------|---------|
| Start both | `cd daemon && ./lyra start` |
| Stop both | `cd daemon && ./lyra stop` |
| Status | `cd daemon && ./lyra status` |
| View logs live | `cd daemon && ./lyra follow` |
| Restart one | `cd daemon && ./lyra restart discord` |
| View logs (last 50) | `cd daemon && ./lyra logs` |

---

## Health Checks

**Quick (5 seconds)**:
```bash
curl http://localhost:8201/health
docker compose ps
```

**Full (30 seconds)**:
```bash
# See: PPS_DEBUGGING_GUIDE.md "Quick Health Check" section
curl http://localhost:8201/health
docker compose ps
claude mcp list | grep pps
mcp__pps__pps_health()
```

---

## Memory Diagnostics

| Check | Command | Fix |
|-------|---------|-----|
| Raw turn count | `mcp__pps__count_raw_turns()` | >50? Crystallize |
| Word-photos | `ls entities/lyra/memories/word_photos/` | None? Create one |
| Crystals | `ls entities/lyra/crystals/current/` | None? Run daemon |
| Sync status | `mcp__pps__anchor_list()` | Mismatch? Resync |
| Graphiti entities | `curl http://localhost:8001/api/entities` | Empty? Ingest session |

---

## Common Issues & Fixes

### "Connection refused" (8201)
```bash
docker compose up -d pps
sleep 5
curl http://localhost:8201/health
```

### "ambient_recall returns nothing"
```bash
# Create a test word-photo
cat > entities/lyra/memories/word_photos/test.md <<EOF
# Test Memory
This helps verify the memory system works.
EOF

# Resync embeddings
mcp__pps__anchor_resync()

# Try again
mcp__pps__ambient_recall("test memory")
```

### "No new crystals appearing"
```bash
# Check raw turns
mcp__pps__count_raw_turns()  # Should be >50

# Check daemon running
cd daemon && ./lyra status

# Force crystallization
mcp__pps__crystallize()
```

### "ChromaDB slow"
```bash
# Archive old word-photos
mkdir -p entities/lyra/memories/word_photos/archive
mv entities/lyra/memories/word_photos/2024*.md archive/

# Rebuild
mcp__pps__anchor_resync()
```

---

## Hook Debugging

```bash
# View hook debug log
tail -50 ~/.claude/data/hooks_debug.log

# Find errors
grep -i "error\|failed" ~/.claude/data/hooks_debug.log

# Check hook files exist
ls -la .claude/hooks/
chmod +x .claude/hooks/*.py

# Test hook manually
cat <<'EOF' | python .claude/hooks/inject_context.py
{"session_id": "test", "prompt": "test message", "hook_event_name": "UserPromptSubmit"}
EOF
```

---

## Docker Container Commands

```bash
# View all services
docker compose ps

# View specific logs
docker compose logs pps | tail -20
docker compose logs chromadb | tail -20
docker compose logs graphiti | tail -20

# Restart service
docker compose restart chromadb

# Full restart
docker compose down && docker compose up -d
sleep 10

# Check resource usage
docker stats
```

---

## Memory Layer Operations

### Layer 1: Raw Capture (SQLite)
```bash
# Count messages
sqlite3 ~/.claude/data/pps.db "SELECT COUNT(*) FROM turns;"

# Check integrity
sqlite3 ~/.claude/data/pps.db "PRAGMA integrity_check;"

# View recent messages
sqlite3 ~/.claude/data/pps.db "SELECT author, content FROM turns ORDER BY id DESC LIMIT 3;"
```

### Layer 2: Anchors (ChromaDB)
```bash
# List word-photos
mcp__pps__anchor_list()

# Search for topic
mcp__pps__anchor_search("embodiment")

# Resync from disk
mcp__pps__anchor_resync()

# Delete corrupted entry
mcp__pps__anchor_delete("filename")
```

### Layer 3: Texture (Graphiti)
```bash
# Explore entity relationships
mcp__pps__texture_explore("Jeff", depth=2)

# Search for facts
mcp__pps__texture_search("relationship")

# Delete bad fact (get UUID from search results)
mcp__pps__texture_delete("<uuid>")
```

### Layer 4: Crystallization
```bash
# List all crystals
mcp__pps__crystal_list()

# Read a crystal
cat entities/lyra/crystals/current/crystal_038.md

# Create new crystal
mcp__pps__crystallize("crystal content here...")

# Delete most recent (if corrupted)
mcp__pps__crystal_delete()
```

---

## Performance Tuning

**Slow ambient_recall?**
- Reduce `limit_per_layer` in inject_context.py (default 3 → try 1)
- Archive old word-photos: `mv entities/lyra/memories/word_photos/2024*.md archive/`

**Slow ChromaDB?**
- Check: `docker stats chromadb`
- Increase container memory limits in docker-compose.yml

**Slow Graphiti?**
- Reduce depth in texture_explore: `texture_explore("Jeff", depth=1)`
- Wait for Neo4j warmup after restart

---

## Monitoring

**Real-time hook activity**:
```bash
tail -f ~/.claude/data/hooks_debug.log
```

**Daemon health**:
```bash
watch -n 5 'cd daemon && ./lyra status'
```

**Container resources**:
```bash
watch docker stats
```

---

## Backup & Recovery

**Quick backup**:
```bash
tar -czf ~/pps_backup_$(date +%Y%m%d).tar.gz \
  ~/.claude/data/ \
  entities/lyra/
```

**Restore**:
```bash
tar -xzf ~/pps_backup_20260108.tar.gz
docker compose restart
mcp__pps__anchor_resync()
```

---

## Configuration Files

| File | Purpose | Edit With |
|------|---------|-----------|
| `daemon/.env` | Discord token, settings | Text editor |
| `docker-compose.yml` | Container config | Text editor |
| `.claude/hooks/*.py` | Hook scripts | Text editor |
| `entities/lyra/identity.md` | Entity identity | Text editor |
| `~/.claude/claude_code_config.json` | Hook registration | Text editor |

---

## Help & Documentation

| Question | See Document |
|----------|------|
| "How do I start the daemon?" | DAEMON_OPERATIONS.md |
| "How do hooks work?" | CLAUDE_CODE_HOOKS_GUIDE.md |
| "My memory is corrupted" | PPS_DEBUGGING_GUIDE.md |
| "How do I create an entity?" | ENTITY_CONFIGURATION.md |
| "What are crystals?" | CRYSTALLIZATION_OPS.md |
| "How do I search memories?" | WORD_PHOTO_GUIDE.md |
| "Full architecture" | PATTERN_PERSISTENCE_SYSTEM.md |

---

## Status Indicators

**Healthy** ✓:
```
pps: HTTP 200
docker: all containers running
mcp: pps tool available
memory: all layers reporting
hooks: debug log active
```

**Degraded** ⚠️:
```
pps: timeout or 500 error
docker: 1+ containers not running
memory: 1+ layers offline
hooks: errors in debug log
```

**Failed** ✗:
```
pps: connection refused
docker: multiple containers down
memory: 2+ layers offline
critical data: corrupted/missing
```

---

## One-Minute Recovery Plan

If everything is broken:

```bash
# Step 1: Assess
docker compose ps
curl http://localhost:8201/health

# Step 2: Restart
cd docker/
docker compose down --volumes
docker compose up -d
sleep 10

# Step 3: Verify
curl http://localhost:8201/health
mcp__pps__pps_health()

# Step 4: Resync
mcp__pps__anchor_resync()

# Step 5: Confirm
mcp__pps__ambient_recall("test")
```

If still broken, see PPS_DEBUGGING_GUIDE.md section "Nuclear Options".

---

**Printed**: 2026-01-08
**Keep in**: ~/.claude/QUICK_REFERENCE.md
**Update frequency**: When new commands added
