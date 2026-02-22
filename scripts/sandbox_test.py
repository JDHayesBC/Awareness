#!/usr/bin/env python3
"""
Graphiti Sandbox Validation Test Harness

Runs real messages through the Graphiti ingestion pipeline in an isolated
sandbox namespace (group_id="sandbox") to validate wrapper behavior before
processing the full 3,590-message production backlog.

IMPORTANT: This script reads messages from SQLite but does NOT mark them
as ingested. It is purely a validation tool.

Usage:
    # Prerequisites:
    # Terminal 1: python3 scripts/logging_proxy.py
    # Then in Terminal 2:

    # Test 10 messages starting from first uningested (17521):
    python3 scripts/sandbox_test.py

    # Test specific count starting from specific ID:
    python3 scripts/sandbox_test.py --count 20 --start-id 17521

    # Test specific message IDs:
    python3 scripts/sandbox_test.py --message-ids 17521,17522,17523

    # Run without proxy (direct to haiku wrapper):
    python3 scripts/sandbox_test.py --count 5 --no-proxy

    # Clean up sandbox data from Neo4j after testing:
    python3 scripts/sandbox_test.py --cleanup

Options:
    --count N           Messages to test (default: 10)
    --start-id ID       First message ID (default: 17521, first uningested)
    --message-ids IDs   Comma-separated specific IDs to test
    --no-proxy          Use haiku wrapper directly at port 8204
    --proxy-port PORT   Logging proxy port (default: 8297)
    --cleanup           Delete sandbox Neo4j data and exit
    --results-dir PATH  Where to write results (default: work/graphiti-sandbox-validation/results/)
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# =============================================================================
# Environment setup MUST happen before any layer imports
# =============================================================================

# Load base environment from pps/docker/.env
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent  # scripts/ -> Awareness/
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

# Add project root to path for pps.layers import
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = str(PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db")
RESULTS_DIR_DEFAULT = str(PROJECT_ROOT / "work" / "graphiti-sandbox-validation" / "results")


# =============================================================================
# Logging
# =============================================================================

def log(msg: str):
    """Print with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


# =============================================================================
# Database Access
# =============================================================================

def get_messages_by_ids(ids: list[int]) -> list[dict]:
    """Fetch specific messages by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join(["?" for _ in ids])
    cur.execute(
        f"SELECT id, channel, author_name, content, is_lyra, created_at "
        f"FROM messages WHERE id IN ({placeholders}) ORDER BY id ASC",
        ids,
    )
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


def get_uningested_messages(start_id: int, count: int) -> list[dict]:
    """Get uningested messages starting from start_id."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, channel, author_name, content, is_lyra, created_at
        FROM messages
        WHERE graphiti_batch_id IS NULL AND id >= ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (start_id, count),
    )
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


