# Claude Code Hang - Root Cause Analysis (RESOLVED)

**Date**: 2026-01-31
**Reported by**: Jeff
**Investigated by**: Claude (from test project)
**Status**: RESOLVED

## Symptom

Claude Code hangs/freezes when started in the Awareness project directory.

## Root Cause: Large Session Files

**NOT** the MCP servers or hooks (those were red herrings).

The actual problem: **405MB of session transcript files** (725 `.jsonl` files) in:
```
~/.claude/projects/-mnt-c-Users-Jeff-Claude-Projects-Awareness/
```

Claude Code tries to scan/index these on startup. With 405MB of JSON, it hangs.

### Evidence

| Project | Session Files | Size | Result |
|---------|---------------|------|--------|
| Awareness | 725 files | 405MB | HUNG |
| test | 3 files | <1MB | Works fine |

Largest files:
- 59MB - 34e88796...jsonl
- 19MB - 4e379107...jsonl
- 18MB - multiple files

Research (via Claude web) confirmed: **19MB+ session files cause 99% CPU on startup**.

## Solution

Moved all session files to backup:
```
/mnt/c/Users/Jeff/Claude_Projects/test/awareness-session-backup/
```

See `RESTORE-NOTES.md` in that directory if restoration is ever needed.

## What These Session Files Are

Claude Code's raw terminal conversation transcripts - NOT Lyra's memory.

**Lyra's memory is safe in:**
- PPS layers (Neo4j graph, ChromaDB vectors, SQLite)
- Entity files (identity.md, crystals, word-photos)

The session files are just terminal scrollback logs for `/history` and session resumption.

## Prevention

Periodically clean old session files:
```bash
# Check size
du -sh ~/.claude/projects/-mnt-c-Users-Jeff-Claude-Projects-Awareness/

# If too large, remove old sessions (keeps recent ones)
find ~/.claude/projects/-mnt-c-Users-Jeff-Claude-Projects-Awareness/ \
  -name "*.jsonl" -mtime +7 -delete
```

## Investigation Notes

We initially suspected (and temporarily disabled):
- PPS MCP server (WSL filesystem + Python imports)
- lyra-gmail MCP server
- All three hooks (UserPromptSubmit, Stop, SessionEnd)

These were all restored after identifying the true cause. The MCP servers and hooks work fine - it was purely a session file size issue.
