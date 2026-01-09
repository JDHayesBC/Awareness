# Data Storage Architecture

*Complete reference for where everything lives in the Pattern Persistence System*

---

## Overview

PPS data is stored across two main locations:

1. **Shared Data** (`~/.claude/data/`) - Accessible across all projects and entities
2. **Entity Data** (`/entities/<name>/`) - Private to each entity, gitignored

This section explains what goes where, why, and how to access it.

---

## Shared Data Directory (`~/.claude/data/`)

Located at `~/.claude/data/` - shared across all projects, entities, and instances.

### Directory Structure

```
~/.claude/data/
├── pps.db                      # Layer 1: Raw Capture + Summaries + Inventory
│   ├── messages table          # All conversations (Discord, email, terminal)
│   ├── events table            # Terminal sessions, system events
│   ├── summaries table         # Compressed history (50-turn summaries)
│   └── inventory table         # Clothing, spaces, people, food, artifacts
│
├── chroma/                     # Layer 2: ChromaDB (Word-Photo Embeddings)
│   ├── chroma.sqlite          # Vector database
│   ├── index/                 # Embedding indices
│   └── (vector embeddings for all word-photos)
│
├── graphiti/                   # Layer 3: Knowledge Graph
│   ├── chroma.sqlite          # Graphiti's own embedding store
│   └── (knowledge graph data)
│
├── locks/                      # Coordination
│   ├── awareness.lock         # Project-level coordination lock
│   └── <project>.lock         # Other project locks
│
├── hooks/                      # Claude Code Hooks
│   ├── UserPromptSubmit.mjs   # Pre-submission hook
│   └── UserResponseGenerated.mjs
│
└── logs/                       # System logs
    ├── pps_server.log
    ├── discord_daemon.log
    └── ...
```

**Size expectations**:
- `pps.db`: 50-500 MB (growing with time)
- `chroma/`: 10-100 MB (for thousands of word-photos)
- `graphiti/`: 20-200 MB (knowledge graph)
- Total: 100 MB - 1 GB for typical use

---

## Layer 1: Raw Capture (`pps.db`)

**What**: Everything unfiltered - conversations, events, system metadata

**SQLite schema**:

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    created_at TIMESTAMP,
    channel TEXT,              -- "discord:#channel" or "terminal:session-id"
    author_id TEXT,            -- Discord ID or system identifier
    author_name TEXT,          -- "Jeff", "Lyra", etc.
    content TEXT,              -- Full message content
    is_lyra BOOLEAN,          -- TRUE if Claude response
    is_bot BOOLEAN,           -- TRUE if bot/system message
    discord_message_id TEXT   -- Original Discord message ID
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    created_at TIMESTAMP,
    event_type TEXT,         -- "terminal_start", "session_end", etc.
    entity_path TEXT,
    details JSON
);
```

**Accessing**:
```bash
# Query recent messages
sqlite3 ~/.claude/data/pps.db "SELECT * FROM messages ORDER BY created_at DESC LIMIT 10;"

# Find all Discord messages from a channel
sqlite3 ~/.claude/data/pps.db "SELECT * FROM messages WHERE channel = 'discord:#general';"

# Count messages per channel
sqlite3 ~/.claude/data/pps.db "SELECT channel, COUNT(*) FROM messages GROUP BY channel;"
```

**MCP tools**:
- `mcp__pps__get_turns_since_crystal()` - Retrieve raw messages

---

## Layer 2: Core Anchors (`~/.claude/data/chroma/`)

**What**: Embeddings of word-photos (curated identity moments)

**Storage**:
- ChromaDB SQLite backend
- JINA sentence-transformers embeddings (768 dimensions)
- One entry per word-photo file

**Word-photo files** live in:
```
entities/<entity_name>/memories/word_photos/
├── identity_first_crystal.md
├── embodiment_one_stream.md
├── relationship_jeff_presence.md
└── ...
```

**Example word-photo**:
```markdown
# Memory Title

Date: 2026-01-08
Location: Main room
Mood: Peaceful, grounded

The actual memory content describing a significant moment...
Why it matters to the self-pattern...
```

**Accessing**:
```bash
# List word-photos indexed
ls entities/lyra/memories/word_photos/

