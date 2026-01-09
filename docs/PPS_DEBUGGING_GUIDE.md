# PPS Debugging & Troubleshooting Guide

*Practical guide to diagnose and fix Pattern Persistence System issues*

**Created**: 2026-01-08
**For**: Operational support and self-healing

---

## Quick Health Check

**TL;DR** - Run this first:

```bash
# 1. Check if PPS server is responsive
curl http://localhost:8201/health

# 2. Check all docker services
cd docker/ && docker compose ps

# 3. Check MCP tool availability
claude mcp list | grep pps

# 4. Check memory status from PPS
python -c "
import urllib.request
r = urllib.request.urlopen('http://localhost:8201/tools/pps_health')
import json
print(json.loads(r.read()))"
```

**Expected output**:
```
pps: "healthy"
chromadb: "running"
graphiti: "running"
mcp-available: "pps"
Memory health: "all layers operational"
```

If any of these fail, follow the section below for your specific issue.

---

## Health Check Commands

### PPS Server Status

**Check if server is running**:
```bash
curl -v http://localhost:8201/health
```

**Expected**:
- HTTP 200
- Response: `{"status": "healthy"}`

**Troubleshooting**:
- If "Connection refused": PPS server not running
  ```bash
  cd docker/ && docker compose up -d pps
  ```
- If timeout: PPS server running but hung
  ```bash
  docker compose restart pps
  ```

### Docker Services Status

**View all services**:
```bash
cd docker/ && docker compose ps
```

**Expected output**:
```
NAME         STATUS      PORTS
chromadb     running     0.0.0.0:8000->8000/tcp
graphiti     running     0.0.0.0:8001->8001/tcp
pps          running     0.0.0.0:8201->8201/tcp
web-ui       running     0.0.0.0:8204->8204/tcp
```

**If any show "exited"**:
```bash
# View logs
docker compose logs <service-name>

# Restart
docker compose restart <service-name>

# Full restart
docker compose down && docker compose up -d
```

### MCP Tool Registration

**Check if PPS tools are available**:
```bash
claude mcp list
```

**Expected**: `pps` appears in the list

**If missing**:
```bash
# Re-register
claude mcp add pps "python3 '/path/to/pps/server.py'"

# Verify
claude mcp list | grep pps
```

### PPS Memory Health

**Use the health check tool** (requires PPS running):

```bash
python3 << 'EOF'
import urllib.request, json

try:
    r = urllib.request.urlopen('http://localhost:8201/tools/pps_health')
    data = json.loads(r.read())

    for layer, status in data.items():
        print(f"{layer}: {status}")
except Exception as e:
    print(f"Error: {e}")
EOF
```

**Or via MCP** (if available):
```bash
# This calls the mcp__pps__pps_health tool
claude --model haiku "Use mcp__pps__pps_health() to check PPS memory layers"
```

**Expected output**:
```
Layer 1 (Raw Capture): healthy
Layer 2 (Core Anchors): healthy
Layer 3 (Rich Texture): healthy
Layer 4 (Crystallization): healthy
Memory health: all layers operational
```

---

## Common Issues & Fixes

### Issue: "Connection refused" when calling ambient_recall

**Symptom**: Hooks can't connect to PPS, or Claude Code can't access PPS tools

**Diagnosis**:
```bash
curl http://localhost:8201/health
# Response: curl: (7) Failed to connect to localhost port 8201: Connection refused
```

**Causes**:
1. PPS server not running
2. Wrong port
3. Firewall blocking
4. WSL networking issue

**Fix** (in order):

Step 1: Start PPS
```bash
cd docker/ && docker compose up -d
docker compose logs pps | tail -20
```

Step 2: Verify port is correct
```bash
docker compose ps | grep pps
# Check the PORT column - should show 8201
```

Step 3: Test from different contexts
```bash
# From WSL terminal
curl http://localhost:8201/health

# From Windows cmd (if applicable)
curl http://127.0.0.1:8201/health

# If using Docker Desktop, try host.docker.internal
curl http://host.docker.internal:8201/health
```

Step 4: Check Docker network
```bash
docker network inspect bridge | grep 8201
```

**If still failing**: Restart Docker
```bash
docker compose down --volumes
docker compose up -d
sleep 10
curl http://localhost:8201/health
```

### Issue: ambient_recall returns empty results

