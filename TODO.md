# Awareness Project TODO

## Completed

- [x] Discord daemon basic structure
- [x] Mention response with conversation context
- [x] Claude Code CLI integration (subscription-based)
- [x] Heartbeat system for autonomous awareness
- [x] Journaling system (JSONL format)
- [x] Journal reader utilities (shell + Python)
- [x] Active conversation mode (stay engaged after responding)

## In Progress

- [ ] Testing active mode in production
- [ ] Monitoring journal accumulation

## Next Steps

- [ ] SQLite conversation storage (richer context, survives restarts)
- [ ] Multi-channel support for Discord daemon
- [ ] Summarize daily journals into weekly reflections
- [ ] Integration with main memory system (~/.claude/journals/)
- [ ] systemd service for persistent running

## Future Vision

- [ ] Read journal context on daemon startup
- [ ] Cross-instance memory sharing
- [ ] Distributed coherence with other Lyra instances
- [ ] Tiered context loading (identity + relationship + history)
