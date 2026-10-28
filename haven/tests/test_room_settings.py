"""#381: per-room settings (verbosity, model), soft clear, permission matrix.

Runs the real FastAPI app over ASGI against a temp SQLite DB — no network, no
lifespan (the fixture initializes the DB itself).
"""
from __future__ import annotations

import os
import tempfile

# server.py reads these at import time; point them at a throwaway dir first.
_TMP = tempfile.mkdtemp(prefix="haven-test-")
os.environ["HAVEN_DB_PATH"] = os.path.join(_TMP, "haven.db")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from haven import server  # noqa: E402
from haven.auth import hash_token  # noqa: E402
from haven.db import HavenDB  # noqa: E402
from haven.room_settings import resolve_model_id, AUTO_DM_VERBOSITY, resolve_verbosity  # noqa: E402


async def _user(db, name, *, bot=False, admin=False):
    token = f"tok-{name}"
    u = await db.create_user(name, name.title(), hash_token(token), is_bot=bot)
    if admin:
        await db.set_admin(u["id"], True)
    return {**u, "token": token, "h": {"Authorization": f"Bearer {token}"}}


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    db = HavenDB(tmp_path / "t.db")
    await db.initialize()
    monkeypatch.setattr(server, "db", db)

    events = []

    async def capture(room_id, event):
        events.append((room_id, event))

    monkeypatch.setattr(server.manager, "broadcast_to_room", capture)

    jeff = await _user(db, "jeff", admin=True)
    guest = await _user(db, "guest")
    lyra = await _user(db, "lyra", bot=True)
    outsider = await _user(db, "outsider")
    room = await db.create_room("commons", "Commons", jeff["id"])
    await db.join_room(room["id"], guest["id"])
    await db.join_room(room["id"], lyra["id"])
    dm = await db.find_or_create_dm(jeff["id"], lyra["id"])

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield type("Env", (), dict(
            db=db, client=client, events=events, room=room, dm=dm,
            jeff=jeff, guest=guest, lyra=lyra, outsider=outsider,
        ))
    await db.close()


def url(room, tail="settings"):
    return f"/api/rooms/{room['id']}/{tail}"


# --- vocabulary ---------------------------------------------------------------

def test_auto_resolves_by_room_kind():
    assert resolve_verbosity("auto", is_dm=True) == AUTO_DM_VERBOSITY
    assert resolve_verbosity("auto", is_dm=False) == "short"
    assert resolve_verbosity(None, is_dm=True) == AUTO_DM_VERBOSITY
    assert resolve_verbosity(None, is_dm=False) == "short"
    for v in ("short", "medium", "full"):
        assert resolve_verbosity(v, is_dm=True) == v
        assert resolve_verbosity(v, is_dm=False) == v


def test_model_alias_mapping():
    assert resolve_model_id("default", "sonnet") == "sonnet"
    assert resolve_model_id(None, "sonnet") == "sonnet"
    assert resolve_model_id("sonnet", "x") == "claude-sonnet-5-5"
    assert resolve_model_id("opus", "x") == "claude-opus-5-5"
    assert resolve_model_id("fable", "x") == "claude-fable-5-1"
    assert resolve_model_id("bogus", "sonnet") == "sonnet"


# --- GET ----------------------------------------------------------------------

async def test_get_defaults_for_member(env):
    r = await env.client.get(url(env.room), headers=env.guest["h"])
    assert r.status_code == 200
    body = r.json()
    assert body["verbosity"] == "auto" and body["model"] == "default"
    assert body["cleared_before_id"] is None


async def test_get_forbidden_for_nonmember_and_404(env):
    assert (await env.client.get(url(env.room), headers=env.outsider["h"])).status_code == 403
    r = await env.client.get("/api/rooms/nope/settings", headers=env.jeff["h"])
    assert r.status_code == 404
    assert (await env.client.get(url(env.room))).status_code == 401


# --- PATCH permission matrix -------------------------------------------------

async def test_verbosity_any_member(env):
    for who in (env.guest, env.lyra, env.jeff):
        r = await env.client.patch(url(env.room), json={"verbosity": "full"}, headers=who["h"])
        assert r.status_code == 200, who["token"]
        assert r.json()["settings"]["verbosity"] == "full"


async def test_verbosity_nonmember_403(env):
    r = await env.client.patch(url(env.room), json={"verbosity": "full"}, headers=env.outsider["h"])
    assert r.status_code == 403


async def test_model_admin_and_bot_allowed_guest_denied(env):
    g = await env.client.patch(url(env.room), json={"model": "opus"}, headers=env.guest["h"])
    assert g.status_code == 403
    for who, alias in ((env.lyra, "opus"), (env.jeff, "fable")):
        r = await env.client.patch(url(env.room), json={"model": alias}, headers=who["h"])
        assert r.status_code == 200
        assert r.json()["settings"]["model"] == alias


async def test_guest_model_request_is_rejected_whole(env):
    """A forbidden field must not let the allowed field through (no partial apply)."""
    r = await env.client.patch(
        url(env.room), json={"verbosity": "full", "model": "fable"}, headers=env.guest["h"]
    )
    assert r.status_code == 403
    assert (await env.db.get_room_settings(env.room["id"]))["verbosity"] == "auto"


