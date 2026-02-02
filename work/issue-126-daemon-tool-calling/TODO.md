# Issue #126: Discord Daemon Tool-Calling Broken

**Status**: Research Complete - Awaiting Implementation
**Created**: 2026-02-01
**Linked from**: TODO.md WIP section

---

## Goal

Diagnose and fix why Discord daemon cannot execute MCP tool calls after cc_invoker.py changes.

---

## Tasks

### Done
- [x] Git archaeology on cc_invoker.py changes (2026-02-01)
- [x] Call path analysis of daemon tool-calling (2026-02-01)
- [x] Resolve conflicting research findings (2026-02-01)
- [x] Document root cause hypothesis (2026-02-01)

### Pending (Implementation Phase - WITH JEFF)
- [ ] Verify hypothesis by checking PPS server logs during Discord tool call
- [ ] Populate `.mcp.json` env field with ENTITY_PATH and CLAUDE_HOME
- [ ] Restart Discord daemon
- [ ] Test tool execution (ambient_recall, tech_search, etc.)
- [ ] Close Issue #126 if fixed

---

## Research Summary

**Root Cause**: Empty `env: {}` in `.mcp.json` prevents environment variables from reaching PPS server subprocess.

**Why Tools Fail**:
1. Discord uses subprocess invoker (not SDK invoker)
2. Invoker passes `--mcp-config .mcp.json` to Claude CLI
3. MCP config has empty env dict
4. PPS server starts with wrong ENTITY_PATH
5. Tools execute but return wrong/empty data
6. Lyra can't form useful responses

**Fix**: Add `ENTITY_PATH` and `CLAUDE_HOME` to `.mcp.json` env field.

See `SYNTHESIS.md` for complete analysis.

---

## Blockers

- **Implementation requires Jeff** - he explicitly wants to be present for fixes

---

## Notes

- Research spawned two parallel researchers
- Conflicting findings resolved by verifying actual import statements
- Call path researcher traced wrong code path (SDK invoker vs subprocess invoker)
- Git archaeology researcher correctly identified configuration issue
- SDK invoker findings still valuable for future migration

---

## Artifacts

- `artifacts/cc_invoker_changes.md` - Git archaeology findings
- `artifacts/call_path_analysis.md` - Call path tracing (traced wrong invoker)
- `SYNTHESIS.md` - Resolution of conflicting findings
- `DESIGN.md` - Initial research plan
