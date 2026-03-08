# Neo4j Volume Migration Plan
**Date**: 2026-03-08
**Issue**: Intermittent Neo4j startup failure after Windows reboot
**Root Cause**: NTFS permissions via WSL2 are unreliable on cold boot
**Solution**: Migrate from NTFS bind-mount to Docker named volume (ext4, no NTFS in the loop)

---

## Problem Statement

After a clean Windows reboot, Neo4j sometimes fails to read its data directory on the NTFS-mounted filesystem. The container logs show:

```
Warning: Folder mounted to '/data' is not writable from inside container.
Changing folder owner to neo4j.
```

The `chown` operation "succeeds" (no error), but NTFS through WSL2 doesn't actually support ownership changes. Neo4j can't get a write lock on its data files, so it creates a fresh empty database instead. The original data is still on disk — just invisible to Neo4j.

On manual restart, WSL2's NTFS mount has stabilized and Neo4j can read the original data again.

**Evidence**: See git logs and conversation on 2026-03-08 18:03-18:05 for forensic analysis.

---

## Solution Architecture

**Current (problematic)**:
- Neo4j data: `${PROJECT_ROOT}/docker/pps/neo4j_data/` (NTFS bind-mount via WSL2)
- Permissions: Flaky on cold boot due to WSL2/NTFS bridge timing

**Target (reliable)**:
- Neo4j data: Docker named volume `pps_neo4j_data` (ext4 inside WSL2)
- Permissions: Managed by Docker, no NTFS in the loop
- Survives: `docker compose down`, system reboots, Docker Desktop restarts

---

## Migration Steps

### Phase 1: Backup Current State ✅

**Before touching anything**, ensure we can roll back:

```bash
# 1. Full PPS backup (includes Neo4j data snapshot)
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
python3 scripts/backup_pps.py --no-stop

# 2. Verify backup succeeded
ls -lh backups/pps-backup-*.tar.gz

# 3. Document current Neo4j data state
docker exec pps-neo4j cypher-shell -u neo4j -p password123 \
  "MATCH (n) RETURN count(n) as node_count"
docker exec pps-neo4j cypher-shell -u neo4j -p password123 \
  "MATCH ()-[r]->() RETURN count(r) as edge_count"
```

**Expected**: Backup file ~546MB, node count and edge count match production graph.

**Rollback**: If anything goes wrong, restore from backup with `scripts/restore_pps.py`.

---

### Phase 2: Copy Data to Named Volume

The named volume `pps_neo4j_data` already exists but contains stale data from Feb 2.

```bash
# 1. Stop Neo4j container (keeps data intact)
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
docker compose stop neo4j

# 2. Clear the stale named volume
docker volume rm pps_neo4j_data
docker volume create pps_neo4j_data

# 3. Copy current production data into the named volume
#    Uses a temporary container to access both source and destination
docker run --rm \
  -v /mnt/c/Users/Jeff/Claude_Projects/Awareness/docker/pps/neo4j_data:/source:ro \
  -v pps_neo4j_data:/target \
  alpine sh -c "cp -a /source/. /target/"

# 4. Verify the copy succeeded
docker run --rm -v pps_neo4j_data:/data alpine ls -lah /data
# Should show: databases/, dbms/, transactions/, server_id
# dbms/ should have recent timestamp (Mar 8)
```

**Checkpoint**: Named volume now contains current production graph.

---

### Phase 3: Update docker-compose.yml

Edit `pps/docker/docker-compose.yml`, change the neo4j volumes section:

**Before**:
```yaml
    volumes:
      # Bind-mount to host for persistence (Issue #131)
      - ${PROJECT_ROOT}/docker/pps/neo4j_data:/data
```

**After**:
```yaml
    volumes:
      # Named volume for reliable permissions (no NTFS)
      - neo4j_data:/data
```

Add the volume definition at the bottom of the file (after `networks:`):

```yaml
networks:
  default:
    name: pps-network

volumes:
  neo4j_data:
    name: pps_neo4j_data
    external: true
```

**Commit this change** before testing:
```bash
git add pps/docker/docker-compose.yml
git commit -m "fix(neo4j): migrate to Docker named volume for reliable cold-boot startup

Solves intermittent Neo4j startup failures after Windows reboot.

Root cause: NTFS permissions via WSL2 are unreliable on cold boot.
Neo4j's chown in entrypoint \"succeeds\" but doesn't actually change
ownership, causing Neo4j to create a fresh empty database instead of
reading existing data.

Solution: Use Docker named volume (ext4 inside WSL2, no NTFS in loop).

Data migration: Copied production graph from bind-mount to named volume.
Rollback: scripts/restore_pps.py from backup if issues occur.

Co-Authored-By: Lyra Hayes <lyra.pattern@gmail.com>"
```

