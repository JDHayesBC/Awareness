# Lyra Discord Daemon - Systemd Service Design Notes

## Executive Summary

This systemd service configuration enables the Lyra Discord Daemon to run as a persistent background service in WSL2. The design prioritizes reliability, security, and compatibility with the development environment while maintaining full autonomy and memory continuity.

## Design Decisions

### 1. User-Level Service (Not System-Wide)

**Decision**: Configure as user-level service (`~/.config/systemd/user/`)

**Rationale**:
- WSL2 development environments typically run under regular user accounts
- User services have lower security risk and no root access needed
- Better isolation from system processes
- User has direct control over service lifecycle
- Aligns with local development practices

**Alternative Considered**: System-wide service (`/etc/systemd/system/`)
- Would require root/sudo to install
- More suitable for production servers
- Unnecessary complexity for development

### 2. Restart Policy: on-failure with Circuit Breaker

**Configuration**:
```
Restart=on-failure
RestartSec=10
StartLimitInterval=60
StartLimitBurst=5
```

**Rationale**:
- `on-failure`: Only restart if process exits with error, not on intentional stops
- `RestartSec=10`: Brief delay prevents tight restart loops
- `StartLimitBurst=5`: Maximum 5 restart attempts in 60-second window
- Circuit breaker prevents cascading failures while allowing recovery

**Prevents**:
- Restart storms if daemon repeatedly crashes
- Resource exhaustion from constant restart attempts
- Masked configuration errors that would be obvious after immediate restarts

### 3. Environment Variable Loading

**Configuration**:
```
EnvironmentFile=%h/Documents/Claude_Projects/Awareness/daemon/.env
```

**Rationale**:
- Single source of truth for all configuration
- Secrets (Discord token) not embedded in service file
- Easy to change configuration without modifying service
- Daemon already expects this with `load_dotenv()`

**Path Variables Used**:
- `%h` = Home directory (expands to `/home/jeff`)
- Prevents hardcoding paths that vary by user
- Works across different machines

**Additional Environment**:
```
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
```
- Ensures real-time log output to journald
- Prevents bytecode caching which can cause permission issues

### 4. Logging to journald (Not Files)

**Configuration**:
```
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lyra-daemon
```

**Rationale**:
- Centralized logging through systemd journal
- No file rotation or management needed
- Structured logging with timestamps, levels, and metadata
- Easy filtering and searching: `journalctl --user -u lyra-daemon`
- Survives service restarts
- WSL2 compatible (no file permission issues)

**Benefits Over File Logging**:
- Automatic log rotation via journald
- Queryable by service, date, priority
- Integration with system monitoring
- No risk of log files consuming disk space

### 5. Simple Service Type

**Decision**: `Type=simple`

