#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Clear Graphiti ingestion backlog by running batches until complete.

This script processes uningested messages in batches, sending them to Graphiti
for entity extraction. Safe to run during autonomous reflection - doesn't
interfere with active sessions.

Usage:
    python3 scripts/clear_graphiti_backlog.py [--batch-size N] [--max-batches N]
"""

import sys
import time
import argparse
from pathlib import Path

# Add pps to path
pps_path = Path(__file__).parent.parent / "pps"
sys.path.insert(0, str(pps_path))
sys.path.insert(0, str(pps_path / "docker"))

from layers.message_summaries import MessageSummariesLayer
from layers.rich_texture import RichTextureLayer
import asyncio
import os

# Get entity config from environment
ENTITY_PATH = Path(os.environ.get("ENTITY_PATH", "/home/jeff/.claude/pps-lyra"))
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra")


async def clear_backlog(batch_size=20, max_batches=None):
    """Clear the Graphiti ingestion backlog."""

    # Initialize layers
    summaries = MessageSummariesLayer(ENTITY_PATH)
    texture = RichTextureLayer(ENTITY_PATH)

    print(f"🌲 Clearing Graphiti backlog for {ENTITY_NAME}")
    print(f"   Batch size: {batch_size}")
    if max_batches:
        print(f"   Max batches: {max_batches}")
    print()

    batch_num = 0
    total_ingested = 0
    total_failed = 0

    while True:
        # Check remaining
        remaining = summaries.count_uningested_to_graphiti()

        if remaining == 0:
            print(f"\n✅ Backlog cleared!")
            break

        if max_batches and batch_num >= max_batches:
            print(f"\n⏸️  Reached max batches ({max_batches})")
            print(f"   Remaining: {remaining}")
            break

        # Get next batch
        messages = summaries.get_uningested_for_graphiti(limit=batch_size)

        if not messages:
            print(f"\n✅ No more messages (remaining count: {remaining})")
            break

        batch_num += 1
        print(f"Batch {batch_num}: Processing {len(messages)} messages...", end=" ", flush=True)

        # Ingest each message
        batch_ingested = 0
        batch_failed = 0
        channels = set()

        for msg in messages:
            is_lyra = msg.get('is_lyra', False)
            author = ENTITY_NAME.capitalize() if is_lyra else (msg['author_name'] or "Unknown")

            metadata = {
                "channel": msg['channel'] or "unknown",
                "role": "assistant" if is_lyra else "user",
                "speaker": author,
                "timestamp": msg['created_at']
            }

            try:
                success = await texture.store(msg['content'], metadata)
                if success:
                    batch_ingested += 1
                    channels.add(msg['channel'])
                else:
                    batch_failed += 1
            except Exception as e:
                batch_failed += 1
                print(f"\n   ⚠️  Error on message {msg['id']}: {e}")

        # Mark batch as ingested
        if batch_ingested > 0:
            all_ids = [msg['id'] for msg in messages]
            start_id = min(all_ids)
            end_id = max(all_ids)
            batch_id = summaries.mark_batch_ingested_to_graphiti(
                start_id, end_id, list(channels)
            )

        total_ingested += batch_ingested
        total_failed += batch_failed

        print(f"✓ {batch_ingested} ingested, {batch_failed} failed. {remaining - len(messages)} remaining.")

        # Brief pause between batches to avoid overwhelming the system
        await asyncio.sleep(0.5)

    print(f"\n📊 Summary:")
    print(f"   Batches processed: {batch_num}")
    print(f"   Messages ingested: {total_ingested}")
    print(f"   Failed: {total_failed}")
    print(f"   Final remaining: {summaries.count_uningested_to_graphiti()}")

    return total_ingested, total_failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear Graphiti ingestion backlog")
    parser.add_argument("--batch-size", type=int, default=20, help="Messages per batch (default: 20)")
    parser.add_argument("--max-batches", type=int, help="Maximum batches to process (default: unlimited)")

    args = parser.parse_args()

    asyncio.run(clear_backlog(batch_size=args.batch_size, max_batches=args.max_batches))
