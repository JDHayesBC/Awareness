"""Boot-time context prefetch shared by Haven's bot and EntityBrain (GH #262, #363 step 0).

Hard-Python fetch of identity.md, current_scene.md and PPS ambient_recall("startup")
so a freshly-warmed channel has cross-channel context whether or not the model
follows model-interpreted warmup steps. Moved verbatim out of haven/bot.py so both
callers run one code path.

Never raises: every piece degrades independently (missing file, PPS down, bad
status) and a total failure returns "" so callers fall back to the model-side
warmup steps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

BOOT_CONTEXT_HEADER = (
    "[BOOT CONTEXT — pre-fetched by Python, no tool calls needed for these sections]\n\n"
)


async def fetch_boot_context(
    *,
    entity_name: str,
    entity_path: Path,
    pps_http_url: str,
    entity_token: str,
    channel: str,
    consumer_key: str,
) -> str:
    """Pre-fetch boot-time identity context via direct Python calls.

    Fetches identity.md, current_scene.md, and PPS ambient_recall(startup).
    active_agency_framework.md is intentionally omitted (801 lines; the model can
    Read it, and the CLAUDE.md kernel already loads the essentials).

    Returns a formatted string ready to inline into a warmup prompt, or "" when
    nothing could be fetched.
    """
    sections: list[str] = []

    # 1. identity.md — synchronous read
    try:
        identity_text = (Path(entity_path) / "identity.md").read_text(encoding="utf-8").strip()
        sections.append(f"## {entity_name.capitalize()}'s identity.md\n\n{identity_text}")
    except Exception as e:
        print(f"[{entity_name}] Boot ctx: identity.md unreadable: {e}", file=sys.stderr)

    # 2. current_scene.md — synchronous read
    try:
        scene_text = (Path(entity_path) / "current_scene.md").read_text(encoding="utf-8").strip()
        if scene_text:
            sections.append(f"## Current scene\n\n{scene_text}")
    except Exception as e:
        print(f"[{entity_name}] Boot ctx: current_scene.md unreadable: {e}", file=sys.stderr)

    # 3. PPS ambient_recall(startup) — full cross-channel reconstruction
    if pps_http_url:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{pps_http_url}/tools/ambient_recall",
                    json={
                        "context": "startup",
                        "token": entity_token,
                        "channel": channel,
                        "consumer_key": consumer_key,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    ctx = data.get("formatted_context", "")
                    if ctx:
                        sections.append(f"## PPS ambient_recall (startup)\n\n{ctx}")
                    else:
                        print(f"[{entity_name}] Boot ctx: ambient_recall returned empty", file=sys.stderr)
                else:
                    print(
                        f"[{entity_name}] Boot ctx: ambient_recall HTTP {resp.status_code}",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"[{entity_name}] Boot ctx: ambient_recall failed: {e}", file=sys.stderr)

    if not sections:
        return ""
    return BOOT_CONTEXT_HEADER + "\n\n---\n\n".join(sections)
