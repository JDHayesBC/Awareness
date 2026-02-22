#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Bulk Graphiti Ingestion Script

Ingests messages to Graphiti using add_episode_bulk(), which processes a batch
of episodes together instead of one at a time. This skips per-episode edge
invalidation and date extraction steps, reducing total LLM calls and avoiding
some of the Haiku index-out-of-bounds crashes seen in paced_ingestion.py.

Usage:
    python bulk_ingestion.py [--batch-size 10] [--pause 30] [--max-batches 0]

Options:
    --batch-size:  Messages per bulk call (default: 10)
    --pause:       Seconds between batches (default: 30)
    --max-batches: Stop after N batches, 0 = unlimited (default: 0)
    --sandbox:     Use sandbox group_id (no production writes)
    --dry-run:     Fetch and format messages but don't call Graphiti

Notes:
    - Uses the same SQLite DB and per-row tracking as paced_ingestion.py
    - Batch failures mark ALL messages in the batch as 'failed'
    - Start with small --batch-size (5-10) and verify before scaling up
"""

import asyncio
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load environment from pps/docker/.env BEFORE importing modules that need it
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent  # scripts/ -> Awareness/
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

# Add project root to path
sys.path.insert(0, str(PROJECT_ROOT))

# Log file for monitoring
LOG_FILE = Path(__file__).parent / "bulk_ingestion.log"


def log(msg: str):
    """Print and log to file."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# =============================================================================
# Database Access
# =============================================================================

def get_db_path() -> str:
    """Get path to conversations DB, same logic as paced_ingestion.py."""
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        return str(Path(entity_path) / "data" / "conversations.db")
    return str(PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db")


def get_pending_messages(db_path: str, limit: int) -> list[dict]:
    """Get batch of messages not yet ingested to Graphiti."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, channel, author_name, content, is_lyra, created_at
        FROM messages
        WHERE (graphiti_status IS NULL OR graphiti_status = 'pending')
        ORDER BY id ASC
        LIMIT ?
    """, (limit,))

    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


def mark_batch_result(
    db_path: str,
    all_messages: list[dict],
    success: bool,
    error_reason: str = "",
) -> int:
    """
    Mark a batch of messages after a bulk ingestion attempt.

    On success: all messages marked 'ingested' with a shared batch_id.
    On failure: all messages marked 'failed' with error_reason.

    Returns batch_id (even on failure, for audit trail).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    start_id = all_messages[0]["id"]
    end_id = all_messages[-1]["id"]
    message_count = len(all_messages)
    time_span_start = all_messages[0]["created_at"]
    time_span_end = all_messages[-1]["created_at"]
    channels = list({m["channel"] for m in all_messages})

    # Create batch record (audit trail)
    cur.execute("""
        INSERT INTO graphiti_batches
        (start_message_id, end_message_id, message_count, channels,
         time_span_start, time_span_end, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (start_id, end_id, message_count, json.dumps(channels),
          time_span_start, time_span_end))

    batch_id = cur.lastrowid

    if success:
        for msg in all_messages:
            cur.execute("""
                UPDATE messages
                SET graphiti_batch_id = ?,
                    graphiti_status = 'ingested',
                    graphiti_attempted_at = datetime('now')
                WHERE id = ?
            """, (batch_id, msg["id"]))
    else:
        truncated_error = error_reason[:500] if error_reason else "bulk ingestion failed"
        for msg in all_messages:
            cur.execute("""
                UPDATE messages
                SET graphiti_status = 'failed',
                    graphiti_error = ?,
                    graphiti_attempted_at = datetime('now')
                WHERE id = ?
            """, (truncated_error, msg["id"]))

    conn.commit()
    conn.close()
    return batch_id


