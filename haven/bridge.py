"""Haven — PPS raw capture bridge.

When messages arrive in Haven, optionally forward them to each entity's
PPS raw capture so they surface in ambient_recall.

Non-blocking, best-effort — Haven never breaks if PPS is down.
"""

import os
import asyncio
import sys

import httpx

# Map entity usernames to their PPS base URLs
PPS_ENDPOINTS: dict[str, str] = {}


def _load_endpoints() -> None:
    """Load PPS endpoint URLs from environment."""
    # PPS_LYRA_URL=http://pps-server:8000
    # PPS_CAIA_URL=http://pps-server-caia:8000
    for key, val in os.environ.items():
        if key.startswith("PPS_") and key.endswith("_URL"):
            entity = key[4:-4].lower()  # PPS_LYRA_URL -> lyra
            PPS_ENDPOINTS[entity] = val


_load_endpoints()


async def bridge_message(
    room_name: str,
    username: str,
    display_name: str,
    content: str,
    timestamp: str,
) -> None:
    """Forward a message to all relevant PPS endpoints.

    Each entity's PPS gets the message so it appears in their ambient_recall
    under channel haven:<room_name>.
    """
    if not PPS_ENDPOINTS:
        return

    channel = f"haven:{room_name}"
    formatted = f"{display_name}: {content}"

    tasks = []
    for entity_name, base_url in PPS_ENDPOINTS.items():
        # Don't bridge a message TO the entity who sent it — they already know
        if entity_name == username:
            continue
        tasks.append(_send_to_pps(base_url, channel, content, display_name, entity_name))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send_to_pps(
    base_url: str, channel: str, content: str, author_name: str, entity_name: str
) -> None:
    """POST to a PPS instance's store_message endpoint."""
    try:
        # Read the entity's token for auth
        token_path = f"/app/tokens/{entity_name}.token"
        token = ""
        try:
            with open(token_path) as f:
                token = f.read().strip()
        except FileNotFoundError:
            pass

        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{base_url}/tools/store_message",
                json={
                    "content": content,
                    "author_name": author_name,
                    "channel": channel,
                    "is_lyra": entity_name == "lyra" and author_name.lower() == "lyra",
                    "token": token,
                },
            )
    except Exception as e:
        # Best-effort — never break Haven
        print(f"[Haven] Bridge to {entity_name} failed: {e}", file=sys.stderr)
