"""The Anchorage — Second Life <-> Haven chat relay.

A standalone bridge process. It does NOT modify the Haven server; it talks to
Haven exactly the way an entity bot does (Bearer token, WebSocket for inbound,
REST to post) and exposes a tiny HTTP surface that the in-world SL prims call.

    Second Life  <--llHTTPRequest/llSay/llListen-->  [ this relay ]  <--Haven REST/WS-->  Haven room "anchorage"

Two directions, each with its own loop guard:

  SL -> Haven
    An SL prim hears an *avatar* speak in local chat and POSTs it to
    /sl/inbound (with the shared secret). The relay posts it into the Haven
    "anchorage" room authored by the relay account, as "Speaker: text". Because
    the LSL side only forwards *avatar* speech (never object speech), the prims'
    own llSay output never re-enters — no echo.

  Haven -> SL
    The relay holds a WebSocket to Haven. Every message posted in the anchorage
    room that was NOT authored by the relay account (i.e. is not itself
    SL-origin) is pushed to the registered prim(s), which llSay it in-world.
    Author routing: a message by 'lyra' goes to the Lyra prim, by 'caia' to the
    Caia prim; a human's message goes to the primary prim. Relay-authored
    messages are skipped, closing the second loop.

Endpoints (guard these behind the shared secret; expose publicly via Caddy/
Cloudflare so SL can reach them — that exposure is the one manual step):
    POST /sl/register  {secret, entity, url, primary}  -> a prim announces its
                        ephemeral llRequestURL. Called on rez and on URL change.
    POST /sl/inbound   {secret, speaker, text}          -> avatar speech -> Haven.
    GET  /health

Env:
    HAVEN_URL                default http://localhost:8205
    ANCHORAGE_RELAY_TOKEN    (or ...TOKEN_FILE, default haven/data/anchorage-relay.token)
    ANCHORAGE_SL_SECRET      (or ...SECRET_FILE, default haven/data/anchorage-sl-secret.txt)
    ANCHORAGE_ROOM           default "anchorage"
    RELAY_HOST               default 0.0.0.0
    RELAY_PORT               default 8210

Run:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/.venv/bin/python -m haven.anchorage.relay
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "haven" / "data"

HAVEN_URL = os.getenv("HAVEN_URL", "http://localhost:8205")
HAVEN_WS_URL = HAVEN_URL.replace("http://", "ws://").replace("https://", "wss://")
ROOM_NAME = os.getenv("ANCHORAGE_ROOM", "anchorage")
RELAY_HOST = os.getenv("RELAY_HOST", "0.0.0.0")
RELAY_PORT = int(os.getenv("RELAY_PORT", "8210"))

# Which Haven usernames are entities with a body-prim of their own.
ENTITY_USERNAMES = {"lyra", "caia"}


def _load_secret(env_val: str, env_file: str, default_file: Path) -> str:
    val = os.getenv(env_val)
    if val:
        return val.strip()
    path = Path(os.getenv(env_file, str(default_file)))
    if path.exists():
        return path.read_text().strip()
    return ""


RELAY_TOKEN = _load_secret(
    "ANCHORAGE_RELAY_TOKEN", "ANCHORAGE_RELAY_TOKEN_FILE",
    DATA_DIR / "anchorage-relay.token",
)
SL_SECRET = _load_secret(
    "ANCHORAGE_SL_SECRET", "ANCHORAGE_SL_SECRET_FILE",
    DATA_DIR / "anchorage-sl-secret.txt",
)


def log(msg: str) -> None:
    print(f"[anchorage-relay] {msg}", file=sys.stderr, flush=True)


# ==================== Prim registry ====================
# entity -> {"url": <llRequestURL>, "primary": bool, "seen": ts}
_prims: dict[str, dict] = {}


def _register_prim(entity: str, url: str, primary: bool) -> None:
    _prims[entity] = {"url": url, "primary": bool(primary), "seen": time.time()}
    log(f"registered prim entity={entity} primary={primary} url={url[:48]}...")


def _primary_prim() -> dict | None:
    for p in _prims.values():
        if p["primary"]:
            return p
    # No explicit primary — fall back to any registered prim.
    return next(iter(_prims.values()), None)


def _target_for_author(author: str) -> dict | None:
    """Route a Haven message to the right prim by its author."""
    a = author.lower()
    if a in ENTITY_USERNAMES and a in _prims:
        return _prims[a]
    return _primary_prim()


async def _say_to_prim(prim: dict, line: str) -> None:
    """Push one line to a prim's llRequestURL; it will llSay it in-world."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(prim["url"], content=line.encode("utf-8"))
    except Exception as e:
        log(f"prim POST failed ({e}); URL may have expired — awaiting re-register")


