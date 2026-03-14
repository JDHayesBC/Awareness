#!/bin/bash
# Neo4j Entrypoint Wrapper
# Prevents Neo4j from reinitializing an existing database after WSL2 cold boot.
#
# Problem: After Windows reboot or OOM kill, Docker starts Neo4j before the WSL2
# NTFS bind-mount is fully accessible. Neo4j sees a permission error reading its
# existing database files and treats it as a first-time startup, wiping the graph.
#
# Solution: If database files exist on the bind-mount path, wait until they are
# readable before allowing Neo4j to start. An empty data dir means genuine first
# run — proceed immediately. Unreadable files mean the mount isn't ready — wait.
#
# Usage: Set as container entrypoint. Delegates to the stock Neo4j entrypoint
# (/startup/docker-entrypoint.sh) once the gate passes.

set -e

NEO4J_DATA_DIR="/data/databases/neo4j"

# Sentinel file that Neo4j always creates once a store is initialized.
# If this file exists (even as zero bytes from a bad mount), we know there
# SHOULD be a live database here and we must not let Neo4j reinitialize.
SENTINEL="${NEO4J_DATA_DIR}/neostore"

MAX_WAIT=90
ELAPSED=0
INTERVAL=2

echo "[NEO4J-GATE] Checking data directory: ${NEO4J_DATA_DIR}"

# --- Case 1: data dir doesn't exist or is empty → genuine first run ---
if [ ! -d "$NEO4J_DATA_DIR" ] || [ -z "$(ls -A "$NEO4J_DATA_DIR" 2>/dev/null)" ]; then
    echo "[NEO4J-GATE] No existing database found — first-run startup, proceeding"
    exec tini -g -- /startup/docker-entrypoint.sh neo4j "$@"
fi

# --- Case 2: data dir exists and has files → must be an existing database ---
# Wait until the sentinel file is readable, proving the NTFS mount is live.
echo "[NEO4J-GATE] Existing database directory detected — waiting for mount readiness..."

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Test that we can actually stat the sentinel (or any file in the dir).
    # ls -la is the same probe the SQLite gate uses.
    if ls -la "$NEO4J_DATA_DIR" >/dev/null 2>&1; then
        # Directory is listable. Now verify the sentinel is a real, readable file.
        if [ -f "$SENTINEL" ] && [ -r "$SENTINEL" ]; then
            echo "[NEO4J-GATE] Mount is ready — neostore sentinel is readable"
            break
        elif [ ! -f "$SENTINEL" ]; then
            # Files present but no sentinel — could be a partial/corrupt store.
            # Don't wait forever; log a warning and let Neo4j handle it.
            echo "[NEO4J-GATE] Warning: data dir has files but no neostore sentinel"
            echo "[NEO4J-GATE]   This may indicate a partial or corrupt store"
            echo "[NEO4J-GATE]   Proceeding — Neo4j will verify on startup"
            break
        else
            # Sentinel exists but isn't readable yet — mount still warming up.
            echo "[NEO4J-GATE] Sentinel not readable yet (NTFS mount warming up) — ${ELAPSED}s elapsed"
        fi
    else
        echo "[NEO4J-GATE] Data directory not listable yet (NTFS mount not ready) — ${ELAPSED}s elapsed"
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "[NEO4J-GATE] ERROR: Timeout waiting for Neo4j data mount after ${MAX_WAIT}s"
    echo "[NEO4J-GATE] Existing database files are present but unreadable."
    echo "[NEO4J-GATE] NOT starting Neo4j — would risk reinitializing the database."
    echo "[NEO4J-GATE] Fix: ensure WSL2 NTFS mount is healthy, then restart the container."
    echo "[NEO4J-GATE]   docker restart pps-neo4j"
    exit 1
fi

echo "[NEO4J-GATE] Gate passed — handing off to Neo4j startup"
exec tini -g -- /startup/docker-entrypoint.sh neo4j "$@"
