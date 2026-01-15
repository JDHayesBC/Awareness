#!/bin/bash
# HTTP fallback for mcp__pps__texture_delete
# Usage: ./texture_delete.sh "uuid"

uuid="$1"

if [ -z "$uuid" ]; then
  echo "Error: UUID required"
  echo "Usage: $0 <uuid>"
  exit 1
fi

curl -s http://localhost:8201/tools/texture_delete/$uuid \
  -X DELETE | jq
