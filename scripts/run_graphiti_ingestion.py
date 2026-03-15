#!/usr/bin/env python3
"""
Autonomous Graphiti ingestion script.

Runs parallel batches of 12 messages at a time until the backlog is cleared.
Designed to run in the background during reflection cycles.
"""

import asyncio
import aiohttp
import json
import time
import sys
from datetime import datetime
from pathlib import Path

# Configuration
PPS_URL = "http://localhost:8201"
BATCH_SIZE = 24  # Process 24 messages per batch (2 parallel batches of 12)
MAX_BATCHES = None  # None = run until complete, or set a number for limited run
DELAY_BETWEEN_BATCHES = 5  # seconds between batches to avoid overwhelming the system


async def get_ingestion_stats(session):
    """Get current ingestion statistics."""
    url = f"{PPS_URL}/tools/graphiti_ingestion_stats"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                print(f"Error getting stats: {resp.status}", file=sys.stderr)
                return None
    except Exception as e:
        print(f"Error getting stats: {e}", file=sys.stderr)
        return None


async def ingest_batch(session, batch_size, parallel=True):
    """Ingest a single batch of messages."""
    url = f"{PPS_URL}/tools/ingest_batch_to_graphiti"
    data = {
        "batch_size": batch_size,
        "parallel": parallel,
        "token": ""
    }

    try:
        # Generous timeout: 2 minutes per message
        timeout = aiohttp.ClientTimeout(total=batch_size * 120)
        async with session.post(url, json=data, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                error_text = await resp.text()
                print(f"Error ingesting batch: {resp.status} - {error_text}", file=sys.stderr)
                return None
    except asyncio.TimeoutError:
        print(f"Batch timed out after {batch_size * 120} seconds", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error ingesting batch: {e}", file=sys.stderr)
        return None


async def main():
    """Main ingestion loop."""
    start_time = time.time()
    total_ingested = 0
    total_failed = 0
    batch_count = 0

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Graphiti ingestion")
    print(f"Batch size: {BATCH_SIZE} messages (parallel processing enabled)")
    print(f"Max batches: {'unlimited' if MAX_BATCHES is None else MAX_BATCHES}")
    print()

    async with aiohttp.ClientSession() as session:
        # Get initial stats
        initial_stats = await get_ingestion_stats(session)
        if not initial_stats:
            print("Failed to get initial stats. Exiting.")
            return 1

        initial_remaining = initial_stats.get('uningested_messages', 0)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Initial backlog: {initial_remaining} messages")
        print()

        # Process batches until complete or max reached
        while True:
            # Check if we should stop
            if MAX_BATCHES is not None and batch_count >= MAX_BATCHES:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Reached max batches ({MAX_BATCHES}). Stopping.")
                break

            # Get current stats
            stats = await get_ingestion_stats(session)
            if not stats:
                print("Failed to get stats. Stopping.")
                break

            remaining = stats.get('uningested_messages', 0)
            if remaining == 0:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✅ All messages ingested!")
                break

            # Process one batch
            batch_count += 1
            batch_start = time.time()

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Batch {batch_count}: Processing {min(BATCH_SIZE, remaining)} messages...", end='', flush=True)

            result = await ingest_batch(session, BATCH_SIZE, parallel=True)

            batch_elapsed = time.time() - batch_start

            if result:
                ingested = result.get('ingested', 0)
                failed = result.get('failed', 0)
                new_remaining = result.get('remaining', 0)

                total_ingested += ingested
                total_failed += failed

                # Calculate rate and projection
                rate = ingested / batch_elapsed if batch_elapsed > 0 else 0
                projected_hours = (new_remaining / rate / 3600) if rate > 0 else 0

                print(f" ✅ {ingested} ingested, {failed} failed ({batch_elapsed:.1f}s)")
                print(f"    Rate: {rate:.2f} msg/s | Remaining: {new_remaining} | ETA: {projected_hours:.1f}h")

                if failed > 0 and result.get('errors'):
                    print(f"    Errors: {result['errors'][:3]}")  # Show first 3 errors
            else:
                print(f" ❌ Failed")
                # Don't count failed batches in the retry logic, just continue

            # Delay between batches
            if remaining > BATCH_SIZE:  # Only delay if more work remains
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)

        # Final summary
        total_elapsed = time.time() - start_time
        print()
        print("=" * 60)
        print(f"Ingestion complete")
        print(f"Total time: {total_elapsed / 3600:.1f} hours")
        print(f"Total ingested: {total_ingested} messages")
        print(f"Total failed: {total_failed} messages")
        print(f"Batches processed: {batch_count}")
        if total_elapsed > 0:
            print(f"Average rate: {total_ingested / total_elapsed:.2f} messages/second")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Progress has been saved.")
        sys.exit(130)
