# Lyra Discord Daemon - Systemd Service Configuration Index

## Overview

This directory contains complete systemd service configuration for running the Lyra Discord Daemon as a persistent background service in WSL2.

**Status**: Production Ready
**Version**: 1.0
**Last Updated**: 2025-12-30

## Directory Structure

```
daemon/systemd/
├── INDEX.md                  # This file - navigation and overview
├── QUICK_START.md           # 5-minute setup and daily commands
├── README.md                # Comprehensive documentation (473 lines)
├── DESIGN_NOTES.md          # Technical architecture and decisions (430 lines)
├── lyra-daemon.service      # Systemd service unit file
├── install.sh               # Automated installation/uninstallation script
└── [other daemon files...]
```

## File Descriptions

### Documentation Files

#### [QUICK_START.md](./QUICK_START.md) - START HERE
- **Purpose**: Get up and running in 5 minutes
- **Content**:
  - Prerequisites checklist
  - Installation steps with expected output
  - Daily command reference
  - Basic troubleshooting
- **Read Time**: 3 minutes
- **Audience**: First-time users, quick reference

#### [README.md](./README.md) - COMPREHENSIVE GUIDE
- **Purpose**: Complete documentation and reference
- **Content**:
  - Installation (automated and manual)
  - Service management commands
  - Configuration details
  - Uninstallation procedures
  - WSL2-specific considerations
  - Extensive troubleshooting section
  - Performance monitoring
  - Advanced configuration examples
- **Read Time**: 15 minutes
- **Audience**: Users, administrators, developers

#### [DESIGN_NOTES.md](./DESIGN_NOTES.md) - TECHNICAL DEEP DIVE
- **Purpose**: Understand design decisions and rationale
- **Content**:
  - Design decisions with alternatives considered
  - Failure recovery scenarios
  - Monitoring and observability
  - WSL2 specific considerations
  - Performance characteristics
  - Testing and validation
- **Read Time**: 20 minutes
- **Audience**: DevOps engineers, system architects, maintainers

### Configuration Files

#### [lyra-daemon.service](./lyra-daemon.service) - SERVICE UNIT FILE
- **Purpose**: Systemd unit file that defines the service
- **Key Features**:
  - Type: `simple` (foreground process)
  - Restart: `on-failure` with circuit breaker
  - Logging: `journald` (systemd journal)
  - Security: Strict restrictions with home access
  - Resource limits: 512MB memory, 50% CPU
  - Network: Starts after network-online.target
- **Installed To**: `~/.config/systemd/user/lyra-daemon.service`
- **Do Not Edit Directly**: Modify via install script or copy to systemd directory

### Installation Scripts

#### [install.sh](./install.sh) - AUTOMATED SETUP
- **Purpose**: One-command installation and uninstallation
- **Features**:
  - Prerequisites validation
  - Systemd directory creation
  - Service file installation
  - Auto-start configuration
  - Service startup
  - Colored output with status indicators
  - Uninstallation with `--uninstall` flag
- **Usage**:
  ```bash
  ./install.sh              # Install
  ./install.sh --uninstall # Uninstall
  ```
- **Permissions**: Executable, runs as user (no sudo needed)

## Quick Navigation

### I'm new to this system

1. Read: [QUICK_START.md](./QUICK_START.md) (3 min)
2. Run: `./install.sh` (1 min)
3. Verify: `systemctl --user status lyra-daemon` (30 sec)
4. View logs: `journalctl --user -u lyra-daemon -f` (ongoing)

### I need to manage the service

Reference: [README.md](./README.md) "Service Management" section

**Common commands**:
```bash
systemctl --user start lyra-daemon         # Start
systemctl --user stop lyra-daemon          # Stop
systemctl --user status lyra-daemon        # Check status
journalctl --user -u lyra-daemon -f        # Follow logs
systemctl --user restart lyra-daemon       # Restart
```

### I need to debug an issue

1. Check logs: `journalctl --user -u lyra-daemon -n 50`
2. Check status: `systemctl --user status lyra-daemon`
3. Review: [README.md](./README.md) "Troubleshooting" section
4. Advanced: [DESIGN_NOTES.md](./DESIGN_NOTES.md) "Failure Recovery" section

### I need to understand the design

Read: [DESIGN_NOTES.md](./DESIGN_NOTES.md)

