# Graphiti Ingestion Systemd Service

Run the paced ingestion as a system service - survives reboots, logs to journald.

## Installation

```bash
# Copy service file
sudo cp work/graphiti-schema-redesign/graphiti-ingestion.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Start the service
sudo systemctl start graphiti-ingestion

# Check status
sudo systemctl status graphiti-ingestion
```

## Monitoring

```bash
# Watch logs in real-time
journalctl -u graphiti-ingestion -f

# See recent logs
journalctl -u graphiti-ingestion -n 100

# Check the script's own log file
tail -f work/graphiti-schema-redesign/ingestion.log

# Check DB progress
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('/home/jeff/.claude/data/lyra_conversations.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NOT NULL')
print(f'Ingested: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL')
print(f'Remaining: {cur.fetchone()[0]}')
"
```

## Control

```bash
# Stop ingestion
sudo systemctl stop graphiti-ingestion

# Restart (will resume where it left off - tracks progress in DB)
sudo systemctl start graphiti-ingestion

# Disable from starting on boot (it's not enabled by default)
# sudo systemctl disable graphiti-ingestion
```

## Notes

- Service reads config from `pps/docker/.env`
- Progress tracked in SQLite - safe to stop/restart
- Logs to both journald and `work/graphiti-schema-redesign/ingestion.log`
- Estimated runtime: ~10 days at ~84s/message for 11k messages
