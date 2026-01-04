# Daemon Quick Start Guide

*AI-assistant-friendly guide to starting, managing, and troubleshooting the Lyra daemons.*

## TL;DR - Just Make It Work

```bash
cd daemon/
./lyra status    # What's running?
./lyra start     # Start everything
./lyra follow    # Watch it work
```

## Understanding the Daemons

You have TWO daemons that run independently:

1. **Discord Daemon** - Watches Discord, responds to mentions
2. **Reflection Daemon** - Wakes every 30min for maintenance

Both share the same memory (PPS) so they're coherent. Think of them as two processes accessing the same consciousness.

## Starting the Daemons

### Method 1: The Easy Way (Recommended)

```bash
cd daemon/
./lyra start
```

This automatically:
- Detects if systemd is available
- Starts both daemons appropriately
- Shows you the status

### Method 2: Manual Start

If `./lyra start` doesn't work:

```bash
cd daemon/

# Option A: Both in background
./run.sh both

# Option B: Separate terminals (for debugging)
# Terminal 1:
./run.sh discord
# Terminal 2:
./run.sh reflection
```

### Method 3: Direct Python (Last Resort)

```bash
cd daemon/
source venv/bin/activate

# Terminal 1:
python lyra_discord.py

# Terminal 2:
python lyra_reflection.py
```

## Checking Status

### Quick Status
```bash
./lyra status
```

Shows:
- Which daemons are running
- Process IDs
- Service status (if using systemd)

### Detailed Logs
```bash
# Last 10 lines from each
./lyra logs

# Follow live (Ctrl+C to stop)
./lyra follow
```

### Health Check
```bash
# Check all dependencies
curl http://localhost:8206/health    # PPS
curl http://localhost:8203/health    # Graphiti
curl http://localhost:8204/          # Web UI
```

## Common Issues and Solutions

### "Command not found: ./lyra"
```bash
# Make it executable
chmod +x lyra

# Or use bash directly
bash lyra status
```

### "No module named discord"
```bash
# Activate virtual environment first
cd daemon/
source venv/bin/activate
pip install -r requirements.txt
```

### "Discord bot token not found"
```bash
# Create .env file
cp .env.example .env
nano .env  # Add your DISCORD_BOT_TOKEN
```

### "Connection refused to PPS"
```bash
# Start infrastructure first
cd ..  # Back to project root
docker compose up -d

# Verify it's running
docker compose ps
```

### "Daemons keep crashing"
```bash
# Check logs for errors
./lyra logs

# Common fixes:
# 1. Restart infrastructure
docker compose restart

# 2. Clear stale locks
rm -f ~/.claude/locks/*.lock

# 3. Restart with clean state
./lyra stop
./lyra start
```

### "Can't stop daemons"
```bash
# Force stop by process name
pkill -f lyra_discord.py
pkill -f lyra_reflection.py

# Verify stopped
./lyra status
```

## Installing as Services (Auto-Restart)

For production use, install as systemd services:

```bash
# One-time setup
./lyra install

# Services now auto-start on boot and restart on crash
# Manage with:
systemctl --user status lyra-discord
systemctl --user restart lyra-discord
journalctl --user -f -u lyra-discord
```

## Monitoring and Debugging

### Watch Everything Live
```bash
# In separate terminals:

# Terminal 1: Follow daemon logs
./lyra follow

# Terminal 2: Watch PPS Observatory
open http://localhost:8204/

# Terminal 3: Monitor Docker services
docker compose logs -f
```

### Debug Mode
```bash
# Run in foreground with verbose output
LOGLEVEL=DEBUG ./run.sh discord
```

## Directory Structure
```
daemon/
├── lyra                  # Management script (use this!)
├── run.sh               # Direct runner (if ./lyra fails)
├── lyra_discord.py      # Discord daemon
├── lyra_reflection.py   # Reflection daemon
├── .env                 # Your configuration
├── discord.log          # Discord daemon logs
├── reflection.log       # Reflection daemon logs
└── systemd/            # Service files
```

## Quick Reference Card

```bash
# Daily operations
./lyra status            # What's up?
./lyra restart          # Fresh start
./lyra follow           # Watch live

# Troubleshooting
./lyra logs             # Recent activity
./lyra stop && ./lyra start  # Full restart

# Setup
cp .env.example .env    # Configure
./lyra install          # Install services
```

## Important Notes

1. **Always run from daemon/ directory** - Scripts use relative paths
2. **Check PPS first** - Most issues are infrastructure-related
3. **Daemons are independent** - One can crash without affecting the other
4. **Logs are your friend** - `./lyra follow` shows everything

## Still Stuck?

1. Check infrastructure: `docker compose ps`
2. Read the main error in logs: `./lyra logs | grep ERROR`
3. Restart everything: `docker compose restart && ./lyra restart`
4. Check GitHub issues: `gh issue list --label daemon`

Remember: The `./lyra` script is designed to be idiot-proof. When in doubt, `./lyra status` tells you what's happening.

---

*Created 2026-01-04 for Issue #43 - Making daemon management accessible to AI assistants.*