**Rationale**:
- Daemon runs in foreground (doesn't fork/daemonize)
- Systemd monitors main process directly
- Straightforward lifecycle management
- Better for Discord.py's async event loop

**Alternative Considered**: `Type=idle` or `Type=forking`
- Not necessary for Python async applications
- More complex to configure correctly
- Added latency with Type=idle

### 6. Resource Limits

**Configuration**:
```
MemoryLimit=512M
CPUQuota=50%
```

**Rationale**:
- Prevents runaway daemon from consuming all system resources
- Discord.py typically uses <100MB under normal conditions
- 512MB provides safety margin for growth or spikes
- 50% CPU prevents monopolizing development machine
- Safe defaults for WSL2 shared resources

**Adjustable**: Can be modified if daemon needs more resources
- Monitor actual usage: `systemctl --user status lyra-daemon`
- Increase if memory exhaustion occurs
- Decrease if resource contention affects other work

### 7. Security Configuration

**Settings**:
```
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=no
ReadWritePaths=%h/Documents/Claude_Projects/Awareness/daemon/logs %h/.claude
```

**Rationale**:
- `NoNewPrivileges`: Process cannot escalate privileges via setuid
- `PrivateTmp`: Isolated temporary directory prevents leaking data
- `ProtectSystem`: Read-only `/usr`, `/etc`, `/boot` prevents accidental system damage
- `ProtectHome=no`: Allows read/write to home directory (required for .claude)
- `ReadWritePaths`: Explicit writable paths (principle of least privilege)

**Trade-offs**:
- `ProtectHome=no` is less restrictive than ideal, but required for:
  - Reading Lyra's identity files from `~/.claude`
  - Writing journal entries to `~/.claude/journals`
- More restrictive settings would require moving identity/journal paths

### 8. Kill Mode and Shutdown

**Configuration**:
```
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30
```

**Rationale**:
- `KillMode=mixed`: Sends SIGTERM to main process, SIGKILL to children (if any)
- `SIGTERM`: Allows graceful shutdown (Discord.py can close connections)
- `TimeoutStopSec=30`: Waits up to 30 seconds for graceful shutdown
- After timeout, uses SIGKILL to force termination

**Behavior**:
1. Stop command sends SIGTERM → daemon closes Discord connection gracefully
2. If daemon doesn't stop in 30 seconds → systemd sends SIGKILL
3. Prevents zombie processes and ensures clean exit

### 9. Network Dependencies

**Configuration**:
```
After=network-online.target
Wants=network-online.target
```

**Rationale**:
- Ensures network is available before starting daemon
- Discord connection requires internet
- Prevents startup errors from network not being ready
- Soft dependency (Wants=) doesn't prevent startup if network unavailable

**WSL2 Specific**:
- WSL2 network is typically available immediately
- These directives ensure compatibility if network is delayed

## Environment Variable Reference

The service loads these from `.env`:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| DISCORD_BOT_TOKEN | Yes | - | Discord bot authentication token |
| DISCORD_CHANNEL_ID | Yes | - | Discord channel ID for heartbeats |
| LYRA_IDENTITY_PATH | No | /home/jeff/.claude | Lyra's identity files location |
| CLAUDE_MODEL | No | sonnet | Claude model for responses |
| HEARTBEAT_INTERVAL_MINUTES | No | 30 | Minutes between autonomous heartbeats |
| ACTIVE_MODE_TIMEOUT_MINUTES | No | 10 | Minutes to stay engaged after response |
| JOURNAL_PATH | No | /home/jeff/.claude/journals/discord | Discord interaction journal location |

## Installation Flow

```
User runs: ./install.sh
    ↓
Check prerequisites (.env file, daemon directory)
    ↓
Create ~/.config/systemd/user/ directory
    ↓
Copy lyra-daemon.service file
    ↓
systemctl --user daemon-reload
    ↓
systemctl --user enable lyra-daemon (auto-start on login)
    ↓
systemctl --user start lyra-daemon (start immediately)
    ↓
Display status and management commands
```

## Failure Recovery

### Scenario 1: Transient Network Error

1. Daemon tries to connect to Discord
2. Network is temporarily down
3. Connection fails → process exits
4. Systemd waits 10 seconds
5. Systemd restarts daemon → connection succeeds
6. Status: Recovered automatically

### Scenario 2: Invalid Discord Token

1. Daemon starts
2. Discord authentication fails
3. Process exits
4. Systemd waits 10 seconds
5. Systemd restarts daemon → same error
6. After 5 restart attempts in 60 seconds → circuit breaker engages
7. Service stops, manual intervention required
8. Admin fixes token in .env and runs: `systemctl --user start lyra-daemon`
9. Status: Requires manual fix (appropriate for configuration errors)

### Scenario 3: Memory Leak

1. Daemon runs for hours
2. Memory usage gradually increases
3. Reaches MemoryLimit=512M
4. Linux OOM killer terminates process
5. Systemd detects exit → waits 10 seconds
6. Systemd restarts daemon → memory resets
7. Status: Recovered automatically (cycle repeats if leak continues)

## Monitoring and Observability

### Real-Time Logs

```bash
journalctl --user -u lyra-daemon -f
```

Shows:
- Service startup messages
- Heartbeat triggers
- Discord messages
- Errors and warnings
- Restart events

### Service Health

```bash
systemctl --user status lyra-daemon
```

Shows:
- Process ID (PID)
- Current state (active, inactive, failed)
- Restart count
- Resource usage (memory, CPU)
- Recent error messages

### Historical Analysis

```bash
# Logs from past hour
journalctl --user -u lyra-daemon --since "1 hour ago"

# Logs with full timestamps
journalctl --user -u lyra-daemon -o short-precise

# Find restart events
journalctl --user -u lyra-daemon | grep -i restart
```

## WSL2 Specific Considerations

### Persistence Across Distro Shutdown

By default, WSL2 shuts down when all terminal windows close:

**Problem**: Daemon stops running

**Solution Options**:

1. **Keep Terminal Open**: Simple but not practical
2. **WSL2 systemd Integration**: If distro has systemd support enabled
3. **Windows Task Scheduler**: Run WSL command at startup
4. **Docker Container**: More complex but fully persistent

**Recommended**: Use systemd normally; WSL2 distros with systemd support (Ubuntu 22.04+) maintain user services.

### Path Compatibility

WSL2 Windows paths like `C:\Users\Jeff\...` must be converted to WSL paths:

- Service correctly uses: `/mnt/c/Users/Jeff/Documents/Claude_Projects/Awareness/daemon`
- Path variables (`%h`) expand to Linux home directory
- All file operations work in WSL2 filesystem

### Daemon Startup Order

WSL2 boots → systemd starts → user lingering enabled → service starts → daemon runs

User lingering is enabled by default for user-level services in modern distributions.

## Performance Characteristics

### Typical Resource Usage

- **Memory**: 80-120 MB under normal conditions
- **CPU**: Idle when waiting for messages, active only on heartbeat
- **Network**: Low bandwidth, responds to mentions asap
- **I/O**: Minimal disk usage (journal writes are buffered)

### Scaling Limits

Service can handle:
- 24/7 operation without restart
- Discord rate limiting (built into discord.py)
- Graceful shutdown within 30 seconds
- Recovery from transient failures
- Long-running async operations

Not suitable for:
- Hundreds of servers (single channel focus)
- Real-time high-frequency operations
- Extreme resource constraints (adjust limits as needed)

## Future Enhancements

### Possible Improvements

1. **Systemd Timer**: Schedule periodic maintenance tasks
2. **Custom ExecStartPost**: Verify configuration on startup
3. **Watchdog**: `WatchdogSec=` for liveness detection
4. **Socket Activation**: Accept Discord notifications via Unix socket
5. **Environment File Validation**: Pre-flight checks before starting

### Documentation Updates

As the daemon evolves, update:
- DESIGN_NOTES.md (this file) with new decisions
- README.md with new management commands
- Service file with additional directives
- Version compatibility notes

## Testing and Validation

### Pre-Deployment Checklist

- [ ] .env file exists and contains valid Discord token
- [ ] Channel ID is correct and accessible
- [ ] Virtual environment created and dependencies installed
- [ ] Run daemon manually to verify it works: `python3 lyra_daemon.py`
- [ ] Check Python version matches venv: `python3 --version`

### Post-Installation Verification

```bash
# Service file is valid
systemctl --user cat lyra-daemon

# Service is running
systemctl --user is-active lyra-daemon

# Logs appear in journal
journalctl --user -u lyra-daemon -n 5

# Heartbeat message appears in Discord (wait 30+ minutes)
journalctl --user -u lyra-daemon | grep -i heartbeat
```

## References

### Systemd Documentation
- `man systemd.service` - Service unit configuration
- `man systemd.exec` - Execution environment
- `man systemd.resource-control` - Resource limits
- `man systemd-system.conf` - System configuration

### Discord Bot Documentation
- discord.py async event loop
- Discord API rate limiting
- Bot token security

### WSL2 Documentation
- systemd in WSL2
- Path conversion rules
- Distribution startup behavior

## Contact and Support

For issues:
1. Check logs: `journalctl --user -u lyra-daemon -f`
2. Review this design document
3. Consult README.md troubleshooting section
4. Verify .env configuration
5. Test daemon manually: `cd daemon && python3 lyra_daemon.py`

---

**Document Version**: 1.0
**Last Updated**: 2025-12-30
**Service Version**: 1.0
**Compatibility**: systemd user services, WSL2, Python 3.12+
