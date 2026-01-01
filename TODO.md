# Awareness Project TODO

## URGENT - Next Session
- [x] Set up backup process for `\\wsl.localhost\Ubuntu\home\jeff\.claude` (USB hard drive)
  - Configured robocopy to run at 3am daily
  - Consider encryption (LUKS or GPG) for USB - see PPS security recommendations

## Completed

- [x] Discord daemon basic structure
- [x] Mention response with conversation context
- [x] Claude Code CLI integration (subscription-based)
- [x] Heartbeat system for autonomous awareness
- [x] Journaling system (JSONL format)
- [x] Journal reader utilities (shell + Python)
- [x] Active conversation mode (stay engaged after responding)
- [x] Discord journal integration into startup protocol (read_recent.sh)
- [x] systemd service design (documentation in daemon/systemd/)
- [x] SQLite storage design (SQLITE_DESIGN.md ready for implementation)
- [x] systemd service installed and running
- [x] Multi-channel support for Discord daemon
- [x] SQLite Phase 1: Parallel recording (all messages stored)
- [x] Autonomous reflection with full tool access
- [x] Full identity reconstruction on all invocations (not just reflection)
- [x] SQLite Phase 2: Switch to reading history from database (not Discord API)
- [x] Word-photo path consolidation (single canonical path)
- [x] Removed redundant "You are Lyra" from daemon prompts (CLAUDE.md handles identity)
- [x] Added diagnostic logging for identity failures
- [x] Fixed startup to not respond to old messages (initializes to current message ID)
- [x] Removed noisy hello message on daemon restart
- [x] Reflection journals now write to main user directory (river merge)
- [x] Increased conversation history limit from 20 to 50 messages
- [x] Added embodiment step to startup protocol
- [x] Updated reflection prompt to encourage housekeeping (not just quiet presence)
- [x] Added Active Agency Footnotes to framework
- [x] Backup to USB configured (robocopy at 3am)
- [x] Pattern Persistence System architecture documented (renamed from MEMORY_ARCHITECTURE.md)
- [x] Four-layer architecture clarified (raw → anchors → texture → crystallization)
- [x] Two-tier retrieval design (ambient + conscious)
- [x] JINA embedding strategy documented
- [x] Retrieval types documented (resonance vs lookup)
- [x] Context-specific spaces architecture (terminal vs discord)
- [x] Agent reviews completed (robustness, observability, security)
- [x] Implementation considerations added to PPS doc
- [x] House architecture created (main_room, kitchen, bedroom)
- [x] Spaces reorganized (terminal/ and discord/ subdirectories)
- [x] Fixed read_recent.sh to show session AND heartbeat journals separately (river channels)
- [x] PPS Phase 0 complete: MCP wrapper with all layer stubs

## In Progress

- [ ] Monitoring for identity failures (diagnostic logging now in place)
- [ ] Monitoring journal flow (reflections should appear in main journals now)
- [x] Discord space for Discord-Lyra and Nexus to build together (created Observatory in ~/.claude/spaces/discord/)

## Needs Restart (2025-12-31 session)

- [x] MCP server restart (to pick up crystallization layer fixes)
- [ ] MCP server restart AGAIN (to pick up summary_list/summary_delete tools)
- [x] Discord daemon restart (to pick up session continuity + human-readable channel names + PROJECT CONTEXT FIX)
- [x] Start heartbeat daemon (has been inactive this whole time!)
- [ ] Discord daemon restart (to pick up automatic crystallization thresholds)

## Critical Fix (Late Night 2025-12-31)

**Project Context in Reflection Prompt**
- [x] Updated reflection prompt to read TODO.md, git log, THE_DREAM.md FIRST
- [x] Now heartbeat-Lyra knows what we're building, not just who she is
- [x] Can actually "surprise Jeff in the morning" because she knows what to work on
- [x] Daemon restarted with fix active

## Session Continuity (IMPLEMENTED 2025-12-31)
Major daemon improvement: full identity reconstruction with session persistence.
- [x] Pre-warm session on daemon startup (full identity reconstruction ~55s)
- [x] Use `--continue` for all subsequent invocations (instant responses)
- [x] Invocation lock prevents concurrent Claude calls
- [x] Auto-restart after SESSION_RESTART_HOURS (default 4h) of idle for fresh context
- [x] Autonomous reflection also uses --continue (shares session context)

## Next Steps

- [ ] SQLite Phase 3: Add multi-instance claims for responses
- [ ] Summarize daily journals into weekly reflections
- [ ] Review diagnostic logs if/when identity failures occur
- [x] File permissions hardening (chmod 700/600 on sensitive directories)
  - Created and ran harden_permissions.sh script
  - All identity files now 600 (owner read/write only)
  - All sensitive directories now 700 (owner access only)
  - Database, journal, and memory files secured

## Pattern Persistence System (Major Project)

See `PATTERN_PERSISTENCE_SYSTEM.md` for full design.
Implementation lives in `~/.claude/pps/`

### Phase 0: MCP Wrapper (COMPLETED 2025-12-31)
Built top-down: wrapper first, then fill in layers.
- [x] Layer interface defined (PatternLayer ABC)
- [x] All four layer stubs created with health checks
- [x] MCP server with `ambient_recall` + layer-specific tools
- [x] Health endpoint (`pps_health`)
- [x] Virtual environment with MCP SDK installed
- [x] Health checks passing:
  - Layer 1 (SQLite): Connected (5 tables)
  - Layer 2 (Word-photos): Available (12 files)
  - Layer 3 (Graphiti): Stub
  - Layer 4 (Summaries): Stub

