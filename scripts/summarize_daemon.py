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


async def run_summarize(client: httpx.AsyncClient, pps_url: str, token: str, entity_name: str) -> dict:
    """Call the summarize_messages endpoint. Server drives LLM internally."""
    resp = await client.post(
        f"{pps_url}/tools/summarize_messages",
        json={
            "token": token,
            "limit": BATCH_LIMIT,
            "target_unsummarized": TARGET_UNSUMMARIZED,
        },
        timeout=300.0,  # Allow up to 5 min for LLM calls
    )
    resp.raise_for_status()
    return resp.json()


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
        t0 = time.monotonic()

        try:
            result = await run_summarize(client, pps_url, token, name)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                log(f"[{name}] NUC LLM unavailable (503) — skipping this cycle")
            else:
                log(f"[{name}] ERROR: HTTP {e.response.status_code} from PPS")
            return
        except Exception as e:
            log(f"[{name}] ERROR during summarization: {e}")
            return

        elapsed = time.monotonic() - t0
        status = result.get("status", "unknown")

        if status == "completed":
            log(
                f"[{name}] Done in {elapsed:.1f}s: "
                f"{result.get('summarized_count', 0)} messages → "
                f"{result.get('summaries_created', 0)} summaries, "
                f"{result.get('remaining', '?')} remaining"
            )
        else:
            log(f"[{name}] WARNING: status={status}, result={json.dumps(result)}")


async def main() -> None:
    log("summarize_daemon starting")
    t0 = time.monotonic()

    for entity in ENTITY_CONFIGS:
        await process_entity(entity)

    elapsed = time.monotonic() - t0
    log(f"summarize_daemon done in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
