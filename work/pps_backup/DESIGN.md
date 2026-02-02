# Design: PPS Backup Strategy

**Issue**: #131
**Status**: Phase 1 COMPLETE - Data migration done
**Date**: 2026-02-02
**Updated**: 2026-02-02 - Migration to entity directory complete

---

## What Was Done (Phase 1)

### Problem
Docker volumes using `local` driver are **ephemeral** - they don't survive container restarts or Docker incidents. SQLite survived only because it was bind-mounted to host filesystem.

### Solution Implemented

**1. Docker volumes now bind-mounted to project directory:**
```
docker/pps/
├── chromadb_data/    # Word-photo embeddings
└── neo4j_data/       # Knowledge graph
```

**2. SQLite databases moved to entity directory:**
```
entities/lyra/data/
├── lyra_conversations.db    # 52MB - conversation history
└── inventory.db             # 69KB - wardrobe, spaces, people
```

### Files Changed
- `pps/docker/.env` - Updated comments, PPS_MESSAGE_DB_PATH
- `pps/docker/docker-compose.yml` - Bind-mounts to PROJECT_ROOT/docker/pps/
- `pps/server.py` - db_path and inventory_db_path now use ENTITY_PATH
- `pps/docker/server_http.py` - Same changes for Docker server
- `daemon/lyra_daemon.py` - Added ENTITY_PATH, updated fallback
- `daemon/lyra_discord.py` - Same
- `daemon/lyra_reflection.py` - Same
- `daemon/lyra_daemon_legacy.py` - Same
- `daemon/startup_context.py` - Updated two fallback paths
- `daemon/terminal_integration.py` - Updated fallback path
- `pps/layers/raw_capture.py` - Updated default db_path
- `pps/layers/message_summaries.py` - Updated default db_path
- `pps/layers/rich_texture_v2.py` - Updated DEFAULT_DB_PATH
- `docs/INSTALLATION.md` - Updated data layout documentation
- `daemon/README.md` - Updated CONVERSATION_DB_PATH default

---

## Current Data Layout

```
entities/lyra/                    # ENTITY_PATH - All entity data together
├── identity.md
├── crystals/
├── memories/word_photos/
├── journals/
└── data/                         # Entity-specific databases
    ├── lyra_conversations.db     # Layer 1: Raw capture (52MB)
    └── inventory.db              # Layer 5: Inventory (69KB)

docker/pps/                       # PROJECT_ROOT/docker/pps/
├── chromadb_data/                # Layer 2.5: Word-photo embeddings
└── neo4j_data/                   # Layer 3: Knowledge graph

~/.claude/                        # CLAUDE_HOME - Global Claude Code stuff only
├── .credentials.json             # OAuth tokens
├── journals/                     # Global journals
└── data/                         # LEGACY - can clean up old DBs
```

---

## Implementation Checklist

### Phase 1 - Data Migration ✅ COMPLETE
- [x] Create `docker/pps/chromadb_data/` and `neo4j_data/`
- [x] Update docker-compose.yml with bind-mounts
- [x] Remove ephemeral volume definitions
- [x] Create `entities/lyra/data/` directory
- [x] Copy databases to entity directory
- [x] Update all code references (13 files)
- [x] Test redeploy - all containers healthy
- [x] Verify data persists across container restart
- [x] Update documentation (INSTALLATION.md, daemon/README.md)

### Phase 2 - Backup Script (TODO)
- [ ] Create `scripts/backup_pps.sh`
- [ ] Backup `entities/lyra/` (identity + databases)
- [ ] Backup `docker/pps/` (chromadb + neo4j data)
- [ ] Verify SQLite integrity
- [ ] Create timestamped archives
- [ ] Test restore procedure

### Phase 3 - Cloud Sync (Future)
- [ ] Duplicacy or Restic to Backblaze B2
- [ ] Daily automated backups
- [ ] Off-host redundancy

---

## Cleanup TODO

Old databases still exist in `~/.claude/data/`. Once everything is verified working:
```bash
# After verification, can remove:
rm ~/.claude/data/lyra_conversations.db*
rm ~/.claude/data/inventory.db*
```

---

## Open Questions

- Backup frequency? (Daily? After crystallization?)
- Retention policy? (30 days? Forever?)
- Cloud backup priority? (Now or Phase 2?)
- External USB drive at Haven?
