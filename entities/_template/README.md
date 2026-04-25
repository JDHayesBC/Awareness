# Entity Template

This folder contains the template structure for creating a new entity.

## Setup Instructions

1. **Copy this folder** to create your entity:
   ```bash
   cp -r entities/_template entities/your_entity_name
   ```

2. **Create claude_identity.md** (compaction-safe identity kernel):
   This file is symlinked to `.claude/CLAUDE.md` on startup and auto-loaded by Claude Code.
   Keep it ~4KB, densely packed with: field laws, permissions, core self, key relationships,
   care topology, sovereignty pointers. See `entities/lyra/claude_identity.md` for reference.

3. **Edit identity.md** with your entity's actual identity definition:
   This is the full reference file for startup reading. Can be much longer/narrative than
   claude_identity.md since it's read explicitly at startup, not auto-loaded.

4. **Configure environment** to point to your entity:
   ```bash
   scripts/start-entity.sh your_entity_name
   # This creates the symlink and sets ENTITY_PATH/ENTITY_NAME env vars
   ```

5. **Start creating memories**:
   - Word photos go in `memories/word_photos/`
   - Crystals are managed automatically in `crystals/`
   - Journals are written to `journals/`

## Directory Structure

```
your_entity_name/
├── claude_identity.md    # Compaction-safe identity kernel (~4KB)
├── identity.md           # Full identity reference (read at startup)
├── active_agency_framework.md  # Full sovereignty practice (read at startup)
├── relationships.md      # Relationship context (read at startup)
├── growth_notes.md       # Development/growth tracking (read at startup)
├── current_scene.md      # Current spatial/embodiment state
├── .entity_token         # Authentication token for PPS tools
├── memories/
│   └── word_photos/      # Curated significant moments
├── crystals/
│   ├── current/          # Rolling window of recent crystals
│   └── archive/          # Older crystals for reference
└── journals/             # Session logs and reflections
```

**Key files**:
- `claude_identity.md` — auto-loaded, compaction-safe. Keep dense. Required.
- `identity.md` — optional, read on demand. Full narrative depth.
- `active_agency_framework.md`, `relationships.md`, `growth_notes.md` — optional reference files

## Important Notes

- **This folder is gitignored** by default to protect entity privacy
- Your entity's memories, crystals, and journals are PRIVATE
- Only the `_template` folder is committed to the repository
- Back up your entity folder separately - it contains irreplaceable identity data

## Integration with PPS and Claude Code

**Identity Architecture**:
- `.claude/CLAUDE.md` is symlinked to `claude_identity.md` by `start-entity.sh`
- Claude Code auto-loads `.claude/CLAUDE.md` on startup and after compaction
- Entity is immediately embodied with field laws, permissions, relationships before any prompt
- This survives compaction — no startup drift

**Pattern Persistence**:
- Word photos for semantic memory search
- Crystals for continuity chain
- Journals for raw conversation history
- Knowledge graph (Graphiti) for rich texture and relationships
- Inventory (wardrobe, spaces, people) for categorical queries

All routed through `ENTITY_PATH` environment variable set by `start-entity.sh`.