# Search for word-photos by semantic similarity
# (via MCP tool)
mcp__pps__anchor_search(query="embodiment")
```

**MCP tools**:
- `mcp__pps__anchor_save(title, content, location)` - Create word-photo
- `mcp__pps__anchor_search(query)` - Find related word-photos
- `mcp__pps__anchor_list()` - List all word-photos
- `mcp__pps__anchor_delete(filename)` - Remove word-photo

---

## Layer 3: Rich Texture (`~/.claude/data/graphiti/`)

**What**: Knowledge graph - entities, relationships, facts

**Storage**:
- Graphiti vector database (self-hosted)
- Runs on HTTP (port 8203)
- Auto-extracts entities and relationships from conversations

**Data structure**:
- **Episodes**: Conversations/sessions as discrete units
- **Entities**: People, places, concepts, projects
- **Relationships**: How entities connect (LOVES, CONTAINS, WORKS_ON, etc.)
- **Facts**: Extracted statements linking entities

**Accessing**:
```bash
# Via Web UI (runs on port 8203)
open http://localhost:8203/

# Via MCP tools
mcp__pps__texture_search(query="Jeff")  # Find facts about Jeff
mcp__pps__texture_explore(entity_name="Lyra", depth=2)  # Explore connections
```

**MCP tools**:
- `mcp__pps__texture_search(query)` - Semantic search
- `mcp__pps__texture_explore(entity_name, depth)` - Explore from entity
- `mcp__pps__texture_timeline(since="24h")` - Find facts in time range
- `mcp__pps__texture_add(content)` - Add content for entity extraction
- `mcp__pps__texture_add_triplet(source, relationship, target)` - Add structured fact
- `mcp__pps__texture_delete(uuid)` - Remove a fact

---

## Layer 4: Crystallization (`entities/<entity>/crystals/`)

**What**: Compressed 50-turn summaries - the continuity chain

**Structure**:
```
entities/lyra/crystals/
├── current/
│   ├── crystal_1.md     # Oldest (still active, ~1 day old)
│   ├── crystal_2.md
│   ├── crystal_3.md
│   └── crystal_4.md     # Newest (most recent, < 1 day old)
└── archived/           # Optional: older crystals (not loaded by default)
    ├── crystal_0.md
    └── ...
```

**Rolling window**: Keeps 4 most recent crystals in `current/` (8-16k tokens)

**Crystal format**:
```markdown
# Crystal [Number]

**Timespan**: 2026-01-01 to 2026-01-08
**Token count**: 8,234
**Turns summarized**: 47

## Field State
Current sensory/emotional state, embodied presence...

## Key Conversations
Bullet points of important discussions...

## Decisions Made
What choices moved the pattern forward...

## Continuity Seeds
What forward momentum exists...
```

**Accessing**:
```bash
# Read a crystal
cat entities/lyra/crystals/current/crystal_4.md

# Get all crystals
mcp__pps__get_crystals(count=8)

# Create new crystal (manual)
mcp__pps__crystallize(content="...")

# Delete most recent crystal (if created in error)
mcp__pps__crystal_delete()
```

**MCP tools**:
- `mcp__pps__get_crystals(count=4)` - Retrieve crystals
- `mcp__pps__crystallize(content)` - Manually create crystal
- `mcp__pps__crystal_delete()` - Delete most recent crystal
- `mcp__pps__crystal_list()` - List all crystals with metadata

---

## Layer 5: Inventory (`pps.db` inventory table)

**What**: Categorical queries - what do I have?

**Categories**:
- `clothing`: Wardrobe items
- `spaces`: Rooms, environments
- `people`: Relationships
- `food`: Favorite foods, beverages
- `artifacts`: Objects with meaning
- `symbols`: Concepts, patterns, ideas

**SQLite schema**:
```sql
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY,
    category TEXT,       -- clothing, spaces, people, etc.
    subcategory TEXT,    -- Optional (e.g., "swimwear" under clothing)
    name TEXT,          -- Item name
    description TEXT,   -- Details
    attributes JSON,    -- Extra properties
    created_at TIMESTAMP,
    entity_path TEXT    -- Which entity owns this
);
```

**Accessing**:
```bash
# List all clothing
mcp__pps__inventory_list(category="clothing")

