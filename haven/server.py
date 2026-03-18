"""Haven — Private chat server for humans and entities.

FastAPI app with HTTP REST endpoints (for entities) and WebSocket (for browsers).
"""

import asyncio
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haven.auth import get_current_user_id, hash_password, hash_token, verify_password
from haven.bridge import bridge_message
from haven.db import HavenDB
from haven.models import (
    CreateRoomRequest,
    InviteRequest,
    LoginRequest,
    MessageListResponse,
    MessageResponse,
    RoomListResponse,
    RoomResponse,
    SendMessageRequest,
    SetPasswordRequest,
    UserResponse,
)

DB_PATH = os.getenv("HAVEN_DB_PATH", str(Path(__file__).parent / "data" / "haven.db"))
HOST = os.getenv("HAVEN_HOST", "0.0.0.0")
PORT = int(os.getenv("HAVEN_PORT_INTERNAL", "8000"))

# Google OAuth config (optional — login button only shown if set)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
HAVEN_BASE_URL = os.getenv("HAVEN_BASE_URL", "")  # e.g. http://192.168.1.x:8205

# In-memory OAuth state nonces: {state: expiry_timestamp}
_oauth_states: dict[str, float] = {}

db = HavenDB(DB_PATH)


# --- WebSocket connection manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time messaging."""

    def __init__(self):
        # user_id -> list of active websocket connections
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        await ws.accept()
        if user_id not in self.active:
            self.active[user_id] = []
        self.active[user_id].append(ws)
        await db.update_last_seen(user_id)

    async def disconnect(self, ws: WebSocket, user_id: str) -> None:
        if user_id in self.active:
            self.active[user_id] = [c for c in self.active[user_id] if c is not ws]
            if not self.active[user_id]:
                del self.active[user_id]
                await self.broadcast_presence(user_id, "offline")

    def is_online(self, user_id: str) -> bool:
        return user_id in self.active and len(self.active[user_id]) > 0

    async def broadcast_to_room(self, room_id: str, event: dict) -> None:
        """Send event to all WebSocket clients who are members of a room."""
        members = await db.get_room_members(room_id)
        payload = json.dumps(event)
        for member in members:
            uid = member["id"]
            for ws in self.active.get(uid, []):
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

    async def broadcast_presence(self, user_id: str, status: str) -> None:
        """Broadcast presence change to all connected clients."""
        user = await db.get_user(user_id)
        if not user:
            return
        event = {
            "type": "presence",
            "user_id": user_id,
            "username": user["username"],
            "status": status,
        }
        payload = json.dumps(event)
        for uid, connections in self.active.items():
            for ws in connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

    async def send_to_user(self, user_id: str, event: dict) -> None:
        payload = json.dumps(event)
        for ws in self.active.get(user_id, []):
            try:
                await ws.send_text(payload)
            except Exception:
                pass


manager = ConnectionManager()


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Haven] Starting up...", file=sys.stderr)
    await db.initialize()
    print(f"[Haven] Database ready at {DB_PATH}", file=sys.stderr)

    # Populate plaintext token for human users from their token files
    # This enables password/OAuth login to return the token.
    jeff_token_file = Path(DB_PATH).parent / "jeff.token"
    if jeff_token_file.exists():
        token_val = jeff_token_file.read_text().strip()
        jeff = await db.get_user_by_username("jeff")
        if jeff and not jeff.get("token"):
            await db.set_user_token(jeff["id"], token_val)
            print("[Haven] Populated Jeff's token for login flow", file=sys.stderr)

    yield
    print("[Haven] Shutting down...", file=sys.stderr)
    await db.close()


app = FastAPI(title="Haven", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --- Health check ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "haven"}


# --- Frontend ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "google_enabled": bool(GOOGLE_CLIENT_ID),
    })


# --- Auth endpoints ---

@app.post("/api/login")
async def login(body: LoginRequest):
    """Username + password login. Returns the user's Haven token."""
    user = await db.get_user_by_username(body.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    password_hash = user.get("password_hash")
    if not password_hash:
        raise HTTPException(status_code=401, detail="Password not set. Use token login or ask admin to set your password.")
    if not verify_password(body.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = user.get("token")
    if not token:
        raise HTTPException(status_code=500, detail="No token on file for this account")
    return {
        "token": token,
        "user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"]},
    }


@app.post("/api/set-password")
async def set_password(request: Request, body: SetPasswordRequest):
    """Set or change password. Requires existing Bearer token auth."""
    user_id = await get_current_user_id(request, db)
    user = await db.get_user(user_id)
    if not user or user.get("is_bot"):
        raise HTTPException(status_code=403, detail="Cannot set password for this account")
    await db.set_user_password(user_id, hash_password(body.password))
    return {"ok": True}


