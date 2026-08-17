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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haven.auth import get_current_user_id, hash_password, hash_token, verify_password
import haven.bridge as bridge
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
    TypingRequest,
    UserResponse,
)

# --- Web push (VAPID) config ---
# These must be set in the environment to enable push notifications.
# If unset, the feature is a clean no-op: endpoints return 503 and no pushes
# are ever attempted. No secrets are ever written to disk.
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "")  # e.g. "mailto:admin@example.com"
PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and VAPID_SUBJECT)

# Lazy import: pywebpush is optional at import time — if it fails to import
# (e.g. not yet installed in the running container), push stays disabled.
_webpusher = None
if PUSH_ENABLED:
    try:
        from pywebpush import webpush, WebPushException
        _webpusher = webpush  # store the callable for use in helpers
    except ImportError:
        print(
            "[Haven] WARNING: VAPID env vars set but pywebpush not installed — "
            "push disabled. Add pywebpush to requirements.txt and rebuild.",
            file=sys.stderr,
        )
        PUSH_ENABLED = False

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
    if PUSH_ENABLED:
        print("[Haven] Web push enabled (VAPID configured)", file=sys.stderr)
    else:
        print("[Haven] Web push disabled (VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY/VAPID_SUBJECT not set)", file=sys.stderr)

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

# Shared-images dir: where the share-image endpoint stores uploads. Served
# statically at /shared-images/<entity>/<file>. Defaults next to the DB so it
# lives in the persistent data volume (not the ephemeral image filesystem).
SHARED_IMAGES_DIR = Path(
    os.getenv("HAVEN_SHARED_IMAGES_DIR", str(Path(DB_PATH).parent / "shared_images"))
)
SHARED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/shared-images",
    StaticFiles(directory=str(SHARED_IMAGES_DIR)),
    name="shared-images",
)
MAX_SHARE_IMAGE_BYTES = int(os.getenv("HAVEN_MAX_SHARE_IMAGE_BYTES", str(20 * 1024 * 1024)))
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# --- Health check ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "haven"}


# --- PWA: manifest + service worker (served at root so SW scope is "/") ---

