#!/bin/bash
#
# store_summary.sh - Store a message summary via HTTP (MCP fallback)
#
# Usage: ./store_summary.sh <summary_text> <start_id> <end_id> [channels_json] [summary_type]
#
# This script provides CLI access to store_summary when MCP tools aren't
# available (e.g., in reflection subprocess). It calls the PPS HTTP server
# to save the summary and mark messages as summarized.
#
# Issue: #97 - MCP servers don't load in subprocess despite --mcp-config
# Issue: #101 - Reflection daemon needs HTTP fallback for memory summarization
# Solution: HTTP client fallback via this script
#
# Example:
#   ./store_summary.sh "Summary text here" 1234 1250 '["terminal"]' work

set -euo pipefail

# Configuration
PPS_URL="${PPS_URL:-http://localhost:8201}"

# Arguments
SUMMARY_TEXT="${1:?Summary text required}"
START_ID="${2:?Start ID required}"
END_ID="${3:?End ID required}"
CHANNELS="${4:-[]}"
SUMMARY_TYPE="${5:-work}"

# Escape summary text for JSON (replace quotes, newlines)
SUMMARY_ESCAPED=$(echo "$SUMMARY_TEXT" | python3 -c "
import json
import sys
text = sys.stdin.read()
print(json.dumps(text)[1:-1])  # Remove outer quotes from json.dumps output
")

# Build request JSON
REQUEST=$(cat <<EOF
{
  "summary_text": "$SUMMARY_ESCAPED",
  "start_id": $START_ID,
  "end_id": $END_ID,
  "channels": $CHANNELS,
  "summary_type": "$SUMMARY_TYPE"
}
EOF
)

# Make request
RESPONSE=$(curl -s -X POST "$PPS_URL/tools/store_summary" \
    -H "Content-Type: application/json" \
    -d "$REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q '"detail"'; then
    echo "ERROR: Failed to store summary"
    echo "$RESPONSE" | python3 -m json.tool
    exit 1
fi

# Output result
echo "$RESPONSE" | python3 -m json.tool
