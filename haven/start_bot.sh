#!/bin/bash
# Start a Haven bot for an entity.
#
# Usage:
#   ./haven/start_bot.sh lyra    # Start Lyra's Haven bot
#   ./haven/start_bot.sh caia    # Start Caia's Haven bot
#
# Prerequisites:
#   - Haven server running (http://localhost:8205)
#   - Claude Code installed and authenticated
#   - Entity token exists at entities/<name>/.entity_token

set -euo pipefail

ENTITY=${1:-lyra}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Find entity token
TOKEN_FILE="$PROJECT_DIR/entities/$ENTITY/.entity_token"
if [ ! -f "$TOKEN_FILE" ]; then
    echo "ERROR: Token not found at $TOKEN_FILE"
    exit 1
fi

export ENTITY_NAME="$ENTITY"
export ENTITY_TOKEN_FILE="$TOKEN_FILE"
export HAVEN_URL="${HAVEN_URL:-http://localhost:8205}"
export CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"
export PROJECT_DIR="$PROJECT_DIR"

echo "Starting Haven bot for $ENTITY"
echo "  Haven: $HAVEN_URL"
echo "  Token: $TOKEN_FILE"
echo "  Model: $CLAUDE_MODEL"
echo ""

cd "$PROJECT_DIR"

# Use project venv (has claude-agent-sdk)
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: Project venv not found at $PROJECT_DIR/.venv"
    echo "Run: python3 -m venv $PROJECT_DIR/.venv && $PROJECT_DIR/.venv/bin/pip install claude-agent-sdk websockets httpx"
    exit 1
fi

exec "$VENV_PYTHON" -m haven.bot
