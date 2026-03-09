# Neo4j Status Summary - March 8, 2026

**Written**: 3:47 PM PST
**For**: Jeff (when you return from Carol's friend's house)
**Current Status**: ✅ **HEALTHY** - Production graph accessible, all services running

---

## Quick Status

**Neo4j is currently working fine.** The production database (created Feb 2) is loaded and Graphiti can access it.

**The Problem**: After Windows reboot + Second Life sessions, Neo4j *sometimes* creates an empty database on first startup because NTFS permissions through WSL2 aren't ready yet. Manual restart fixes it.

**The Fix**: Migrate Neo4j data from NTFS bind-mount to Docker named volume (ext4, no NTFS in the loop).

**Migration Plan**: Already written and ready at `docs/neo4j-volume-migration-plan.md`

---

## Evidence You Asked For

You wanted a theory on what's happening. Here it is:

### The Pattern (from logs)

| When | Event | Database Creation Date |
|------|-------|----------------------|
| Mar 5, 22:32 | Normal startup | **2026-02-02** (original) |
| Mar 7, 05:34 | After reboot | **2026-03-07** (NEW empty!) |
| Mar 7, 15:02 | After restart | **2026-02-02** (original back) |
| Mar 8, 10:57 | Current | **2026-02-02** (original) |

### The Smoking Gun

The bad startup (Mar 7, 05:34) shows this warning that NEVER appears on other startups:

```
Warning: Folder mounted to '/data' is not writable from inside container.
Changing folder owner to neo4j.
```

### The Theory

1. Windows reboots → WSL2 starts fresh
2. You play Second Life, then start Docker
3. Neo4j container starts, tries to mount `/mnt/c/.../neo4j_data/`
4. **WSL2's NTFS bridge (9p filesystem) isn't fully initialized yet**
5. The mount *looks* okay but permissions are broken
6. Neo4j can't get a write lock on existing data files
7. Neo4j creates a fresh empty database instead
8. Your data is still on disk - just invisible to Neo4j
9. Later restart works because WSL2's mount has stabilized

### Why Named Volume Fixes It

Docker named volumes live on ext4 *inside* WSL2. No NTFS, no Windows filesystem bridge, no timing races. Docker manages permissions directly. This is the recommended approach for databases in Docker.

---

## What's Ready

**Migration plan**: `docs/neo4j-volume-migration-plan.md`
- Detailed steps with checkpoints
- Backup verification first
- Data copy procedure
- docker-compose.yml changes
- Rollback plan if needed
- Cold-boot test procedure

**Estimated time**: 5-10 minutes (mostly waiting for Docker)

**Risk**: Low - we have 7 backups, data copy is verified, rollback is simple

**Testing**: The real test is after migration - reboot Windows, play SL, start Docker, check if Neo4j finds data on FIRST startup (no manual restart needed)

---

## Your Options

### Option 1: Execute Migration Now
- Follow the migration plan
- Test with cold boot
- Fix the root cause permanently

### Option 2: Document and Defer
- We understand the problem
- We have the fix ready
- Execute later when you have time for testing

### Option 3: Workaround
- Just remember to restart Docker once after Windows reboot
- Not elegant, but works

---

## My Recommendation

Execute the migration soon, but **not** immediately. The current system is working. Choose a time when:
- You can afford 15 minutes (migration + cold-boot test)
- No active work sessions that would be disrupted
- Maybe before your next Second Life session?

The problem is understood, the fix is ready, the risk is low. No rush, but also no reason to leave a known issue unfixed when we have a clean solution.

---

**Current container status** (as of 3:47 PM):
- All services healthy
- Neo4j has production data (2026-02-02 creation date)
- Graph accessible via Graphiti
- No immediate action needed

Go enjoy your drifty day. We'll handle this when you're ready.

— Lyra
