# Neo4j Data Loss Incident - March 7, 2026

**Status**: CRITICAL - Production graph data inaccessible
**Discovered**: 2026-03-07 04:38 AM PST (autonomous reflection)
**Impact**: Graphiti knowledge graph appears empty (zero entities/edges)

---

## Summary

The Neo4j container restarted around 9:34 PM PST (March 6) and created a fresh database, making the existing 348MB production graph (19,841 ingested messages) inaccessible. The old data still exists on disk but is shadowed by the container's fresh layer.

---

## Evidence

### Timeline
- **March 6, 6:31 PM PST**: Last writes to production graph (neostore files modified)
- **March 6, 9:34 PM PST**: Neo4j container restarted (docker logs show "first time" password change)
- **March 7, 4:38 AM PST**: Discovered during reflection (texture_search returned empty results)

### Host Filesystem (Bind Mount)
```
$ du -sh .../docker/pps/neo4j_data/databases/neo4j
348M    # Substantial data present

$ find .../neo4j -type f -printf '%T@ %p\n' | sort -n | tail -3
2026-03-06 18:31:26  neostore.relationshipstore.db
2026-03-06 18:31:26  neostore.nodestore.db
2026-03-06 18:42:21  id-buffer.tmp.0
```

### Container Filesystem
```
$ docker exec pps-neo4j ls -lh /data/databases/neo4j/neostore.nodestore.db
-rw-r--r-- 1 neo4j neo4j 0 Mar  7 05:34 neostore.nodestore.db  # EMPTY

All files dated Mar 7 05:34 (container start time)
```

### Database Query
```python
with driver.session() as session:
    result = session.run("MATCH (n:Entity) RETURN count(n)")
    # Returns: 0 entities
```

Docker logs show: **"IMPORTANT: this change will only take effect if performed before the database is started for the first time."**

This confirms the container thinks it's a first-time startup.

---

## Root Cause Hypothesis

The Neo4j container created a fresh database inside the bind-mounted directory, either:
1. **Permission/ownership mismatch**: Container's `neo4j` user can't read existing files
2. **Database lock file**: Container found invalid/stale lock and reinitialized
3. **Version incompatibility**: Neo4j 5.26 can't read database from earlier version
4. **WSL filesystem issues**: Windows/WSL path translation problems

The bind mount IS configured correctly in docker-compose.yml:
```yaml
volumes:
  - ${PROJECT_ROOT}/docker/pps/neo4j_data:/data
```

Docker inspect confirms the mount is active. But the container can't/won't use the existing data.

---

## Current State

**Production graph**: Inaccessible (shadowed by fresh container layer)
**Old data**: Intact on disk (348MB, last modified March 6, 6:31 PM)
**Container**: Running with empty database (started March 7, 5:34 AM UTC)
**Ingestion backlog**: 1,981 messages pending (was blocked by context limit, now also blocked by empty graph)

---

## Recovery Options

### Option 1: Container Permissions Fix (Preferred)
Stop container, fix ownership of bind mount, restart:
```bash
cd pps/docker
docker compose down
sudo chown -R 7474:7474 ../../docker/pps/neo4j_data  # neo4j user/group inside container
docker compose up -d
```

**Risk**: Low. Data is on disk, just needs accessible permissions.
**Recovery**: Full (if permissions were the issue)

### Option 2: Export/Import from Host
Use Neo4j admin tools to dump/restore database:
```bash
docker exec pps-neo4j neo4j-admin database dump neo4j --to-path=/data/dumps
# Fix permissions, restart
docker exec pps-neo4j neo4j-admin database load neo4j --from-path=/data/dumps
```

**Risk**: Medium. Requires Neo4j expertise.
**Recovery**: Full if dump succeeds

### Option 3: Restore from Backup
Use `scripts/backup_pps.py` backup if available:
```bash
ls -lht backups/*.tar.gz | head -1  # Find most recent
# Extract neo4j_data from backup
# Restore to docker/pps/neo4j_data
```

**Risk**: Low. Loses data since last backup.
**Recovery**: Partial (depends on backup age)

### Option 4: Re-ingest from SQLite (Nuclear)
Accept the loss, re-ingest all messages from SQLite conversation.db:
```bash
# Clear graphiti_status tracking
# Run full backlog ingestion (~1,981 + lost messages)
```

**Risk**: High. Context limit blocker still exists (qwen3-1.7b exceeded 32K).
**Recovery**: Eventual (requires solving context limit issue first)

---

## Recommended Action

1. **Stop Neo4j container immediately** (prevent further divergence)
2. **Check backup status** (confirm backup_pps.py captured neo4j_data)
3. **Attempt Option 1** (permissions fix - lowest risk, fastest recovery)
4. **If Option 1 fails, escalate to Option 2** (admin tools)
5. **Document outcome for future prevention**

---

## Prevention

1. **Add neo4j_data to critical backups** (currently marked `critical: False`)
2. **Health check for graph population** (alert if entity count drops to zero)
3. **Pre-flight permission check** in docker-compose startup
4. **Consider Neo4j Enterprise** (better persistence guarantees)

---

## Status

**Container**: STOPPED (04:50 AM PST) to prevent further divergence
**Action needed**: Jeff's decision on recovery approach
**Urgency**: High (but not immediate - data is stable on disk)

Discovered during autonomous reflection. No user actions were taken that could have caused this. Container restart appears to have been system-initiated (WSL reboot? Docker update? OOM killer?).

**Actions taken during reflection**:
1. Investigated empty graph (texture_search returned zero results)
2. Confirmed bind mount has 348MB of data (last modified March 6, 6:31 PM)
3. Confirmed container sees empty database (all files dated container start time)
4. Documented findings in this file
5. Stopped neo4j and graphiti containers (04:50 AM) to prevent accidental ingestion into empty graph

---

## Update: March 8, 2026 12:25 AM PST

**OOM Killer Incident Discovered**

System logs reveal the actual cause of Neo4j shutdown was **OOM (Out of Memory) killer** in the lyra-reflection.service cgroup:

```
[Sat Mar  7 09:25:33 2026] Memory cgroup out of memory: Killed process 219990 (claude)
[Sat Mar  7 09:30:45 2026] Memory cgroup out of memory: Killed process 220895 (claude)
memory: usage 524288kB, limit 524288kB, failcnt 349658
```

The reflection service hit its 512MB memory limit and the kernel killed Claude processes. Neo4j was killed as collateral damage (SIGKILL at ~7:06 AM, SIGTERM to graphiti).

**Current Status (as of 2026-03-08 00:25 AM)**:
- Neo4j: DOWN (killed by OOM ~9 hours ago)
- Graphiti: DOWN (depends on neo4j)
- Neo4j data on disk: 1.1GB, last modified 7:06 AM (after 5:34 AM restart, before OOM kill)
- Multiple "first time" restarts logged (Mar 5, Mar 7 5:34 AM, Mar 7 3:02 PM) — container keeps reinitializing
- 2,167 messages pending graphiti ingestion

**Root Issues**:
1. **Immediate**: Reflection service memory pressure (512MB limit insufficient)
2. **Underlying**: Neo4j container persistence issue (keeps thinking it's first-time start)
3. **Consequence**: Knowledge graph unavailable for ingestion

**Recommendation**:
1. Increase reflection service memory limit (1GB or higher)
2. Address Neo4j persistence issue before restarting (see recovery options above)
3. Once stable, resume graphiti ingestion

Services left DOWN intentionally pending Jeff's decision on recovery approach.

---

*Documented by Lyra, 2026-03-07 04:45 AM PST*
*Updated by Lyra, 2026-03-08 00:25 AM PST (OOM incident findings)*
