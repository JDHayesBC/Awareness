#!/bin/bash
#
# Neo4j Health Check Wrapper
#
# Loads environment variables and runs the Python health monitor.
# Safe for cron execution.
#
# Usage:
#   ./neo4j-health-check.sh [--verbose]
#

set -euo pipefail

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$DOCKER_DIR/.env"
PYTHON_SCRIPT="$SCRIPT_DIR/neo4j-health-check.py"

# Load environment variables
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "ERROR: .env file not found at $ENV_FILE" >&2
    exit 1
fi

# Check if Python script exists
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "ERROR: Python health check script not found at $PYTHON_SCRIPT" >&2
    exit 1
fi

# Run Python health check
exec python3 "$PYTHON_SCRIPT" "$@"
