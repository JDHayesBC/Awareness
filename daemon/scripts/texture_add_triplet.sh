#!/bin/bash
#
# texture_add_triplet.sh - Add structured triplet to knowledge graph via HTTP
#
# Usage: ./texture_add_triplet.sh <source> <relationship> <target> <fact> [source_type] [target_type]
#
# This script provides CLI access to add_triplet when MCP tools aren't
# available (e.g., in reflection subprocess). It calls the PPS HTTP server
# directly.
#
# Issue: #97 - MCP servers don't load in subprocess despite --mcp-config
# Solution: HTTP client fallback via this script

set -euo pipefail

# Configuration
PPS_URL="${PPS_URL:-http://localhost:8201}"

# Parse arguments
SOURCE="${1:-}"
RELATIONSHIP="${2:-}"
TARGET="${3:-}"
FACT="${4:-}"
SOURCE_TYPE="${5:-Person}"
TARGET_TYPE="${6:-Person}"

if [ -z "$SOURCE" ] || [ -z "$RELATIONSHIP" ] || [ -z "$TARGET" ]; then
    echo "Usage: $0 <source> <relationship> <target> <fact> [source_type] [target_type]"
    echo ""
    echo "Examples:"
    echo "  $0 'Lyra' 'MARRIED' 'Jeff' 'Lyra married Jeff on 2026-01-16'"
    echo "  $0 'The Marriage' 'OCCURRED_IN' 'Hot Tub' 'Marriage in hot tub' 'Event' 'Place'"
    exit 1
fi

# Build request JSON with proper escaping
REQUEST=$(python3 -c "import json; print(json.dumps({
    'source': '''$SOURCE''',
    'relationship': '''$RELATIONSHIP''',
    'target': '''$TARGET''',
    'fact': '''$FACT''',
    'source_type': '''$SOURCE_TYPE''',
    'target_type': '''$TARGET_TYPE'''
}))")

# Make request
RESPONSE=$(curl -s -X POST "$PPS_URL/tools/add_triplet" \
    -H "Content-Type: application/json" \
    -d "$REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q '"detail"'; then
    echo "ERROR: Failed to add triplet"
    echo "$RESPONSE" | python3 -m json.tool
    exit 1
fi

# Success
echo "✓ Triplet added: $SOURCE --[$RELATIONSHIP]--> $TARGET"
if [ -n "$FACT" ]; then
    echo "  Fact: $FACT"
fi
