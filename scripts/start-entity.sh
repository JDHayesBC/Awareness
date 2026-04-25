#!/bin/bash
# Launch Claude Code for a specific entity
# Usage: ./scripts/start-entity.sh [entity-name]
# Default: lyra

ENTITY_NAME="${1:-lyra}"
ENTITY_NAME="${ENTITY_NAME,,}"  # normalize to lowercase so "Caia", "CAIA", etc. all work
shift 2>/dev/null  # consume entity name, pass remaining args to claude
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTITY_PATH="$PROJECT_ROOT/entities/$ENTITY_NAME"

if [ ! -d "$ENTITY_PATH" ]; then
    echo "Error: Entity directory not found: $ENTITY_PATH"
    echo "Available entities:"
    ls -1 "$PROJECT_ROOT/entities/" | grep -v _template
    exit 1
fi

# Symlink entity identity into .claude/CLAUDE.md (auto-loaded + compaction-safe)
IDENTITY_FILE="$ENTITY_PATH/claude_identity.md"
CLAUDE_DIR="$PROJECT_ROOT/.claude"
SYMLINK_TARGET="$CLAUDE_DIR/CLAUDE.md"

if [ ! -f "$IDENTITY_FILE" ]; then
    echo "Warning: No claude_identity.md found for $ENTITY_NAME at $IDENTITY_FILE"
    echo "Entity will start without compaction-safe identity block."
else
    # Remove existing symlink or file (but not the canary backup)
    rm -f "$SYMLINK_TARGET"
    ln -s "$IDENTITY_FILE" "$SYMLINK_TARGET"
    echo "Identity linked: .claude/CLAUDE.md -> $IDENTITY_FILE"
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