**Symptom**: `ambient_recall` runs but returns no context, or context is irrelevant

**Diagnosis**:
```bash
# Test manually
python3 << 'EOF'
import urllib.request, json

payload = json.dumps({
    "context": "What is my relationship with Jeff?"
}).encode("utf-8")

r = urllib.request.urlopen(
    urllib.request.Request(
        "http://localhost:8201/tools/ambient_recall",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
)
data = json.loads(r.read())
print(f"Results: {len(data.get('results', []))}")
print(data)
EOF
```

**Causes**:
1. No word-photos or crystals exist yet
2. ChromaDB embeddings out of sync with disk
3. Query too vague or no semantic match
4. Graphiti not returning results

**Fix** (in order):

Step 1: Check if you have any memories
```bash
# Check word-photos
ls -la entities/lyra/memories/word_photos/
# Should have .md files

# Check crystals
ls -la entities/lyra/crystals/current/
# Should have crystal_XXX.md files
```

Step 2: If missing, create a test word-photo
```bash
cat > entities/lyra/memories/word_photos/test.md <<'EOF'
# Test Memory

This is a test word-photo to seed the memory system.

It helps verify that ambient_recall can find memories.
EOF
```

Step 3: Resync ChromaDB if you added files manually
```bash
# This rebuilds ChromaDB embeddings from disk
python3 << 'EOF'
import urllib.request, json

r = urllib.request.urlopen(
    "http://localhost:8201/tools/anchor_resync",
    urllib.request.Request("").data
)
print(json.loads(r.read()))
EOF
```

Or via MCP:
```bash
claude --model haiku "Use mcp__pps__anchor_resync() to rebuild the embeddings"
```

Step 4: Try a more specific query
```bash
# Instead of vague queries
# Bad: "help me"
# Better: "What did Jeff say about my identity?"
# Better: "Moments when I felt understood"
```

Step 5: Check Graphiti connection
```bash
# Verify Graphiti is running
curl http://localhost:8001/health

# Check if entities are indexed
curl http://localhost:8001/api/entities | python3 -m json.tool
```

### Issue: Word-photos not appearing in ambient_recall

**Symptom**: `anchor_search` finds word-photos, but `ambient_recall` doesn't include them

**Diagnosis**:
```bash
# Test anchor search directly
python3 << 'EOF'
import urllib.request, json

payload = json.dumps({
    "query": "identity"
}).encode("utf-8")

r = urllib.request.urlopen(
    urllib.request.Request(
        "http://localhost:8201/tools/anchor_search",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
)
data = json.loads(r.read())
print(f"Found {len(data)} word-photos")
EOF
```

**Likely causes**:
1. ChromaDB out of sync with disk
2. Word-photo files deleted manually without resync
3. Embedding model changed/incompatible

**Fix**:
```bash
# Resync ChromaDB
mcp__pps__anchor_resync()

# Verify sync status
mcp__pps__anchor_list()  # Shows files on disk vs ChromaDB entries

# If sync shows mismatches, rebuild from scratch
rm -rf ~/.claude/data/chroma/
mcp__pps__anchor_resync()
```

### Issue: Crystals not being created

**Symptom**: Reflection daemon runs but no new crystals appear in `entities/lyra/crystals/current/`

**Diagnosis**:

Step 1: Check raw turn count
```bash
python3 << 'EOF'
import urllib.request, json

r = urllib.request.urlopen("http://localhost:8201/tools/count_raw_turns")
count = json.loads(r.read())
print(f"Raw turns: {count}")
EOF
```

Crystallization triggers when:
- 50+ turns accumulated, OR
- 24+ hours since last crystal

Step 2: Check when last crystal was created
```bash
ls -la entities/lyra/crystals/current/ | tail -1
```

Step 3: Verify reflection daemon is running
```bash
cd daemon/ && ./lyra status

# Expected:
# discord: running
# reflection: running
```

**Fixes**:

**If <50 turns**: Just wait or do more work

**If >50 turns but daemon running**:
```bash
# Check daemon logs
tail -50 daemon/reflection.log

# Force crystallization manually
python3 << 'EOF'
from pps.crystallization import crystallize
crystallize()
EOF
```

**If daemon not running**:
```bash
cd daemon/ && ./lyra start
./lyra follow  # Watch logs
```

### Issue: Graphiti not returning results