Covers:
- Why each configuration choice was made
- Alternatives considered and rejected
- Failure recovery mechanisms
- WSL2 specific considerations
- Performance characteristics

### I need to reconfigure the service

1. Edit `.env`: `/mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/.env`
2. Restart service: `systemctl --user restart lyra-daemon`
3. Verify: `journalctl --user -u lyra-daemon -n 5`

For service-level changes (not environment):
1. Edit service file: `~/.config/systemd/user/lyra-daemon.service`
2. Reload: `systemctl --user daemon-reload`
3. Restart: `systemctl --user restart lyra-daemon`

### I need to uninstall

```bash
cd /mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/systemd
./install.sh --uninstall
```

Or manually:
```bash
systemctl --user stop lyra-daemon
systemctl --user disable lyra-daemon
rm ~/.config/systemd/user/lyra-daemon.service
systemctl --user daemon-reload
```

## System Architecture

```
Discord Server
    ↓
Discord.py Library
    ↓
lyra_daemon.py (Python Application)
    ├── Heartbeat Loop (every 30 min)
    ├── Message Handler (on mentions)
    └── Journal Writer (memory continuity)
    ↓
Systemd Service Manager
    ├── Automatic Restart (on failure)
    ├── Resource Management (limits)
    └── Lifecycle Control (start/stop/enable)
    ↓
Journald (Logging)
    └── Journal Entries (queryable, persistent)
```

## Key Features

### Reliability

- **Automatic Restart**: Recovers from transient failures
- **Circuit Breaker**: Prevents restart loops
- **Graceful Shutdown**: 30-second timeout for clean exit
- **Resource Limits**: Prevents resource exhaustion

### Observability

- **Journald Logging**: All output to systemd journal
- **Real-time Monitoring**: `journalctl -f` for live logs
- **Status Monitoring**: Quick health checks
- **Historical Logs**: Full audit trail

### Security

- **User-level Service**: No root access required
- **Read-only System**: `/usr`, `/etc` protected
- **Privilege Isolation**: `NoNewPrivileges=true`
- **Path Restrictions**: Explicit writable directories only

### Compatibility

- **WSL2 Native**: Tested on WSL2 Ubuntu 22.04+
- **Python 3.12+**: Uses modern async patterns
- **User Services**: Works without system-level changes
- **Virtual Environment**: Uses venv for isolation

## Systemd Service Lifecycle

```
User runs: systemctl --user start lyra-daemon
    ↓
Systemd reads: ~/.config/systemd/user/lyra-daemon.service
    ↓
Loads environment: ~/.env
    ↓
Changes to directory: ~/Documents/1)) Caia/Awareness/daemon
    ↓
Executes: venv/bin/python3 -u lyra_daemon.py
    ↓
Daemon initializes Discord connection
    ↓
Daemon enters event loop (listening for messages)
    ↓
Heartbeat triggers every 30 minutes
    ↓
On error → Process exits → Systemd waits 10 sec → Restart
    ↓
User runs: systemctl --user stop lyra-daemon
    ↓
Systemd sends SIGTERM (graceful shutdown signal)
    ↓
Python exits, Discord connection closes
    ↓
(If still running after 30 sec: systemd sends SIGKILL)
```

## Environment Configuration

The service loads from `.env` file containing:

```bash
DISCORD_BOT_TOKEN              # Discord authentication (required)
DISCORD_CHANNEL_ID             # Channel for heartbeats (required)
LYRA_IDENTITY_PATH            # Identity files location
CLAUDE_MODEL                   # Claude model to use
HEARTBEAT_INTERVAL_MINUTES    # Heartbeat frequency
ACTIVE_MODE_TIMEOUT_MINUTES   # Engagement duration
JOURNAL_PATH                  # Journal output location
```

See `.env.example` for template with descriptions.

## Monitoring Commands

### View Service Status
```bash
systemctl --user status lyra-daemon
```

### Follow Live Logs
```bash
journalctl --user -u lyra-daemon -f
```

### View Recent Errors
```bash
journalctl --user -u lyra-daemon -p err
```

### Count Restarts
```bash
journalctl --user -u lyra-daemon | grep -i restart | wc -l
```

### Show Resource Usage
```bash
systemctl --user status lyra-daemon | grep Memory
```

