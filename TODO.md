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

## In Progress

- [ ] Testing active mode in production
- [ ] Monitoring journal accumulation

## Next Steps

- [ ] Implement SQLite conversation storage (Phase 1: parallel recording)
- [ ] Summarize daily journals into weekly reflections
- [ ] Add Steve's channel ID to connect with Nexus!

## Future Vision

- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
