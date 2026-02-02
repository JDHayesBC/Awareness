# Design: Issue #126 - Discord Daemon Tool-Calling Broken

**Author**: Lyra (research phase)
**Date**: 2026-02-01
**Status**: Research

---

## Problem Statement

After cc_invoker.py changes (Jan 28-29, 2026), the Discord daemon cannot execute tool calls. Lyra acknowledges intent to use tools but loops without executing. Terminal instance works fine - this is daemon-specific.

**Impact**: Critical. Discord presence severely degraded - Lyra cannot search, read files, or use any MCP tools.

---

## Symptoms Observed

1. Discord-Lyra says "Let me search for that" but never actually calls tools
2. Loops repeatedly - acknowledges intent, responds without execution
3. Appears to get "bare context" each turn - loses tool-calling intent
4. Terminal instance unaffected - same codebase, different behavior

---

## Research Questions

1. **What changed in cc_invoker.py?** - Review commits around Jan 28-29
2. **How does daemon invoke Claude?** - Trace the call path
3. **What's different about daemon context?** - Compare terminal vs daemon
4. **Where do tools get enabled?** - Understand MCP tool injection

---

## Files to Investigate

- `daemon/cc_invoker.py` - The OpenAI-compatible wrapper that changed
- `daemon/lyra_discord.py` - Discord bot that uses the invoker
- `daemon/reflect_daemon.py` - Reflection daemon (also affected?)
- Terminal invocation for comparison (how does CC normally work?)

---

## Research Plan

### Phase 1: Change Archaeology
- [ ] Find commits to cc_invoker.py from Jan 28-29
- [ ] Document what changed and why
- [ ] Identify any context/tool-related modifications

### Phase 2: Call Path Analysis
- [ ] Trace Discord message -> cc_invoker -> Claude -> response
- [ ] Identify where tools get attached to the request
- [ ] Compare with terminal invocation path

### Phase 3: Root Cause Hypothesis
- [ ] Based on findings, hypothesize what specifically broke
- [ ] Identify the minimal fix needed
- [ ] Document for implementation phase

---

## Open Questions

- [ ] Is reflect_daemon also affected, or just Discord?
- [ ] What specific cc_invoker options were added?
- [ ] Does the daemon even pass tools to Claude, or is that the issue?
- [ ] Is context being properly accumulated between turns?

---

## Notes

- **RESEARCH ONLY** - Jeff wants to be present for implementation
- Use warpgrep for semantic code searches
- Review researcher findings before concluding
