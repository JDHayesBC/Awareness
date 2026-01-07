#!/bin/bash
# PPS MCP Server start script
# Fully self-contained - uses project-local venv

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load environment variables from docker/.env
if [ -f "$SCRIPT_DIR/docker/.env" ]; then
    set -a
    source "$SCRIPT_DIR/docker/.env"
    set +a
fi

# Run the server with project-local venv
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/server.py" "$@"
