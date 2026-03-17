#!/bin/bash
# Launch Claude Code for a specific entity
# Usage: ./scripts/start-entity.sh [entity-name]
# Default: lyra

ENTITY_NAME="${1:-lyra}"
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
exec claude