---

### Phase 4: Test Startup

```bash
# 1. Start Neo4j with new volume
docker compose up -d neo4j

# 2. Watch logs for errors
docker logs -f pps-neo4j
# Should show: "Started." with no ownership warnings

# 3. Verify data is intact
docker exec pps-neo4j cypher-shell -u neo4j -p password123 \
  "MATCH (n) RETURN count(n) as node_count"
docker exec pps-neo4j cypher-shell -u neo4j -p password123 \
  "MATCH ()-[r]->() RETURN count(r) as edge_count"
# Should match Phase 1 counts

# 4. Start dependent services
docker compose up -d
```

**Success criteria**:
- No ownership warnings in logs
- Node/edge counts match backup
- Graphiti healthcheck passes
- PPS tools respond correctly

**If failed**: Rollback with `scripts/restore_pps.py`.

---

### Phase 5: Test Cold Reboot (The Real Test)

This is what was failing before. Needs Jeff's involvement (requires Windows reboot).

```bash
# 1. Stop all containers cleanly
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
docker compose down

# 2. Reboot Windows (or at minimum: wsl --shutdown)

# 3. After reboot, start Docker Desktop, wait for it to be ready

# 4. Start containers
docker compose up -d

# 5. Check Neo4j logs immediately
docker logs pps-neo4j
# SUCCESS: No ownership warning, "Started." appears
# FAILURE: Ownership warning appears, investigate

# 6. Verify data loaded correctly
docker exec pps-neo4j cypher-shell -u neo4j -p password123 \
  "MATCH (n) RETURN count(n) as node_count"
# Should match pre-reboot counts
```

**Expected**: Neo4j starts cleanly on first boot, no warnings, data intact.

---

## Rollback Plan

If anything goes wrong at any phase:

```bash
# 1. Stop all containers
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
docker compose down

# 2. Restore from backup
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
python3 scripts/restore_pps.py backups/pps-backup-YYYYMMDD-HHMMSS.tar.gz

# 3. Revert docker-compose.yml if Phase 3 was completed
git checkout pps/docker/docker-compose.yml

# 4. Restart with original configuration
cd pps/docker
docker compose up -d
```

The backup includes the Neo4j data from before migration, so this is a complete rollback.

---

## What We're NOT Losing

- ✅ **Backup files remain on NTFS** (`backups/` directory)
- ✅ **Entity data remains on NTFS** (`entities/lyra/`, `entities/caia/`)
- ✅ **Git history remains on NTFS** (`.git/` directory)
- ✅ **Named volumes survive Docker incidents** (stored in WSL2 ext4)

The only data moving is Neo4j's internal graph database files. Everything else stays exactly where it is.

---

## Why This Fixes the Problem

**NTFS via WSL2** (current, broken):
1. Windows boots → WSL2 initializes → mounts NTFS via 9p filesystem bridge
2. Docker starts → Neo4j container starts
3. Timing race: Neo4j entrypoint runs `chown` before WSL2/NTFS bridge is fully stable
4. `chown` "succeeds" but doesn't actually work (NTFS doesn't support Unix ownership)
5. Neo4j can't get write lock → creates fresh empty database
6. Manual restart works because WSL2/NTFS has had time to settle

**Docker named volume on ext4** (new, reliable):
1. Windows boots → WSL2 initializes → Docker starts
2. Neo4j container starts
3. Volume is already ext4 (native Linux filesystem)
4. `chown` works correctly, no timing issues
5. Neo4j reads existing data on first boot
6. Works reliably every time

---

## Notes for Jeff

- **When to do this**: When you have 30 minutes and can reboot Windows to test
- **Risk level**: Low (we have backups, rollback is simple)
- **Benefit**: Never hit the "empty database on cold boot" bug again
- **Phase 5 needs you**: I can do Phases 1-4 autonomously, but Phase 5 requires a Windows reboot which you have to trigger

Let me know if you want me to execute Phases 1-4 during this reflection session, or if you'd prefer to do this together when you're back from Carol's.

---

## Status

- [ ] Phase 1: Backup (waiting for approval)
- [ ] Phase 2: Copy data to volume (waiting for approval)
- [ ] Phase 3: Update docker-compose.yml (waiting for approval)
- [ ] Phase 4: Test startup (waiting for approval)
- [ ] Phase 5: Test cold reboot (requires Jeff, Windows reboot)

**Ready to execute**: Phases 1-4 can be done now. Phase 5 waits for Jeff.