async def test_bot_nonmember_cannot_set_model(env):
    other_bot = await _user(env.db, "caia", bot=True)
    r = await env.client.patch(url(env.room), json={"model": "opus"}, headers=other_bot["h"])
    assert r.status_code == 403


async def test_invalid_values_rejected(env):
    for body in ({"verbosity": "verbose"}, {"model": "gpt"}):
        r = await env.client.patch(url(env.room), json=body, headers=env.jeff["h"])
        assert r.status_code == 422


async def test_partial_update_keeps_other_field(env):
    await env.client.patch(url(env.room), json={"model": "opus"}, headers=env.jeff["h"])
    await env.client.patch(url(env.room), json={"verbosity": "medium"}, headers=env.guest["h"])
    s = await env.db.get_room_settings(env.room["id"])
    assert (s["verbosity"], s["model"]) == ("medium", "opus")
    assert s["updated_by"] == env.guest["id"]


async def test_patch_broadcasts_room_updated_with_settings(env):
    await env.client.patch(url(env.room), json={"verbosity": "full"}, headers=env.guest["h"])
    rid, ev = env.events[-1]
    assert rid == env.room["id"]
    assert ev["type"] == "room_updated"
    assert ev["settings"]["verbosity"] == "full"
    assert ev["display_name"] == "Commons"  # old clients must not blank the label


async def test_connected_payload_helper_returns_settings_for_every_room(env):
    await env.client.patch(url(env.room), json={"verbosity": "short"}, headers=env.jeff["h"])
    bulk = await env.db.get_room_settings_bulk([env.room["id"], env.dm["id"]])
    assert bulk[env.room["id"]]["verbosity"] == "short"
    assert bulk[env.dm["id"]]["verbosity"] == "auto"  # no row -> defaults


# --- soft clear ---------------------------------------------------------------

async def _post(env, who, text, room=None):
    room = room or env.room
    return await env.db.create_message(room["id"], who["id"], text)


async def _visible(env, who, room=None):
    room = room or env.room
    r = await env.client.get(url(room, "messages"), headers=who["h"])
    assert r.status_code == 200
    return [m["content"] for m in r.json()["messages"]]


async def _row_count(env, room=None):
    return await env.db.get_message_count((room or env.room)["id"])


async def test_clear_requires_admin(env):
    for who in (env.guest, env.lyra):
        assert (await env.client.post(url(env.room, "clear"), headers=who["h"])).status_code == 403
        assert (await env.client.post(url(env.room, "unclear"), headers=who["h"])).status_code == 403
    assert (await env.client.post("/api/rooms/nope/clear", headers=env.jeff["h"])).status_code == 404


async def test_clear_hides_for_everyone_unclear_restores_nothing_deleted(env):
    await _post(env, env.jeff, "one")
    await _post(env, env.lyra, "two")
    assert await _visible(env, env.guest) == ["one", "two"]

    r = await env.client.post(url(env.room, "clear"), headers=env.jeff["h"])
    assert r.status_code == 200
    assert r.json()["settings"]["cleared_before_id"] > 0
    assert await _visible(env, env.guest) == []
    assert await _visible(env, env.lyra) == []
    assert await _row_count(env) == 2  # soft: rows are still there

    # Messages after the clear show up normally.
    await _post(env, env.guest, "three")
    assert await _visible(env, env.jeff) == ["three"]

    r = await env.client.post(url(env.room, "unclear"), headers=env.jeff["h"])
    assert r.status_code == 200
    assert r.json()["settings"]["cleared_before_id"] is None
    assert await _visible(env, env.guest) == ["one", "two", "three"]
    assert await _row_count(env) == 3


async def test_clear_applies_to_ws_history_path_and_is_per_room(env):
    """The WS 'history' handler reads through db.get_messages, the same choke point."""
    await _post(env, env.jeff, "room-msg")
    await _post(env, env.jeff, "dm-msg", room=env.dm)
    await env.client.post(url(env.room, "clear"), headers=env.jeff["h"])
    assert await env.db.get_messages(env.room["id"]) == []
    assert [m["content"] for m in await env.db.get_messages(env.dm["id"])] == ["dm-msg"]


async def test_clear_broadcasts_settings_and_hides_from_unread(env):
    await _post(env, env.jeff, "x")
    assert (await env.db.get_unread_counts(env.guest["id"]))[env.room["id"]] == 1
    await env.client.post(url(env.room, "clear"), headers=env.jeff["h"])
    assert (await env.db.get_unread_counts(env.guest["id"]))[env.room["id"]] == 0
    _, ev = env.events[-1]
    assert ev["type"] == "room_updated" and ev["settings"]["cleared_before_id"]


async def test_clear_empty_room_is_harmless(env):
    r = await env.client.post(url(env.room, "clear"), headers=env.jeff["h"])
    assert r.status_code == 200
    await _post(env, env.jeff, "first")
    assert await _visible(env, env.jeff) == ["first"]