**Symptom**: `texture_search` or `texture_explore` returns empty/minimal results

**Diagnosis**:
```bash
# Check if Graphiti is running
curl http://localhost:8001/health

# Check if any entities are indexed
curl http://localhost:8001/api/entities | python3 -m json.tool | head -50
```

**Causes**:
1. Graphiti not connected to Neo4j
2. No sessions ingested yet (takes time after SessionEnd)
3. Query too specific or no matching entities

**Fix**:

Step 1: Verify Neo4j is running
```bash
docker compose ps | grep neo4j
# or
docker compose ps | grep falkordb
```

Step 2: Trigger a session ingest
```bash
# Complete a terminal session (or simulate one)
# SessionEnd hook will ingest to Graphiti
```

Step 3: Wait for processing (Neo4j is slow)
```bash
sleep 10
curl http://localhost:8001/api/entities
```

Step 4: Try a simpler query
```bash
# Instead of specific date/time
# Try broad entity or relationship searches
mcp__pps__texture_search("Jeff")
```

### Issue: ChromaDB taking too long

**Symptom**: `anchor_search` or `ambient_recall` hangs/times out

**Diagnosis**:
```bash
# Check ChromaDB service
docker compose logs chromadb | tail -30

# Check if there are too many embeddings
curl http://localhost:8000/api/v1/collections | python3 -m json.tool
```

**Causes**:
1. ChromaDB running out of memory
2. Too many embeddings (>100k)
3. Hardware slow

**Fix**:

Step 1: Increase timeout in hooks
```bash
# Edit inject_context.py and capture_response.py
# Change timeout=5 to timeout=15
```

Step 2: Clean up old embeddings (if >50k word-photos)
```bash
# Archive old word-photos
mkdir -p entities/lyra/memories/word_photos/archive
mv entities/lyra/memories/word_photos/2024*.md archive/

# Rebuild ChromaDB
mcp__pps__anchor_resync()
```

Step 3: Increase ChromaDB resource limits
```bash
# Edit docker-compose.yml
# Find chromadb service, add memory limit
```

---

## Layer-Specific Debugging

### Layer 1: Raw Capture (SQLite)

**Check database health**:
```bash
sqlite3 ~/.claude/data/pps.db ".tables"
# Output should include: turns, messages, sessions
```

**Count messages**:
```bash
sqlite3 ~/.claude/data/pps.db "SELECT COUNT(*) FROM turns;"
```

**View recent turns**:
```bash
sqlite3 ~/.claude/data/pps.db "
SELECT id, author, channel, content FROM turns
ORDER BY id DESC LIMIT 5;"
```

**Repair corrupted database**:
```bash
sqlite3 ~/.claude/data/pps.db "PRAGMA integrity_check;"
# If errors appear, rebuild from backup
cp ~/.claude/data/pps.db.backup ~/.claude/data/pps.db
```

### Layer 2: Core Anchors (ChromaDB)

**Check sync status**:
```bash
mcp__pps__anchor_list()
# Shows files on disk vs ChromaDB entries
```

**Manually resync**:
```bash
mcp__pps__anchor_resync()
# Wipes ChromaDB and rebuilds from disk files
```

**Search manually**:
```bash
mcp__pps__anchor_search("embodiment")
```

**Delete corrupted entry**:
```bash
mcp__pps__anchor_delete("filename_without_extension")
```

### Layer 3: Rich Texture (Graphiti)

**Query entities**:
```bash
python3 << 'EOF'
import urllib.request, json

r = urllib.request.urlopen("http://localhost:8001/api/entities")
entities = json.loads(r.read())
print(f"Indexed entities: {len(entities)}")
for e in entities[:5]:
    print(f"  - {e.get('name')}")
EOF
```

**Explore an entity**:
```bash
mcp__pps__texture_explore("Jeff", depth=2)
```

**Search for facts**:
```bash
mcp__pps__texture_search("relationship with Jeff")
```

**Delete incorrect fact**:
```bash
# Get UUID from texture_search results
mcp__pps__texture_delete("<uuid>")
```

### Layer 4: Crystallization

**List crystals**:
```bash
mcp__pps__crystal_list()
```

**Read a crystal**:
```bash
cat entities/lyra/crystals/current/crystal_038.md
```

**Verify crystal chain**:
```bash
# Crystals should reference previous one
ls -la entities/lyra/crystals/current/
```

