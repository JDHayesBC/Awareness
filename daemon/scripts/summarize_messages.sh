#!/bin/bash
#
# summarize_messages.sh - Get unsummarized messages via HTTP (MCP fallback)
#
# Usage: ./summarize_messages.sh [limit] [summary_type]
#
# This script provides CLI access to summarize_messages when MCP tools aren't
# available (e.g., in reflection subprocess). It calls the PPS HTTP server
# and returns the messages/prompt for agent summarization.
#
# Issue: #97 - MCP servers don't load in subprocess despite --mcp-config
# Issue: #101 - Reflection daemon needs HTTP fallback for memory summarization
# Solution: HTTP client fallback via this script

set -euo pipefail

# Configuration
PPS_URL="${PPS_URL:-http://localhost:8201}"
LIMIT="${1:-50}"
SUMMARY_TYPE="${2:-work}"

# Build request JSON
REQUEST=$(cat <<EOF
{
  "limit": $LIMIT,
  "summary_type": "$SUMMARY_TYPE"
}
EOF
)

# Make request
RESPONSE=$(curl -s -X POST "$PPS_URL/tools/summarize_messages" \
    -H "Content-Type: application/json" \
    -d "$REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q '"detail"'; then
    echo "ERROR: PPS request failed"
    echo "$RESPONSE" | python3 -m json.tool
    exit 1
fi

# Output raw JSON for agent consumption
echo "$RESPONSE" | python3 -m json.tool
