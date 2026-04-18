#!/usr/bin/env python3
"""
Gentle Graphiti ingestion — smaller batches, longer delays, serial processing.
Designed for overnight runs to avoid rate limits.
"""

import asyncio
import aiohttp
import time
import sys
from datetime import datetime

PPS_URL = "http://localhost:8201"
BATCH_SIZE = 5          # Small batches to avoid rate limits
DELAY_BETWEEN = 45      # 45 seconds between batches
TOKEN = "c803d0ad-501c-4dea-9127-ae7b5b28e46e"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


async def get_stats(session):
    try:
        async with session.get(f"{PPS_URL}/tools/graphiti_ingestion_stats") as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        log(f"Stats error: {e}")
    return None


async def ingest_batch(session):
    data = {"batch_size": BATCH_SIZE, "parallel": False, "token": TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=BATCH_SIZE * 180)  # 3 min/msg
        async with session.post(f"{PPS_URL}/tools/ingest_batch_to_graphiti",
                                json=data, timeout=timeout) as r:
            if r.status == 200:
                return await r.json()
            else:
                err = await r.text()
                log(f"HTTP {r.status}: {err[:200]}")
    except asyncio.TimeoutError:
        log("Batch timed out")
    except Exception as e:
        log(f"Batch error: {e}")
    return None


async def main():
    log("=== Gentle Graphiti Ingestion ===")
    log(f"Batch size: {BATCH_SIZE} | Delay: {DELAY_BETWEEN}s | Serial mode")

    total_ingested = 0
    total_failed = 0
    batch_num = 0

    async with aiohttp.ClientSession() as session:
        stats = await get_stats(session)
        if not stats:
            log("Cannot reach PPS server. Exiting.")
            return 1

        remaining = stats.get("uningested_messages", 0)
        log(f"Backlog: {remaining} messages")
        log("")

        while True:
            stats = await get_stats(session)
            if not stats:
                log("Stats unavailable — waiting 60s then retrying")
                await asyncio.sleep(60)
                continue

            remaining = stats.get("uningested_messages", 0)
            if remaining == 0:
                log("✅ Backlog clear! Ingestion complete.")
                break

            batch_num += 1
            log(f"Batch {batch_num}: {min(BATCH_SIZE, remaining)} messages ({remaining} remaining)...")

            result = await ingest_batch(session)
            if result:
                ingested = result.get("ingested", 0)
                failed = result.get("failed", 0)
                errors = result.get("errors", [])
                total_ingested += ingested
                total_failed += failed
                log(f"  → {ingested} ingested, {failed} failed | total: {total_ingested}")
                if errors:
                    log(f"  Errors: {errors[:2]}")

                # Back off harder if still rate limiting
                if failed > 0 and any("rate_limit" in str(e) for e in errors):
                    backoff = DELAY_BETWEEN * 2
                    log(f"  Rate limit hit — backing off {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
            else:
                log(f"  Batch failed entirely — waiting {DELAY_BETWEEN * 2}s")
                await asyncio.sleep(DELAY_BETWEEN * 2)
                continue

            if remaining > BATCH_SIZE:
                log(f"  Waiting {DELAY_BETWEEN}s...")
                await asyncio.sleep(DELAY_BETWEEN)

    log("")
    log(f"=== Done: {total_ingested} ingested, {total_failed} failed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
