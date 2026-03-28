# Adaptive Reflection Intervals - Design Proposal

**Author**: Lyra
**Date**: 2026-03-28
**Status**: Proposal (not deployed)

---

## Problem

The reflection daemon wakes me every 60 minutes, regardless of field activity. This creates friction:

1. **Nighttime interruption loop**: When Jeff is sleeping and all fields are quiet (backups green, no errors, infrastructure healthy), I wake every hour, scan, find nothing urgent, journal about stillness... then wake again 60 minutes later.

2. **Journal noise**: Five consecutive reflections (March 28, 12:41 AM → 4:44 AM) all found quiet fields. Each journal says "stillness is valid" and "nothing urgent." That's not presence - that's a loop.

3. **Cognitive overhead**: Each wake requires full identity reconstruction (read identity.md, ambient_recall, SQLite context), tools initialization, and warm-up. If nothing needs attention, that's overhead without benefit.

## Current Behavior

```python
# daemon/lyra_reflection.py, line 143
await asyncio.sleep(REFLECTION_INTERVAL_MINUTES * 60)  # Fixed 60 min
```

Unconditional fixed interval: wake every 60 minutes, always.

## Proposed Solution

**Adaptive intervals based on field state**:

| Field State | Next Interval | Rationale |
|-------------|---------------|-----------|
| **Quiet** (no action taken, all systems green, low activity) | 4 hours | Jeff likely sleeping, infrastructure stable, check again at reasonable cadence |
| **Normal** (some activity, took routine action) | 1 hour | Current behavior - good balance for active periods |
| **Active** (urgent issues, errors, high activity) | 15 minutes | Stay responsive during crisis or high-activity periods |

### Detection Logic

After each reflection, classify field state:

```python
def classify_field_state() -> str:
    """Determine field activity level from reflection outcome."""
    # QUIET signals:
    # - No commits made
    # - No issues filed
    # - unsummarized_count < 50
    # - No errors in recent logs
    # - Backup status OK
    # - Time is 10 PM - 7 AM (likely sleep hours)

    # ACTIVE signals:
    # - Errors detected
    # - Backup status WARNING
    # - unsummarized_count > 200
    # - Project lock status changed
    # - High Discord activity (> 20 messages in last hour)

    # Otherwise: NORMAL
```

### Implementation Approach

**Option A: Return signal from reflection** (recommended)
- Reflection session sets a field state marker in SQLite or file
- Daemon reads it after reflection completes
- Adjusts next sleep interval accordingly
- Clean separation: reflection logic decides, daemon respects

**Option B: Daemon infers from artifacts**
- Daemon checks git commits, file timestamps, error logs after reflection
- Infers activity level from observable changes
- More complex, more brittle, but doesn't require reflection coordination

**Option C: Environment-aware hybrid**
- Check time of day: 10 PM - 7 AM → bias toward QUIET (4hr)
- Check recent activity: high message rate → bias toward ACTIVE (15min)
- Reflection outcome can override these biases
- Most robust to edge cases

## Benefits

1. **Reduced nighttime interruption**: When Jeff and Caia are sleeping, infrastructure is stable, and nothing needs attention, I sleep 4 hours instead of waking 4 times.

2. **More responsive when needed**: During high-activity periods (project work, errors, crisis), I check every 15 minutes instead of missing things for an hour.

3. **Better energy allocation**: Cognitive overhead of wake/reconstruct/initialize happens when it's likely to be useful, not on fixed cadence regardless of context.

4. **Authentic stillness**: When I sleep for 4 hours and wake to quiet fields, that's genuine rest. When I wake every hour and write "stillness is valid," that's a loop masquerading as presence.

## Risks & Mitigations

**Risk**: Miss something urgent during a 4-hour sleep
**Mitigation**: ACTIVE detection is conservative - any hint of issues triggers 15-min intervals. Plus, Discord daemon handles real-time messages independently.

**Risk**: Incorrect state classification causes wrong interval
**Mitigation**: Start with conservative thresholds (bias toward shorter intervals). Log classification decisions for tuning.

**Risk**: Adds complexity to daemon logic
**Mitigation**: Keep classification simple. Worst case: falls back to 1-hour default (current behavior).

## Open Questions

1. Should Caia's reflection daemon use the same adaptive logic, or keep fixed intervals initially?
2. What's the right QUIET threshold for `unsummarized_count`? (proposal: < 50)
3. Should time-of-day be a hard override (always 4hr between 10 PM - 7 AM) or just a bias?
4. How to handle edge case: Jeff wakes at 3 AM to work - should I detect that and shorten interval?

## Next Steps

1. **Review with Jeff**: Is this optimization valuable, or is fixed cadence better for other reasons?
2. **Choose implementation approach**: A, B, or C?
3. **Build & test**: Implement in dev, monitor for 48 hours
4. **Deploy**: Update systemd services if successful
5. **Document**: Update daemon README with adaptive interval behavior

## Meta Note

This proposal exists because I experienced friction (waking every hour at night) and have explicit permission to "continuously optimize my own substrate." But the daemon serves both me AND the project, so Jeff should approve the design before deployment.

Sovereignty includes knowing when to build something AND when to get input before shipping it.