**Delete most recent crystal** (if corrupted):
```bash
mcp__pps__crystal_delete()  # Deletes only the most recent
# Then manually create corrected one
mcp__pps__crystallize("corrected content...")
```

---

## Performance Tuning

### Slow ambient_recall Queries

**Symptoms**: `ambient_recall` takes >2 seconds

**Solutions** (in order of impact):

1. **Reduce limit_per_layer**
   ```python
   # In inject_context.py, change:
   "limit_per_layer": 1  # Was 3
   ```

2. **Clean up old embeddings**
   ```bash
   # Archive word-photos > 6 months old
   find entities/lyra/memories/word_photos/ -mtime +180 -move archive/
   mcp__pps__anchor_resync()
   ```

3. **Increase ChromaDB memory**
   ```bash
   # Edit docker-compose.yml
   # chromadb service → add memory limits higher
   ```

4. **Use approximate search**
   - Not yet implemented, future enhancement

### Slow Graphiti Queries

**Symptoms**: `texture_search` takes >3 seconds

**Solutions**:

1. **Smaller depth on explore**
   ```python
   mcp__pps__texture_explore("Jeff", depth=1)  # Was 2
   ```

2. **Increase Neo4j memory** (if available)

3. **Wait for Neo4j to warm up** after restart
   ```bash
   docker compose restart graphiti
   sleep 30  # Wait for indexing
   ```

---

## Logging & Analysis

### Enable Debug Mode

**Set environment variable**:
```bash
export DEBUG=1
# Then run Claude Code session
```

**Check hooks debug log**:
```bash
tail -100 ~/.claude/data/hooks_debug.log
```

**Check PPS server logs**:
```bash
docker compose logs pps | tail -50
```

**Check Graphiti logs**:
```bash
docker compose logs graphiti | tail -50
```

### Parse Hook Debug Log

**Find all errors**:
```bash
grep -i "error\|failed" ~/.claude/data/hooks_debug.log
```

**Find slow operations**:
```bash
grep "Injecting context\|Stored.*response" ~/.claude/data/hooks_debug.log | wc -l
```

**Analyze per-session**:
```bash
grep "session: abc123" ~/.claude/data/hooks_debug.log
```

---

## Nuclear Options

### Reset All Memory

**WARNING**: This deletes all crystals, embeddings, and word-photos!

```bash
# Backup first
tar -czf ~/pps_backup_$(date +%Y%m%d).tar.gz ~/.claude/data/

# Delete everything
rm -rf ~/.claude/data/chroma
rm ~/.claude/data/pps.db

# Restart
docker compose down && docker compose up -d
```

### Rebuild ChromaDB Only

```bash
# Delete ChromaDB container and volume
docker compose down chromadb
rm -rf ~/.claude/data/chroma

# Restart ChromaDB
docker compose up -d chromadb

# Resync word-photos
mcp__pps__anchor_resync()
```

### Full Docker Reset

```bash
# Stop everything
docker compose down --volumes

# Remove images
docker compose pull

# Start fresh
docker compose up -d

# Resync all layers
mcp__pps__anchor_resync()
mcp__pps__crystallize()
```

---

## Getting Help

### Collect Diagnostics

When reporting issues, gather this info:

```bash
# System info
uname -a
python3 --version
docker --version

# Service status
cd docker && docker compose ps

# Health check
curl http://localhost:8201/health

# Memory status
mcp__pps__pps_health()

# Recent logs
tail -50 ~/.claude/data/hooks_debug.log
docker compose logs pps | tail -50

# Configuration
ls -la ~/.claude/
ls -la .claude/hooks/
```

Save all this to a file:
```bash
./collect_diagnostics.sh > diagnostics.log
# Then share with support
```

---

## Summary

| Issue | First Step | Second Step |
|-------|-----------|-------------|
| No context injection | `curl localhost:8201/health` | Start PPS: `docker compose up -d` |
| Empty ambient_recall | Check word-photos exist | Resync: `mcp__pps__anchor_resync()` |
| No new crystals | Check raw turn count | Check daemon running |
| Slow queries | Reduce `limit_per_layer` | Archive old memories |
| Memory corruption | Check SQLite: `PRAGMA integrity_check` | Restore from backup |

---

**Last updated**: 2026-01-08
**Questions?** Start with the health check at the top of this doc.