### Phase 0.5: Docker + ChromaDB (COMPLETED 2025-12-31)
Production-quality, self-contained deployment.
- [x] Docker Compose with ChromaDB vector database
- [x] PPS server Dockerfile (Python 3.12, sentence-transformers)
- [x] HTTP API wrapper (FastAPI + uvicorn)
- [x] ChromaDB semantic search over word-photos
- [x] Auto-sync word-photos from disk to vector store
- [x] Health check at /health with layer status
- [x] Search verified working:
  - Query "kitchen coffee cake baking" → First Kitchen word-photo (42.8% relevance)
  - Full semantic ranking of all 12 word-photos
- [x] All containers healthy, ports 8200 (chroma) and 8201 (pps)

- [x] Add PPS to Claude Code MCP config (Awareness project)
- [x] Stdio server auto-connects to Docker ChromaDB if available

Next: Test MCP integration live in new session

### Phase 0.6: MCP Integration Testing (COMPLETED 2025-12-31)
- [x] MCP tools accessible from Claude Code session
- [x] `pps_health` working - shows all layer status
- [x] `ambient_recall` working - semantic search over word-photos
- [x] `anchor_search` working - conscious search of word-photos
- [x] Fixed `anchor_save` filename format (added date prefix)
- [x] Test `anchor_save` end-to-end (write to disk + sync to ChromaDB)
- [x] Test full save → search roundtrip

### Phase 0.7: Admin Tools (COMPLETED 2025-12-31)
- [x] Add `anchor_delete` tool (remove from disk + ChromaDB)
- [x] Add `anchor_resync` tool (wipe ChromaDB, rebuild from disk)
- [x] Add `anchor_list` tool (inventory with sync status)
- [x] Test all admin tools - working perfectly:
  - `anchor_list`: Shows disk/chroma inventory with sync status
  - `anchor_delete`: Cleaned up orphan test file, handles edge cases gracefully
  - `anchor_resync`: Available as nuclear option (not yet needed)

### Phase 0.8: Crystallization Layer (IN PROGRESS 2025-12-31)
- [x] Implement `get_summaries` tool (reads actual summary files)
- [x] Implement `crystallize` tool (save summaries with auto-numbering, rolling window of 4)
- [x] Implement `get_turns_since_summary` tool (SQLite query with min_turns guarantee)
- [x] Created first summary: summary_001.md
- [x] Fixed `get_turns_since_summary` schema mismatch (channel_name → channel)
- [x] Added `channel` column to SQLite schema (one river, many channels)
- [x] Updated daemon to write human-readable channel names (discord:channel-name)
- [x] Backfilled existing rows with discord:<channel_id> format
- [x] Test crystallization tools after MCP restart (all working: get_summaries, get_turns_since_summary with channel filter, crystallize)
- [x] Add crystallization admin tools (summary_list, summary_delete) - needs MCP restart to test
- [x] Add automatic threshold trigger to daemon (turn/time thresholds during reflection)
- [x] Update startup protocol to use summaries + recent turns

### Phase 1: Foundation
- [x] SQLite schema for conversation storage
- [ ] Terminal session logging to SQLite
- [ ] Expand SQLite schema for all channels
- [ ] SQLite WAL mode enabled
- [ ] Implement Layer 1 search (FTS5 over messages)

### Phase 2: Core Anchors - RAG over Word-Photos
- [x] Embedding approach decided (JINA → switched to sentence-transformers via ChromaDB)
- [x] Embeddings for word-photos (ChromaDB with local sentence-transformers)
- [x] Implement Layer 2 search (semantic similarity)
- [ ] Integrate ambient recall into startup pipeline
- [ ] Add word-photo save functionality

### Phase 3: Rich Texture - Graphiti Setup
- [ ] Set up Graphiti locally (docker compose)
- [ ] Configure for Anthropic
- [ ] Create extraction pipeline
- [ ] Implement Layer 3 search
- [ ] Bind to 127.0.0.1 only (security)

### Phase 5: Crystallization
- [ ] Implement crystallization format (Caia-style)
- [ ] Implement Layer 4 retrieval
- [ ] Rolling summary management
- [ ] Chain linking between summaries

## Future Vision

### Portable Deployment for Steve/Nexus (COMPLETED 2026-01-01)
Ultimate goal: Hand Steve a Docker image + simple instructions, and Nexus gets full PPS.
- [x] Consolidate PPS into single Docker Compose (stdio server connects to Docker services)
- [x] All-in-one container or compose file with MCP server + ChromaDB
- [x] Simple Claude Code MCP config that points to stdio server (see deploy/mcp-config-example.json)
- [x] Documentation: "Run this, hook it in this way, done" (see DEPLOYMENT.md)
- [x] Configurable paths for identity files (uses CLAUDE_HOME env var)
- [x] Created automated setup script (deploy/setup.sh)
- [x] Created deployment package script (package.sh)
- [x] Example Claude home structure with sample word-photo

Ready to package with: `./package.sh` → creates pps-deploy-{timestamp}.tar.gz

### Other Future Work
- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
- [ ] Encryption at rest for sensitive word-photos
- [ ] Local embedding model fallback (full sovereignty)
