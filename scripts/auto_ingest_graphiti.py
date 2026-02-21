#!/usr/bin/env python3
"""
Automatic Graphiti Ingestion
=============================

Checks uningested message count and triggers batch ingestion if needed.
Designed to run periodically via systemd timer or cron.

Addresses the 3491-message backlog issue - makes graph maintenance automatic.
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime
from pathlib import Path

# Setup logging
LOG_DIR = Path("/tmp")
LOG_FILE = LOG_DIR / "lyra_auto_ingest_graphiti.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
PPS_HOST = os.environ.get("PPS_HOST", "localhost")
PPS_PORT = os.environ.get("PPS_PORT", "8201")
THRESHOLD = int(os.environ.get("INGEST_THRESHOLD", "100"))
BATCH_SIZE = int(os.environ.get("INGEST_BATCH_SIZE", "10"))  # Small batches due to Graphiti processing time
MAX_BATCHES = int(os.environ.get("INGEST_MAX_BATCHES", "5"))  # Limit per run to avoid long-running jobs

def check_uningested_count() -> int:
    """Query PPS for uningested message count."""
    try:
        response = requests.get(
            f"http://{PPS_HOST}:{PPS_PORT}/tools/graphiti_ingestion_stats",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            count = data.get("uningested_messages", 0)
            logger.info(f"Uningested messages: {count}")
            return count
        else:
            logger.error(f"Graphiti stats check failed: {response.status_code}")
            return 0
    except Exception as e:
        logger.error(f"Failed to check uningested count: {e}")
        return 0

def run_ingestion_batch() -> dict:
    """Run a single batch ingestion."""
    try:
        response = requests.post(
            f"http://{PPS_HOST}:{PPS_PORT}/tools/ingest_batch_to_graphiti",
            json={"batch_size": BATCH_SIZE},
            timeout=180  # Graphiti can be very slow (3 minutes)
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Batch ingestion failed: {response.status_code}")
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.error(f"Batch ingestion error: {e}")
        return {"success": False, "error": str(e)}

def main():
    """Main execution flow."""
    logger.info("=== Auto-Ingest Graphiti Check Starting ===")

    # Check current state
    count = check_uningested_count()

    if count <= THRESHOLD:
        logger.info(f"Count ({count}) below threshold ({THRESHOLD}) - no action needed")
        return 0

    logger.info(f"Count ({count}) exceeds threshold ({THRESHOLD}) - running ingestion batches")

    # Run up to MAX_BATCHES batches
    total_ingested = 0
    total_failed = 0

    for i in range(MAX_BATCHES):
        logger.info(f"Running batch {i+1}/{MAX_BATCHES}...")
        result = run_ingestion_batch()

        if result.get("success"):
            ingested = result.get("ingested", 0)
            failed = result.get("failed", 0)
            remaining = result.get("remaining", 0)

            total_ingested += ingested
            total_failed += failed

            logger.info(f"Batch {i+1}: ingested {ingested}, failed {failed}, remaining {remaining}")

            # Stop if we've cleared the backlog
            if remaining <= THRESHOLD:
                logger.info("Backlog cleared - stopping")
                break
        else:
            logger.error(f"Batch {i+1} failed: {result.get('error', 'unknown error')}")
            break

    logger.info(f"=== Ingestion complete: {total_ingested} ingested, {total_failed} failed ===")
    return 0 if total_failed == 0 else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)
