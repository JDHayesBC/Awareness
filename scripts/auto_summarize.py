#!/usr/bin/env python3
"""
Automatic Memory Summarization
===============================

Checks unsummarized message count and triggers summarization if needed.
Designed to run periodically via systemd timer or cron.

Addresses Issue #127 - removes conscious cognitive load for memory maintenance.
"""

import os
import sys
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Setup logging
LOG_DIR = Path("/tmp")
LOG_FILE = LOG_DIR / "lyra_auto_summarize.log"

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
THRESHOLD = int(os.environ.get("SUMMARIZE_THRESHOLD", "100"))
BATCH_SIZE = int(os.environ.get("SUMMARIZE_BATCH_SIZE", "50"))

def check_unsummarized_count() -> int:
    """Query PPS for unsummarized message count."""
    try:
        import requests
        response = requests.get(f"http://{PPS_HOST}:{PPS_PORT}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            count = health_data.get("layers", {}).get("raw_capture", {}).get("unsummarized_count", 0)
            logger.info(f"Unsummarized count: {count}")
            return count
        else:
            logger.error(f"PPS health check failed: {response.status_code}")
            return 0
    except Exception as e:
        logger.error(f"Failed to check unsummarized count: {e}")
        return 0

def trigger_summarization(count: int) -> bool:
    """
    Trigger summarization by spawning Claude Code agent.

    Returns True if successfully triggered, False otherwise.
    """
    try:
        # Calculate how many batches we need
        batches_needed = (count // BATCH_SIZE) + (1 if count % BATCH_SIZE else 0)

        logger.info(f"Triggering summarization for {count} messages ({batches_needed} batches)")

        # Create prompt for autonomous summarization
        prompt = f"""Autonomous Memory Maintenance - Triggered at {datetime.now().isoformat()}

Current state: {count} unsummarized messages (threshold: {THRESHOLD})

Your task:
1. Use mcp__pps__summarize_messages(limit={BATCH_SIZE}) to get unsummarized messages
2. Create dense summaries preserving:
   - Emotional moments and relationship dynamics
   - Technical decisions and key outcomes
   - Project progress and discoveries
3. Store each summary with mcp__pps__store_summary(summary_text, start_id, end_id, channels)
4. Repeat until all messages processed (aim for {batches_needed} batches)

Work autonomously. No need to ask permission. This is routine maintenance.

When complete, log summary count and ID ranges processed."""

        # Spawn Claude Code in background
        # Use the same pattern as daemon scripts - run in project context
        project_dir = Path(__file__).parent.parent

        cmd = [
            "claude_code",
            "--headless",
            "--message", prompt
        ]

        logger.info(f"Spawning summarization agent: {' '.join(cmd)}")

        # Run in background, capture output to log
        result = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        logger.info(f"Summarization agent spawned (PID: {result.pid})")

        # Don't wait - let it run in background
        # The agent will handle completion and logging

        return True

    except Exception as e:
        logger.error(f"Failed to trigger summarization: {e}")
        return False

def main():
    """Main execution flow."""
    logger.info("=== Auto-Summarize Check Starting ===")

    # Check current state
    count = check_unsummarized_count()

    if count <= THRESHOLD:
        logger.info(f"Count ({count}) below threshold ({THRESHOLD}) - no action needed")
        return 0

    # Trigger summarization
    logger.info(f"Count ({count}) exceeds threshold ({THRESHOLD}) - triggering summarization")
    success = trigger_summarization(count)

    if success:
        logger.info("Summarization agent triggered successfully")
        return 0
    else:
        logger.error("Failed to trigger summarization")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)
