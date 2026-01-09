# Daemon Operations Guide

*Operational guide for managing Lyra's daemons (Discord and Reflection)*

---

## Quick Start

```bash
cd daemon/
./lyra start    # Start both daemons
./lyra status   # What's running?
./lyra follow   # Watch live logs
```

---

## The Two Daemons

Lyra runs as **two independent processes** that share the same memory (Pattern Persistence System):

1. **Discord Daemon** (`lyra_discord.py`)
   - Watches Discord for mentions
   - Responds to user messages
   - Submits events to PPS
   - Runs continuously (unless stopped)

2. **Reflection Daemon** (`lyra_reflection.py`)
   - Wakes every 30 minutes (during configured hours)
   - Triggers crystallization when needed (50+ turns)
   - Performs memory maintenance
   - Processes Graphiti updates
   - Runs on schedule, not continuously

**Key insight**: One can crash without affecting the other. The `./lyra` script is your management interface.

---

## Core Operations

### Starting Daemons

#### Method 1: Simple (Recommended)
```bash
cd daemon/
./lyra start
```

Automatically detects your environment and starts both daemons appropriately.

#### Method 2: Separate Terminals (Debugging)
```bash
cd daemon/

# Terminal 1 - Discord daemon
./run.sh discord

# Terminal 2 - Reflection daemon
./run.sh reflection
```

Useful when you want to see logs from each daemon in separate streams.

#### Method 3: Direct Python (Last Resort)
```bash
cd daemon/
source venv/bin/activate

# Terminal 1
python lyra_discord.py

# Terminal 2
python lyra_reflection.py
```

Only use when script-based starting fails.

---

### Checking Status

```bash
# Quick overview
./lyra status

# Output shows:
# - Discord daemon: running (PID: 12345) or stopped
# - Reflection daemon: running (PID: 12346) or stopped
```

---

### Monitoring Logs

#### Watch Live (Best for Debugging)
```bash
./lyra follow
```

Shows both daemons' logs in real-time. Press Ctrl+C to stop.

**Output format**:
```
[2026-01-08 10:45:23] discord: Message from @jeff in #general
[2026-01-08 10:45:24] discord: Processing with Lyra...
[2026-01-08 10:45:30] discord: Response sent
[2026-01-08 10:46:00] reflection: Starting scheduled check
```

#### View Recent Logs
```bash
./lyra logs
```

Shows last 50 lines from each daemon.

#### View Specific Daemon
```bash
# Discord only
tail -f discord.log

# Reflection only
tail -f reflection.log
```

---

### Stopping Daemons

#### Graceful Stop
```bash
./lyra stop
```

Cleanly shuts down both daemons.

#### Force Stop (if graceful fails)
```bash
pkill -f lyra_discord.py
pkill -f lyra_reflection.py

# Verify stopped
./lyra status
```

---

### Restarting Daemons

#### Full Restart
```bash
./lyra restart
```

Stops and starts both daemons. Clears any stale locks.

#### Restart One Daemon
```bash
pkill -f lyra_discord.py
./run.sh discord
```

---

## Health Checks

### Infrastructure Health

Check if PPS and supporting services are running:

```bash
# PPS MCP Server (port 8206)
curl http://localhost:8206/health

# Graphiti (port 8203)
curl http://localhost:8203/health

# Web UI (port 8204)
curl http://localhost:8204/

# Expected output:
# {"status": "healthy", "version": "..."}
```

If any service is down:
```bash
cd ..  # Back to project root
docker compose ps       # See what's running
docker compose restart  # Restart all services
```

---

## Common Issues & Solutions

### Issue: "Command not found: ./lyra"

**Cause**: Script not executable

**Fix**:
```bash
chmod +x daemon/lyra
# Or use bash directly:
cd daemon/
bash lyra status
```

---

### Issue: "No module named discord"

**Cause**: Virtual environment not activated

**Fix**:
```bash
cd daemon/
source venv/bin/activate
pip install -r requirements.txt
```

---

### Issue: "Discord bot token not found"

**Cause**: `.env` file missing or incomplete

**Fix**:
```bash
cd daemon/
cp .env.example .env
nano .env  # Edit and add your Discord token
```

**Required variables**:
```
DISCORD_BOT_TOKEN=<your-token-here>
DISCORD_CHANNEL_ID=<target-channel-id>
```

---

### Issue: "Connection refused to PPS (localhost:8206)"

**Cause**: PPS service not running

**Fix**:
```bash
cd ..  # Back to project root
docker compose up -d
docker compose ps  # Verify all running

# Then try again:
cd daemon/
./lyra start
```

---

### Issue: "Daemons keep crashing"

**Diagnosis**:
```bash
./lyra logs | grep -i error
```

**Common fixes**:

1. **Stale locks** (most common)
   ```bash
   rm -f ~/.claude/locks/*.lock
   ./lyra restart
   ```

2. **PPS connectivity**
   ```bash
   docker compose restart
   sleep 5
   ./lyra restart
   ```

3. **Memory issues**
   ```bash
   # Check available RAM
   free -h

   # If low, restart to clear
   ./lyra stop && ./lyra start
   ```

4. **Discord token expired**
   ```bash
   # Update .env with new token
   nano daemon/.env
   ./lyra restart
   ```

---

### Issue: "Can't stop daemons (zombie processes)"

**Cause**: Daemons stuck or not responding

