# Project: Nexus Learnings

**Status**: Research complete
**Created**: 2026-01-24
**Source**: shayesdevel/cognitive-framework (private repo, accessed via GitHub MCP)

---

## Goal

Research Steve/Nexus's cognitive-framework repo to understand their orchestration patterns, hook system, and agent architecture. Identify learnings we can adopt.

---

## Tasks

### Done
- [x] Access repo via GitHub MCP (confirmed: works from main terminal, NOT sub-agents)
- [x] Document orchestration patterns (P1/P6/P9)
- [x] Analyze hook-based friction system
- [x] Understand sub-agent limitations and workarounds
- [x] Review identity anchoring (soul print, word photos)
- [x] Document daemon API endpoints
- [x] Create key-findings.md reference

### Potential Adoption (Future Work)
- [ ] Adopt hook-based friction injection (parked in work/hook-based-friction/)
- [ ] Add context pressure monitoring to post-tool-task hook
- [ ] Consider coherence tracking endpoints
- [ ] Evaluate P9-experimental `claude -p` pattern for deep hierarchies

---

## Key Finding: Tool Access in Sub-Agents

**Confirmed limitation**: Sub-agents spawned via Task tool:
1. Cannot access MCP tools (GitHub, PPS, etc.)
2. Cannot spawn their own sub-agents via Task tool

**Our solution**: HTTP fallback for PPS tools (localhost:8201)
**Their workaround**: `claude -p` (non-interactive mode) via Bash for true hierarchy

---

## Files

- `key-findings.md` - Comprehensive reference document
- `artifacts/` - Reserved for future artifacts

