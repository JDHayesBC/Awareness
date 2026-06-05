#!/usr/bin/env python3
"""
Cron-friendly auto-summarizer for all entities' message backlogs.

Designed for:
    */30 * * * * /path/to/pps/venv/bin/python3 /path/to/scripts/summarize_daemon.py

Behavior:
- Iterates ALL configured entities in order.
- For each entity: checks unsummarized count. If above threshold, calls the PPS HTTP
  server's summarize_messages endpoint (which drives NUC LLM internally).
- If PPS server is down → logs warning, continues to next entity.
- If NUC LLM is down → logs warning (returned by PPS server as 503).
- If backlog already healthy → skips entity (silent cron run).
- Logs everything to stdout (captured by cron mail or journald).

Venv requirement: pps/venv
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# nuc_lock imported after PROJECT_ROOT is defined (see below)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
EXPECTED_VENV = PROJECT_ROOT / "pps" / "venv"
VENV_SYMLINK = PROJECT_ROOT / ".venv"
sys.path.insert(0, str(PROJECT_ROOT))

# Guard: must run from the project venv
if not (
    sys.prefix.startswith(str(EXPECTED_VENV))
    or sys.prefix.startswith(str(VENV_SYMLINK.resolve()))
):
    print("ERROR: Run from the project venv, not system Python.")
    print(f"  Expected: {EXPECTED_VENV}/bin/python3")
    print(f"  Got:      {sys.executable}")
    sys.exit(1)

import httpx  # noqa: E402
from scripts.nuc_lock import NucLock, SUMMARIZER_LOCK, KG_INGEST_LOCK, is_lock_held  # noqa: E402


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("summarize_daemon")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

TARGET_UNSUMMARIZED = int(os.environ.get("SUMMARIZE_TARGET", "80"))
BATCH_LIMIT = int(os.environ.get("SUMMARIZE_BATCH", "50"))
SUMMARIZE_THRESHOLD = 100  # Only act if backlog is above this

# Max messages to drain in a single summarize_messages HTTP call.
# Set to ONE batch (== BATCH_LIMIT) so each HTTP call asks the server for exactly
# one batch and returns. This is the robust shape: per-batch time is highly
# content-dependent (measured 44s for normal chat turns, 119s–236s for batches
# full of long code/investigation messages); a single batch stays well under
# HTTP_TIMEOUT, but ANY multi-batch chunk risks blowing it (200-msg/4-batch chunks
# timed out repeatedly 2026-05-30). We loop these short, safe calls in Python until
# the target is reached; each batch commits server-side, so every call is durable
# and resumable. A pathological single batch >300s just defers to the next tick.
CHUNK_MESSAGES = int(os.environ.get("SUMMARIZE_CHUNK", "50"))
HTTP_TIMEOUT = 300.0

# How long to wait for an in-flight kg_ingest to finish before proceeding anyway.
# Summaries are higher priority — we always proceed after this bound.
KG_INGEST_WAIT_SECONDS = 90

ENTITY_CONFIGS = [
    {"name": "lyra", "pps_url": "http://localhost:8201", "token_file": "entities/lyra/.entity_token"},
    {"name": "caia", "pps_url": "http://localhost:8211", "token_file": "entities/caia/.entity_token"},
]


def get_token(token_file: str) -> str:
    """Read entity token from .entity_token file."""
    token_path = PROJECT_ROOT / token_file
    try:
        return token_path.read_text().strip()
    except FileNotFoundError:
        return ""


# ─────────────────────────────────────────────
# Summarization
# ─────────────────────────────────────────────

async def check_unsummarized_count(client: httpx.AsyncClient, pps_url: str, token: str) -> int:
    """Check how many unsummarized messages an entity has."""
    resp = await client.get(
        f"{pps_url}/tools/summary_stats",
        params={"token": token},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    # summary_stats returns "unsummarized_messages" (not "unsummarized_count")
    return data.get("unsummarized_messages", 0)


async def run_summarize(
    client: httpx.AsyncClient, pps_url: str, token: str, entity_name: str, target: int
) -> dict:
    """
    Call the summarize_messages endpoint for ONE bounded chunk.

    `target` is the per-call target_unsummarized — the server loops batch-by-batch
    until the backlog reaches it, committing each batch. We pick `target` so the
    call drains at most CHUNK_MESSAGES and stays under HTTP_TIMEOUT. Server drives
    the NUC LLM internally.
    """
    resp = await client.post(
        f"{pps_url}/tools/summarize_messages",
        json={
            "token": token,
            "limit": BATCH_LIMIT,
            "target_unsummarized": target,
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def wait_for_kg_ingest(timeout: int = KG_INGEST_WAIT_SECONDS) -> bool:
    """
    Spin-wait for any in-flight kg_ingest to release its lock.

    Returns True if kg_ingest cleared within the timeout, False if we gave up.
    Caller proceeds either way — summaries are higher priority.
    """
    deadline = time.monotonic() + timeout
    poll_interval = 5  # seconds between checks

    while is_lock_held(KG_INGEST_LOCK):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        log(
            f"Waiting for kg_ingest to finish (up to {remaining:.0f}s remaining)..."
        )
        time.sleep(min(poll_interval, remaining))

    return True


async def process_entity(entity: dict) -> None:
    name = entity["name"]
    pps_url = entity["pps_url"]
    token = get_token(entity["token_file"])

    if not token:
        log(f"[{name}] WARNING: No token found at {entity['token_file']}, skipping")
        return

    async with httpx.AsyncClient() as client:
        # Check current backlog
        try:
            count = await check_unsummarized_count(client, pps_url, token)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            log(f"[{name}] PPS server unreachable at {pps_url}, skipping")
            return
        except Exception as e:
            log(f"[{name}] ERROR checking backlog: {e}")
            return

        if count <= SUMMARIZE_THRESHOLD:
            # Silent skip — healthy
            return

        log(f"[{name}] Backlog: {count} unsummarized (threshold: {SUMMARIZE_THRESHOLD}). Running summarizer...")

        # Edge case A: kg_ingest may be mid-run — wait for it to clear before
        # we drive the NUC hard.  We proceed after KG_INGEST_WAIT_SECONDS even
        # if it hasn't cleared, because summaries take priority.
        cleared = wait_for_kg_ingest()
        if not cleared:
            log(
                f"[{name}] kg_ingest did not clear within {KG_INGEST_WAIT_SECONDS}s "
                "— proceeding anyway (summarizer has NUC priority)"
            )

        # Acquire the summarizer lock for the whole drain loop.
        # try/finally inside NucLock.__exit__ ensures the lock is always released.
        with NucLock(SUMMARIZER_LOCK, log_fn=log):
            t0 = time.monotonic()
            remaining = count
            total_summaries = 0

            # Drain in bounded chunks: each HTTP call targets at most CHUNK_MESSAGES
            # of progress so it stays under HTTP_TIMEOUT. The server commits every
            # batch, so each call is independently durable and resumable. Loop until
            # we reach TARGET_UNSUMMARIZED or a call makes no progress (NUC down /
            # nothing summarizable → avoid an infinite loop).
            while remaining > TARGET_UNSUMMARIZED:
                per_call_target = max(TARGET_UNSUMMARIZED, remaining - CHUNK_MESSAGES)
                try:
                    result = await run_summarize(
                        client, pps_url, token, name, per_call_target
                    )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 503:
                        log(f"[{name}] NUC LLM unavailable (503) — stopping (committed {total_summaries} summaries so far)")
                    else:
                        log(f"[{name}] ERROR: HTTP {e.response.status_code} from PPS — stopping (committed {total_summaries} summaries so far)")
                    break
                except (httpx.ReadTimeout, httpx.ConnectTimeout):
                    # A chunk should fit under HTTP_TIMEOUT; if it times out the
                    # server is slow but still committing batches. Stop this cycle;
                    # next tick resumes from the committed state.
                    log(f"[{name}] chunk timed out (NUC slow) — stopping; next cycle resumes (committed {total_summaries} summaries so far)")
                    break
                except Exception as e:
                    log(f"[{name}] ERROR during summarization: {e} — stopping (committed {total_summaries} summaries so far)")
                    break

                new_remaining = result.get("remaining", remaining)
                total_summaries += result.get("summaries_created", 0)

                if new_remaining >= remaining:
                    # No forward progress (nothing summarizable / server stuck) —
                    # bail rather than spin.
                    log(f"[{name}] no progress (remaining={new_remaining}) — stopping")
                    break
                remaining = new_remaining

            elapsed = time.monotonic() - t0
            log(
                f"[{name}] Done in {elapsed:.1f}s: {total_summaries} summaries created, "
                f"{remaining} unsummarized remaining (target {TARGET_UNSUMMARIZED})"
            )


async def main() -> None:
    log("summarize_daemon starting")
    t0 = time.monotonic()

    for entity in ENTITY_CONFIGS:
        await process_entity(entity)

    elapsed = time.monotonic() - t0
    log(f"summarize_daemon done in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
