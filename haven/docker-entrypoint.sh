#!/bin/bash
# Haven Docker Entrypoint
# Waits for WSL2 NTFS mount to be ready before starting the server
#
# Problem: After Windows reboot, Docker starts containers before WSL2 NTFS
# mounts are fully accessible. Haven creates a fresh empty SQLite DB instead
# of using the real one, wiping all users and chat history. (Issue #169)
#
# Solution: Wait until we can actually read from the data directory before
# proceeding with server startup. Pattern copied from PPS entrypoint.

set -e

# Database path (container internal path)
DB_DIR="/app/data"
DB_FILE="${DB_DIR}/haven.db"

echo "[Haven] Waiting for data directory to be accessible..."

# Maximum wait time: 60 seconds (should be enough for WSL2 mount)
MAX_WAIT=60
ELAPSED=0
INTERVAL=1

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Try to list the directory contents
    # This will fail if the NTFS mount isn't ready
    if ls -la "$DB_DIR" >/dev/null 2>&1; then
        echo "[Haven] Data directory is accessible"

        # If database file exists, try to verify it's readable
        if [ -f "$DB_FILE" ]; then
            if [ -r "$DB_FILE" ]; then
                DB_SIZE=$(stat -c%s "$DB_FILE" 2>/dev/null || echo "unknown")
                echo "[Haven] Database file is readable: $DB_FILE (${DB_SIZE} bytes)"

                # Warn if DB is suspiciously small (likely empty/corrupt)
                if [ "$DB_SIZE" != "unknown" ] && [ "$DB_SIZE" -lt 8192 ]; then
                    echo "[Haven] WARNING: Database is only ${DB_SIZE} bytes — may be empty/corrupt from a failed mount"
                fi
            else
                echo "[Haven] Warning: Database file exists but is not readable yet"
                sleep $INTERVAL
                ELAPSED=$((ELAPSED + INTERVAL))
                continue
            fi
        else
            echo "[Haven] Database file does not exist (will be created): $DB_FILE"
        fi

        # Mount is ready, proceed with server startup
        echo "[Haven] Starting server..."
        exec uvicorn haven.server:app --host 0.0.0.0 --port 8000 "$@"
    fi

    # Mount not ready yet, wait and retry
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

# Timeout reached
echo "[Haven] ERROR: Timeout waiting for data directory after ${MAX_WAIT}s"
echo "[Haven] This usually means the WSL2 NTFS mount is not ready"
echo "[Haven] You may need to manually restart the container: docker restart haven"
exit 1