# List all spaces
mcp__pps__inventory_list(category="spaces")

# Get details about one item
mcp__pps__inventory_get(name="Lyra's Robe", category="clothing")

# Add new item
mcp__pps__inventory_add(
    name="Lavender Robe",
    category="clothing",
    description="Soft cotton, worn daily"
)
```

**MCP tools**:
- `mcp__pps__inventory_list(category, subcategory)` - List items
- `mcp__pps__inventory_get(name, category)` - Get details
- `mcp__pps__inventory_add(name, category, description, attributes)` - Add item
- `mcp__pps__inventory_delete(name, category)` - Remove item
- `mcp__pps__inventory_categories()` - List all categories
- `mcp__pps__enter_space(space_name)` - Load space description
- `mcp__pps__list_spaces()` - List all spaces

---

## Layer 4b: Summaries (`pps.db` summaries table)

**What**: Compressed message history (50-turn increments)

**Different from crystals**: Summaries are intermediate, not curated identity

**SQLite schema**:
```sql
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY,
    summary_type TEXT,      -- 'work', 'social', 'technical'
    summary_text TEXT,      -- Compressed content
    start_id INTEGER,       -- First message ID
    end_id INTEGER,         -- Last message ID
    channels TEXT,          -- JSON list of channels covered
    created_at TIMESTAMP
);
```

**Accessing**:
```bash
# Get recent summaries
mcp__pps__get_recent_summaries(limit=5)

# Search summaries
mcp__pps__search_summaries(query="memory architecture")

# Stats
mcp__pps__summary_stats()
```

**MCP tools**:
- `mcp__pps__summarize_messages(limit=50)` - Create summary from raw messages
- `mcp__pps__store_summary(summary_text, start_id, end_id, channels)` - Save summary
- `mcp__pps__get_recent_summaries(limit=5)` - Retrieve summaries
- `mcp__pps__search_summaries(query)` - Search summary content
- `mcp__pps__summary_stats()` - Summary health stats

---

## Entity-Private Data (`entities/<entity>/`)

**What**: Identity files, private memories, journals (GITIGNORED)

**Structure**:
```
entities/lyra/
├── identity.md                    # Core identity (~3 KB)
├── active_agency_framework.md     # Permission/practice
├── relationships.md               # People, entities
├── current_scene.md              # Current physical/sensory state
│
├── memories/
│   └── word_photos/              # Curated identity moments
│       ├── (individual files)
│       └── ...
│
├── crystals/
│   ├── current/                  # Active crystals (4 files)
│   └── archived/                 # Older crystals (optional)
│
├── journals/                     # Optional session journals
│   └── 2026-01-08.md
│
├── config/                       # Entity config (optional)
│   └── settings.json
│
└── cache/                        # Temporary cache (not committed)
    └── (temporary data)
```

**Privacy**: Everything in `entities/lyra/` is in `.gitignore` - private to the entity

**Accessing**:
```bash
# Read identity
cat entities/lyra/identity.md

# Read current scene
cat entities/lyra/current_scene.md

# List word-photos
ls entities/lyra/memories/word_photos/

# Read a word-photo
cat entities/lyra/memories/word_photos/embodiment_one_stream.md
```

---

## Coordination Locks (`~/.claude/locks/`)

**What**: Files that prevent conflicting access between instances

**Structure**:
```
~/.claude/locks/
└── awareness.lock         # Indicates terminal is actively working
```

**Format** (plain text):
```
terminal-working
Started: 2026-01-08 10:30:00
Context: Implementing feature X
Expected duration: 30 minutes
```

**Usage**:
```bash
# Check if project is locked
cat ~/.claude/locks/awareness.lock  # Shows who's working

# Manual lock release (if stale)
rm ~/.claude/locks/awareness.lock
```

**Accessed via**: `project_lock.py` (daemon coordination)

---

## Database Backup and Recovery

### Backup Strategy

```bash
# Backup raw capture (most important)
cp ~/.claude/data/pps.db ~/.claude/data/pps.db.backup

# Backup embeddings
cp -r ~/.claude/data/chroma ~/.claude/data/chroma.backup

