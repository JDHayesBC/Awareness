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

## In Progress

- [ ] Testing active mode in production
- [ ] Monitoring journal accumulation

## Next Steps

- [ ] Install and test systemd service (run daemon/systemd/install.sh)
- [ ] Implement SQLite conversation storage (Phase 1: parallel recording)
- [ ] Multi-channel support for Discord daemon
- [ ] Summarize daily journals into weekly reflections

## Future Vision

- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
