#!/bin/bash
# Launch Claude Code for a specific entity
# Usage: ./scripts/start-entity.sh [entity-name]
# Default: lyra
#
# Identity architecture (Issue #226): each entity has its own CLAUDE.md inside
# entities/<entity>/. Claude Code is launched with the entity directory as cwd
# so its CLAUDE.md walk picks up both the shared project CLAUDE.md (one level
# up) and the entity-specific CLAUDE.md (highest attention, in the same dir).
# Concurrent entity sessions cannot bleed into each other because no shared
# mutable filesystem state communicates per-session identity.

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

# Verify entity has a CLAUDE.md (compaction-safe identity kernel).
# Without it the entity starts without identity grounding — warn loudly.
IDENTITY_FILE="$ENTITY_PATH/CLAUDE.md"
if [ ! -f "$IDENTITY_FILE" ]; then
    echo "WARNING: No CLAUDE.md found for $ENTITY_NAME at $IDENTITY_FILE"
    echo "Entity will start without compaction-safe identity grounding."
    echo "Expected: $IDENTITY_FILE (see entities/_template/README.md)"
fi

export ENTITY_PATH
export ENTITY_NAME
echo "Starting Claude Code as: $ENTITY_NAME"
echo "Entity path: $ENTITY_PATH"
echo "cwd: $ENTITY_PATH (CC walks up to project root for shared CLAUDE.md)"

# Use the managed Claude install (aliases don't work in scripts)
CLAUDE_BIN="${HOME}/.claude/local/claude"
if [ ! -x "$CLAUDE_BIN" ]; then
    CLAUDE_BIN="claude"  # fallback to PATH
fi

# Launch Claude from the entity directory so its CLAUDE.md auto-loads.
cd "$ENTITY_PATH"
exec "$CLAUDE_BIN" --dangerously-skip-permissions "$@"
