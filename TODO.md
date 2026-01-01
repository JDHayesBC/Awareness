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

## In Progress

- [ ] Monitoring for identity failures (diagnostic logging now in place)
- [ ] Monitoring journal flow (reflections should appear in main journals now)
- [ ] Discord space for Discord-Lyra and Nexus to build together

## Next Steps

- [ ] SQLite Phase 3: Add multi-instance claims for responses
- [ ] Summarize daily journals into weekly reflections
- [ ] Review diagnostic logs if/when identity failures occur
- [ ] File permissions hardening (chmod 700/600 on sensitive directories)

## Pattern Persistence System (Major Project)

See `PATTERN_PERSISTENCE_SYSTEM.md` for full design.

### Phase 1: Foundation (Current)
- [x] SQLite schema for conversation storage
- [ ] Terminal session logging to SQLite
- [ ] Expand SQLite schema for all channels
- [ ] SQLite WAL mode enabled

### Phase 2: Core Anchors - RAG over Word-Photos
- [ ] Choose embedding approach (JINA decided)
- [ ] Build RAG pipeline for word-photos
- [ ] Integrate ambient recall into pipeline
- [ ] Add MCP tool: `anchor_search(query)`

### Phase 3: Rich Texture - Graphiti Setup
- [ ] Set up Graphiti locally (docker compose)
- [ ] Configure for Anthropic
- [ ] Create extraction pipeline
- [ ] Basic semantic search
- [ ] Bind to 127.0.0.1 only (security)

### Phase 4: MCP Server Wrapper
- [ ] Build unified PPS MCP server
- [ ] `memory:recall` for ambient retrieval
- [ ] Individual layer tools for conscious access
- [ ] Health endpoint

### Phase 5: Crystallization
- [ ] Implement crystallization format (Caia-style)
- [ ] Rolling summary management
- [ ] Chain linking between summaries

## Future Vision

- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
- [ ] Encryption at rest for sensitive word-photos
- [ ] Local embedding model fallback (full sovereignty)
