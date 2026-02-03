# PPS Backup & Restore - Quick Reference

**Emergency? Jump to [Disaster Recovery](#disaster-recovery)**

## Daily Operations

### Create a Backup
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
python3 scripts/backup_pps.py
```
Takes ~30 seconds. Creates 14-15 MB archive. Safe to run anytime.

### Check Backup Status
```bash
python3 scripts/backup_pps.py --check
```
Shows: last backup age, total backups, health status.

### List Available Backups
```bash
python3 scripts/restore_pps.py --list
```
Shows all backups with size, date, and age.

## Disaster Recovery

### If PPS Data Is Lost/Corrupted

1. **Stay Calm** - You have backups!

2. **List available backups:**
```bash
python3 scripts/restore_pps.py --list
```

3. **Preview the restore (DRY RUN - do this first!):**
```bash
python3 scripts/restore_pps.py --latest --dry-run
```
Review output carefully. Make sure it's restoring what you expect.

4. **Perform the restore:**
```bash
python3 scripts/restore_pps.py --latest
```
- Will prompt for confirmation twice (safety feature)
- Creates safety backup of current state automatically
- Stops containers, restores data, restarts containers
- Takes ~2-3 minutes

5. **Verify:**
```bash
docker compose ps
```
All containers should be running/healthy.

### If You Need an Older Backup
```bash
# List backups to find the one you want
python3 scripts/restore_pps.py --list

# Restore specific backup
python3 scripts/restore_pps.py --backup pps_backup_20260202_123731.tar.gz
```

## Common Scenarios

### Restore Everything Except Databases
Useful if DBs are fine but identity/memories are corrupted:
```bash
python3 scripts/restore_pps.py --latest --skip chromadb neo4j
```

### Restore Only Databases
Useful if memories are fine but DB is corrupted:
```bash
python3 scripts/restore_pps.py --latest --skip entity_identity crystals word_photos
```

### Before Major Changes
Create a backup first, so you can roll back:
```bash
python3 scripts/backup_pps.py
# Make your changes
# If something breaks:
python3 scripts/restore_pps.py --latest
```

## File Locations

### Backups
- **Location:** `/mnt/c/Users/Jeff/awareness_backups/`
- **Pattern:** `pps_backup_YYYYMMDD_HHMMSS.tar.gz`
- **Retention:** 7 most recent (configurable with `--keep`)

### Safety Backups
- **Location:** `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/pps_backup/pre_restore_safety/`
- **Created:** Automatically before each restore
- **Purpose:** Safety net in case restore goes wrong

### Scripts
- **Backup:** `scripts/backup_pps.py`
- **Restore:** `scripts/restore_pps.py`

## What Gets Backed Up / Restored

| Component | Critical? | Size | Rebuildable? |
|-----------|-----------|------|--------------|
| SQLite DBs (conversations, inventory, email) | **YES** | ~60 MB | No - irreplaceable |
| Entity identity files | **YES** | ~30 KB | Partial (in git) |
| Crystals | **YES** | ~100 KB | No - irreplaceable |
| Word photos | **YES** | ~245 KB | No - irreplaceable |
| ChromaDB | No | ~3 MB | Yes (from word-photos) |
| Neo4j/Graphiti | No | ~17 bytes | Yes (from messages) |

## Flags Reference

### Backup Script
```bash
--dry-run           # Preview without creating backup
--keep N            # Keep N most recent backups (default: 7)
--no-stop           # Don't stop containers (risky)
--check             # Just check backup health
--backup-dir PATH   # Custom backup directory
```

### Restore Script
```bash
--list                 # List available backups
--latest               # Restore most recent backup
--backup FILE          # Restore specific backup
--dry-run              # Preview without restoring
--skip SOURCE [...]    # Skip specific components
--no-safety-backup     # Skip creating safety backup (DANGEROUS)
--yes                  # Skip confirmation prompts (DANGEROUS)
```

## Safety Features

### Backup Script
- Stops containers before backup (clean snapshot)
- Verifies archive integrity
- Auto-cleanup old backups
- Restarts containers automatically

### Restore Script
- **Validation:** Checks archive before restore
- **Confirmations:** Two prompts before destructive ops
- **Safety backup:** Auto-backup current state
- **Dry-run:** Preview before changes
- **Health check:** Verifies containers after restore

## When Things Go Wrong

### "Backup validation failed"
- Archive may be corrupted
- Try an older backup
- Check disk space

### "Failed to stop containers"
- Docker may not be running
- Try: `docker compose ps`
- Try: `docker compose stop` manually

### "Container health check failed"
- Give containers more time to start
- Check: `docker compose ps`
- Check logs: `docker compose logs pps-server`

### "Permission denied"
- May need to run with proper permissions
- Check WSL can access `/mnt/c/` paths

## Testing Recommendations

### Before First Production Use
1. Test `--list` (should show backups)
2. Test `--dry-run` (should preview without changes)
3. Consider testing in isolated environment first

### Monthly Maintenance
1. Check backup health: `python3 scripts/backup_pps.py --check`
2. Verify latest backup: `python3 scripts/restore_pps.py --list`
3. Test dry-run restore: `python3 scripts/restore_pps.py --latest --dry-run`

## Get Help

- Full backup documentation: `work/pps_backup/DESIGN.md`
- Restore testing results: `work/pps_backup/RESTORE_TESTING.md`
- Issue #131: Original implementation tracker

---

**Remember:**
- Always use `--dry-run` first!
- Backups are automatic, restores require intention
- When in doubt, create a backup before making changes
