#!/bin/bash
# Run Lyra Daemons Directly (without systemd)
# Usage: ./run.sh [discord|reflection|both]
#
# This script runs the daemons directly in the foreground.
# Useful for WSL2 or debugging without systemd.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

DAEMON="${1:-discord}"

# Activate project-level venv (consolidated in Issue #111)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

case "$DAEMON" in
    discord)
        echo "Starting Discord daemon..."
        python3 -u lyra_discord.py
        ;;
    reflection)
        echo "Starting Reflection daemon..."
        python3 -u lyra_reflection.py
        ;;
    both)
        echo "Starting both daemons in background..."
        echo "Discord logs: discord.log"
        echo "Reflection logs: reflection.log"
        python3 -u lyra_discord.py > discord.log 2>&1 &
        DISCORD_PID=$!
        echo "Discord PID: $DISCORD_PID"

        python3 -u lyra_reflection.py > reflection.log 2>&1 &
        REFLECTION_PID=$!
        echo "Reflection PID: $REFLECTION_PID"

        echo ""
        echo "Both daemons started. To stop:"
        echo "  kill $DISCORD_PID $REFLECTION_PID"
        echo ""
        echo "To follow logs:"
        echo "  tail -f discord.log reflection.log"

        # Wait for either to exit
        wait
        ;;
    *)
        echo "Usage: $0 [discord|reflection|both]"
        echo ""
        echo "  discord     - Run Discord daemon in foreground"
        echo "  reflection  - Run Reflection daemon in foreground"
        echo "  both        - Run both daemons in background"
        exit 1
        ;;
esac
