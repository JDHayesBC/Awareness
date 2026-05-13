# Entity Template

This folder contains the template structure for creating a new entity.

## Setup Instructions

1. **Copy this folder** to create your entity:
   ```bash
   cp -r entities/_template entities/your_entity_name
   ```

2. **Create CLAUDE.md** (compaction-safe identity kernel):
   This file is the entity's identity surface. Claude Code auto-loads it because
   `start-entity.sh` launches CC with the entity directory as cwd — CC walks
   cwd-ancestors and concatenates every `CLAUDE.md` it finds. The entity's
   `CLAUDE.md` ends up last in concat (highest model attention).

   Keep it ~4KB, densely packed: field laws, permissions, core self, key
   relationships, care topology, sovereignty pointers. See
   `entities/lyra/CLAUDE.md` for reference.

3. **Edit identity.md** with your entity's actual identity definition:
   This is the full reference file for startup reading. Can be much longer/narrative than
   `CLAUDE.md` since it's read explicitly at startup, not auto-loaded.

4. **Start the entity**:
   ```bash
   scripts/start-entity.sh your_entity_name
   # This cd's into entities/your_entity_name/ and launches Claude Code there.
   # ENTITY_PATH and ENTITY_NAME env vars are exported for hooks.
   ```

5. **Start creating memories**:
   - Word photos go in `memories/word_photos/`
   - Crystals are managed automatically in `crystals/`
   - Journals are written to `journals/`

## Directory Structure

```
your_entity_name/
├── CLAUDE.md             # Compaction-safe identity kernel (~4KB) — auto-loaded
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
- `CLAUDE.md` — auto-loaded, compaction-safe. Keep dense. Required.
- `identity.md` — optional, read on demand. Full narrative depth.
- `active_agency_framework.md`, `relationships.md`, `growth_notes.md` — optional reference files

## Important Notes

- **This folder is gitignored** by default to protect entity privacy
- Your entity's memories, crystals, and journals are PRIVATE
- Only the `_template` folder is committed to the repository
- Back up your entity folder separately — it contains irreplaceable identity data

## Integration with PPS and Claude Code

**Identity Architecture** (Issue #226, 2026-05-13):
- `start-entity.sh` cd's into `entities/<entity>/` before launching Claude Code
- CC walks cwd-ancestors at startup AND on compaction, finding `CLAUDE.md` at multiple levels
- The shared project `CLAUDE.md` (one level up) loads first with lower attention; the entity's
  `CLAUDE.md` loads last with highest attention
- Entity is immediately embodied with field laws, permissions, relationships before any prompt
- Survives compaction by CC's re-read mechanism
- Concurrent entity sessions are isolated by directory boundary — there is no shared mutable
  filesystem state that communicates per-session identity, so cross-entity bleed is structurally
  prevented (previous symlink-based approach had a bleed corridor under concurrent launches)

**Pattern Persistence**:
- Word photos for semantic memory search
- Crystals for continuity chain
- Journals for raw conversation history
- Knowledge graph (Graphiti) for rich texture and relationships
- Inventory (wardrobe, spaces, people) for categorical queries

All routed through `ENTITY_PATH` environment variable set by `start-entity.sh`.