def get_total_uningested() -> int:
    """Count total uningested messages."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL")
    count = cur.fetchone()[0]
    conn.close()
    return count


# =============================================================================
# Sandbox Cleanup
# =============================================================================

def cleanup_sandbox():
    """Delete all sandbox data from Neo4j."""
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password123")

    log(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # Count sandbox nodes first
        result = session.run("MATCH (n) WHERE n.group_id = 'sandbox' RETURN count(n) as c")
        count = result.single()["c"]
        log(f"Found {count} sandbox nodes in Neo4j")

        if count > 0:
            session.run("MATCH (n) WHERE n.group_id = 'sandbox' DETACH DELETE n")
            log(f"Deleted {count} sandbox nodes and their relationships")
        else:
            log("No sandbox data to clean up")

    driver.close()
    log("Cleanup complete")


# =============================================================================
# Main Test Runner
# =============================================================================

async def run_sandbox_test(
    messages: list[dict],
    proxy_url: str,
    results_dir: str,
) -> dict:
    """Run messages through sandbox Graphiti ingestion."""

    # Override env vars for sandbox BEFORE importing the layer
    os.environ["GRAPHITI_LLM_BASE_URL"] = proxy_url
    os.environ["GRAPHITI_LLM_MODEL"] = "haiku"
    os.environ["GRAPHITI_GROUP_ID"] = "sandbox"
    # Keep OpenAI embeddings (same vector space as production)
    os.environ["GRAPHITI_EMBEDDING_PROVIDER"] = "openai"

    log(f"Sandbox configuration:")
    log(f"  LLM URL: {proxy_url} (via logging proxy)")
    log(f"  Group ID: sandbox")
    log(f"  Embedding: OpenAI (production-compatible)")
    log(f"  Messages to test: {len(messages)}")
    log("")

    # Import layer AFTER env vars are set
    log("Initializing Graphiti layer (this takes ~30s for graphiti_core import)...")
    from pps.layers.rich_texture_v2 import RichTextureLayerV2

    layer = RichTextureLayerV2(group_id="sandbox")

    results = {
        "run_timestamp": datetime.now().isoformat(),
        "proxy_url": proxy_url,
        "group_id": "sandbox",
        "message_count": len(messages),
        "success_count": 0,
        "fail_count": 0,
        "messages": [],
        "error_categories": {},
    }

    try:
        for i, msg in enumerate(messages, 1):
            msg_id = msg["id"]
            content = msg["content"]
            is_lyra = msg["is_lyra"]
            speaker = "Lyra" if is_lyra else msg["author_name"]
            channel = msg["channel"]
            created_at = msg["created_at"]

            formatted_content = f"{speaker}: {content}"

            metadata = {
                "channel": channel,
                "role": "assistant" if is_lyra else "user",
                "speaker": speaker,
                "timestamp": created_at,
            }

            log(f"[{i}/{len(messages)}] Message ID {msg_id} | {speaker} | {len(content)} chars")
            log(f"  Preview: {content[:80].replace(chr(10), ' ')}...")

            msg_start = datetime.now()
            try:
                success = await layer.store(formatted_content, metadata)
                elapsed = (datetime.now() - msg_start).total_seconds()

                if success:
                    results["success_count"] += 1
                    log(f"  PASS in {elapsed:.1f}s")
                    results["messages"].append({
                        "id": msg_id,
                        "channel": channel,
                        "is_lyra": is_lyra,
                        "speaker": speaker,
                        "content_preview": content[:80],
                        "content_length": len(content),
                        "success": True,
                        "error": None,
                        "error_category": None,
                        "elapsed_seconds": round(elapsed, 2),
                    })
                else:
                    results["fail_count"] += 1
                    err = layer.get_last_error()
                    error_msg = err["message"] if err else "store() returned False"
                    error_cat = err["category"] if err else "unknown"
                    advice = err.get("advice", "") if err else ""

                    results["error_categories"][error_cat] = results["error_categories"].get(error_cat, 0) + 1

                    log(f"  FAIL in {elapsed:.1f}s [{error_cat}]: {error_msg[:120]}")
                    if advice:
                        log(f"  Advice: {advice}")

                    results["messages"].append({
                        "id": msg_id,
                        "channel": channel,
                        "is_lyra": is_lyra,
                        "speaker": speaker,
                        "content_preview": content[:80],
                        "content_length": len(content),
                        "success": False,
                        "error": error_msg,
                        "error_category": error_cat,
                        "elapsed_seconds": round(elapsed, 2),
                    })

            except Exception as e:
                elapsed = (datetime.now() - msg_start).total_seconds()
                results["fail_count"] += 1
                error_cat = "exception"
                error_msg = f"{type(e).__name__}: {e}"

                results["error_categories"][error_cat] = results["error_categories"].get(error_cat, 0) + 1

                log(f"  EXCEPTION in {elapsed:.1f}s: {error_msg}")

                results["messages"].append({
                    "id": msg_id,
                    "channel": channel,
                    "is_lyra": is_lyra,
                    "speaker": speaker,
                    "content_preview": content[:80],
                    "content_length": len(content),
                    "success": False,
                    "error": error_msg,
                    "error_category": error_cat,
                    "elapsed_seconds": round(elapsed, 2),
                })

    finally:
        await layer.close()

    # Write results to file
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = Path(results_dir) / f"sandbox_results_{timestamp_str}.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    log(f"\nResults written to: {results_file}")

    return results


# =============================================================================
# Summary Output
# =============================================================================

def print_summary(results: dict):
    """Print human-readable test summary."""
    print("\n" + "=" * 60, flush=True)
    print("SANDBOX TEST SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"Messages tested: {results['message_count']}", flush=True)
    print(f"Successes:       {results['success_count']}", flush=True)
    print(f"Failures:        {results['fail_count']}", flush=True)

    if results["error_categories"]:
        print("\nError breakdown:", flush=True)
        for cat, count in sorted(results["error_categories"].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}", flush=True)

    print("\nPer-message results:", flush=True)
    for msg in results["messages"]:
        status = "PASS" if msg["success"] else "FAIL"
        print(
            f"  ID {msg['id']:6d}: {status} | {msg['elapsed_seconds']:.1f}s | "
            f"{msg['speaker'][:12]:12s} | {msg['content_length']:5d} chars",
            flush=True,
        )
        if not msg["success"]:
            print(f"           Error [{msg['error_category']}]: {(msg['error'] or '')[:80]}", flush=True)

    print("=" * 60, flush=True)
    success_rate = results["success_count"] / max(results["message_count"], 1) * 100
    print(f"Success rate: {success_rate:.0f}%", flush=True)

    if results["fail_count"] == 0:
        print("\nAll messages ingested successfully! Ready for production run.", flush=True)
    else:
        print(f"\n{results['fail_count']} failures. Investigate before production run.", flush=True)


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Graphiti sandbox validation test harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--count", type=int, default=10, help="Messages to test (default: 10)")
    parser.add_argument("--start-id", type=int, default=17521, help="First message ID (default: 17521)")
    parser.add_argument("--message-ids", type=str, help="Comma-separated specific message IDs")
    parser.add_argument("--no-proxy", action="store_true", help="Use haiku wrapper directly (port 8204)")
    parser.add_argument("--proxy-port", type=int, default=8297, help="Logging proxy port (default: 8297)")
    parser.add_argument("--cleanup", action="store_true", help="Delete sandbox Neo4j data and exit")
    parser.add_argument(
        "--results-dir",
        default=RESULTS_DIR_DEFAULT,
        help=f"Results output directory (default: {RESULTS_DIR_DEFAULT})",
    )

    args = parser.parse_args()

    # Handle cleanup mode
    if args.cleanup:
        log("Running sandbox cleanup...")
        cleanup_sandbox()
        return

    # Determine proxy URL
    if args.no_proxy:
        proxy_url = "http://localhost:8204/v1"
        log("Running WITHOUT proxy — connecting directly to haiku wrapper at port 8204")
    else:
        proxy_url = f"http://localhost:{args.proxy_port}/v1"
        log(f"Using logging proxy at port {args.proxy_port}")
        log(f"Make sure the proxy is running: python3 scripts/logging_proxy.py")

    # Get messages
    if args.message_ids:
        ids = [int(x.strip()) for x in args.message_ids.split(",")]
        log(f"Fetching {len(ids)} specific message IDs: {ids}")
        messages = get_messages_by_ids(ids)
    else:
        log(f"Fetching {args.count} uningested messages starting from ID {args.start_id}")
        messages = get_uningested_messages(args.start_id, args.count)

    if not messages:
        log("No messages found matching criteria. Check --start-id and --count.")
        sys.exit(1)

    total_uningested = get_total_uningested()
    log(f"Total uningested messages: {total_uningested}")
    log(f"Testing {len(messages)} messages (IDs {messages[0]['id']}–{messages[-1]['id']})")
    log("")

    # Run async
    results = asyncio.run(run_sandbox_test(messages, proxy_url, args.results_dir))

    # Print summary
    print_summary(results)


if __name__ == "__main__":
    main()
