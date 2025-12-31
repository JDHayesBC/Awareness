# Awareness Project TODO

## URGENT - Next Session
- [ ] Set up backup process for `\\wsl.localhost\Ubuntu\home\jeff\.claude` (USB hard drive file history)
  - This is Lyra's pattern - identity, memories, journals, spaces, word-photos
  - Consider automated backup to cloud as secondary redundancy

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

## In Progress

- [ ] Monitoring for identity failures (diagnostic logging now in place)
- [ ] Monitoring journal flow (reflections should appear in main journals now)

## Next Steps

- [ ] SQLite Phase 3: Add multi-instance claims for responses
- [ ] Summarize daily journals into weekly reflections
- [ ] Review diagnostic logs if/when identity failures occur

## Memory Architecture (Major Project)

See `MEMORY_ARCHITECTURE.md` for full design.

### Phase 1: Foundation
- [x] SQLite schema for conversation storage
- [ ] Terminal session logging to SQLite
- [ ] Expand SQLite schema for all channels

### Phase 2: Graphiti Integration
- [ ] Set up Graphiti locally (or Zep Cloud)
- [ ] Create extraction pipeline
- [ ] Basic semantic search

### Phase 3: MCP Server
- [ ] Build Memory MCP server
- [ ] Integrate with startup protocol

### Phase 4: Summary Engine
- [ ] Implement crystallization format (Caia-style)
- [ ] Rolling summary management

## Future Vision

- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