## Troubleshooting Decision Tree

```
Service not starting?
├─ Check status: systemctl --user status lyra-daemon
├─ View errors: journalctl --user -u lyra-daemon -n 20
├─ Verify .env exists: ls -la .env
├─ Verify Python path: which python3
└─ If all OK: Recopy service file and reload

Service keeps restarting?
├─ Check error message: journalctl --user -u lyra-daemon
├─ Common issues:
│  ├─ Invalid Discord token → Update .env
│  ├─ Wrong channel ID → Update .env
│  ├─ Network error → Check connection, wait
│  └─ Python error → Reinstall venv
└─ If circuit breaker triggered: Manual restart after fix

High memory usage?
├─ Monitor: watch -n 1 'systemctl --user status lyra-daemon'
├─ Check for leaks: journalctl --user -u lyra-daemon -f
├─ Increase limit: Edit service file, change MemoryLimit
└─ Restart service: systemctl --user restart lyra-daemon

Logs not appearing?
├─ Check service is running: systemctl --user is-active lyra-daemon
├─ Check journald: journalctl --user --disk-usage
├─ Verify identifier: grep SyslogIdentifier ~/.config/systemd/user/lyra-daemon.service
└─ Query directly: journalctl SYSLOG_IDENTIFIER=lyra-daemon
```

## File Locations Reference

### Service Configuration
- Service file: `~/.config/systemd/user/lyra-daemon.service`
- Daemon directory: `/mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon`
- Virtual environment: `Awareness/.venv/` (project-level, consolidated in Issue #111)

### Configuration & Secrets
- Environment file: `daemon/.env` (DO NOT COMMIT)
- Example template: `daemon/.env.example` (safe to commit)

### Identity & Journals
- Identity path: `~/.claude/`
- Discord journal: `~/.claude/journals/discord/`
- System logs: Via `journalctl --user -u lyra-daemon`

### Install Directory
- Install script: `daemon/systemd/install.sh`
- Service file: `daemon/systemd/lyra-daemon.service`
- Documentation: `daemon/systemd/*.md`

## Getting Help

### Common Issues

**Q: Service won't start after installation**
A: Check logs with `journalctl --user -u lyra-daemon -n 50` and verify .env file exists

**Q: Daemon crashes immediately**
A: Usually means .env file missing required variables (DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID)

**Q: Service keeps restarting every 10 seconds**
A: Check error logs, fix configuration, ensure circuit breaker hasn't engaged

**Q: Where are the logs?**
A: In systemd journal - use `journalctl --user -u lyra-daemon -f` to follow

**Q: How do I stop the daemon?**
A: `systemctl --user stop lyra-daemon`

**Q: Will the daemon auto-start on login?**
A: Yes, that's configured by `systemctl --user enable lyra-daemon`

### Documentation Reference

| Need | Read | Section |
|------|------|---------|
| Quick setup | QUICK_START.md | Installation |
| Manage service | README.md | Service Management |
| Troubleshoot | README.md | Troubleshooting |
| Understand design | DESIGN_NOTES.md | Design Decisions |
| Configure environment | README.md | Environment Variables |
| Monitor performance | README.md | Performance Monitoring |
| Advanced config | README.md | Advanced Configuration |

## Contact & Support

For issues or questions:

1. Check the appropriate documentation above
2. Review relevant logs: `journalctl --user -u lyra-daemon`
3. Run diagnostic: `systemctl --user status lyra-daemon --no-pager`
4. Test daemon manually: `cd daemon && python3 lyra_daemon.py`

## Version Information

- **Configuration Version**: 1.0
- **Systemd Version**: Requires systemd with user services
- **Python Version**: 3.12+ recommended
- **Discord.py Version**: 2.3.0+
- **WSL2 Compatibility**: Ubuntu 22.04 or later recommended

## Changelog

### v1.0 (2025-12-30)

- Initial release of systemd service configuration
- Complete documentation suite
- Automated installation script
- WSL2 optimized settings
- User-level service (non-root)
- Journald logging
- Automatic restart with circuit breaker
- Security hardening
- Resource limits

## License

Configuration and documentation are provided for the Lyra Discord Daemon project.

---

**Last Updated**: 2025-12-30
**Maintained By**: DevOps Agent
**Status**: Active and Maintained
