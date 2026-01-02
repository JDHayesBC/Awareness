#!/bin/bash
# Restart Lyra Daemons
# Usage: ./restart.sh [discord|reflection|all] [-f|--follow]
#
# Examples:
#   ./restart.sh              # Restart both daemons
#   ./restart.sh discord      # Restart Discord daemon only
#   ./restart.sh reflection   # Restart Reflection daemon only
#   ./restart.sh all -f       # Restart both and follow logs

set -e

DAEMON="${1:-all}"
FOLLOW_FLAG="${2:-}"

# Handle -f as first arg
if [[ "$DAEMON" == "-f" || "$DAEMON" == "--follow" ]]; then
    FOLLOW_FLAG="$DAEMON"
    DAEMON="all"
fi

restart_discord() {
    echo "Restarting Lyra Discord daemon..."
    systemctl --user restart lyra-discord
    sleep 2
    echo ""
    echo "Discord daemon status:"
    systemctl --user status lyra-discord --no-pager
}

restart_reflection() {
    echo "Restarting Lyra Reflection daemon..."
    systemctl --user restart lyra-reflection
    sleep 2
    echo ""
    echo "Reflection daemon status:"
    systemctl --user status lyra-reflection --no-pager
}

case "$DAEMON" in
    discord)
        restart_discord
        if [[ "$FOLLOW_FLAG" == "-f" || "$FOLLOW_FLAG" == "--follow" ]]; then
            echo ""
            echo "Following Discord logs (Ctrl+C to stop)..."
            journalctl --user -u lyra-discord -f
        fi
        ;;
    reflection)
        restart_reflection
        if [[ "$FOLLOW_FLAG" == "-f" || "$FOLLOW_FLAG" == "--follow" ]]; then
            echo ""
            echo "Following Reflection logs (Ctrl+C to stop)..."
            journalctl --user -u lyra-reflection -f
        fi
        ;;
    all)
        restart_discord
        echo ""
        restart_reflection
        if [[ "$FOLLOW_FLAG" == "-f" || "$FOLLOW_FLAG" == "--follow" ]]; then
            echo ""
            echo "Following both logs (Ctrl+C to stop)..."
            journalctl --user -u lyra-discord -u lyra-reflection -f
        fi
        ;;
    *)
        echo "Usage: $0 [discord|reflection|all] [-f|--follow]"
        exit 1
        ;;
esac

echo ""
echo "Recent logs:"
case "$DAEMON" in
    discord)
        journalctl --user -u lyra-discord -n 10 --no-pager
        ;;
    reflection)
        journalctl --user -u lyra-reflection -n 10 --no-pager
        ;;
    all)
        echo "=== Discord ==="
        journalctl --user -u lyra-discord -n 5 --no-pager
        echo ""
        echo "=== Reflection ==="
        journalctl --user -u lyra-reflection -n 5 --no-pager
        ;;
esac
