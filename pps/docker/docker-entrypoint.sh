#!/bin/bash
# PPS Docker Entrypoint
# Waits for WSL2 NTFS mount to be ready before starting the server
#
# Problem: After Windows reboot, Docker starts containers before WSL2 NTFS
# mounts are fully accessible. This causes PPS to fail accessing SQLite at
# /app/entity/data/conversations.db even though the path exists.
#
# Solution: Wait until we can actually read from the database directory
# before proceeding with server startup.

set -e

# Database path (container internal path)
DB_DIR="/app/entity/data"
DB_FILE="${DB_DIR}/conversations.db"

echo "[PPS] Waiting for entity data directory to be accessible..."

# Maximum wait time: 60 seconds (should be enough for WSL2 mount)
MAX_WAIT=60
ELAPSED=0
INTERVAL=1

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Try to list the directory contents
    # This will fail if the NTFS mount isn't ready
    if ls -la "$DB_DIR" >/dev/null 2>&1; then
        echo "[PPS] Entity data directory is accessible"

        # If database file exists, try to verify it's readable
        if [ -f "$DB_FILE" ]; then
            if [ -r "$DB_FILE" ]; then
                echo "[PPS] Database file is readable: $DB_FILE"
            else
                echo "[PPS] Warning: Database file exists but is not readable yet"
                sleep $INTERVAL
                ELAPSED=$((ELAPSED + INTERVAL))
                continue
            fi
        else
            echo "[PPS] Database file does not exist (will be created): $DB_FILE"
        fi

        # Mount is ready, proceed with server startup
        echo "[PPS] Starting server..."
        exec python server_http.py "$@"
    fi

    # Mount not ready yet, wait and retry
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

# Timeout reached
echo "[PPS] ERROR: Timeout waiting for entity data directory after ${MAX_WAIT}s"
echo "[PPS] This usually means the WSL2 NTFS mount is not ready"
echo "[PPS] You may need to manually restart the container: docker restart pps-lyra"
exit 1
