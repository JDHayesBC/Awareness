"""Corrade notification receiver — durable in-world event intake for the SL daemon.

Corrade (Wizardry and Steamworks) POSTs "notifications" (events) to a callback URL
we register with the ``notify`` command. Each POST body is a WAS key-value string
(``&``-joined ``key=value``, each side percent-encoded — decode with
``decode_kv``). This module promotes the proven throwaway receiver into real
infrastructure: a bounded store, a dialog parser, subscription install (with the
login-settle retry the event queue needs — see corrade.md §9a), and the
token-guarded FastAPI routes the daemon exposes.

The single most important notification is ``dialog`` — an in-world ``llDialog``
blue-menu. Those drive ~3/4 of SL (vendors, teleporters, pose menus, HUDs, the
AVsitter furniture loop). We keep the most recent dialogs in a pending map keyed
by their dialog ``id`` so a later ``replytoscriptdialog`` can close the loop
(``sense -> decide -> act -> confirm``, proven live 2026-08-23).

Attribution (WAS PC & OD 1.0): Corrade is by Wizardry and Steamworks.

Scope boundary (deliberate): this is the RECEIVER only. It NEVER calls the brain
(``EntityBrain.respond``) — Corrade wants a fast ack, and salience/turn routing is
the next phase. The POST handler carries a clearly-marked TODO seam where a future
``SLPerception`` layer will consume the ``NotificationStore``.

Concurrency: the daemon runs a single asyncio event loop, so the plain
``deque``/``dict`` here need no locks. The synchronous ``CorradeClient`` calls are
pushed to a worker thread (``asyncio.to_thread``) so they never block the loop.

Env (see build_client_from_env / sl_daemon docstring):
    CORRADE_BASE_URL       default http://127.0.0.1:8080/  (Corrade HTTP server)
    CORRADE_GROUP          the SL group name = half of Corrade's auth
    CORRADE_PASSWORD       plaintext group password (or ...PASSWORD_FILE)
    CORRADE_PASSWORD_FILE  default haven/data/corrade-group-password.txt

Reference: haven/anchorage/corrade.md  (esp. §1b, §7, §9a — verbatim syntax).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

# FastAPI/pydantic imported at module level so that string annotations (this module
# uses `from __future__ import annotations`) on the route handlers resolve against
# the module globals — FastAPI can't see names local to register_routes.
from fastapi import HTTPException, Request
from pydantic import BaseModel

# Work both as a package module (haven.anchorage.corrade_events) and when the
# anchorage dir is on sys.path directly (the self-running test harness).
try:  # pragma: no cover - import shim
    from haven.anchorage.corrade_client import CorradeClient, CorradeError, decode_kv
except ImportError:  # pragma: no cover - import shim
    from corrade_client import CorradeClient, CorradeError, decode_kv

# --------------------------------------------------------------------------- #
# Logging (mirrors sl_daemon.log's shape so journal lines stay consistent).
# NEVER log the group password or the full callback secret.
# --------------------------------------------------------------------------- #

ENTITY_NAME = os.getenv("ENTITY_NAME", "unknown")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "haven" / "data"

# Notification types we subscribe to by default. Overridable via env so a live
# session can widen/narrow without a redeploy (matches SL_CAPTURE/SL_COMMANDS style).
DEFAULT_NOTIFY_TYPES = (
    "local,message,dialog,avatars,collision,sit,"
    "animation,appearance,balance,alert,typing,region"
)


def log(msg: str) -> None:
    print(f"[{ENTITY_NAME}-corrade] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Dialog button parsing (pure — unit-tested against the verbatim §9a capture)
# --------------------------------------------------------------------------- #

def parse_dialog_buttons(button_csv: str) -> list[dict]:
    """Parse Corrade's flat ``button`` CSV into ``[{"index": n, "label": ...}]``.

    The wire shape is the literal token ``index`` followed by repeating
    ``<n>,<label>`` pairs, e.g.::

        index,0,OPTIONS*,1,[ADJUST],2,[SWAP],3,ORAL*,...,5,CUM&CLEAN*,...

    Assumption (holds in practice): a *label* never contains a comma, so a plain
    ``str.split(",")`` recovers the fields. A label CAN contain ``&`` (e.g.
    ``CUM&CLEAN*``) — that survives because on the wire the whole value arrived
    percent-encoded and ``decode_kv`` already un-escaped it before we get here,
    so the ``&`` is a literal character inside one comma-delimited field.
    """
    if not button_csv:
        return []
    parts = button_csv.split(",")
    # Drop the leading literal "index" sentinel token if present.
    if parts and parts[0] == "index":
        parts = parts[1:]
    buttons: list[dict] = []
    # Walk repeating (n, label) pairs; ignore a dangling odd tail defensively.
    for i in range(0, len(parts) - 1, 2):
        idx_str, label = parts[i], parts[i + 1]
        try:
            idx = int(idx_str)
        except ValueError:
            continue  # skip a malformed pair rather than crash the whole parse
        buttons.append({"index": idx, "label": label})
    return buttons


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

class NotificationStore:
    """Bounded in-memory record of decoded Corrade notifications.

    ``notifications`` is a rolling window (``deque(maxlen)``) of *every* decoded
    event, each wrapped as ``{"received": <ts>, "data": <decoded dict>}``.
    ``pending_dialogs`` is a separate id-keyed map of just the ``dialog`` events
    still awaiting a reply (capped; oldest evicted on overflow). ``time.time()``
    is fine for the timestamp here — this is not a workflow script, we only need a
    monotonic-ish "when did this land" for display/ordering.

    Single event loop => no locks needed.
    """

    def __init__(self, maxlen: int = 300, dialog_cap: int = 50) -> None:
        self.notifications: deque[dict] = deque(maxlen=maxlen)
        self.pending_dialogs: dict[str, dict] = {}
        self._dialog_cap = dialog_cap

    def add(self, data: dict) -> dict:
        """Append any decoded notification to the rolling window."""
        record = {"received": time.time(), "data": data}
        self.notifications.append(record)
        return record

    def add_dialog(self, data: dict) -> None:
        """Record a ``dialog`` notification in the pending-reply map.

        Keyed by the dialog ``id`` (the UUID needed to reply). Re-inserting an
        existing id refreshes it to newest position so eviction stays true-oldest.
        No-op if the payload has no ``id`` (nothing to reply to).
        """
        dialog_id = data.get("id")
        if not dialog_id:
            return
        # Move-to-end on refresh so FIFO eviction really drops the oldest.
        if dialog_id in self.pending_dialogs:
            del self.pending_dialogs[dialog_id]
        self.pending_dialogs[dialog_id] = {"received": time.time(), "data": data}
        while len(self.pending_dialogs) > self._dialog_cap:
            oldest = next(iter(self.pending_dialogs))
            del self.pending_dialogs[oldest]

    def drop_dialog(self, dialog_id: str) -> None:
        """Remove a dialog from pending (e.g. after a successful reply)."""
        self.pending_dialogs.pop(dialog_id, None)

    def pending_list(self, *, message_cap: int = 300) -> list[dict]:
        """The pending dialogs as JSON-serialisable dicts with parsed buttons."""
        out: list[dict] = []
        for dialog_id, record in self.pending_dialogs.items():
            d = record["data"]
            message = d.get("message", "") or ""
            out.append(
                {
                    "id": dialog_id,
                    "item": d.get("item"),
                    "name": d.get("name"),
                    "message": message[:message_cap],
                    "owner": d.get("owner"),
                    "channel": d.get("channel"),
                    "buttons": parse_dialog_buttons(d.get("button", "")),
                    "received": record["received"],
                }
            )
        return out


# --------------------------------------------------------------------------- #
# Client construction from env
# --------------------------------------------------------------------------- #

def _load_corrade_password() -> str:
    """Load the plaintext group password: env ``CORRADE_PASSWORD`` OR the file at
    ``CORRADE_PASSWORD_FILE`` (default haven/data/corrade-group-password.txt).

    Same shape as sl_daemon._load_secret — the value is never logged.
    """
    val = os.getenv("CORRADE_PASSWORD")
    if val:
        return val.strip()
    default_file = DATA_DIR / "corrade-group-password.txt"
    path = Path(os.getenv("CORRADE_PASSWORD_FILE", str(default_file)))
    if path.exists():
        return path.read_text().strip()
    return ""


def build_client_from_env() -> CorradeClient | None:
    """Construct a ``CorradeClient`` from the environment, or ``None`` if creds
    are absent (so the receiver routes can still come up while subscriptions and
    replies stay disabled). Requires both a group name and a group password."""
    base_url = os.getenv("CORRADE_BASE_URL", "http://127.0.0.1:8080/")
    group = os.getenv("CORRADE_GROUP", "").strip()
    password = _load_corrade_password()
    if not group or not password:
        return None
    return CorradeClient(base_url, group, password)


# --------------------------------------------------------------------------- #
# Subscription install (retry across the event-queue login-settle window)
# --------------------------------------------------------------------------- #

async def install_subscriptions(
    client: CorradeClient | None,
    callback_url: str,
    types: Any = DEFAULT_NOTIFY_TYPES,
    *,
    attempts: int = 5,
    base_delay: float = 5.0,
) -> bool:
    """Install/replace our notification subscriptions, retrying with backoff.

    The SL event queue can be down for ~30 s to a few minutes after login
    (corrade.md §9a), during which ``notify`` may be refused or return failure.
    So a failed install is NON-fatal: retry a few times with linear backoff, log
    each attempt, and give up gracefully (return ``False``) rather than raise.

    Uses ``action='set'`` + a stable ``tag='daemon'`` so repeated calls are
    idempotent (they replace rather than accumulate callback URLs).
    """
    if client is None:
        log("install_subscriptions skipped — no Corrade client (creds absent)")
        return False
    if not isinstance(types, str):
        types = ",".join(types)

    for attempt in range(1, attempts + 1):
        try:
            # client.notify is synchronous (stdlib urllib) — off-load it.
            result = await asyncio.to_thread(
                client.notify, types, callback_url, action="set", tag="daemon"
            )
            if CorradeClient.ok(result):
                log(f"notify subscriptions installed (types={types})")
                return True
            log(
                f"notify not accepted (attempt {attempt}/{attempts}): "
                f"{result.get('error', result)}"
            )
        except CorradeError as exc:
            log(f"notify transport failed (attempt {attempt}/{attempts}): {exc}")
        if attempt < attempts:
            await asyncio.sleep(base_delay * attempt)

    log("notify subscriptions NOT installed — event queue likely still settling; "
        "will rely on a later /corrade-events/subscribe or restart")
    return False


# --------------------------------------------------------------------------- #
# FastAPI routes
# --------------------------------------------------------------------------- #

class ReplyBody(BaseModel):
    token: str
    dialog: str
    index: int | None = None
    button: str | None = None
    action: str = "reply"  # reply | ignore | purge


class SubscribeBody(BaseModel):
    token: str


def register_routes(
    app,
    *,
    secret: str,
    store: NotificationStore,
    client: CorradeClient | None,
    callback_url: str | None = None,
    types: Any = DEFAULT_NOTIFY_TYPES,
    on_event: "Optional[Callable[[dict], None]]" = None,
) -> None:
    """Register the token-guarded ``/corrade-events/*`` routes on ``app``.

    Every route is guarded by a token that must equal ``secret`` (reuse the
    daemon's ``ANCHORAGE_SL_SECRET``). ``callback_url``/``types`` are only needed
    by the manual re-subscribe hook.

    Route registration ORDER matters: the static paths (``/pending``, ``/reply``,
    ``/subscribe``) are registered BEFORE the catch-all ``POST /{token}`` so a
    POST to e.g. ``/corrade-events/reply`` matches the reply handler, not the
    token path with ``token='reply'``.
    """

    def _guard(token: str) -> None:
        if not secret or token != secret:
            raise HTTPException(status_code=403, detail="bad token")

    # -- GET /corrade-events/pending -------------------------------------- #
    @app.get("/corrade-events/pending")
    async def corrade_pending(token: str):  # noqa: ANN202 - FastAPI handler
        _guard(token)
        return {"ok": True, "pending": store.pending_list()}

    # -- POST /corrade-events/reply --------------------------------------- #
    @app.post("/corrade-events/reply")
    async def corrade_reply(body: ReplyBody):  # noqa: ANN202
        _guard(body.token)
        if client is None:
            raise HTTPException(status_code=503, detail="no Corrade client (creds absent)")
        # Build replytoscriptdialog args, omitting whichever of index/button is
        # not supplied (Corrade accepts either or both — corrade.md §9a).
        kwargs: dict[str, Any] = dict(
            command="replytoscriptdialog", action=body.action, dialog=body.dialog
        )
        if body.index is not None:
            kwargs["index"] = body.index
        if body.button is not None:
            kwargs["button"] = body.button
        try:
            result = await asyncio.to_thread(client.command, **kwargs)
        except CorradeError as exc:
            raise HTTPException(status_code=502, detail=f"corrade: {exc}") from exc
        # On success, retire the dialog from pending so it stops showing up.
        if CorradeClient.ok(result):
            store.drop_dialog(body.dialog)
        return {"ok": CorradeClient.ok(result), "result": result}

    # -- POST /corrade-events/subscribe (manual re-subscribe hook) -------- #
    @app.post("/corrade-events/subscribe")
    async def corrade_subscribe(body: SubscribeBody):  # noqa: ANN202
        _guard(body.token)
        if client is None or callback_url is None:
            raise HTTPException(status_code=503, detail="subscribe unavailable (no client/callback)")
        installed = await install_subscriptions(client, callback_url, types)
        return {"ok": installed}

    # -- POST /corrade-events/{token}  (the callback Corrade POSTs to) ---- #
    # Registered LAST so the static routes above win the match.
    @app.post("/corrade-events/{token}")
    async def corrade_callback(token: str, request: Request):  # noqa: ANN202
        _guard(token)
        raw = (await request.body()).decode("utf-8", errors="replace")
        data = decode_kv(raw)
        store.add(data)

        # A dialog is discriminated by either key depending on notification vs
        # the older 'type' framing — accept both.
        ntype = data.get("type") or data.get("notification") or "?"
        if data.get("type") == "dialog" or data.get("notification") == "dialog":
            store.add_dialog(data)
            log(
                f"dialog id={data.get('id', '?')[:8]}… name={data.get('name', '?')!r} "
                f"buttons={len(parse_dialog_buttons(data.get('button', '')))}"
            )
        else:
            log(f"notification type={ntype!r} keys={len(data)}")

        # SLPerception hook (sl_daemon supplies it): salience-score the event and,
        # when it tips arousal over threshold, spawn a brain turn. Must stay FAST
        # and non-blocking — Corrade wants a quick ack — so the hook only schedules
        # a background task; it never awaits the brain here. Guarded so a hook bug
        # can never break the ack.
        if on_event is not None:
            try:
                on_event(data)
            except Exception as exc:
                log(f"on_event hook error (non-fatal): {exc}")
        return {"ok": True}
