#!/bin/bash
# Restart Lyra Discord Daemon
# Usage: ./restart.sh [-f|--follow]

set -e

echo "Restarting Lyra daemon..."
systemctl --user restart lyra-daemon

sleep 2

echo ""
echo "Status:"
systemctl --user status lyra-daemon --no-pager

echo ""
echo "Recent logs:"
journalctl --user -u lyra-daemon -n 15 --no-pager

# If -f or --follow flag, tail the logs
if [[ "$1" == "-f" || "$1" == "--follow" ]]; then
    echo ""
    echo "Following logs (Ctrl+C to stop)..."
    journalctl --user -u lyra-daemon -f
fi