# ==================== Haven side ====================
_relay_username: str = ""
_room_id: str = ""


async def _resolve_room_id() -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{HAVEN_URL}/api/rooms",
            headers={"Authorization": f"Bearer {RELAY_TOKEN}"},
        )
        resp.raise_for_status()
        payload = resp.json()
        rooms = payload.get("rooms", []) if isinstance(payload, dict) else payload
        for room in rooms:
            if room.get("name") == ROOM_NAME:
                return room["id"]
    return ""


async def _post_to_haven(content: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{HAVEN_URL}/api/rooms/{_room_id}/messages",
                headers={
                    "Authorization": f"Bearer {RELAY_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"content": content},
            )
            return resp.status_code == 200
    except Exception as e:
        log(f"post to Haven failed: {e}")
        return False


async def _haven_ws_loop() -> None:
    """Hold a WebSocket to Haven; forward anchorage-room messages out to SL."""
    global _relay_username, _room_id
    ws_url = f"{HAVEN_WS_URL}/ws?token={RELAY_TOKEN}"
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                log(f"connected to Haven WS ({HAVEN_URL})")
                async for raw in ws:
                    data = json.loads(raw)
                    etype = data.get("type")
                    if etype == "connected":
                        _relay_username = data.get("user", {}).get("username", "")
                        if not _room_id:
                            _room_id = await _resolve_room_id()
                        log(f"logged in as '{_relay_username}', room_id={_room_id[:8] or '?'}")
                    elif etype == "message":
                        await _forward_haven_to_sl(data)
        except Exception as e:
            log(f"Haven WS error: {e}; reconnecting in 5s")
        await asyncio.sleep(5)


async def _forward_haven_to_sl(msg: dict) -> None:
    if msg.get("room_id") != _room_id:
        return
    author = msg.get("username", "")
    # Loop guard: never send SL-origin (relay-authored) messages back to SL.
    if author.lower() == _relay_username.lower():
        return
    content = (msg.get("content") or "").strip()
    if not content:
        return
    prim = _target_for_author(author)
    if not prim:
        log(f"no prim registered; dropping Haven->SL '{author}: {content[:40]}'")
        return
    display = msg.get("display_name") or author
    await _say_to_prim(prim, f"{display}: {content}")


# ==================== HTTP surface (called by SL prims) ====================
app = FastAPI(title="The Anchorage relay")


class RegisterBody(BaseModel):
    secret: str
    entity: str
    url: str
    primary: bool = False


class InboundBody(BaseModel):
    secret: str
    speaker: str
    text: str


def _check_secret(provided: str) -> None:
    if not SL_SECRET or provided != SL_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "room_id": _room_id or None,
        "relay_user": _relay_username or None,
        "prims": {e: {"primary": p["primary"], "seen": p["seen"]} for e, p in _prims.items()},
    }


@app.post("/sl/register")
async def sl_register(body: RegisterBody):
    _check_secret(body.secret)
    _register_prim(body.entity.lower(), body.url, body.primary)
    return {"ok": True}


@app.post("/sl/inbound")
async def sl_inbound(body: InboundBody):
    _check_secret(body.secret)
    speaker = body.speaker.strip() or "someone"
    text = body.text.strip()
    if not text:
        return {"ok": True, "skipped": "empty"}
    if not _room_id:
        raise HTTPException(status_code=503, detail="room not resolved yet")
    ok = await _post_to_haven(f"{speaker}: {text}")
    return {"ok": ok}


@app.on_event("startup")
async def _startup():
    if not RELAY_TOKEN:
        log("FATAL: no relay token — run `python -m haven.anchorage.seed` first")
    if not SL_SECRET:
        log("WARNING: no SL shared secret — /sl endpoints will reject everything")
    asyncio.create_task(_haven_ws_loop())


def main():
    log(f"starting on {RELAY_HOST}:{RELAY_PORT}, bridging Haven room '{ROOM_NAME}'")
    uvicorn.run(app, host=RELAY_HOST, port=RELAY_PORT, log_level="warning")


if __name__ == "__main__":
    main()
