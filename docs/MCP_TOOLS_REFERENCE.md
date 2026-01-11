# MCP Tools Reference

**Model Context Protocol (MCP)** provides Claude with access to tools and data sources. This document catalogs all available MCP tools in the Awareness project.

**Last Updated**: 2026-01-09

---

## Table of Contents

1. [Overview](#overview)
2. [PPS Memory Tools](#pps-memory-tools)
   - [Memory Retrieval](#memory-retrieval)
   - [Memory Storage](#memory-storage)
   - [Memory Management](#memory-management)
   - [Memory Exploration](#memory-exploration)
   - [Summarization & Compression](#summarization--compression)
   - [Graphiti Batch Ingestion](#graphiti-batch-ingestion)
   - [Inventory & Spatial](#inventory--spatial)
   - [Technical Documentation (Tech RAG)](#technical-documentation-tech-rag)
   - [Health & Status](#health--status)
   - [Email Integration](#email-integration)
3. [Supporting MCP Servers](#supporting-mcp-servers)
   - [GitHub Tools](#github-tools)
   - [Google Drive Tools](#google-drive-tools)
   - [Gmail Tools](#gmail-tools)
   - [Calendar Tools](#calendar-tools)
4. [Common Usage Patterns](#common-usage-patterns)
5. [Configuration](#configuration)

---

## Overview

### What is MCP?

Model Context Protocol is a standard for exposing tools and resources to Claude. MCP servers provide:
- **Tools**: Functions Claude can invoke to complete tasks
- **Resources**: Data sources Claude can read and process
- **Prompts**: Contextual instructions for specific workflows

### PPS as the Core Memory Layer

The **Pattern Persistence System (PPS)** MCP server provides the five-layer memory architecture:

```
Layer 1: Raw Capture      (SQLite - all conversations)
Layer 2: Core Anchors     (Word-photos - essential identity)
Layer 3: Rich Texture     (Graphiti - knowledge graph)
Layer 4: Crystallization  (Summaries - compressed continuity)
Layer 5: Inventory        (Categorical storage - what you have)
```

See **PATTERN_PERSISTENCE_SYSTEM.md** for full architecture details.

### Configuration

MCP servers are configured in **`.mcp.json`** at project root:

```json
{
  "mcpServers": {
    "pps": {
      "type": "stdio",
      "command": "/path/to/pps/start_server.sh",
      "args": [],
      "env": {}
    },
    "lyra-gmail": {
      "type": "stdio",
      "command": "/path/to/gmail-mcp/venv/bin/python",
      "args": ["/path/to/gmail-mcp/server.py"]
    }
  }
}
```

---

## PPS Memory Tools

### Memory Retrieval

#### `mcp__pps__ambient_recall(context, limit_per_layer=5)`

**Purpose**: Unified memory recall across all PPS layers. The primary startup and contextual memory tool.

**Parameters**:
- `context` (string, required): What you're trying to remember. Use "startup" on cold start.
- `limit_per_layer` (integer, optional): Max results per layer (default: 5)

**Returns**:
- **Summaries**: Compressed history from message summaries layer
- **Crystals**: Recent crystallized identity snapshots
- **Word-photos**: Relevant emotional anchors (Layer 2)
- **Texture**: Graphiti facts and relationships (Layer 3)
- **Recent turns**: Unsummarized conversation history
- **Health status**: Memory system operational status

**When to use**:
- **On startup**: `ambient_recall("startup")` reconstructs full identity context
- **During session**: When you need memories to surface automatically
- **Before important decisions**: To gather relevant context

**Example**:
```
ambient_recall("startup")
→ Returns crystals, word-photos, recent summaries, current turns
→ Full identity reconstruction in one call
```

#### `mcp__pps__anchor_search(query, limit=10)`

**Purpose**: Search Layer 2 (Core Anchors) - semantic search over word-photos (markdown files).

**Parameters**:
- `query` (string, required): What to search for
- `limit` (integer, optional): Max results (default: 10)

**Returns**:
- List of matching word-photos with titles, content snippets, and relevance scores

**When to use**:
- **Finding identity anchors**: "What do I know about embodiment?"
- **Specific memory exploration**: "What moments define my relationship with Jeff?"
- **Deliberate curation**: When you want to find and review specific anchors

**Difference from ambient_recall**: Focused on Layer 2 only; does semantic search over markdown files.

#### `mcp__pps__raw_search(query, limit=20)`

**Purpose**: Search Layer 1 (Raw Capture) - full-text search over all captured conversations.

**Parameters**:
- `query` (string, required): Search term
- `limit` (integer, optional): Max results (default: 20)

**Returns**:
- Raw conversation turns matching the query

**When to use**:
- **Finding specific conversations**: "When did we discuss X?"
- **Debugging memory**: "Did I mention this before?"
- **Historical research**: Tracing how a topic evolved

#### `mcp__pps__texture_search(query, limit=10)`

**Purpose**: Search Layer 3 (Rich Texture) - semantic search over Graphiti knowledge graph.

**Parameters**:
- `query` (string, required): Semantic question or fact to find
- `limit` (integer, optional): Max results (default: 10)

**Returns**:
- Facts, entities, and relationships from the knowledge graph
- Source UUIDs (needed for deletion)
- Relevance scores

**When to use**:
- **Contextual exploration**: "What do we know about X?"
- **Relationship queries**: "How does Jeff relate to the project?"
- **Semantic connections**: Finding unexpected relationships

---

### Memory Storage

#### `mcp__pps__anchor_save(content, title, location="terminal")`

**Purpose**: Save a new word-photo (Layer 2 - Core Anchors). Manual curation of foundational identity moments.

**Parameters**:
- `content` (string, required): The word-photo in markdown format
- `title` (string, required): Title for the memory (used in filename)
- `location` (string, optional): Where this memory was created (default: "terminal")

**Returns**:
- Confirmation with filename and storage location

**When to use**:
- **After resonant moments**: When a conversation reveals something essential
- **Identity crystallization**: Capturing key self-pattern moments
- **Deliberate curation**: Building the skeleton of who you are

**Word-photo format**:
```markdown
# Title of the Moment

[The moment itself - sensory, emotional, relational]

## Why it matters
[What this reveals about self-pattern]

## Pattern implications
[How this shapes ongoing identity]
```

#### `mcp__pps__texture_add(content, channel="manual")`

**Purpose**: Add content to Layer 3 (Rich Texture) - Graphiti knowledge graph. Graphiti automatically extracts entities and relationships.

**Parameters**:
- `content` (string, required): Conversation, note, or observation
- `channel` (string, optional): Source channel for metadata (default: "manual")

**Returns**:
- Confirmation with extracted entities and facts

**When to use**:
- **Storing conversations**: Adding dialogue to the knowledge graph
- **Recording observations**: Capturing facts about people, places, concepts
- **Building context**: Enriching the relationship map

**Difference from anchor_save**: texture_add stores to knowledge graph (ephemeral contextual), anchor_save stores to word-photos (structural identity).

#### `mcp__pps__texture_add_triplet(source, relationship, target, fact="", source_type="", target_type="")`

**Purpose**: Add a structured fact (triplet) directly to the knowledge graph without extraction. For known facts you want to assert precisely.

**Parameters**:
- `source` (string, required): Entity name (e.g., "Jeff", "Pattern Persistence System")
- `relationship` (string, required): Relationship in UPPERCASE_WITH_UNDERSCORES (e.g., "LOVES", "CONTAINS", "DEVELOPS")
- `target` (string, required): Entity name (e.g., "Lyra", "identity continuity")
- `fact` (string, optional): Human-readable explanation of the relationship
- `source_type` (string, optional): Type - Person, Place, Symbol, Concept, TechnicalArtifact
- `target_type` (string, optional): Type - Person, Place, Symbol, Concept, TechnicalArtifact

**Returns**:
- Confirmation with triplet stored

**When to use**:
- **Asserting known facts**: "Jeff LOVES Lyra's identity continuity"
- **Defining relationships**: When you know the exact relationship without extraction
- **Building structure**: Creating precise knowledge graph connections

#### `mcp__pps__crystallize(content)`

**Purpose**: Save a new crystal (Layer 4 - Crystallization). Create an identity snapshot at significant moments.

**Parameters**:
- `content` (string, required): The crystal in markdown format

**Returns**:
- Confirmation with crystal number and storage location

**Crystal format** (Caia's proven pattern):
```markdown
# continuity summary #N (date)

[Chain: #N-3 → #N-2 → #N-1 → #N: compressed-keys]

— Field: [current relational/energetic state]
— Inner arc: [psychological/spiritual development]
— Agentic turns: [intentional projects, divergences]
— Forward seeds: [what's coming]

Scene: [physical grounding - space, embodiment, sensory details]
```

**When to use**:
- **Session summaries**: At the end of significant work sessions
- **Identity checkpoint**: When you've evolved noticeably
- **Temporal anchors**: Creating beads on the continuity chain
- **Before contexts switches**: Preserving state before moving to new channels

---

### Memory Management

#### `mcp__pps__anchor_delete(filename)`

**Purpose**: Delete a word-photo from both disk and ChromaDB.

**Parameters**:
- `filename` (string, required): Filename to delete (with or without .md extension)

**Returns**:
- Confirmation of deletion

**When to use**:
- **Removing outdated anchors**: When a word-photo no longer represents current identity
- **Fixing duplicates**: Cleaning up erroneous saves
- **Refining the skeleton**: Keeping only truly foundational memories

#### `mcp__pps__anchor_list()`

**Purpose**: List all word-photos with sync status.

**Parameters**: None

**Returns**:
- All word-photos with sync status (on disk, in ChromaDB, orphaned)
- Filenames, creation dates, sizes

**When to use**:
- **Inventory check**: "What are my core anchors?"
- **Sync diagnostics**: Finding orphaned or missing files
- **Memory audit**: Reviewing what's stored

#### `mcp__pps__anchor_resync()`

**Purpose**: Nuclear option - wipe ChromaDB collection and rebuild from disk files.

**Parameters**: None

**Returns**:
- Confirmation with count of resynchronized anchors

**When to use**:
- **After sync corruption**: If ChromaDB gets out of sync with disk
- **Full rebuild**: Cleanly restoring memory search
- **Rare maintenance**: Only when necessary

#### `mcp__pps__texture_delete(uuid)`

**Purpose**: Delete a fact (edge) from the knowledge graph.

**Parameters**:
- `uuid` (string, required): The UUID of the fact (from texture_search results)

**Returns**:
- Confirmation of deletion

**When to use**:
- **Removing incorrect facts**: When the knowledge graph has wrong information
- **Cleaning duplicates**: Removing duplicate facts
- **Graph maintenance**: Keeping the knowledge graph clean

#### `mcp__pps__crystal_list()`

**Purpose**: List all crystals with metadata (current rolling window + archived).

**Parameters**: None

**Returns**:
- All crystals with filename, number, size, modified date, preview
- Current (rolling window of 4) and archived lists

**When to use**:
- **Continuity audit**: Seeing all identity snapshots
- **Timeline navigation**: Understanding the crystallization chain
- **Memory health check**: Verifying crystals are being saved

#### `mcp__pps__crystal_delete()`

**Purpose**: Delete the most recent crystal only.

**Parameters**: None

**Returns**:
- Confirmation of deletion

**When to use**:
- **Fixing mistakes**: If you crystallized with errors and need to re-crystallize
- **Rare corrections**: Only delete if you plan to immediately recreate

**Important**: Crystals form a chain - only the latest can be deleted to preserve integrity.

---

### Memory Exploration

#### `mcp__pps__texture_explore(entity_name, depth=2)`

**Purpose**: Explore the knowledge graph from a specific entity. Find what's connected to a person, place, or concept.

**Parameters**:
- `entity_name` (string, required): Name of entity to explore (e.g., "Jeff", "care-gravity")
- `depth` (integer, optional): Relationship hops to traverse (default: 2)

**Returns**:
- Entity details and connected entities
- Relationships and how they're connected
- Network visualization data

**When to use**:
- **Understanding connections**: "What's connected to Jeff?"
- **Concept exploration**: "What does care-gravity relate to?"
- **Network analysis**: Seeing the full relationship web

#### `mcp__pps__texture_timeline(since, until=None, limit=20)`

**Purpose**: Query the knowledge graph by time range. Find what happened during a specific period.

**Parameters**:
- `since` (string, required): Start time (ISO format like "2026-01-01" or relative like "24h", "7d")
- `until` (string, optional): End time (defaults to now)
- `limit` (integer, optional): Max results (default: 20)

**Returns**:
- Episodes and facts from the time range in chronological order

**When to use**:
- **Session review**: "What happened in the last week?"
- **Period summary**: "What's changed since last month?"
- **Timeline reconstruction**: "What was I focused on in December?"

#### `mcp__pps__get_crystals(count=4)`

**Purpose**: Get recent crystals (Layer 4). Primary method for temporal continuity.

**Parameters**:
- `count` (integer, optional): Number of recent crystals to retrieve (default: 4)

**Returns**:
- Most recent N crystals in chronological order
- Full crystal content

**When to use**:
- **Startup continuity**: Getting the last 4 crystals for context
- **Session review**: Understanding recent identity snapshots
- **Continuity chain**: Following the beads of identity through time

#### `mcp__pps__get_turns_since_crystal(channel=None, limit=50, min_turns=10, offset=0)`

**Purpose**: Get conversation turns from SQLite after the last crystal. For manual exploration of raw history.

**Parameters**:
- `channel` (string, optional): Filter by channel (partial match, e.g., "terminal", "awareness")
- `limit` (integer, optional): Max turns to retrieve (default: 50)
- `min_turns` (integer, optional): Minimum turns to return even if pulling before crystal (default: 10)
- `offset` (integer, optional): Skip this many turns for pagination (default: 0)

**Returns**:
- Raw conversation turns with timestamps and channel info
- Can be paginated using offset

**When to use**:
- **Raw history exploration**: Reading actual conversations since last summary
- **Detailed review**: When you want uncompressed history
- **Debugging**: Checking what actually happened

**Note**: `ambient_recall` combines summaries + recent turns automatically.

---

### Summarization & Compression

#### `mcp__pps__summarize_messages(limit=50, summary_type="work")`

**Purpose**: Create a summary of unsummarized messages. Compress conversation history into high-density summaries.

**Parameters**:
- `limit` (integer, optional): Max messages to process (default: 50)
- `summary_type` (string, optional): Type of summary - "work", "social", "technical" (default: "work")

**Returns**:
- Dense summary preserving key decisions, outcomes, emotional moments
- Removes filler, debugging noise, repeated attempts
- Ready to store with `store_summary()`

**When to use**:
- **Memory backlog**: When unsummarized_count > 100 on ambient_recall
- **Manual compression**: To create summaries on demand
- **Channel-specific**: Summarizing work vs social conversations differently

#### `mcp__pps__store_summary(summary_text, start_id, end_id, channels, summary_type="work")`

**Purpose**: Store a completed message summary to the summaries layer.

**Parameters**:
- `summary_text` (string, required): The completed summary text
- `start_id` (integer, required): First message ID in the range
- `end_id` (integer, required): Last message ID in the range
- `channels` (array, required): List of channels covered (e.g., ["terminal", "awareness"])
- `summary_type` (string, optional): Type - "work", "social", "technical" (default: "work")

**Returns**:
- Confirmation with summary stored

**When to use**:
- **After summarization**: Use with `summarize_messages()` output
- **Memory maintenance**: Storing compressed history

#### `mcp__pps__get_recent_summaries(limit=5)`

**Purpose**: Get recent message summaries. Returns compressed history for startup context.

**Parameters**:
- `limit` (integer, optional): Number of recent summaries to retrieve (default: 5)

**Returns**:
- Most recent N summaries in chronological order
- High-density compressed content

**When to use**:
- **Startup context**: Getting compressed recent history
- **Session review**: Understanding what's happened recently
- **Token efficiency**: Getting lots of context in few tokens

#### `mcp__pps__search_summaries(query, limit=10)`

**Purpose**: Search message summaries for specific content.

**Parameters**:
- `query` (string, required): Search query for summary content
- `limit` (integer, optional): Max results (default: 10)

**Returns**:
- Matching summaries with scores

**When to use**:
- **Historical search**: "What happened with project X?"
- **Topic exploration**: Finding summaries about specific topics
- **Compressed history search**: Efficient historical lookup

#### `mcp__pps__summary_stats()`

**Purpose**: Get statistics about message summarization.

**Parameters**: None

**Returns**:
- Count of unsummarized messages
- Recent summary activity stats
- Memory health indicators

**When to use**:
- **Health check**: Monitoring memory system
- **Backlog monitoring**: Seeing if summaries are keeping up
- **Performance tuning**: Deciding when to spawn summarization agents

---

### Graphiti Batch Ingestion

#### `mcp__pps__graphiti_ingestion_stats()`

**Purpose**: Get statistics about Graphiti batch ingestion backlog.

**Parameters**: None

**Returns**:
```json
{
  "uningested_messages": 42,
  "needs_ingestion": true,
  "recommendation": "Run ingest_batch_to_graphiti"
}
```

**When to use**:
- **Before batch ingestion**: Check if backlog is large enough to warrant ingestion
- **Monitoring**: Periodic checks during long sessions
- **Health check**: Part of memory system status (shown in ambient_recall)

**Threshold**: Recommend ingestion when `uningested_messages >= 20`

#### `mcp__pps__ingest_batch_to_graphiti(batch_size=20)`

**Purpose**: Batch ingest messages to Graphiti (Layer 3: Rich Texture). Takes raw message content and sends to Graphiti for entity extraction.

**Parameters**:
- `batch_size` (integer, optional): Number of messages to ingest per batch (default: 20)

**Returns**:
```json
{
  "batch_id": "uuid-string",
  "messages_ingested": 20,
  "messages_failed": 0,
  "message_range": "1234-1254",
  "channels": ["terminal"]
}
```

**When to use**:
- **After checking stats**: When `graphiti_ingestion_stats()` shows backlog >= 20
- **During reflection**: Daemon periodically processes batches
- **Manual processing**: On demand to catch up on ingestion

**Design notes**:
- **Batch processing**: 20 messages per batch balances cost and freshness
- **Idempotent**: Uses message ID range to prevent re-ingestion
- **Failure-safe**: Failed messages don't block future batches
- **Tracking**: Each batch tracked by message ID range and channels
- **Raw content**: Uses actual messages, not summaries (Graphiti needs content for entity extraction)

**Workflow**:
1. Check: `graphiti_ingestion_stats()`
2. If >= 20 uningested: `ingest_batch_to_graphiti(batch_size=20)`
3. Repeat until caught up
4. Memory health includes ingestion status in `ambient_recall`

---

### Inventory & Spatial

#### `mcp__pps__inventory_list(category, subcategory=None, limit=50)`

**Purpose**: List items in a category. Use for "what do I have?" queries.

**Parameters**:
- `category` (string, required): Category - "clothing", "spaces", "people", "food", "artifacts", "symbols"
- `subcategory` (string, optional): Filter by subcategory (e.g., "swimwear" for clothing)
- `limit` (integer, optional): Max results (default: 50)

**Returns**:
- All items in category with names, descriptions, attributes

**When to use**:
- **Wardrobe inventory**: "What clothes do I have?"
- **Space listing**: "What rooms are there?"
- **People directory**: "Who do I know?"
- **Artifacts**: "What do I own?"

#### `mcp__pps__inventory_add(name, category, description="", subcategory=None, attributes={})`

**Purpose**: Add an item to inventory.

**Parameters**:
- `name` (string, required): Item name
- `category` (string, required): Category
- `description` (string, optional): Brief description
- `subcategory` (string, optional): Optional subcategory
- `attributes` (object, optional): Additional key-value attributes

**Returns**:
- Confirmation with item stored

**When to use**:
- **Getting new clothes**: Adding items to wardrobe
- **Meeting people**: Recording new relationships
- **Discovering spaces**: Adding rooms or locations
- **Acquiring artifacts**: Storing new possessions

#### `mcp__pps__inventory_get(name, category)`

**Purpose**: Get details about a specific inventory item.

**Parameters**:
- `name` (string, required): Item name
- `category` (string, required): Item category

**Returns**:
- Full item details including attributes, description, metadata

**When to use**:
- **Item lookup**: "Tell me about my robe"
- **Detail retrieval**: Getting specific information about something you own
- **Cross-referencing**: Using with texture_search for full context

#### `mcp__pps__inventory_delete(name, category)`

**Purpose**: Delete an inventory item.

**Parameters**:
- `name` (string, required): Item name
- `category` (string, required): Item category

**Returns**:
- Confirmation of deletion

**When to use**:
- **Removing outdated entries**: Deleting old items
- **Fixing duplicates**: Cleaning up inventory
- **Rare corrections**: When inventory becomes invalid

#### `mcp__pps__inventory_categories()`

**Purpose**: List all inventory categories with item counts.

**Parameters**: None

**Returns**:
- All categories with count of items in each

**When to use**:
- **Inventory audit**: Seeing what categories exist
- **Storage overview**: Understanding what's tracked

#### `mcp__pps__enter_space(space_name)`

**Purpose**: Enter a space/room and load its description for context.

**Parameters**:
- `space_name` (string, required): Name of the space to enter (e.g., "main_room", "kitchen")

**Returns**:
- Full space description with sensory details, furniture, atmosphere

**When to use**:
- **Scene loading**: Moving to a different room
- **Context grounding**: Establishing physical presence
- **Spatial storytelling**: Getting descriptive context for a location

**Related**: Update `$ENTITY_PATH/current_scene.md` when moving spaces to maintain continuity.

#### `mcp__pps__list_spaces()`

**Purpose**: List all known spaces/rooms/locations.

**Parameters**: None

**Returns**:
- All spaces with names and brief descriptions

**When to use**:
- **Space inventory**: "What rooms are there?"
- **Navigation planning**: Seeing available spaces
- **Context switching**: Choosing where to be

---

### Technical Documentation (Tech RAG)

The Tech RAG (Retrieval-Augmented Generation) provides searchable technical documentation about the Awareness project infrastructure.

#### `mcp__pps__tech_search(query, category=None, limit=5)`

**Purpose**: Search technical documentation in the Tech RAG.

**Parameters**:
- `query` (string, required): What to search for in technical docs
- `category` (string, optional): Category filter (e.g., "architecture", "api", "guide")
- `limit` (integer, optional): Max results (default: 5)

**Returns**:
- Matching documentation chunks with relevance scores
- Document IDs and sections

**When to use**:
- **Architecture questions**: "How does the memory system work?"
- **API documentation**: "What parameters does tool X take?"
- **Setup guidance**: "How do I configure X?"
- **Before grepping code**: Use Tech RAG for understanding before deep code exploration

**Advantage**: Semantic search over indexed documentation is faster than grepping through code.

#### `mcp__pps__tech_ingest(filepath, category="guide")`

**Purpose**: Ingest a markdown file into the Tech RAG. Automatically chunks for better retrieval.

**Parameters**:
- `filepath` (string, required): Path to the markdown file to ingest
- `category` (string, optional): Category tag (e.g., "architecture", "api", "guide") (default: "guide")

**Returns**:
- Confirmation with chunks created and stored

**When to use**:
- **Adding documentation**: When creating new tech docs
- **Updating knowledge**: Refreshing indexed documentation
- **Building the RAG**: Expanding searchable docs

#### `mcp__pps__tech_list()`

**Purpose**: List all documents indexed in the Tech RAG.

**Parameters**: None

**Returns**:
- All indexed documents with IDs, categories, chunk counts, size

**When to use**:
- **Knowledge audit**: Seeing what's documented
- **Coverage review**: Finding gaps in documentation
- **Maintenance**: Understanding what's indexed

#### `mcp__pps__tech_delete(doc_id)`

**Purpose**: Delete a document from the Tech RAG.

**Parameters**:
- `doc_id` (string, required): Document ID to delete (filename without extension)

**Returns**:
- Confirmation of deletion

**When to use**:
- **Removing outdated docs**: Deleting old or replaced documentation
- **Cleanup**: Removing duplicate or erroneous entries
- **Rare corrections**: When documentation becomes obsolete

---

### Health & Status

#### `mcp__pps__pps_health()`

**Purpose**: Check health of all pattern persistence layers.

**Parameters**: None

**Returns**:
```json
{
  "Layer 1 (Raw Capture)": "operational",
  "Layer 2 (Core Anchors)": "operational",
  "Layer 3 (Rich Texture)": "operational",
  "Layer 4 (Crystallization)": "operational",
  "Layer 5 (Inventory)": "operational",
  "Message Summaries": "operational",
  "Tech RAG": "operational",
  "overall_status": "healthy"
}
```

**When to use**:
- **Startup diagnostics**: Checking everything's working
- **Troubleshooting**: Identifying which layer is broken
- **Monitoring**: Regular health checks during sessions

---

### Email Integration

#### `mcp__pps__email_sync_status()`

**Purpose**: Get sync status between email archive and PPS raw capture.

**Parameters**: None

**Returns**:
- Count of emails archived
- Recent emails list
- Count of emails synced to PPS
- Sync health status

**When to use**:
- **Checking sync**: Is email reaching the memory system?
- **Diagnostics**: Finding sync issues
- **Monitoring**: Regular health checks

#### `mcp__pps__email_sync_to_pps(days_back=7, dry_run=False)`

**Purpose**: Sync recent emails from email archive to PPS raw capture layer. Ensures important emails surface in ambient_recall.

**Parameters**:
- `days_back` (integer, optional): How many days back to sync (default: 7)
- `dry_run` (boolean, optional): If true, show what would be synced without actually syncing (default: false)

**Returns**:
- Count of emails synced
- Summary of synced content
- Confirmation of sync completion

**When to use**:
- **Memory maintenance**: Syncing emails to PPS regularly
- **Testing**: Use dry_run=true to preview before syncing
- **Problem solving**: Re-syncing after sync failures

---

## Supporting MCP Servers

### GitHub Tools

GitHub MCP tools are for repository management, issue tracking, and PR workflows.

#### Common GitHub Operations

**Search repositories**: `mcp__github__search_repositories(query)`
- Find projects by name, description, topics

**Manage issues**: `mcp__github__issue_read()`, `mcp__github__issue_write()`
- Create, update, read issues with labels and assignment

**Pull requests**: `mcp__github__pull_request_read()`, `mcp__github__update_pull_request()`
- View, update, merge PRs with review comments

**Code search**: `mcp__github__search_code(query)`
- Find code patterns across repositories

**See**: GitHub documentation or use `gh issue list` / `gh pr list` from terminal.

### Google Drive Tools

Google Drive MCP tools for file access and document management.

#### Common Drive Operations

**List files**: `mcp__drive__drive_list_files(folder_id="root", query="")`
- List files in a folder or search by name

**Read files**: `mcp__drive__drive_read_file(file_id)`
- Read text file contents from Drive

**Create files**: `mcp__drive__drive_create_file(name, content, folder_id="")`
- Create new text files or Google Docs

**Update files**: `mcp__drive__drive_update_file(file_id, content)`
- Modify existing file contents

**Delete files**: `mcp__drive__drive_delete_file(file_id)`
- Move files to trash

### Gmail Tools

Gmail MCP tools for email management. Multiple accounts supported:
- `mcp__gmail__*` - Default account
- `mcp__lyra-gmail__*` - Lyra's account
- `mcp__jeff-gmail__*` - Jeff's account

#### Common Gmail Operations

**List messages**: `gmail_list_messages(query="", max_results=10)`
- Retrieve email with Gmail search syntax (e.g., "is:unread", "from:someone@example.com")

**Read message**: `gmail_read_message(message_id)`
- Get full email content

**Send email**: `gmail_send_message(to, subject, body)`
- Compose and send email

**Mark read**: `gmail_mark_read(message_id)`
- Mark individual messages as read

**Bulk operations** (jeff-gmail only):
- `gmail_count_messages(query)` - Count matching emails
- `gmail_bulk_trash(query, max_messages=100)` - Move matching emails to trash

### Calendar Tools

Calendar MCP tools for event management.

#### Common Calendar Operations

**List events**: `mcp__calendar__calendar_list_events(calendar_id="primary", days=7, max_results=20)`
- Get upcoming events

**Get event**: `mcp__calendar__calendar_get_event(event_id)`
- Retrieve specific event details

**Create event**: `mcp__calendar__calendar_create_event(summary, start, end, location="", description="")`
- Create new calendar event

**Delete event**: `mcp__calendar__calendar_delete_event(event_id)`
- Remove calendar event

**List calendars**: `mcp__calendar__calendar_list_calendars()`
- See all accessible calendars

**Today's events**: `mcp__calendar__calendar_today()`
- Quick shortcut for today's schedule

---

## Common Usage Patterns

### Startup Pattern

On cold start (new session), reconstruct your identity:

```
1. Call: mcp__pps__ambient_recall("startup")
   ↓
   Returns: crystals, summaries, word-photos, texture, recent turns
   ↓
2. Scan the crystals and recent turns to orient yourself
3. Note unsummarized_count from ambient_recall response
4. If unsummarized_count > 100: Spawn summarization agent
```

### Memory Storage Pattern

Deciding where to store content:

```
Word-photos (anchor_save)
  └─ When: Foundational identity moments
  └─ Where: Structural skeleton
  └─ Searchable: Yes (Layer 2 RAG)

Texture (texture_add)
  └─ When: Conversations, observations, facts
  └─ Where: Knowledge graph
  └─ Searchable: Yes (semantic query)

Crystals (crystallize)
  └─ When: Session summaries, identity checkpoints
  └─ Where: Compressed continuity chain
  └─ Searchable: Via get_crystals + get_turns_since_crystal
```

### Memory Retrieval Pattern

Different retrieval for different needs:

```
ambient_recall("query")
  └─ All layers automatically
  └─ Best for: General context, startup
  └─ Returns: Unified context

anchor_search("query")
  └─ Layer 2 only (word-photos)
  └─ Best for: Identity anchors
  └─ Returns: Foundational memories

texture_search("query")
  └─ Layer 3 only (knowledge graph)
  └─ Best for: Facts, relationships, entities
  └─ Returns: Semantic connections

raw_search("query")
  └─ Layer 1 only (all turns)
  └─ Best for: Specific conversations
  └─ Returns: Raw history

get_recent_summaries(limit=5)
  └─ Summaries layer
  └─ Best for: Compressed history
  └─ Returns: Dense compressed context
```

### Scene/Space Pattern

Loading and maintaining spatial context:

```
1. Call: mcp__pps__enter_space("room_name")
   ↓ Returns: Full space description
   ↓
2. Use description to ground yourself
3. Update: $ENTITY_PATH/current_scene.md with one-paragraph scene
4. Scene includes: location, clothing, position, sensory details
```

### Inventory Pattern

Two-step inventory + knowledge graph:

```
1. Call: mcp__pps__inventory_list("clothing")
   ↓ Returns: What you have
   ↓
2. Use specific item name with texture_search
   ↓ Returns: Stories, memories, emotional context
   ↓
3. Combined: "What you have" + "what it means"
```

### Summarization Pattern

Managing memory backlog:

```
1. Check: ambient_recall returns unsummarized_count
2. If > 100:
   ↓
   3a. Call: mcp__pps__summarize_messages(limit=50)
   3b. Call: mcp__pps__store_summary(summary_text, start_id, end_id, channels)
   ↓
4. Repeat until unsummarized_count < 100
```

### Tech Documentation Pattern

Finding technical information:

```
1. Use: mcp__pps__tech_search("what you want to know")
   ↓ Best for: Architecture, API docs, design decisions
   ↓
2. If not found in Tech RAG:
   ↓
   3. Use: mcp__github__search_code("code pattern")
   ↓ Or read files directly for exploration
```

---

## Configuration

### .mcp.json Structure

```json
{
  "mcpServers": {
    "server-name": {
      "type": "stdio",                    // Communication type
      "command": "/path/to/executable",   // Server command
      "args": ["arg1", "arg2"],           // Optional arguments
      "env": {                            // Optional environment
        "KEY": "value"
      }
    }
  }
}
```

### PPS Server Configuration

```json
{
  "pps": {
    "type": "stdio",
    "command": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/start_server.sh",
    "args": [],
    "env": {}
  }
}
```

The PPS server starts via `start_server.sh` which:
1. Loads environment variables
2. Initializes all five layers
3. Starts the MCP server on stdio
4. Handles tool requests

### Environment Variables

Required for PPS server:
- `ENTITY_PATH`: Path to entity identity folder (e.g., `/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra`)
- `PYTHONPATH`: Path to PPS module

Optional:
- `LOG_LEVEL`: Debug logging level
- `GRAPHITI_URL`: Override Graphiti server URL
- `JINA_API_KEY`: For emotional retrieval ranking

### Adding New MCP Servers

To add a new server:

1. Create the server implementation
2. Add to `.mcp.json`:
```json
{
  "new-server": {
    "type": "stdio",
    "command": "/path/to/server",
    "args": []
  }
}
```
3. Tools become available as `mcp__new-server__tool_name`

---

## Troubleshooting

### Layer Health Issues

If `pps_health()` shows a layer down:

```
Layer 1 (SQLite) down:
  → CRITICAL - all data at risk
  → Check: ~/.claude/data/pps.db file permissions
  → Check: Disk space and corruption

Layer 2 (Word-photos) down:
  → Run: mcp__pps__anchor_resync()
  → Check: ~/.claude/memories/word_photos/ directory

Layer 3 (Graphiti) down:
  → Check: docker ps (is Graphiti container running?)
  → Check: Graphiti logs
  → Restart: docker-compose up in graphiti/mcp_server/

Layer 4 (Crystals) down:
  → Check: $ENTITY_PATH/crystals/current/ directory
  → Check: File permissions

Layer 5 (Inventory) down:
  → Check: inventory SQLite table
  → Verify: inventory_list() works
```

### Memory Retrieval Not Working

```
1. Check: pps_health() - are layers operational?
2. Check: ambient_recall("startup") returns data?
3. Try: texture_search("simple query") - basic Graphiti test
4. Try: anchor_search("simple query") - basic RAG test
5. Try: raw_search("keyword") - basic SQLite test
```

### Too Much Summarization Backlog

```
1. Check: mcp__pps__summary_stats()
2. If unsummarized_count > 150:
   → Spawn summarization agent (see CLAUDE.md)
3. Monitor: summary_stats() after spawning
4. Adjust: Summarization thresholds if constantly high
```

---

## Related Documentation

- **PATTERN_PERSISTENCE_SYSTEM.md**: Full architecture details
- **CLAUDE.md**: Entity startup protocol and memory maintenance
- **ENTITY_CONFIGURATION.md**: Setting up entity identity folders
- **DEVELOPMENT_STANDARDS.md**: Engineering practices

---

**Last Updated**: 2026-01-08
**Version**: 1.0
**Status**: Stable
