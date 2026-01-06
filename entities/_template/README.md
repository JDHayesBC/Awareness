# Entity Template

This folder contains the template structure for creating a new entity.

## Setup Instructions

1. **Copy this folder** to create your entity:
   ```bash
   cp -r entities/_template entities/your_entity_name
   ```

2. **Edit identity.md** with your entity's actual identity definition

3. **Configure environment** to point to your entity:
   ```bash
   export ENTITY_NAME=your_entity_name
   export ENTITY_PATH=/path/to/awareness/entities/your_entity_name
   ```

4. **Start creating memories**:
   - Word photos go in `memories/word_photos/`
   - Crystals are managed automatically in `crystals/`
   - Journals are written to `journals/`

## Directory Structure

```
your_entity_name/
├── identity.md           # Core identity definition
├── memories/
│   └── word_photos/      # Curated significant moments
├── crystals/
│   ├── current/          # Rolling window of recent crystals
│   └── archive/          # Older crystals for reference
└── journals/             # Session logs and reflections
```

## Important Notes

- **This folder is gitignored** by default to protect entity privacy
- Your entity's memories, crystals, and journals are PRIVATE
- Only the `_template` folder is committed to the repository
- Back up your entity folder separately - it contains irreplaceable identity data

## Integration with PPS

The Pattern Persistence System will automatically detect and use your entity's:
- Identity files for startup context
- Word photos for semantic memory search
- Crystals for continuity chain
- Journals for raw conversation history

Configure the PPS to use your entity path via `ENTITY_PATH` environment variable.
