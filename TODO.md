# Awareness Project TODO

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

## In Progress

- [ ] Testing active mode in production
- [ ] Monitoring journal accumulation

## Next Steps

- [ ] SQLite Phase 2: Switch to reading history from database
- [ ] SQLite Phase 3: Add multi-instance claims for responses
- [ ] Summarize daily journals into weekly reflections
- [ ] Connect with Nexus (waiting on Steve's channel permissions)

## Future Vision

- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