def get_stats(db_path: str) -> tuple[int, int, int]:
    """Get (ingested, failed, pending) counts."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_status = 'ingested'")
    ingested = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_status = 'failed'")
    failed = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM messages "
        "WHERE (graphiti_status IS NULL OR graphiti_status = 'pending')"
    )
    pending = cur.fetchone()[0]

    conn.close()
    return ingested, failed, pending


# =============================================================================
# Episode Formatting
# =============================================================================

def messages_to_raw_episodes(messages: list[dict], EpisodeType, RawEpisode) -> list:
    """
    Convert SQLite message rows to RawEpisode objects for add_episode_bulk().

    Mirrors paced_ingestion.py format: "Speaker: message content"
    Uses EpisodeType.message for chat-style content.
    """
    episodes = []
    for msg in messages:
        speaker = "Lyra" if msg["is_lyra"] else msg["author_name"]
        formatted_content = f"{speaker}: {msg['content']}"

        # Parse timestamp
        raw_ts = msg["created_at"]
        try:
            reference_time = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            reference_time = datetime.now(timezone.utc)

        # Ensure timezone-aware
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

        episode = RawEpisode(
            name=f"{speaker}_{msg['id']}_{reference_time.strftime('%Y%m%d_%H%M%S')}",
            content=formatted_content,
            source_description=f"Conversation from {msg['channel']} channel",
            source=EpisodeType.message,
            reference_time=reference_time,
        )
        episodes.append(episode)

    return episodes


# =============================================================================
# Main Ingestion Loop
# =============================================================================

async def run_bulk_ingestion(
    batch_size: int,
    pause_seconds: int,
    max_batches: int,
    sandbox: bool = False,
    dry_run: bool = False,
):
    """Run bulk ingestion loop."""
    db_path = get_db_path()

    # Clear old log
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    log("=== Bulk Graphiti Ingestion ===")
    log(f"Batch size:    {batch_size}")
    log(f"Pause:         {pause_seconds}s")
    log(f"Max batches:   {'unlimited' if max_batches == 0 else max_batches}")
    log(f"Mode:          {'SANDBOX' if sandbox else 'PRODUCTION'}")
    log(f"Dry run:       {dry_run}")
    log("")

    if dry_run:
        log("DRY RUN MODE: Episodes will be formatted but not sent to Graphiti.")
        log("")

    # Import graphiti components (deferred to keep startup fast)
    log("Importing graphiti_core...")
    try:
        from graphiti_core.utils.bulk_utils import RawEpisode
        from graphiti_core.nodes import EpisodeType
        log("graphiti_core imported successfully")
    except ImportError as e:
        log(f"FATAL: Cannot import graphiti_core: {e}")
        sys.exit(1)

    # Initialize Graphiti client (via RichTextureLayerV2 for config reuse)
    # but access the underlying graphiti client directly for bulk API
    graphiti_client = None
    group_id = None

    if not dry_run:
        log("Initializing Graphiti client...")
        from pps.layers.rich_texture_v2 import RichTextureLayerV2

        if sandbox:
            os.environ["GRAPHITI_GROUP_ID"] = "sandbox"

        layer = RichTextureLayerV2()
        graphiti_client = await layer._get_graphiti_client()

        if graphiti_client is None:
            log("FATAL: Could not initialize Graphiti client. Check Neo4j and LLM config.")
            sys.exit(1)

        group_id = layer.group_id
        log(f"Graphiti client ready (group_id: {group_id})")
    else:
        group_id = "sandbox" if sandbox else "lyra"
        layer = None

    ingested_total, failed_total, pending_total = get_stats(db_path)
    log(f"Starting state: {ingested_total} ingested, {failed_total} failed, {pending_total} pending")
    log("")

    batch_num = 0
    total_success = 0
    total_fail = 0

    try:
        while True:
            batch_num += 1

            if max_batches > 0 and batch_num > max_batches:
                log(f"Reached max batches ({max_batches}). Stopping.")
                break

            # Fetch batch
            messages = get_pending_messages(db_path, batch_size)

            if not messages:
                log("No more messages to ingest. Done!")
                break

            start_time = datetime.now()
            msg_ids = [m["id"] for m in messages]
            log(f"[Batch {batch_num}] {len(messages)} messages "
                f"(IDs {messages[0]['id']}-{messages[-1]['id']})...")

            # Format as RawEpisode objects
            episodes = messages_to_raw_episodes(messages, EpisodeType, RawEpisode)

            if dry_run:
                log(f"  DRY RUN: Would submit {len(episodes)} episodes as bulk batch")
                for ep in episodes[:3]:
                    log(f"    - {ep.name}: {ep.content[:60]}...")
                if len(episodes) > 3:
                    log(f"    ... and {len(episodes) - 3} more")
                elapsed = (datetime.now() - start_time).total_seconds()
                log(f"  Formatted in {elapsed:.2f}s")
                log("")
                if pending_total <= batch_size:
                    break
                log(f"  Pausing {pause_seconds}s...")
                await asyncio.sleep(pause_seconds)
                continue

            # Call add_episode_bulk()
            try:
                result = await graphiti_client.add_episode_bulk(
                    bulk_episodes=episodes,
                    group_id=group_id,
                )

                elapsed = (datetime.now() - start_time).total_seconds()
                batch_id = mark_batch_result(db_path, messages, success=True)

                total_success += len(messages)
                log(f"  OK: {len(messages)} ingested in {elapsed:.1f}s "
                    f"({elapsed / len(messages):.1f}s/msg) "
                    f"[batch {batch_id}]")
                log(f"  Graph: {len(result.nodes)} nodes, {len(result.edges)} edges, "
                    f"{len(result.episodes)} episodes")

            except Exception as e:
                elapsed = (datetime.now() - start_time).total_seconds()
                error_str = f"{type(e).__name__}: {e}"
                batch_id = mark_batch_result(
                    db_path, messages, success=False, error_reason=error_str
                )

                total_fail += len(messages)
                log(f"  FAIL: {len(messages)} messages failed in {elapsed:.1f}s")
                log(f"  Error: {error_str[:200]}")
                log(f"  Failed IDs: {msg_ids}")

            ingested_total, failed_total, pending_total = get_stats(db_path)
            log(f"  Progress: {ingested_total} ingested, {failed_total} failed, "
                f"{pending_total} pending")

            if pending_total == 0:
                log("All messages ingested!")
                break

            log(f"  Pausing {pause_seconds}s...")
            await asyncio.sleep(pause_seconds)

    finally:
        if layer is not None:
            await layer.close()

    # Final stats
    log("")
    log("=== Final Stats ===")
    ingested_total, failed_total, pending_total = get_stats(db_path)
    log(f"Total ingested:  {ingested_total}")
    log(f"Total failed:    {failed_total}")
    log(f"Total pending:   {pending_total}")
    log(f"This run - ok:   {total_success}")
    log(f"This run - fail: {total_fail}")

    if pending_total == 0 and failed_total == 0:
        log("Status: COMPLETE")
    elif pending_total == 0:
        log("Status: COMPLETE (with failures - review bulk_ingestion.log)")
    else:
        log("Status: STOPPED")


# =============================================================================
# Speed Benchmark
# =============================================================================

async def run_speed_test(
    message_count: int = 10,
    batch_size: int = 10,
):
    """
    Compare bulk vs single ingestion speed using a small test set.

    Reads messages from DB but does NOT mark them as ingested.
    Uses sandbox group_id to avoid polluting production graph.
    """
    db_path = get_db_path()
    log("=== Speed Test: bulk vs single ===")
    log(f"Messages: {message_count}")
    log(f"Bulk batch size: {batch_size}")
    log("")

    log("Importing graphiti_core...")
    from graphiti_core.utils.bulk_utils import RawEpisode
    from graphiti_core.nodes import EpisodeType
    log("OK")

    log("Initializing layer...")
    os.environ["GRAPHITI_GROUP_ID"] = "sandbox_speedtest"
    from pps.layers.rich_texture_v2 import RichTextureLayerV2
    layer = RichTextureLayerV2()
    graphiti_client = await layer._get_graphiti_client()

    if graphiti_client is None:
        log("FATAL: Cannot connect to Graphiti")
        return

    group_id = "sandbox_speedtest"
    log(f"Connected (group: {group_id})")
    log("")

    # Get messages (don't mark as ingested)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, channel, author_name, content, is_lyra, created_at
        FROM messages
        WHERE (graphiti_status IS NULL OR graphiti_status = 'pending')
        ORDER BY id ASC
        LIMIT ?
    """, (message_count,))
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()

    if not messages:
        log("No pending messages to test with.")
        await layer.close()
        return

    actual_count = len(messages)
    log(f"Using {actual_count} messages (IDs {messages[0]['id']}-{messages[-1]['id']})")
    log("")

    episodes = messages_to_raw_episodes(messages, EpisodeType, RawEpisode)

    # --- BULK TEST ---
    log(f"--- BULK: {actual_count} messages in one add_episode_bulk() call ---")
    bulk_start = datetime.now()
    bulk_ok = False
    try:
        result = await graphiti_client.add_episode_bulk(
            bulk_episodes=episodes,
            group_id=group_id,
        )
        bulk_elapsed = (datetime.now() - bulk_start).total_seconds()
        bulk_ok = True
        log(f"BULK OK: {bulk_elapsed:.1f}s total, {bulk_elapsed / actual_count:.2f}s/msg")
        log(f"  Graph: {len(result.nodes)} nodes, {len(result.edges)} edges")
    except Exception as e:
        bulk_elapsed = (datetime.now() - bulk_start).total_seconds()
        log(f"BULK FAIL after {bulk_elapsed:.1f}s: {type(e).__name__}: {e}")

    log("")

    # --- SINGLE TEST ---
    log(f"--- SINGLE: {actual_count} messages via add_episode() one at a time ---")
    single_start = datetime.now()
    single_ok = 0
    single_fail = 0
    for ep in episodes:
        try:
            await graphiti_client.add_episode(
                name=ep.name,
                episode_body=ep.content,
                source_description=ep.source_description,
                reference_time=ep.reference_time,
                source=ep.source,
                group_id=group_id,
            )
            single_ok += 1
        except Exception as e:
            single_fail += 1
            log(f"  SINGLE FAIL: {type(e).__name__}: {str(e)[:80]}")

    single_elapsed = (datetime.now() - single_start).total_seconds()
    log(f"SINGLE: {single_elapsed:.1f}s total, {single_elapsed / actual_count:.2f}s/msg")
    log(f"  Success: {single_ok}, Fail: {single_fail}")

    log("")
    log("=== Speed Comparison ===")
    if bulk_ok and single_elapsed > 0:
        speedup = single_elapsed / bulk_elapsed if bulk_elapsed > 0 else 0
        log(f"Bulk:   {bulk_elapsed:.1f}s ({bulk_elapsed / actual_count:.2f}s/msg)")
        log(f"Single: {single_elapsed:.1f}s ({single_elapsed / actual_count:.2f}s/msg)")
        log(f"Speedup: {speedup:.1f}x")
    else:
        log(f"Bulk: {'OK' if bulk_ok else 'FAILED'} ({bulk_elapsed:.1f}s)")
        log(f"Single: {single_elapsed:.1f}s ({single_ok}/{actual_count} succeeded)")

    await layer.close()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Bulk Graphiti ingestion using add_episode_bulk()",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Messages per bulk call (default: 10)")
    parser.add_argument("--pause", type=int, default=30,
                        help="Seconds between batches (default: 30)")
    parser.add_argument("--max-batches", type=int, default=0,
                        help="Max batches, 0=unlimited (default: 0)")
    parser.add_argument("--sandbox", action="store_true",
                        help="Use sandbox group_id (no production writes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Format episodes but don't call Graphiti")
    parser.add_argument("--speed-test", action="store_true",
                        help="Run speed comparison (bulk vs single) and exit")
    parser.add_argument("--speed-count", type=int, default=10,
                        help="Messages for speed test (default: 10)")

    args = parser.parse_args()

    if args.speed_test:
        asyncio.run(run_speed_test(
            message_count=args.speed_count,
            batch_size=args.batch_size,
        ))
    else:
        asyncio.run(run_bulk_ingestion(
            batch_size=args.batch_size,
            pause_seconds=args.pause,
            max_batches=args.max_batches,
            sandbox=args.sandbox,
            dry_run=args.dry_run,
        ))


if __name__ == "__main__":
    main()