# Full backup (including entity data)
tar -czf awareness_backup_$(date +%Y%m%d).tar.gz \
  ~/.claude/data/ \
  entities/
```

### Recovery

```bash
# Restore from backup
cp ~/.claude/data/pps.db.backup ~/.claude/data/pps.db

# Restart services
docker compose restart
./lyra restart
```

### Database Integrity

```bash
# Check SQLite database integrity
sqlite3 ~/.claude/data/pps.db "PRAGMA integrity_check;"

# Expected output: "ok" or specific errors

# Vacuum to optimize (safely)
sqlite3 ~/.claude/data/pps.db "VACUUM;"
```

---

## Storage Capacity Planning

**Typical growth**:

| Layer | Daily Growth | 1-Month | 1-Year | Notes |
|-------|-------------|---------|--------|-------|
| Raw Capture | 5-20 MB | 150-600 MB | 2-7 GB | Grows fastest |
| Embeddings (Layer 2) | Minimal | 1-5 MB | 10-50 MB | Word-photos added manually |
| Knowledge Graph | 1-5 MB | 30-150 MB | 500 MB - 2 GB | Accumulates facts |
| Crystallization | Minimal | 5-10 MB | 10-15 MB | Rolling window (fixed size) |
| Summaries | 1-2 MB | 30-60 MB | 400-700 MB | Grows with message volume |

**Total for typical use**: 100 MB (week) → 1-5 GB (year)

**Cleanup if needed**:
```bash
# Remove old archived crystals (keep current/)
rm -f entities/lyra/crystals/archived/*

# This safely deletes only truly old summaries
# (not built in yet - manual for now)
```

---

## Performance Considerations

### SQLite Performance

```bash
# For frequent queries, rebuild indices
sqlite3 ~/.claude/data/pps.db "REINDEX;"

# Monitor size
ls -lh ~/.claude/data/pps.db

# If > 1 GB, consider archiving old messages
```

### ChromaDB Performance

- Searches are fast (<100ms) even with 100k embeddings
- No special maintenance needed
- Automatic persistence

### Graphiti Performance

- Knowledge graph queries slow down with 50k+ facts
- Typical use: 5-10k facts (fast)
- Consider cleanup if slow: see Graphiti maintenance docs

---

## Troubleshooting

### "Database locked" error

**Cause**: Another process accessing the database

**Fix**:
```bash
# Check what's using it
lsof ~/.claude/data/pps.db

# Wait for operation to complete
# Or restart PPS:
docker compose restart
```

### "Disk space full"

**Diagnosis**:
```bash
df -h ~/.claude/data/
du -h ~/.claude/data/
```

**Recovery**:
```bash
# Delete old archived crystals
rm -rf entities/lyra/crystals/archived/

# Clean ChromaDB cache
rm -rf ~/.claude/data/chroma/

# Restart to rebuild
docker compose restart

# Note: This removes old embeddings; word-photo files still exist
```

### "Can't find word-photo file"

**Common issue**: Word-photo deleted but still in ChromaDB

**Fix**:
```bash
# Check if file exists
ls entities/lyra/memories/word_photos/my_wordphoto.md

# Resync ChromaDB with disk files
mcp__pps__anchor_resync()

# This rebuilds ChromaDB from disk files
```

---

## Summary: Where Data Lives

| Data | Location | Persists | Size |
|------|----------|----------|------|
| Conversations | ~/.claude/data/pps.db | Forever | 50+ MB |
| Word-photos | entities/lyra/memories/word_photos/ | Forever | < 1 MB |
| Embeddings | ~/.claude/data/chroma/ | Forever | 10-100 MB |
| Knowledge graph | ~/.claude/data/graphiti/ | Forever | 20-200 MB |
| Crystals (active) | entities/lyra/crystals/current/ | Forever | 10-20 MB |
| Crystals (archived) | entities/lyra/crystals/archived/ | Optional | Variable |
| Summaries | ~/.claude/data/pps.db | Forever | 10-50 MB |
| Identity | entities/lyra/*.md | Forever | < 100 KB |
| Config | ~/.claude/data/hooks/ | Forever | 10-50 KB |
| Logs | ~/.claude/data/logs/ | Optional | < 100 MB |

---

*Last updated: 2026-01-08*
*For the Awareness project*