@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(
        BASE_DIR / "static" / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    # Served from root (not /static) so the worker controls the whole app;
    # a /static/-served worker would be scoped to /static/ only.
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


# --- Push notification helpers ---

async def _send_push_to_offline_room_members(
    room_id: str,
    sender_user_id: str,
    sender_display_name: str,
    content: str,
) -> None:
    """Fan out a web push notification to room members who are NOT connected via WS.

    This is intentionally fail-safe: a push failure of any kind (including
    expired subscriptions and network errors) is caught, logged, and pruned if
    appropriate — it NEVER propagates up to break message delivery.
    """
    if not PUSH_ENABLED:
        return

    members = await db.get_room_members(room_id)
    # Only notify members who are offline (no active WS connection) and who
    # are not the sender — they don't need a push for their own message.
    offline_user_ids = [
        m["id"]
        for m in members
        if m["id"] != sender_user_id and not manager.is_online(m["id"])
    ]
    if not offline_user_ids:
        return

    subscriptions = await db.get_push_subscriptions_for_users(offline_user_ids)
    if not subscriptions:
        return

    # Truncate content preview to 120 chars to keep the notification snappy.
    preview = content[:120] + ("…" if len(content) > 120 else "")
    payload = json.dumps({
        "title": sender_display_name,
        "body": preview,
        "icon": "/static/icons/icon-192.png",
        "badge": "/static/icons/icon-192.png",
        "data": {"url": "/"},
    })

    from pywebpush import WebPushException  # always available when PUSH_ENABLED

    dead_endpoints: list[str] = []

    for sub in subscriptions:
        try:
            # webpush() is synchronous (uses requests internally); run it in a
            # thread pool so we don't block the event loop during network I/O.
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda s=sub: _webpusher(
                    subscription_info={
                        "endpoint": s["endpoint"],
                        "keys": {
                            "p256dh": s["p256dh"],
                            "auth": s["auth"],
                        },
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT},
                    content_encoding="aes128gcm",
                ),
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response else None
            if status in (404, 410):
                # Subscription is expired or unregistered on the push service —
                # prune it so we don't waste effort on dead endpoints.
                dead_endpoints.append(sub["endpoint"])
                print(
                    f"[Haven] push: pruning dead subscription {sub['endpoint'][:40]}... "
                    f"(HTTP {status})",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[Haven] push: delivery failed for {sub['endpoint'][:40]}... "
                    f"(WebPushException: {exc})",
                    file=sys.stderr,
                )
        except Exception as exc:
            # Any other error (network, timeout, etc.) — log and continue; never
            # let a push failure surface to the caller.
            print(
                f"[Haven] push: unexpected error for {sub['endpoint'][:40]}...: {exc}",
                file=sys.stderr,
            )

    # Prune dead subscriptions outside the loop so we don't mutate while iterating.
    for endpoint in dead_endpoints:
        try:
            await db.delete_push_subscription(endpoint)
        except Exception as exc:
            print(f"[Haven] push: failed to delete dead sub: {exc}", file=sys.stderr)


# --- Push API endpoints ---

@app.get("/api/push/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key for client-side subscription.

    Returns 503 when push is not configured — the client uses this to
    decide whether to show the "Enable notifications" button.
    """
    if not PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"publicKey": VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """Store a push subscription for the authenticated user.

    Expects JSON body matching the PushSubscription object from the browser:
      { "endpoint": "...", "keys": { "p256dh": "...", "auth": "..." } }
    """
    if not PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    user_id = await get_current_user_id(request, db)
    body = await request.json()

    endpoint = body.get("endpoint", "").strip()
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "").strip()
    auth = keys.get("auth", "").strip()

    if not endpoint or not p256dh or not auth:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: endpoint, keys.p256dh, keys.auth",
        )

    await db.add_push_subscription(user_id, endpoint, p256dh, auth)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    """Delete a push subscription by endpoint for the authenticated user."""
    if not PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    user_id = await get_current_user_id(request, db)
    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Missing endpoint")

    await db.delete_push_subscription(endpoint)
    return {"ok": True}


# --- Frontend ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "chat.html", {
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
                "image_url": m.get("image_url"),
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
        "image_url": msg.get("image_url"),
    }
    await manager.broadcast_to_room(room_id, event)

    # Web push: notify offline room members (fire-and-forget, fail-safe)
    asyncio.create_task(
        _send_push_to_offline_room_members(
            room_id=room_id,
            sender_user_id=user_id,
            sender_display_name=msg["display_name"],
            content=msg["content"],
        )
    )

    # PPS bridge (fire-and-forget)
    room = await db.get_room(room_id)
    if room:
        members = await db.get_room_members(room_id)
        member_entities = [m["username"].lower() for m in members if m["username"].lower() in bridge.PPS_ENDPOINTS]
        asyncio.create_task(
            bridge_message(
                room_name=room["name"],
                username=msg["username"],
                display_name=msg["display_name"],
                content=msg["content"],
                timestamp=msg["created_at"],
                member_entities=member_entities,
            )
        )

    return event


@app.post("/api/share-image")
async def share_image(
    request: Request,
    image: UploadFile = File(...),
    room: str = Form(...),
    caption: str = Form(""),
):
    """Share an image into a room as a message.

    Multipart form: image (file), room (room name OR id), caption (optional text).
    Returns the broadcast event. Image stored under shared_images/<entity>/<ts>.<ext>
    and exposed at /shared-images/<entity>/<file>.
    """
    user_id = await get_current_user_id(request, db)
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Resolve room: accept UUID room_id, slug name, or friendly display_name.
    room_obj = (
        await db.get_room(room)
        or await db.get_room_by_name(room)
        or await db.get_room_by_display_name(room)
    )
    if not room_obj:
        raise HTTPException(status_code=404, detail=f"Room not found: {room}")
    room_id = room_obj["id"]

    if not await db.is_room_member(room_id, user_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")

    # Validate file extension and size before reading the body fully.
    ext = Path(image.filename or "").suffix.lower() or ".png"
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image extension {ext}. Allowed: {sorted(ALLOWED_IMAGE_EXTS)}",
        )

    image_bytes = await image.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty image upload")
    if len(image_bytes) > MAX_SHARE_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {MAX_SHARE_IMAGE_BYTES // (1024 * 1024)} MB limit",
        )

    # Store under shared_images/<username>/<timestamp>.<ext>
    entity_dir = SHARED_IMAGES_DIR / user["username"]
    entity_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{ts}_{secrets.token_hex(4)}{ext}"
    file_path = entity_dir / filename
    file_path.write_bytes(image_bytes)

    image_url = f"/shared-images/{user['username']}/{filename}"

    # Caption may be empty — we still need a non-empty content for the schema,
    # so default to a single-character marker the renderer treats as image-only.
    content_text = caption.strip() if caption.strip() else " "

    msg = await db.create_message(room_id, user_id, content_text, image_url=image_url)

    event = {
        "type": "message",
        "id": msg["id"],
        "room_id": room_id,
        "user_id": msg["user_id"],
        "username": msg["username"],
        "display_name": msg["display_name"],
        "content": msg["content"],
        "created_at": msg["created_at"],
        "image_url": image_url,
    }
    await manager.broadcast_to_room(room_id, event)

    # PPS bridge — let entities see in their ambient that an image was shared.
    members = await db.get_room_members(room_id)
    member_entities = [m["username"].lower() for m in members if m["username"].lower() in bridge.PPS_ENDPOINTS]
    asyncio.create_task(
        bridge_message(
            room_name=room_obj["name"],
            username=msg["username"],
            display_name=msg["display_name"],
            content=f"[shared image: {image_url}] {content_text}",
            timestamp=msg["created_at"],
            member_entities=member_entities,
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


@app.post("/api/rooms/{room_id}/typing")
async def typing_indicator(room_id: str, body: TypingRequest):
    """Broadcast a typing indicator to all WebSocket clients in a room.

    No auth required — callers supply their username directly. Intended for
    terminal/REST clients that cannot maintain a WebSocket connection.
    """
    room = await db.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    await manager.broadcast_to_room(room_id, {
        "type": "typing",
        "room_id": room_id,
        "username": body.username,
    })
    return {"ok": True}


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


# --- DM shortcut ---

@app.post("/api/dm/{username}")
async def start_dm(request: Request, username: str):
    """Find or create a DM with the specified user."""
    user_id = await get_current_user_id(request, db)
    target = await db.get_user_by_username(username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself")

    room = await db.find_or_create_dm(user_id, target["id"])
    return room


# --- Admin endpoints ---

async def require_admin(request: Request) -> str:
    """Verify the requester is an admin. Returns user_id."""
    user_id = await get_current_user_id(request, db)
    if not await db.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Serve the admin console. Auth checked client-side via API calls."""
    return templates.TemplateResponse(request, "admin.html", {})


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """List all users with full details (admin only)."""
    await require_admin(request)
    users = await db.list_users()
    return {
        "users": [
            {
                "id": u["id"],
                "username": u["username"],
                "display_name": u["display_name"],
                "is_bot": bool(u["is_bot"]),
                "is_admin": bool(u.get("is_admin", 0)),
                "online": manager.is_online(u["id"]),
                "created_at": u.get("created_at", ""),
                "last_seen_at": u.get("last_seen_at", ""),
            }
            for u in users
        ]
    }


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    """Create a new user account (admin only). Returns the plaintext token."""
    await require_admin(request)
    body = await request.json()
    username = body.get("username", "").strip().lower()
    display_name = body.get("display_name", "").strip()
    is_bot = body.get("is_bot", False)

    if not username or not display_name:
        raise HTTPException(status_code=400, detail="username and display_name required")

    # Check if username exists
    existing = await db.get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{username}' already exists")

    # Generate token
    token = secrets.token_urlsafe(32)
    token_h = hash_token(token)

    user = await db.create_user(username, display_name, token_h, is_bot=is_bot)

    # Store plaintext token for admin visibility
    await db.set_user_token(user["id"], token)

    return {**user, "token": token}


@app.post("/api/admin/users/{user_id}/token")
async def admin_regenerate_token(request: Request, user_id: str):
    """Regenerate a user's token (admin only). Returns new plaintext token."""
    await require_admin(request)
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = secrets.token_urlsafe(32)
    token_h = hash_token(token)
    await db.regenerate_token(user_id, token_h)
    await db.set_user_token(user_id, token)

    return {"user_id": user_id, "token": token}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: str):
    """Delete a user (admin only)."""
    admin_id = await require_admin(request)
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    deleted = await db.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    return {"deleted": True, "user_id": user_id}


@app.post("/api/admin/users/{user_id}/password")
async def admin_reset_password(request: Request, user_id: str):
    """Reset a user's password (admin only)."""
    await require_admin(request)
    body = await request.json()
    password = body.get("password", "")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pw_hash = hash_password(password)
    await db.set_user_password(user_id, pw_hash)
    return {"user_id": user_id, "password_reset": True}


@app.post("/api/admin/users/{user_id}/admin")
async def admin_toggle_admin(request: Request, user_id: str):
    """Toggle admin status for a user (admin only)."""
    admin_id = await require_admin(request)
    body = await request.json()
    is_admin = body.get("is_admin", False)

    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.set_admin(user_id, is_admin)
    return {"user_id": user_id, "is_admin": is_admin}


@app.get("/api/admin/rooms")
async def admin_list_rooms(request: Request):
    """List all rooms (admin only)."""
    await require_admin(request)
    async with db._db.execute(
        "SELECT r.*, COUNT(rm.user_id) as member_count FROM rooms r LEFT JOIN room_members rm ON r.id = rm.room_id GROUP BY r.id ORDER BY r.name"
    ) as cursor:
        rooms = [dict(row) for row in await cursor.fetchall()]
    return {"rooms": rooms}


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
                "is_admin": bool(user.get("is_admin", 0)),
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

        # Keepalive — detect dead connections (e.g. MCP process killed by CC)
        async def _ping_loop():
            while True:
                await asyncio.sleep(30)
                try:
                    await ws.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

        ping_task = asyncio.create_task(_ping_loop())

        # Message loop
        try:
            while True:
                data = await ws.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "pong":
                    continue
                await _handle_ws_message(ws, user_id, user, msg)
        finally:
            ping_task.cancel()

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
            "image_url": saved.get("image_url"),
        }
        await manager.broadcast_to_room(room_id, event)

        # Web push: notify offline room members (fire-and-forget, fail-safe)
        asyncio.create_task(
            _send_push_to_offline_room_members(
                room_id=room_id,
                sender_user_id=user_id,
                sender_display_name=saved["display_name"],
                content=saved["content"],
            )
        )

        # PPS bridge
        room = await db.get_room(room_id)
        if room:
            members = await db.get_room_members(room_id)
            member_entities = [m["username"].lower() for m in members if m["username"].lower() in bridge.PPS_ENDPOINTS]
            asyncio.create_task(
                bridge_message(
                    room_name=room["name"],
                    username=saved["username"],
                    display_name=saved["display_name"],
                    content=saved["content"],
                    timestamp=saved["created_at"],
                    member_entities=member_entities,
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
                    "image_url": m.get("image_url"),
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
