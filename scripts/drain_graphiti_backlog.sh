#!/bin/bash
#
# Drain Graphiti Backlog - Batch ingest messages to Graphiti
#
# This script:
# 1. Loops calling the PPS MCP server's ingest_batch_to_graphiti endpoint
# 2. Sleeps briefly between batches to avoid overwhelming Graphiti
# 3. Stops when the backlog is empty or after a max number of iterations
# 4. Logs progress
#
# Usage:
#   ./drain_graphiti_backlog.sh [batch_size] [max_iterations] [sleep_seconds]
#
# Example:
#   ./drain_graphiti_backlog.sh 20 100 2
#
# Requires: PPS server running (e.g., in daemon or separate terminal)
#

set -e

# Configuration
BATCH_SIZE=${1:-20}
MAX_ITERATIONS=${2:-100}
SLEEP_SECONDS=${3:-2}
AWARENESS_DIR="${AWARENESS_DIR:-.}"

# Resolve to absolute path
AWARENESS_DIR="$(cd "$AWARENESS_DIR" 2>/dev/null && pwd)" || AWARENESS_DIR="."
export AWARENESS_DIR

# Log file
LOG_DIR="${AWARENESS_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/graphiti_drain_$(date +%Y%m%d_%H%M%S).log"

# Create Python script to do the work
PYTHON_SCRIPT=$(mktemp --suffix=.py)
trap "rm -f $PYTHON_SCRIPT" EXIT

cat > "$PYTHON_SCRIPT" << 'PYTHON_EOF'
#!/usr/bin/env python3
"""
Drain Graphiti backlog by calling PPS layers directly.
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from datetime import datetime

def setup_pps_path(awareness_dir: str):
    """Add PPS to Python path."""
    pps_dir = Path(awareness_dir) / "pps"
    if pps_dir.exists():
        sys.path.insert(0, str(pps_dir))
    else:
        raise RuntimeError(f"PPS directory not found at {pps_dir}")

async def main():
    # Get awareness dir from environment
    awareness_dir = os.environ.get("AWARENESS_DIR", ".")
    setup_pps_path(awareness_dir)

    # Import after path setup
    from layers import LayerType
    from layers.message_summaries import MessageSummariesLayer

    # Get config
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    max_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    sleep_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    log_file = sys.argv[4] if len(sys.argv) > 4 else None

    # Get Claude home
    claude_home = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
    db_path = claude_home / "data" / "lyra_conversations.db"

    # Create layers
    from layers.message_summaries import MessageSummariesLayer
    from layers.rich_texture import RichTextureLayer

    message_summaries = MessageSummariesLayer(db_path=db_path)
    graphiti_layer = RichTextureLayer()

    def log(msg):
        """Log to both stdout and file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        print(full_msg)
        if log_file:
            with open(log_file, 'a') as f:
                f.write(full_msg + "\n")

    log(f"=== Graphiti Backlog Drain ===")
    log(f"Batch size: {batch_size}")
    log(f"Max iterations: {max_iterations}")
    log(f"Sleep between batches: {sleep_seconds}s")
    log("")

    iteration = 0
    total_ingested = 0
    total_failed = 0

    try:
        while iteration < max_iterations:
            iteration += 1

            # Get current stats
            log(f"[{iteration}/{max_iterations}] Checking backlog...")
            uningested_count = message_summaries.count_uningested_to_graphiti()
            log(f"  Uningested messages: {uningested_count}")

            # Stop if backlog is empty
            if uningested_count == 0:
                log("✓ Backlog empty! Drain complete.")
                break

            # Get batch
            log(f"  Ingesting batch of {batch_size} messages...")
            messages = message_summaries.get_uningested_for_graphiti(limit=batch_size)

            if not messages:
                log("✗ No messages to ingest but backlog shows count. Stopping.")
                break

            # Ingest each message
            ingested_count = 0
            failed_count = 0
            channels_in_batch = set()

            for msg in messages:
                try:
                    metadata = {
                        "channel": msg['channel'],
                        "role": "assistant" if msg['is_lyra'] else "user",
                        "speaker": "Lyra" if msg['is_lyra'] else msg['author_name'],
                        "timestamp": msg['created_at']
                    }

                    # Store in Graphiti (synchronous call)
                    success = await graphiti_layer.store(msg['content'], metadata)

                    if success:
                        ingested_count += 1
                        channels_in_batch.add(msg['channel'])
                    else:
                        failed_count += 1

                except Exception as e:
                    failed_count += 1
                    log(f"    Error ingesting message: {e}")

            total_ingested += ingested_count
            total_failed += failed_count

            log(f"  Ingested: {ingested_count}, Failed: {failed_count}")

            # Mark batch as ingested
            if ingested_count > 0:
                start_id = messages[0]['id']
                end_id = messages[-1]['id']
                batch_id = message_summaries.mark_batch_ingested_to_graphiti(
                    start_id, end_id, list(channels_in_batch)
                )
                log(f"  Batch {batch_id} marked as ingested")

            # If nothing was ingested, stop
            if ingested_count == 0:
                log("✗ No messages ingested. Stopping drain.")
                break

            # Sleep before next batch
            if iteration < max_iterations and uningested_count > 0:
                log(f"  Sleeping {sleep_seconds}s before next batch...")
                await asyncio.sleep(sleep_seconds)

            log("")

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    # Summary
    log("=== Drain Summary ===")
    log(f"Total messages ingested: {total_ingested}")
    log(f"Total messages failed: {total_failed}")
    log(f"Iterations: {iteration}/{max_iterations}")
    log("")

    if total_ingested > 0:
        log(f"✓ Drain successful! Ingested {total_ingested} messages to Graphiti.")
    else:
        log("⚠️  No messages were ingested.")

if __name__ == "__main__":
    asyncio.run(main())

PYTHON_EOF

# Run the Python script
python3 "$PYTHON_SCRIPT" "$BATCH_SIZE" "$MAX_ITERATIONS" "$SLEEP_SECONDS" "$LOG_FILE"

echo ""
echo "Log file: $LOG_FILE"
