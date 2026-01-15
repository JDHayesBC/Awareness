#!/bin/bash
# HTTP fallback for mcp__pps__texture_search
# Usage: ./texture_search.sh "query" [limit]

query="$1"
limit="${2:-10}"

curl -s http://localhost:8201/tools/texture_search \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"$query\",\"limit\":$limit}" | jq
