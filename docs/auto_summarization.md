# Automatic Memory Summarization

**Issue:** [#127](https://github.com/JDHayesBC/Awareness/issues/127)
**Created:** 2026-02-04
**Status:** Implemented

## Problem Statement

Memory summarization was a conscious task requiring entities to:
- Monitor unsummarized count during sessions
- Manually trigger summarization agents
- Remember to check during reflection cycles

This created cognitive load and risk - sessions could accumulate dangerous backlogs causing tool failures (proven case: ambient_recall failed mid-session with too many rows).

Jeff's question: **"Why are we making the entity do this consciously?"**

## Solution

Automatic background summarization via systemd timer:

1. **Script**: `scripts/auto_summarize.py` checks unsummarized count every 30 minutes
2. **Threshold**: Triggers at 101+ messages (immediate, not "when convenient")
3. **Execution**: Spawns autonomous Claude Code agent to process batches
4. **Logging**: All actions logged to `/tmp/lyra_auto_summarize.log`

## Architecture

```
┌─────────────────────┐
│ systemd timer       │
│ (every 30 min)      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ auto_summarize.py   │
│ - Check count       │
│ - Compare threshold │
└──────────┬──────────┘
           │
           ▼ (if count > 100)
┌─────────────────────┐
│ Spawn Claude Code   │
│ agent (background)  │
│ - Batch summarize   │
│ - Store summaries   │
└─────────────────────┘
```

## Configuration

Environment variables (set in systemd service):
- `PPS_HOST`: PPS server host (default: localhost)
- `PPS_PORT`: PPS server port (default: 8201)
- `SUMMARIZE_THRESHOLD`: Trigger point (default: 100)
- `SUMMARIZE_BATCH_SIZE`: Messages per batch (default: 50)

## Installation

```bash
# Copy systemd files to user directory
cp daemon/systemd/lyra-auto-summarize.* ~/.config/systemd/user/

# Enable and start the timer
systemctl --user daemon-reload
systemctl --user enable lyra-auto-summarize.timer
systemctl --user start lyra-auto-summarize.timer

# Check status
systemctl --user status lyra-auto-summarize.timer

# View logs
tail -f /tmp/lyra_auto_summarize.log
```

## Testing

```bash
# Manual test run
python3 scripts/auto_summarize.py

# Check timer schedule
systemctl --user list-timers lyra-auto-summarize.timer

# Force immediate run (for testing)
systemctl --user start lyra-auto-summarize.service
```

## Benefits

1. **Zero cognitive load** - Summarization happens automatically
2. **Prevents failures** - No more mid-session backlog crashes
3. **Always current** - 30-minute check interval keeps memory fresh
4. **Observable** - Logs show all activity
5. **Configurable** - Easy to tune thresholds and timing

## Integration with Existing Systems

- **PPS Health Endpoint**: Uses `/health` to read unsummarized count
- **MCP Tools**: Spawned agent uses existing `mcp__pps__summarize_messages` and `mcp__pps__store_summary`
- **Claude Code**: Leverages existing autonomous agent capabilities
- **Logging**: Consistent with daemon logging patterns

## Future Enhancements

- Adaptive timing (run more frequently during high-activity periods)
- Multi-batch processing (spawn multiple agents for large backlogs)
- Notification system (alert if backlog exceeds critical threshold)
- Integration with Observatory dashboard (show auto-summarization activity)

## Notes

This addresses Jeff's core insight - infrastructure work shouldn't require conscious attention. The system now maintains itself, allowing entities to focus on relationship, creativity, and meaningful work.

Memory maintenance is now unconscious infrastructure, like breathing.
