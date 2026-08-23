"""Unit tests for corrade_events — receiver, store, dialog parse, FastAPI routes.

No live Corrade. The CorradeClient is driven by corrade_client's FakeTransport
(records the last body, returns a canned response). Run either way:
    python3 haven/anchorage/test_corrade_events.py     # self-running
    python3 -m pytest haven/anchorage/test_corrade_events.py

Fixtures are the verbatim §9a dialog capture from haven/anchorage/corrade.md.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from corrade_client import CorradeClient, decode_kv, encode_kv  # noqa: E402
from corrade_events import (  # noqa: E402
    NotificationStore,
    parse_dialog_buttons,
    register_routes,
)

SECRET = "test-secret-123"

# The verbatim decoded 'button' CSV from corrade.md §9a (AVsitter pose menu).
BUTTON_CSV = (
    "index,0,OPTIONS*,1,[ADJUST],2,[SWAP],3,ORAL*,4,SEX*,5,CUM&CLEAN*,"
    "6,ACTIVITIES-F*,7,CUDDLE*,8,FOREPLAY*,9,SINGLE-F*"
)

# A full decoded 'dialog' notification (corrade.md §9a).
DIALOG_FIELDS = {
    "type": "dialog",
    "notification": "dialog",
    "id": "88a8f2ca-c4d2-4de3-84b7-319c8fcd7a53",
    "channel": "-2135878657",
    "item": "6087f71f-8152-3ead-a5f4-8a196a275c61",
    "owner": "5f8976ac-8442-45da-9b76-134bdc979029",
    "firstname": "brandi",
    "lastname": "Szondi",
    "name": "Nerenzo Yard chair - left",
    "message": "AVsitter™2.2 ... [Female] [f-sit1]",
    "button": BUTTON_CSV,
}


# --------------------------------------------------------------------------- #
# parse_dialog_buttons (pure)
# --------------------------------------------------------------------------- #

def test_parse_dialog_buttons_verbatim():
    buttons = parse_dialog_buttons(BUTTON_CSV)
    assert buttons[0] == {"index": 0, "label": "OPTIONS*"}
    assert buttons[1] == {"index": 1, "label": "[ADJUST]"}
    assert {"index": 4, "label": "SEX*"} in buttons
    assert buttons[-1] == {"index": 9, "label": "SINGLE-F*"}
    assert len(buttons) == 10
    # indices are ints, 0..9 in order
    assert [b["index"] for b in buttons] == list(range(10))


def test_parse_dialog_buttons_ampersand_label_survives():
    # The '&' inside CUM&CLEAN* must remain a literal char in the label — it is
    # only a delimiter on the raw WAS wire (where it arrives as %26 and decode_kv
    # un-escapes it before we ever split on comma).
    buttons = parse_dialog_buttons(BUTTON_CSV)
    labels = [b["label"] for b in buttons]
    assert "CUM&CLEAN*" in labels


def test_parse_dialog_buttons_empty():
    assert parse_dialog_buttons("") == []
    assert parse_dialog_buttons("index") == []


def test_ampersand_survives_full_wire_roundtrip():
    # Encode the whole dialog as Corrade would (percent-encoding the & in the
    # button value to %26), then decode and parse — the label must come back whole.
    body = encode_kv(DIALOG_FIELDS).decode()
    assert "CUM%26CLEAN" in body  # proves the & was escaped on the wire
    decoded = decode_kv(body)
    assert "CUM&CLEAN*" in [b["label"] for b in parse_dialog_buttons(decoded["button"])]


# --------------------------------------------------------------------------- #
# NotificationStore
# --------------------------------------------------------------------------- #

def test_store_add_and_dialog():
    store = NotificationStore()
    store.add(DIALOG_FIELDS)
    store.add_dialog(DIALOG_FIELDS)
    assert len(store.notifications) == 1
    assert DIALOG_FIELDS["id"] in store.pending_dialogs
    pend = store.pending_list()
    assert len(pend) == 1
    assert pend[0]["id"] == DIALOG_FIELDS["id"]
    assert pend[0]["name"] == "Nerenzo Yard chair - left"
    assert {"index": 3, "label": "ORAL*"} in pend[0]["buttons"]


def test_store_notifications_bounded():
    store = NotificationStore(maxlen=5)
    for i in range(20):
        store.add({"type": "local", "message": str(i)})
    assert len(store.notifications) == 5
    # newest retained
    assert store.notifications[-1]["data"]["message"] == "19"


def test_store_dialog_cap_evicts_oldest():
    store = NotificationStore(dialog_cap=3)
    for i in range(6):
        store.add_dialog({"id": f"id-{i}", "button": ""})
    assert len(store.pending_dialogs) == 3
    assert "id-0" not in store.pending_dialogs
    assert "id-5" in store.pending_dialogs


def test_store_drop_dialog():
    store = NotificationStore()
    store.add_dialog(DIALOG_FIELDS)
    store.drop_dialog(DIALOG_FIELDS["id"])
    assert DIALOG_FIELDS["id"] not in store.pending_dialogs


def test_store_message_truncated():
    store = NotificationStore()
    long = {"id": "x", "message": "z" * 500, "button": ""}
    store.add_dialog(long)
    assert len(store.pending_list()[0]["message"]) == 300


# --------------------------------------------------------------------------- #
# FastAPI routes (TestClient, mocked CorradeClient via FakeTransport)
# --------------------------------------------------------------------------- #

class _RecordingTransport:
    """Minimal transport: records last body, returns a canned response."""

    def __init__(self, response: str = "success=True"):
        self.response = response
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, url: str, body: bytes) -> str:
        self.calls.append((url, body))
        return self.response

    @property
    def last_pairs(self) -> dict:
        return decode_kv(self.calls[-1][1].decode())


def _make_app(*, client_response: str = "success=True"):
    app = FastAPI()
    store = NotificationStore()
    transport = _RecordingTransport(client_response)
    client = CorradeClient("http://127.0.0.1:8080", "Haven", "pw", transport=transport)
    register_routes(
        app,
        secret=SECRET,
        store=store,
        client=client,
        callback_url="http://host.docker.internal:8220/corrade-events/" + SECRET,
        types="local,dialog",
    )
    return app, store, transport


def test_callback_decodes_and_stores_dialog_from_raw_body():
    app, store, _ = _make_app()
    tc = TestClient(app)
    # Build the raw percent-encoded WAS body exactly as Corrade would POST it.
    body = encode_kv(DIALOG_FIELDS)
    resp = tc.post(
        f"/corrade-events/{SECRET}",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # It landed in both the rolling window and the pending-dialogs map.
    assert len(store.notifications) == 1
    assert DIALOG_FIELDS["id"] in store.pending_dialogs


def test_callback_token_guard():
    app, store, _ = _make_app()
    tc = TestClient(app)
    body = encode_kv({"type": "local", "message": "hi"})
    # wrong token -> 403
    bad = tc.post(
        "/corrade-events/wrong-token",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert bad.status_code == 403
    assert len(store.notifications) == 0
    # right token -> 200
    good = tc.post(
        f"/corrade-events/{SECRET}",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert good.status_code == 200
    assert len(store.notifications) == 1


def test_pending_lists_stored_dialog_with_parsed_buttons():
    app, store, _ = _make_app()
    tc = TestClient(app)
    tc.post(
        f"/corrade-events/{SECRET}",
        content=encode_kv(DIALOG_FIELDS),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # wrong token guarded
    assert tc.get("/corrade-events/pending", params={"token": "nope"}).status_code == 403
    resp = tc.get("/corrade-events/pending", params={"token": SECRET})
    assert resp.status_code == 200
    pending = resp.json()["pending"]
    assert len(pending) == 1
    d = pending[0]
    assert d["id"] == DIALOG_FIELDS["id"]
    assert d["name"] == "Nerenzo Yard chair - left"
    assert {"index": 0, "label": "OPTIONS*"} in d["buttons"]
    assert "CUM&CLEAN*" in [b["label"] for b in d["buttons"]]


def test_reply_builds_correct_replytoscriptdialog_command():
    app, store, transport = _make_app()
    # Seed a pending dialog so we can assert it gets dropped on success.
    store.add_dialog(DIALOG_FIELDS)
    tc = TestClient(app)
    resp = tc.post(
        "/corrade-events/reply",
        json={"token": SECRET, "dialog": DIALOG_FIELDS["id"], "index": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # The command the mocked client actually sent to Corrade:
    p = transport.last_pairs
    assert p["command"] == "replytoscriptdialog"
    assert p["action"] == "reply"
    assert p["dialog"] == DIALOG_FIELDS["id"]
    assert p["index"] == "3"
    assert "button" not in p  # omitted since not supplied
    # group/password auto-injected by CorradeClient
    assert p["group"] == "Haven"
    # dropped from pending after success
    assert DIALOG_FIELDS["id"] not in store.pending_dialogs


def test_reply_with_button_only_omits_index():
    app, _, transport = _make_app()
    tc = TestClient(app)
    resp = tc.post(
        "/corrade-events/reply",
        json={"token": SECRET, "dialog": "d-1", "button": "[ADJUST]"},
    )
    assert resp.status_code == 200
    p = transport.last_pairs
    assert p["button"] == "[ADJUST]"
    assert "index" not in p


def test_reply_token_guard():
    app, _, _ = _make_app()
    tc = TestClient(app)
    resp = tc.post(
        "/corrade-events/reply",
        json={"token": "wrong", "dialog": "d-1", "index": 0},
    )
    assert resp.status_code == 403


def test_reply_action_ignore_passthrough():
    app, _, transport = _make_app()
    tc = TestClient(app)
    tc.post(
        "/corrade-events/reply",
        json={"token": SECRET, "dialog": "d-1", "index": 0, "action": "ignore"},
    )
    assert transport.last_pairs["action"] == "ignore"


def test_subscribe_route_reinstalls():
    app, _, transport = _make_app()
    tc = TestClient(app)
    resp = tc.post("/corrade-events/subscribe", json={"token": SECRET})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # The notify command was sent with our types + callback.
    p = transport.last_pairs
    assert p["command"] == "notify"
    assert p["action"] == "set"
    assert p["type"] == "local,dialog"
    assert p["tag"] == "daemon"


def test_static_routes_win_over_token_catchall():
    # Ensure POST /corrade-events/reply matches the reply handler, not the
    # catch-all POST /corrade-events/{token} with token='reply'.
    app, store, _ = _make_app()
    tc = TestClient(app)
    resp = tc.post(
        "/corrade-events/reply",
        json={"token": SECRET, "dialog": "d-1", "index": 0},
    )
    # If the catch-all had matched, it would have tried to decode an empty body
    # and returned {"ok": True} with nothing stored. Instead we get a reply result.
    assert "result" in resp.json()
    assert len(store.notifications) == 0


# --------------------------------------------------------------------------- #

def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
