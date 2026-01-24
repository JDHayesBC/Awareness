#!/bin/bash
# Verify PPS Docker container has latest code
# Usage: ./pps_verify_deployment.sh [container-name] [source-file]

set -e

SERVICE=${1:-pps-server}
SOURCE_FILE=${2:-pps/docker/server_http.py}

echo "Checking deployment status for $SERVICE..."

# Get container creation time
CONTAINER_TIME=$(docker inspect "$SERVICE" --format='{{.Created}}' 2>/dev/null || echo "")
if [ -z "$CONTAINER_TIME" ]; then
  echo "ERROR: Container $SERVICE not found or not running"
  echo "Run: docker-compose ps"
  exit 1
fi

# Check if source file exists
if [ ! -f "$SOURCE_FILE" ]; then
  echo "ERROR: Source file $SOURCE_FILE not found"
  exit 1
fi

# Get source file modification time (cross-platform)
if stat -c %Y "$SOURCE_FILE" &>/dev/null; then
  # GNU stat (Linux)
  SOURCE_TIME=$(stat -c %Y "$SOURCE_FILE")
  format_time() { date -d "@$1" '+%Y-%m-%d %H:%M:%S'; }
elif stat -f %m "$SOURCE_FILE" &>/dev/null; then
  # BSD stat (macOS)
  SOURCE_TIME=$(stat -f %m "$SOURCE_FILE")
  format_time() { date -r "$1" '+%Y-%m-%d %H:%M:%S'; }
else
  echo "ERROR: Unable to get file modification time"
  exit 1
fi

# Convert container time to epoch (cross-platform)
if date -d "$CONTAINER_TIME" +%s &>/dev/null; then
  # GNU date (Linux)
  CONTAINER_EPOCH=$(date -d "$CONTAINER_TIME" +%s)
elif date -j -f "%Y-%m-%dT%H:%M:%S" "${CONTAINER_TIME:0:19}" +%s &>/dev/null; then
  # BSD date (macOS)
  CONTAINER_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${CONTAINER_TIME:0:19}" +%s)
else
  echo "ERROR: Unable to parse container creation time"
  exit 1
fi

echo "Container created: $CONTAINER_TIME (epoch: $CONTAINER_EPOCH)"
echo "Source modified:   $(format_time $SOURCE_TIME) (epoch: $SOURCE_TIME)"
echo ""

TIME_DIFF=$((CONTAINER_EPOCH - SOURCE_TIME))

if [ $TIME_DIFF -gt 0 ]; then
  echo "✓ Deployment is CURRENT (container $TIME_DIFF seconds newer than source)"
  exit 0
else
  ABS_DIFF=$((0 - TIME_DIFF))
  echo "✗ Deployment is STALE (source $ABS_DIFF seconds newer than container)"
  echo ""
  echo "To rebuild and deploy:"
  echo "  cd pps/docker"
  echo "  docker-compose build $SERVICE"
  echo "  docker-compose up -d $SERVICE"
  echo "  docker-compose ps  # verify healthy"
  exit 1
fi
