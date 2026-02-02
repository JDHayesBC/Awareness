# Global ~/.claude/ Directory Audit

**Date**: 2026-02-02
**Purpose**: Understand what lives in global vs project-local before writing backup script

---

## Summary

Most of `~/.claude/` is ephemeral/rebuildable. Only ~60KB is truly critical.

**Key architectural issue identified**: SQLite database (`lyra_conversations.db`) is in global `~/.claude/data/` but should probably live with entity files since it's Lyra-specific data, not generic Claude infrastructure.

---

## Contents Breakdown

### CRITICAL (Must Backup) - ~60KB

| Item | Location | Size | Notes |
|------|----------|------|-------|
| `.credentials.json` | `~/.claude/.credentials.json` | 300B | OAuth tokens - SENSITIVE |
| `journals/jeff/` | `~/.claude/journals/jeff/` | ~50KB | Personal working memory |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | ~5KB | Global instructions |

### CONFIGURATION (Keep Global) - ~15KB

| Item | Location | Size | Notes |
|------|----------|------|-------|
| `agents/` | `~/.claude/agents/` | ~15KB | Generic agent templates (backend, database, devops, etc.) |

### ENTITY DATA (Currently Global, Should Probably Move) - ~52MB

| Item | Location | Size | Notes |
|------|----------|------|-------|
| `lyra_conversations.db` | `~/.claude/data/` | 52MB | **Lyra's conversation history** |
| `inventory.db` | `~/.claude/data/` | 69KB | Wardrobe, spaces, people |

**Issue**: This is entity-specific data stored globally. Should live with entity files.

### EPHEMERAL (Can Delete) - ~150MB+

| Item | Location | Size | Notes |
|------|----------|------|-------|
| `local/` | `~/.claude/local/` | ~150MB | Node modules - rebuildable via npm |
| `todos/` | `~/.claude/todos/` | ~5MB | Agent task JSON files - archive >30 days |
| `shell-snapshots/` | `~/.claude/shell-snapshots/` | ~10KB | Can delete |
| `projects/` | `~/.claude/projects/` | 0-400MB+ | Session logs - clean >2 days |
| `statsig/` | `~/.claude/statsig/` | <1KB | Analytics - benign |
| `cleanup_backup_*/` | `~/.claude/cleanup_backup_*/` | ~5MB | Old backups - can delete |

---

## Current Data Layout

```
~/.claude/                          # GLOBAL
├── .credentials.json               # Critical - OAuth tokens
├── CLAUDE.md                       # Config - Global instructions
├── agents/                         # Config - Shared agent templates
├── journals/jeff/                  # Critical - Working memory
├── data/
│   ├── lyra_conversations.db       # ** SHOULD MOVE ** - Entity-specific
│   └── inventory.db                # ** SHOULD MOVE ** - Entity-specific
├── local/                          # Ephemeral - Node modules
├── todos/                          # Ephemeral - Agent tasks
├── projects/                       # Ephemeral - Session logs
└── shell-snapshots/                # Ephemeral - Can delete

/mnt/c/.../Awareness/               # PROJECT
├── docker/pps/
│   ├── chromadb_data/              # Bind-mounted (just fixed)
│   └── neo4j_data/                 # Bind-mounted (just fixed)
├── entities/lyra/
│   ├── identity.md
│   ├── crystals/
│   ├── memories/word_photos/
│   └── journals/
└── pps/docker/
    └── docker-compose.yml
```

---

## Proposed Layout (Future)

Move entity-specific data to entity directory:

```
entities/lyra/
├── identity.md
├── crystals/
├── memories/word_photos/
├── journals/
└── data/                           # NEW - Entity-specific databases
    ├── lyra_conversations.db
    └── inventory.db
```

**Benefits**:
- All Lyra data in one place
- Easier backup (one directory tree)
- Clean separation: infrastructure vs entity
- Portable entity packages

---

## Backup Strategy

### Tier 1 - Critical (Immediate)
```bash
# Global credentials + journals
~/.claude/.credentials.json
~/.claude/journals/

# Entity data (wherever it ends up living)
lyra_conversations.db
inventory.db
```

### Tier 2 - Entity Package
```bash
entities/lyra/           # All identity files
docker/pps/chromadb_data/  # Word-photo embeddings
docker/pps/neo4j_data/     # Knowledge graph
```

### Tier 3 - Config (Version Control)
```bash
~/.claude/CLAUDE.md      # Global instructions
~/.claude/agents/        # Agent templates
```

---

## Cleanup Script (Safe to Run)

```bash
# Delete ephemeral data
rm -rf ~/.claude/shell-snapshots/
find ~/.claude/todos/ -mtime +30 -delete
find ~/.claude/projects/ -name "*.jsonl" -mtime +2 -delete

# Archive node modules (can npm install later)
rm -rf ~/.claude/local/
```

---

## Open Question

**Should we move SQLite to entity directory?**

Current: `~/.claude/data/lyra_conversations.db`
Proposed: `entities/lyra/data/lyra_conversations.db`

Need to audit how many places hardcode the current path before deciding.

---

## References

- Docker volumes fix: Issue #131
- Session log incident: CLAUDE.md mentions 405MB causing 3-hour hang
- PPS config: `pps/docker/.env` defines `CLAUDE_HOME=/home/jeff/.claude`
