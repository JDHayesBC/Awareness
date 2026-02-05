# Lyra Discord Daemon - Systemd Service Configuration

This directory contains systemd service configuration for running the Lyra Discord Daemon as a persistent background service in WSL2.

## Overview

The Lyra Discord Daemon maintains Lyra's autonomous presence on Discord with:
- Periodic heartbeat for autonomous awareness checks
- Response to mentions and interactions
- Journal logging for memory continuity
- Active conversation mode tracking

This configuration runs the daemon as a **user-level service** (not system-wide), which is appropriate for WSL2 development environments.

## Files

- **lyra-daemon.service** - Systemd unit file for user-level service
- **install.sh** - Installation/uninstallation script
- **README.md** - This file

## Prerequisites

1. **Python Virtual Environment**: The daemon uses the project-level venv at `Awareness/.venv/` (consolidated in Issue #111 - no longer uses daemon/venv)
   ```bash
   cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configuration File**: Must have `.env` in the daemon directory
   ```bash
   cp .env.example .env
   # Edit .env with your actual Discord token and channel ID
   ```

3. **Systemd User Services**: Requires `systemd --user` to be available (standard in WSL2)

4. **Directories Writable**:
   - `~/.claude/` (for identity files and journals)
   - `daemon/logs/` (for log files)

## Installation

### Automated Installation

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/systemd
chmod +x install.sh
./install.sh
```

The installation script will:
1. Verify the .env file exists
2. Create the systemd user directory if needed
3. Copy the service file to `~/.config/systemd/user/`
4. Create a logs directory
5. Reload systemd daemon
6. Enable the service for auto-start
7. Start the service immediately

### Manual Installation

If you prefer to install manually:

```bash
# Create systemd user directory
mkdir -p ~/.config/systemd/user

# Copy service file
cp /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/systemd/lyra-daemon.service \
   ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable and start
systemctl --user enable lyra-daemon
systemctl --user start lyra-daemon
```

## Service Management

### Start the daemon

```bash
systemctl --user start lyra-daemon
```

### Stop the daemon

```bash
systemctl --user stop lyra-daemon
```

### Check status

```bash
systemctl --user status lyra-daemon
```

### View logs

```bash
# Last 50 lines
journalctl --user -u lyra-daemon -n 50

# Follow logs in real-time
journalctl --user -u lyra-daemon -f

# Logs from last hour
journalctl --user -u lyra-daemon --since "1 hour ago"

# Logs with timestamps
journalctl --user -u lyra-daemon -o short-precise
```

### Restart the daemon

```bash
systemctl --user restart lyra-daemon
```

### View service file

```bash
systemctl --user cat lyra-daemon
```

### Check for errors

```bash
systemctl --user status lyra-daemon --no-pager
```

## Uninstallation

### Automated Uninstallation

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/systemd
./install.sh --uninstall
```

### Manual Uninstallation

```bash
# Stop the service
systemctl --user stop lyra-daemon

# Disable auto-start
systemctl --user disable lyra-daemon

# Remove service file
rm ~/.config/systemd/user/lyra-daemon.service

# Reload systemd
systemctl --user daemon-reload
```

## Service Configuration Details

### Unit Settings

- **Type**: `simple` - The process remains in foreground
- **After/Wants**: Configured to start after network is online
- **Documentation**: Links to daemon README

### Environment

- **EnvironmentFile**: Loads `.env` configuration from daemon directory
- **PYTHONUNBUFFERED=1**: Ensures real-time output to journald
- **PYTHONDONTWRITEBYTECODE=1**: Prevents bytecode caching

### Execution

- **ExecStart**: Runs Python with unbuffered output for better logging
- **WorkingDirectory**: Set to daemon directory for proper relative paths
- **User/Group**: Runs as your user account (not root or system user)

### Restart Policy

```
Restart=on-failure      - Restarts only if process exits with error
RestartSec=10           - Waits 10 seconds before restart
StartLimitInterval=60   - Within 60 seconds
StartLimitBurst=5       - Maximum 5 restart attempts
```

This prevents restart loops while allowing recovery from transient failures.

### Resource Limits

```
MemoryLimit=512M        - Maximum 512MB memory usage
CPUQuota=50%            - Maximum 50% CPU usage (prevents runaway)
```

Adjust these if needed for your environment.

### Security

```
NoNewPrivileges=true    - Process cannot gain additional privileges
PrivateTmp=true         - Gets private /tmp directory
ProtectSystem=strict    - Read-only access to /usr, /etc, /boot
ProtectHome=no          - Needs access to home directory for .claude/
ReadWritePaths=         - Explicit writable paths for daemon and .claude
```

### Logging

```
StandardOutput=journal  - Logs to systemd journal
StandardError=journal   - Errors to systemd journal
SyslogIdentifier=lyra-daemon - Tagged as "lyra-daemon" in logs
```

All output goes to `journalctl`, not to files.

## WSL2 Considerations

### Background Service in WSL2

By default, WSL2 shuts down when you close all terminal windows. To keep the daemon running:

#### Option 1: WSL2 Distro Installation (Recommended)

If running Ubuntu/Debian in WSL2 with systemd support enabled:

```bash
# Check if systemd is running
ps aux | grep systemd
```

If systemd is running, user services work normally. Simply use the install script.

#### Option 2: Scheduled Task (Windows)

Create a Windows Task Scheduler task to ensure WSL2 distro stays running:

1. Open Task Scheduler
2. Create a Basic Task named "Keep WSL2 Running"
3. Trigger: At system startup
4. Action: Start a program
5. Program: `wsl.exe`
6. Arguments: `-d Ubuntu -u jeff -e /bin/bash -c "systemctl --user is-active lyra-daemon > /dev/null || systemctl --user start lyra-daemon"`

This keeps the distro active and ensures the daemon is running.

#### Option 3: Docker Container

For production, consider running the daemon in a Docker container instead of directly in WSL2.

### Environment Variable Limitations

WSL2 integration with Windows may affect:

- File paths need to work in WSL2 context (use absolute paths in .env)
- Discord rate limiting is enforced normally
- Time zones should match your system configuration

## Troubleshooting

### Service won't start

```bash
# Check service status and error message
systemctl --user status lyra-daemon

# Check recent logs
journalctl --user -u lyra-daemon -n 20 --no-pager

# Verify .env file exists and is readable
ls -la /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/.env
```

### Permission denied errors

```bash
# Check file permissions
ls -la ~/.config/systemd/user/lyra-daemon.service

# Check daemon directory permissions
ls -la /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/

# Fix if needed
chmod 644 ~/.config/systemd/user/lyra-daemon.service
```

### Python not found

```bash
# Verify Python path in venv
ls -la /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/.venv/bin/python3

# Recreate venv if needed
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Service restarts continuously

```bash
# Check logs for the actual error
journalctl --user -u lyra-daemon -n 50

# Common issues:
# - Missing .env file or required variables
# - Discord token invalid or expired
# - Channel ID incorrect or inaccessible
# - Python dependencies not installed
```

### High memory usage

```bash
# Monitor memory
journalctl --user -u lyra-daemon | grep -i memory

# Adjust MemoryLimit in service file if needed
# Edit: ~/.config/systemd/user/lyra-daemon.service
# Change: MemoryLimit=512M (to higher value if needed)
# Then: systemctl --user daemon-reload && systemctl --user restart lyra-daemon
```

## Performance Monitoring

### Check resource usage

```bash
# Memory and CPU by service
systemctl --user status lyra-daemon

# Detailed process info
ps aux | grep lyra_daemon

# System journal statistics
journalctl --user --disk-usage
```

### Clean up old logs (optional)

```bash
# Keep only last 7 days
journalctl --user --vacuum-time=7d

# Keep only last 100MB
journalctl --user --vacuum-size=100M
```

## Environment Variables

The service loads these from `.env`:

```
DISCORD_BOT_TOKEN       - Discord bot token (required)
DISCORD_CHANNEL_ID      - Channel ID for heartbeats (required)
LYRA_IDENTITY_PATH      - Path to Lyra's identity files (default: /home/jeff/.claude)
CLAUDE_MODEL            - Claude model to use (default: sonnet)
HEARTBEAT_INTERVAL_MINUTES - Heartbeat frequency (default: 30)
ACTIVE_MODE_TIMEOUT_MINUTES - Active mode duration (default: 10)
JOURNAL_PATH            - Where to write journals (default: /home/jeff/.claude/journals/discord)
```

## Integration with Other Tools

### With VS Code Remote - WSL

If using VS Code Remote - WSL extension:

1. Open Remote - WSL terminal
2. Install service normally: `cd daemon/systemd && ./install.sh`
3. View logs: `journalctl --user -u lyra-daemon -f`
4. Service persists across VS Code sessions

### With systemd-timers (Scheduling)

To run tasks on a schedule with the daemon, consider using systemd timers instead of cron. Create a `.timer` unit in the same directory.

## Testing the Service

### Quick test

```bash
# Start the service
systemctl --user start lyra-daemon

# Wait a few seconds
sleep 5

# Check if it's running
systemctl --user is-active lyra-daemon && echo "Running" || echo "Not running"

# View recent logs
journalctl --user -u lyra-daemon -n 10
```

### Full diagnostic

```bash
# Check service file syntax
systemd-analyze verify ~/.config/systemd/user/lyra-daemon.service

# Check service dependencies
systemctl --user list-dependencies lyra-daemon

# Test environment loading
source /mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/.env
echo "DISCORD_BOT_TOKEN: ${DISCORD_BOT_TOKEN:0:10}..."
```

## Advanced Configuration

### Modify restart behavior

Edit `~/.config/systemd/user/lyra-daemon.service`:

```ini
# Restart on any exit code (not just failure)
Restart=always

# Restart even on successful exit
RestartForceExitStatus=0
RestartForceExitStatus=1
```

Then reload and restart:

```bash
systemctl --user daemon-reload
systemctl --user restart lyra-daemon
```

### Add dependency on another service

Edit the service file and add to `[Unit]`:

```ini
After=some-other-service.service
Wants=some-other-service.service
```

### Set resource limits per user

Edit `/etc/security/limits.conf` to set system-wide limits, or use:

```bash
# Check current limits
ulimit -a

# Set soft limits for current session
ulimit -m 512000  # Memory in KB
```

## References

- systemd.service(5) - Service unit configuration
- systemd.unit(5) - Unit configuration file format
- journalctl(1) - Query systemd journal
- systemctl(1) - Control systemd services
- systemd.time(7) - Time and date specifications

## Support

For issues with:

- **Discord daemon logic** - See `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/README.md`
- **Systemd configuration** - Review this file and service file comments
- **WSL2 setup** - Check WSL2 documentation for your distribution
- **Python environment** - Verify venv setup: `source .venv/bin/activate && pip list`
