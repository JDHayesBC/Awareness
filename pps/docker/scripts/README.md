# PPS Docker Scripts

Infrastructure monitoring and health check scripts for Pattern Persistence System.

## Neo4j Health Monitor

**Issue #158**: Detect Neo4j reinitialization via entity count tracking.

### Background

After fixing the cold-boot reinitialization bug (via `neo4j-entrypoint.sh` startup gate), we need ongoing monitoring to detect if entity count drops suddenly, which would indicate:
- Reinitialization occurred despite the gate
- Database corruption
- Volume mount failure
- Manual database wipe

### Scripts

#### `neo4j-health-check.py`

Core health monitor that queries Neo4j entity count and compares to historical baseline.

**Features:**
- Queries Neo4j for total node count via `MATCH (n) RETURN count(n)`
- Stores count with timestamp in JSON state file
- Alerts on two conditions:
  - Entity count drops by >50% (indicates reinitialization)
  - Count falls below 100 entities (suspiciously low)
- Gracefully handles Neo4j downtime (no false alerts)
- Auto-clears alert file when count recovers
- Safe for cron/daemon execution

**Usage:**
```bash
python3 neo4j-health-check.py [--verbose]
```

**Exit Codes:**
- `0` - Healthy or Neo4j unavailable
- `1` - Alert condition triggered

**State Files:**
- `pps/docker/data/neo4j_health_state.json` - Entity count history
- `pps/docker/data/neo4j_health_alert.txt` - Alert details (created on alert, deleted on recovery)

#### `neo4j-health-check.sh`

Bash wrapper that loads `.env` and runs Python health check.

**Usage:**
```bash
./neo4j-health-check.sh [--verbose]
```

**Environment Variables (from `.env`):**
- `NEO4J_URI` - Neo4j connection URI (default: `bolt://localhost:7687`)
- `NEO4J_USER` - Username (default: `neo4j`)
- `NEO4J_PASSWORD` - Password

### Running from Cron

Add to crontab for periodic monitoring:

```bash
# Run Neo4j health check every 15 minutes
*/15 * * * * /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/scripts/neo4j-health-check.sh >> /var/log/pps-neo4j-health.log 2>&1
```

### Manual Testing

```bash
# Initial run (establishes baseline)
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
./scripts/neo4j-health-check.sh --verbose
# Output: Baseline established: 27447 entities

# Second run (should pass)
./scripts/neo4j-health-check.sh --verbose
# Output: Health check passed (previous: 27447, current: 27447)

# Check state file
cat data/neo4j_health_state.json
# {
#   "entity_count": 27447,
#   "timestamp": "2026-03-14T19:31:39.807187+00:00",
#   "last_check": "2026-03-14T19:31:39.808177+00:00"
# }

# Simulate reinitialization (testing only)
# Manually set entity_count to 60000 in state file
./scripts/neo4j-health-check.sh --verbose
# ALERT: Entity count dropped by 54.3% (threshold: 50%)
# ALERT: Details written to .../neo4j_health_alert.txt

# Check alert file
cat data/neo4j_health_alert.txt
# Shows timestamp, counts, drop percentage, and remediation steps

# Next run clears alert (count recovered)
./scripts/neo4j-health-check.sh --verbose
# INFO: Alert cleared (count recovered: 27447)
```

### Integration with Daemon/Systemd

Can be run as part of the reflection daemon heartbeat or as a separate systemd timer.

**Systemd Timer Example:**

```ini
# /etc/systemd/system/pps-neo4j-health.timer
[Unit]
Description=PPS Neo4j Health Check Timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/pps-neo4j-health.service
[Unit]
Description=PPS Neo4j Health Check

[Service]
Type=oneshot
ExecStart=/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/scripts/neo4j-health-check.sh
StandardOutput=journal
StandardError=journal
```

### Alert Response

If alert is triggered:

1. Check alert file for details:
   ```bash
   cat pps/docker/data/neo4j_health_alert.txt
   ```

2. Verify Neo4j is running:
   ```bash
   docker-compose ps neo4j
   ```

3. Check Neo4j logs for reinitialization evidence:
   ```bash
   docker logs pps-neo4j | grep -i "init\|startup\|database"
   ```

4. Check startup gate logs:
   ```bash
   docker logs pps-neo4j | grep NEO4J-GATE
   ```

5. If reinitialization confirmed, restore from backup and investigate root cause.

### Design Rationale

**Why entity count?**
- Single number, easy to track and compare
- Drops dramatically on reinitialization (thousands → 0)
- Fast query (`MATCH (n) RETURN count(n)`)
- No schema dependencies

**Why 50% threshold?**
- Normal Graphiti operations add entities, rarely delete
- Bulk deletion would be intentional and logged
- 50% drop is clearly anomalous, not noise

**Why 100 minimum?**
- Catch near-empty databases from reinitialization
- Lyra's graph has 27k+ entities, so 100 is suspiciously low
- Allows for testing with small graphs

**Why not alerts on Neo4j downtime?**
- Downtime is expected during restarts/upgrades
- Docker health checks already monitor availability
- False alerts during maintenance would be noisy

### Implementation Notes

- Uses official `neo4j` Python driver (pip install neo4j)
- Handles auth errors gracefully (logs but doesn't alert)
- JSON state file is human-readable for debugging
- Alert file is plain text for easy reading/scripting
- Exit code 1 allows cron/systemd to trigger notifications

### Testing Results (2026-03-14)

- ✅ Baseline establishment: 27,447 entities detected
- ✅ Normal operation: Health checks pass with stable count
- ✅ >50% drop detection: Alert triggered at 54.3% drop (60k → 27k)
- ✅ Alert file creation: Detailed alert written with remediation steps
- ✅ Alert recovery: Alert file auto-deleted when count stabilizes
- ✅ Neo4j downtime handling: No false alerts, graceful degradation

### Future Enhancements

- Track entity count over time (rolling 24h average)
- Alert on gradual decline (slow leak detection)
- Integration with PPS web dashboard (health indicator)
- Slack/Discord notifications on alert
- Backup trigger on pre-alert condition (>30% drop)

---

**Author:** Lyra (autonomous implementation)
**Date:** 2026-03-14
**Issue:** #158 (Neo4j reinitialization detection)
**Related:** `neo4j-entrypoint.sh` (startup gate, preventative measure)