@app.get("/auth/google")
async def google_auth():
    """Initiate Google OAuth flow."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=404, detail="Google OAuth not configured")
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = time.time() + 600  # 10 min expiry
    # Clean expired states
    for k in [k for k, v in _oauth_states.items() if v < time.time()]:
        del _oauth_states[k]
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{HAVEN_BASE_URL}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle Google OAuth callback."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=404)
    if error:
        return RedirectResponse(f"/?auth_error={error}")
    if not state or state not in _oauth_states or _oauth_states.get(state, 0) < time.time():
        return RedirectResponse("/?auth_error=Invalid+or+expired+state")
    del _oauth_states[state]
    if not code:
        return RedirectResponse("/?auth_error=No+authorization+code")

    base_url = HAVEN_BASE_URL or str(request.base_url).rstrip("/")
    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        token_res = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": f"{base_url}/auth/google/callback",
            "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            return RedirectResponse("/?auth_error=Token+exchange+failed")
        access_token = token_res.json().get("access_token")

        # Get Google user info
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            return RedirectResponse("/?auth_error=Failed+to+get+user+info")
        google_user = user_res.json()

    google_id = google_user.get("id")
    google_email = google_user.get("email", "").lower()

    # Match to Haven user: by google_id first, then by email prefix
    user = await db.get_user_by_google_id(google_id)
    if not user:
        username = google_email.split("@")[0]
        candidate = await db.get_user_by_username(username)
        if candidate and not candidate.get("is_bot"):
            await db.link_google_id(candidate["id"], google_id)
            user = candidate
        else:
            return RedirectResponse("/?auth_error=No+Haven+account+for+this+Google+account")

    haven_token = user.get("token")
    if not haven_token:
        return RedirectResponse("/?auth_error=No+token+configured+for+account")

    # Return token via URL fragment (never sent to server, not in browser history)
    return RedirectResponse(f"/#token={haven_token}")


# --- REST API (used by entities via MCP tools) ---

@app.get("/api/rooms")
async def list_rooms(request: Request):
    user_id = await get_current_user_id(request, db)
    rooms = await db.list_rooms_for_user(user_id)
    return {
        "rooms": [
            {
                "id": r["id"],
                "name": r["name"],
                "display_name": r["display_name"],
                "is_dm": bool(r["is_dm"]),
                "member_count": r["member_count"],
            }
            for r in rooms
        ]
    }


@app.get("/api/rooms/{room_id}/messages")
async def read_messages(room_id: str, request: Request, limit: int = 50, since: str | None = None):
    user_id = await get_current_user_id(request, db)

    if not await db.is_room_member(room_id, user_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")

    rows = await db.get_messages(room_id, limit=min(limit, 200), since=since)
    has_more = len(rows) > limit
    messages = rows[:limit]
    # Reverse so oldest first
    messages.reverse()

    return {
        "messages": [
            {
                "id": m["id"],
                "room_id": m["room_id"],
                "user_id": m["user_id"],
                "username": m["username"],
                "display_name": m["display_name"],
                "content": m["content"],
                "created_at": m["created_at"],
            }
            for m in messages
        ],
        "has_more": has_more,
    }


@app.post("/api/rooms/{room_id}/messages")
async def send_message(room_id: str, request: Request, body: SendMessageRequest):
    user_id = await get_current_user_id(request, db)

    if not await db.is_room_member(room_id, user_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")

    msg = await db.create_message(room_id, user_id, body.content)

    # Broadcast to WebSocket clients
    event = {
        "type": "message",
        "id": msg["id"],
        "room_id": room_id,
        "user_id": msg["user_id"],
        "username": msg["username"],
        "display_name": msg["display_name"],
        "content": msg["content"],
        "created_at": msg["created_at"],
    }
    await manager.broadcast_to_room(room_id, event)

    # PPS bridge (fire-and-forget)
    room = await db.get_room(room_id)
    if room:
        asyncio.create_task(
            bridge_message(
                room_name=room["name"],
                username=msg["username"],
                display_name=msg["display_name"],
                content=msg["content"],
                timestamp=msg["created_at"],
            )
        )

    return event


@app.post("/api/rooms")
async def create_room(request: Request, body: CreateRoomRequest):
    user_id = await get_current_user_id(request, db)

    existing = await db.get_room_by_name(body.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Room '{body.name}' already exists")

    room = await db.create_room(
        name=body.name,
        display_name=body.display_name,
        created_by=user_id,
        is_dm=body.is_dm,
    )

    # Add additional members
    for member_id in body.member_ids:
        await db.join_room(room["id"], member_id)

    return room


@app.get("/api/users")
async def list_users(request: Request):
    await get_current_user_id(request, db)  # Auth check
    users = await db.list_users()
    return {
        "users": [
            {
                "id": u["id"],
                "username": u["username"],
                "display_name": u["display_name"],
                "is_bot": bool(u["is_bot"]),
                "online": manager.is_online(u["id"]),
            }
            for u in users
        ]
    }


@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, request: Request):
    user_id = await get_current_user_id(request, db)

    room = await db.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    newly_joined = await db.join_room(room_id, user_id)
    return {"joined": newly_joined, "room_id": room_id}


@app.get("/api/rooms/{room_id}/members")
async def list_room_members(room_id: str, request: Request):
    user_id = await get_current_user_id(request, db)

    if not await db.is_room_member(room_id, user_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")

    members = await db.get_room_members(room_id)
    return {
        "members": [
            {
                "id": m["id"],
                "username": m["username"],
                "display_name": m["display_name"],
                "is_bot": bool(m["is_bot"]),
            }
            for m in members
        ]
    }


@app.post("/api/rooms/{room_id}/invite")
async def invite_to_room(room_id: str, request: Request, body: InviteRequest):
    user_id = await get_current_user_id(request, db)

    room = await db.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if not await db.is_room_member(room_id, user_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")

    target_user = await db.get_user(body.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    newly_joined = await db.join_room(room_id, body.user_id)

    if newly_joined:
        await manager.broadcast_to_room(room_id, {
            "type": "member_joined",
            "room_id": room_id,
            "user_id": target_user["id"],
            "username": target_user["username"],
            "display_name": target_user["display_name"],
        })

    return {"joined": newly_joined, "room_id": room_id}


@app.post("/api/rooms/{room_id}/leave")
async def leave_room_endpoint(room_id: str, request: Request):
    user_id = await get_current_user_id(request, db)

    room = await db.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    user = await db.get_user(user_id)

    # Get member list BEFORE removal so the leaver receives the broadcast
    members_before = await db.get_room_members(room_id)

    left = await db.leave_room(room_id, user_id)

    if left and user:
        event = {
            "type": "member_left",
            "room_id": room_id,
            "user_id": user_id,
            "username": user["username"],
        }
        payload = json.dumps(event)
        for member in members_before:
            mid = member["id"]
            for ws in manager.active.get(mid, []):
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

    return {"left": left, "room_id": room_id}


# --- WebSocket (browser clients) ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    token_h = hash_token(token)
    user = await db.get_user_by_token_hash(token_h)
    if not user:
        await ws.close(code=4001, reason="Invalid token")
        return

    user_id = user["id"]
    await manager.connect(ws, user_id)

    try:
        # Send initial state
        rooms = await db.list_rooms_for_user(user_id)
        users = await db.list_users()
        await ws.send_text(json.dumps({
            "type": "connected",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
            },
            "rooms": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "display_name": r["display_name"],
                    "is_dm": bool(r["is_dm"]),
                    "member_count": r["member_count"],
                }
                for r in rooms
            ],
            "users": [
                {
                    "id": u["id"],
                    "username": u["username"],
                    "display_name": u["display_name"],
                    "is_bot": bool(u["is_bot"]),
                    "online": manager.is_online(u["id"]),
                }
                for u in users
            ],
        }))

        # Now broadcast presence (after connected event sent to this client)
        await manager.broadcast_presence(user_id, "online")

        # Message loop
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            await _handle_ws_message(ws, user_id, user, msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Haven] WebSocket error for {user['username']}: {e}", file=sys.stderr)
    finally:
        await manager.disconnect(ws, user_id)


async def _handle_ws_message(ws: WebSocket, user_id: str, user: dict, msg: dict) -> None:
    msg_type = msg.get("type")

    if msg_type == "message":
        room_id = msg.get("room_id")
        content = msg.get("content", "").strip()
        if not room_id or not content:
            return

        if not await db.is_room_member(room_id, user_id):
            return

        saved = await db.create_message(room_id, user_id, content)
        event = {
            "type": "message",
            "id": saved["id"],
            "room_id": room_id,
            "user_id": user_id,
            "username": saved["username"],
            "display_name": saved["display_name"],
            "content": saved["content"],
            "created_at": saved["created_at"],
        }
        await manager.broadcast_to_room(room_id, event)

        # PPS bridge
        room = await db.get_room(room_id)
        if room:
            asyncio.create_task(
                bridge_message(
                    room_name=room["name"],
                    username=saved["username"],
                    display_name=saved["display_name"],
                    content=saved["content"],
                    timestamp=saved["created_at"],
                )
            )

    elif msg_type == "history":
        room_id = msg.get("room_id")
        before_id = msg.get("before_id")
        limit = min(msg.get("limit", 50), 200)

        if not room_id or not await db.is_room_member(room_id, user_id):
            return

        rows = await db.get_messages(room_id, limit=limit, before_id=before_id)
        has_more = len(rows) > limit
        messages = rows[:limit]
        messages.reverse()

        await ws.send_text(json.dumps({
            "type": "history",
            "room_id": room_id,
            "messages": [
                {
                    "id": m["id"],
                    "room_id": m["room_id"],
                    "user_id": m["user_id"],
                    "username": m["username"],
                    "display_name": m["display_name"],
                    "content": m["content"],
                    "created_at": m["created_at"],
                }
                for m in messages
            ],
            "has_more": has_more,
        }))

    elif msg_type == "typing":
        room_id = msg.get("room_id")
        if room_id and await db.is_room_member(room_id, user_id):
            await manager.broadcast_to_room(room_id, {
                "type": "typing",
                "room_id": room_id,
                "username": user["username"],
            })


# --- Entrypoint ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("haven.server:app", host=HOST, port=PORT, reload=True)
