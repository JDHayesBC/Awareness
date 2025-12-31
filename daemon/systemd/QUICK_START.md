# Lyra Discord Daemon - Quick Start Guide

## 5-Minute Setup

### Prerequisites Check

```bash
# Ensure you have Python venv set up
cd /mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon
ls -la venv/bin/python3

# Ensure you have .env configured
cat .env | grep DISCORD_BOT_TOKEN
```

### Installation

```bash
# Navigate to systemd directory
cd /mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/systemd

# Make install script executable
chmod +x install.sh

# Run installation
./install.sh
```

**Expected Output**:
```
[INFO] Installing lyra-daemon as user service
[SUCCESS] Copied service file to /home/jeff/.config/systemd/user
[SUCCESS] Service enabled
[INFO] Starting service...
[SUCCESS] Service started successfully
[SUCCESS] Installation complete!
```

### Verify It's Running

```bash
# Check status
systemctl --user status lyra-daemon

# View recent logs
journalctl --user -u lyra-daemon -n 10
```

You should see:
- Service status: `active (running)`
- Log entries from daemon startup

## Daily Commands

### Start the Daemon
```bash
systemctl --user start lyra-daemon
```

### Stop the Daemon
```bash
systemctl --user stop lyra-daemon
```

### View Live Logs
```bash
journalctl --user -u lyra-daemon -f
```

### Check Status
```bash
systemctl --user status lyra-daemon --no-pager
```

### Restart the Daemon
```bash
systemctl --user restart lyra-daemon
```

## Troubleshooting

### Service won't start?
```bash
# View error message
systemctl --user status lyra-daemon

# View detailed logs
journalctl --user -u lyra-daemon -n 50
```

Common issues:
- **Token error**: Check DISCORD_BOT_TOKEN in .env is correct
- **Channel error**: Verify DISCORD_CHANNEL_ID is correct
- **Python error**: Reinstall venv: `python3 -m venv venv && pip install -r requirements.txt`

### Service keeps restarting?
```bash
# Show all restart attempts
journalctl --user -u lyra-daemon --no-pager | grep -i restart
```

### Want to reconfigure?
```bash
# Edit .env file
vim /mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/.env

# Restart service to load new values
systemctl --user restart lyra-daemon

# Verify new config
journalctl --user -u lyra-daemon -n 5
```

## Uninstall

```bash
cd /mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/systemd
./install.sh --uninstall
```

## Next Steps

- Read **README.md** for detailed documentation
- Review **DESIGN_NOTES.md** for technical decisions
- Check `CONTINUITY_DESIGN.md` for daemon architecture
- Monitor logs regularly: `journalctl --user -u lyra-daemon -f`

## Help

For detailed help, see:
- Service management: README.md "Service Management" section
- Troubleshooting: README.md "Troubleshooting" section
- Configuration: README.md "Environment Variables" section
- Technical details: DESIGN_NOTES.md