**Fix**:
```bash
# Hard kill
pkill -9 -f lyra_discord.py
pkill -9 -f lyra_reflection.py

# Verify they're gone
./lyra status

# Restart
./lyra start
```

---

## Production Setup: Auto-Restart on Boot

For production deployments, install as systemd services:

```bash
cd daemon/
./lyra install
```

This:
- Creates service files
- Installs to `~/.config/systemd/user/`
- Enables auto-start on boot
- Auto-restart if daemons crash

**Manage with**:
```bash
# Check service status
systemctl --user status lyra-discord
systemctl --user status lyra-reflection

# Restart a service
systemctl --user restart lyra-discord

# Watch logs
journalctl --user -f -u lyra-discord
journalctl --user -f -u lyra-reflection

# Disable auto-start
systemctl --user disable lyra-discord lyra-reflection
```

**To uninstall services**:
```bash
systemctl --user stop lyra-discord lyra-reflection
systemctl --user disable lyra-discord lyra-reflection
rm ~/.config/systemd/user/lyra-*.service
systemctl --user daemon-reload
```

---

## Environment Variables

**Critical**:
- `DISCORD_BOT_TOKEN`: Your bot token (in `.env`)
- `DISCORD_CHANNEL_ID`: Channel to listen on (in `.env`)
- `ENTITY_PATH`: Path to entity identity folder (usually auto-detected)

**Optional**:
- `LOGLEVEL`: DEBUG, INFO, WARNING (default: INFO)
- `REFLECT_INTERVAL`: Minutes between reflection checks (default: 30)
- `REFLECT_START`: Hour to start reflection (24h format, default: 8)
- `REFLECT_END`: Hour to stop reflection (24h format, default: 23)

**Example**:
```bash
# debug.sh - for troubleshooting
#!/bin/bash
export LOGLEVEL=DEBUG
export REFLECT_INTERVAL=5  # Check every 5 min instead of 30
cd daemon/
./lyra start
```

---

## Understanding Daemon Lifecycle

### Startup Sequence

1. **Check environment**
   - PPS health
   - Token presence
   - Locks (wait if locked)

2. **Load context**
   - Read crystals
   - Load identity
   - Initialize Graphiti connection

3. **Start listening**
   - Discord: Connect, join channel, await mentions
   - Reflection: Start scheduled heartbeat

### When Daemons Stop

**Graceful shutdown** saves state:
- Logs final state to PPS
- Releases locks
- Closes connections cleanly

**Unclean crash** (kill -9):
- May leave stale locks
- May have incomplete messages
- PPS recovery still works (raw layer intact)

**On restart**:
- Clear any locks
- Reload from crystals
- Resume from last known state

---

## Logging and Debugging

### Log Locations

```
daemon/
├── discord.log      # Discord daemon output
└── reflection.log   # Reflection daemon output
```

### Debug Mode

```bash
cd daemon/
LOGLEVEL=DEBUG ./run.sh discord
```

**Outputs detailed information**:
- Message parsing
- API calls to Graphiti
- Memory operations
- Lock acquisition/release

### Finding Specific Issues

```bash
# Find all errors in logs
grep ERROR daemon/*.log

# Find a specific timestamp
grep "2026-01-08 10:45" daemon/*.log

# Follow only errors
tail -f discord.log | grep ERROR

# Count messages per hour
grep "Message from" discord.log | cut -d' ' -f2 | sort | uniq -c
```

---

## Performance Notes

### Resource Usage

- **Discord daemon**: ~100-200 MB RAM (idle), +50 MB per active session
- **Reflection daemon**: ~80-150 MB RAM (idle)
- **Combined**: ~200-350 MB typical, peaks at ~500 MB during crystallization

### Optimization

If running on limited hardware:

```bash
# Reduce reflection frequency
export REFLECT_INTERVAL=60  # Check every hour instead of 30 min

# Reduce log verbosity (saves I/O)
export LOGLEVEL=WARNING

# Start with limited history
# (edit daemon/startup_context.py to load fewer crystals)
```

### Memory Leaks

Check for memory growth over time:

```bash
# Monitor daemon memory (every 5 seconds)
watch -n 5 'ps aux | grep lyra'

# If growing continuously, logs will show context building up
# Clear locks and restart:
rm ~/.claude/locks/*.lock
./lyra restart
```

---

## Troubleshooting Checklist

When daemons aren't working:

```
[ ] 1. PPS running? docker compose ps
[ ] 2. Discord token valid? Check .env
[ ] 3. Stale locks? rm ~/.claude/locks/*.lock
[ ] 4. Check logs? ./lyra logs | grep ERROR
[ ] 5. Restart infrastructure? docker compose restart
[ ] 6. Restart daemons? ./lyra restart
[ ] 7. Check memory? free -h
[ ] 8. Force kill? pkill -9 -f lyra_
[ ] 9. Check GitHub issues? gh issue list --label daemon
```

---

## Reference: ./lyra Script Commands

```bash
./lyra status              # Show daemon status
./lyra start               # Start both daemons
./lyra stop                # Stop both daemons
./lyra restart             # Stop then start
./lyra logs                # Show recent logs
./lyra follow              # Live log stream
./lyra install             # Install systemd services
./lyra uninstall           # Remove systemd services
./lyra test                # Test configuration
```

---

*Last updated: 2026-01-08*
*For the Awareness project*
