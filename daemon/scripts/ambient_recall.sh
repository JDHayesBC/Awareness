#!/bin/bash
#
# ambient_recall.sh - Call PPS ambient_recall via HTTP (MCP fallback)
#
# Usage: ./ambient_recall.sh [context] [limit_per_layer]
#
# This script provides CLI access to ambient_recall when MCP tools aren't
# available (e.g., in reflection subprocess). It calls the PPS HTTP server
# directly and formats the output for Claude Code consumption.
#
# Issue: #97 - MCP servers don't load in subprocess despite --mcp-config
# Solution: HTTP client fallback via this script

set -euo pipefail

# Configuration
PPS_URL="${PPS_URL:-http://localhost:8201}"
CONTEXT="${1:-startup}"
LIMIT="${2:-5}"

# Build request JSON
REQUEST=$(cat <<EOF
{
  "context": "$CONTEXT",
  "limit_per_layer": $LIMIT
}
EOF
)

# Make request
RESPONSE=$(curl -s -X POST "$PPS_URL/tools/ambient_recall" \
    -H "Content-Type: application/json" \
    -d "$REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q '"error"'; then
    echo "ERROR: PPS request failed"
    echo "$RESPONSE" | python3 -m json.tool
    exit 1
fi

# Format output for readability
echo "=== AMBIENT RECALL ==="
echo ""

# Extract and display clock info
echo "$RESPONSE" | python3 -c "
import json
import sys

data = json.load(sys.stdin)

# Clock
clock = data.get('clock', {})
print(f\"Clock: {clock.get('display', 'N/A')}\")
if clock.get('note'):
    print(f\"  {clock['note']}\")
print()

# Memory health
print(f\"Memory Health: {data.get('memory_health', 'N/A')}\")
print()

# Results by layer
results = data.get('results', [])
if results:
    print(f\"Results: {len(results)} items across layers\")
    print()

    # Group by layer
    by_layer = {}
    for r in results:
        layer = r.get('layer', 'unknown')
        if layer not in by_layer:
            by_layer[layer] = []
        by_layer[layer].append(r)

    # Display each layer's results
    for layer, items in by_layer.items():
        print(f\"--- {layer.upper()} ({len(items)} results) ---\")
        for item in items:
            content = item.get('content', '')
            # Truncate long content
            if len(content) > 300:
                content = content[:300] + '...'
            print(f\"  • {content}\")
        print()
else:
    print(\"No results returned.\")
"
