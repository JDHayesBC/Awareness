#!/bin/bash
# PPS MCP Server start script
# Fully self-contained - uses project-local venv

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Save MCP-provided env vars (from .mcp.json) before sourcing .env
SAVED_ENTITY_PATH="${ENTITY_PATH:-}"
SAVED_CLAUDE_HOME="${CLAUDE_HOME:-}"

# Load environment variables from docker/.env (database URIs, ports, etc.)
if [ -f "$SCRIPT_DIR/docker/.env" ]; then
    set -a
    source "$SCRIPT_DIR/docker/.env"
    set +a
fi

# Restore MCP-provided env vars (take priority over docker/.env)
if [ -n "$SAVED_ENTITY_PATH" ]; then
    export ENTITY_PATH="$SAVED_ENTITY_PATH"
fi
if [ -n "$SAVED_CLAUDE_HOME" ]; then
    export CLAUDE_HOME="$SAVED_CLAUDE_HOME"
fi

# Unset entity-specific vars from docker/.env — MCP servers derive these from ENTITY_PATH.
# ENTITY_NAME: Docker needs this (ENTITY_PATH.name is always "entity" inside containers).
#              MCP servers use ENTITY_PATH.name directly, so ENTITY_NAME=lyra would pollute.
# GRAPHITI_GROUP_ID: Docker hardcodes per-service. MCP servers derive from ENTITY_PATH.
unset ENTITY_NAME GRAPHITI_GROUP_ID

# Run the server with native Linux venv (WSL2 /mnt/c/ is 10-40x slower for Python imports)
# Native venv: /home/jeff/.local/share/pps-venv (sub-second startup)
# Fallback: project-local venv on Windows fs (slow but functional)
PPS_VENV="${PPS_VENV:-/home/jeff/.local/share/pps-venv}"
if [ -x "$PPS_VENV/bin/python" ]; then
    exec "$PPS_VENV/bin/python" "$SCRIPT_DIR/server.py" "$@"
else
    exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/server.py" "$@"
fi
