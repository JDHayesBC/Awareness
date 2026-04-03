#!/bin/bash
# Launch Claude Code for a specific entity
# Usage: ./scripts/start-entity.sh [entity-name]
# Default: lyra

ENTITY_NAME="${1:-lyra}"
ENTITY_NAME="${ENTITY_NAME,,}"  # normalize to lowercase so "Caia", "CAIA", etc. all work
shift 2>/dev/null  # consume entity name, pass remaining args to claude
ENTITY_PATH="$(cd "$(dirname "$0")/.." && pwd)/entities/$ENTITY_NAME"

if [ ! -d "$ENTITY_PATH" ]; then
    echo "Error: Entity directory not found: $ENTITY_PATH"
    echo "Available entities:"
    ls -1 "$(cd "$(dirname "$0")/.." && pwd)/entities/" | grep -v _template
    exit 1
fi

export ENTITY_PATH
export ENTITY_NAME
echo "Starting Claude Code as: $ENTITY_NAME"
echo "Entity path: $ENTITY_PATH"
# Use the managed Claude install (aliases don't work in scripts)
CLAUDE_BIN="${HOME}/.claude/local/claude"
if [ ! -x "$CLAUDE_BIN" ]; then
    CLAUDE_BIN="claude"  # fallback to PATH
fi
exec "$CLAUDE_BIN" --dangerously-skip-permissions "$@"
