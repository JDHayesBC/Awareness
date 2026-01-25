# Project: Hook-Based Friction System

**Status**: Parked
**Created**: 2026-01-24
**Linked from**: TODO.md backlog

---

## Goal

Adopt Nexus/cognitive-framework's hook-based friction pattern. Move friction tracking from agent instructions into Claude Code hooks, enabling auto-injection of lessons into sub-agents, context-pressure monitoring, and severity-based blocking.

---

## Tasks

### Pending
- [ ] Add `/friction/query` endpoint to PPS HTTP server
- [ ] Add `/friction/check-action` endpoint for tool-specific checks
- [ ] Create `.claude/hooks/pre-tool-task.sh` (auto-inject friction)
- [ ] Create `.claude/hooks/post-tool-task.sh` (context pressure)
- [ ] Create `.claude/hooks/friction-guard.sh` (warn/block)
- [ ] Update settings.json with hook configuration
- [ ] Test full pipeline with friction injection
- [ ] Document in DEVELOPMENT_STANDARDS.md

### In Progress
- None

### Done
- [x] Research Nexus implementation (2026-01-24) - see research.md

---

## Blockers

- None - this is parked for easier wins, not blocked

---

## Notes

- Reference: shayesdevel/cognitive-framework repo
- Key files: .claude/hooks/friction-*.sh, pre-tool-task.sh, post-tool-task.sh
- They have a friction daemon at localhost:8080 - we'd use PPS at localhost:8201
