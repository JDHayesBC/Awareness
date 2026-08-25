"""Unit tests for corrade_client — pure wire-format + mocked transport.

No live Corrade needed. Run either way:
    python3 haven/anchorage/test_corrade_client.py     # self-running
    python3 -m pytest haven/anchorage/test_corrade_client.py

Fixtures are the verbatim examples from haven/anchorage/corrade.md.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corrade_client import (  # noqa: E402
    encode_kv,
    decode_kv,
    CorradeClient,
    CorradeError,
)


class FakeTransport:
    """Records the last body sent; returns a canned response."""

    def __init__(self, response: str = "success=True"):
        self.response = response
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, url: str, body: bytes) -> str:
        self.calls.append((url, body))
        return self.response

    @property
    def last_pairs(self) -> dict:
        """Decode the last body sent back into a dict for assertions."""
        return decode_kv(self.calls[-1][1].decode())


# --------------------------------------------------------------------------- #
# encode/decode (pure)
# --------------------------------------------------------------------------- #

def test_encode_spaces_are_percent_not_plus():
    # corrade.md §0: Corrade wants %20, never +
    out = encode_kv({"command": "getbalance", "group": "My Group"}).decode()
    assert out == "command=getbalance&group=My%20Group"
    assert "+" not in out


def test_encode_escapes_delimiters_inside_values():
    # A value containing & and = must not corrupt the pair structure.
    out = encode_kv({"message": "a&b=c"}).decode()
    assert out == "message=a%26b%3Dc"
    # ...and it round-trips back exactly.
    assert decode_kv(out) == {"message": "a&b=c"}


def test_decode_getbalance_response_verbatim():
    # verbatim response body from corrade.md §1a
    result = decode_kv("command=getbalance&balance=0&success=True&group=My%20Group")
    assert result == {
        "command": "getbalance",
        "balance": "0",
        "success": "True",
        "group": "My Group",
    }


def test_decode_ignores_malformed_pairs():
    assert decode_kv("a=1&garbage&b=2") == {"a": "1", "b": "2"}


def test_decode_splits_on_first_equals_only():
    # a value legitimately containing '=' (already unescaped edge)
    assert decode_kv("k=a=b") == {"k": "a=b"}


def test_decode_form_encoded_plus_is_space():
    # Corrade emits application/x-www-form-urlencoded across its whole surface:
    # '+' means space, a literal '+' arrives as %2B. decode_kv must honor both
    # (the daemon 'LyraPattern+Resident' / 'Hi+Lyra' fidelity bug, 2026-08-24).
    d = decode_kv("name=LyraPattern+Resident&msg=Hi+Lyra+%3A%29&math=1%2B1")
    assert d["name"] == "LyraPattern Resident"
    assert d["msg"] == "Hi Lyra :)"
    assert d["math"] == "1+1"          # real '+' survived (sent as %2B)
    # %20 still decodes to space too — both encodings coexist on the wire
    assert decode_kv("k=a%20b")["k"] == "a b"


def test_local_chat_notification_payload_decodes():
    # verbatim 'local' notification payload from corrade.md §1b
    payload = ("type=local&message=boo&firstname=Sneaky&lastname=Resident"
               "&owner=1ad33407-a792-476d-a5e3-06007c0802bf"
               "&item=1ad33407-a792-476d-a5e3-06007c0802bf")
    d = decode_kv(payload)
    assert d["type"] == "local"
    assert d["message"] == "boo"
    assert d["firstname"] == "Sneaky"


# --------------------------------------------------------------------------- #
# CorradeClient (mocked transport)
# --------------------------------------------------------------------------- #

def _client(resp="success=True"):
    ft = FakeTransport(resp)
    c = CorradeClient("http://127.0.0.1:8080", "My Group", "secretpw", transport=ft)
    return c, ft


def test_command_injects_group_and_password():
    c, ft = _client()
    c.command(command="getbalance")
    p = ft.last_pairs
    assert p["command"] == "getbalance"
    assert p["group"] == "My Group"
    assert p["password"] == "secretpw"


def test_command_explicit_pairs_win_over_defaults():
    c, ft = _client()
    c.command(command="x", group="Other Group")
    assert ft.last_pairs["group"] == "Other Group"
    assert ft.last_pairs["password"] == "secretpw"


def test_command_posts_to_base_url_root_with_slash():
    c, ft = _client()
    c.command(command="x")
    url = ft.calls[-1][0]
    assert url == "http://127.0.0.1:8080/"


def test_command_returns_decoded_dict():
    c, _ = _client("command=getbalance&balance=250&success=True")
    result = c.command(command="getbalance")
    assert result["balance"] == "250"
    assert CorradeClient.ok(result) is True


def test_get_parcel_music_url_strips_was_key_prefix():
    # Corrade echoes the requested field as 'MusicURL,<url>' (WAS key,value CSV),
    # NOT the bare URL — the hardware-confirmed 2026-08-23 shape. Return just the URL.
    body = encode_kv({
        "command": "getparceldata", "success": "True",
        "data": "MusicURL,http://listen.181fm.com:8700",
    }).decode()
    c, _ = _client(body)
    assert c.get_parcel_music_url() == "http://listen.181fm.com:8700"


def test_get_parcel_music_url_none_when_no_stream():
    # Empty value (no music set on the parcel) -> None, not "".
    body = encode_kv({"command": "getparceldata", "success": "True",
                      "data": "MusicURL,"}).decode()
    c, _ = _client(body)
    assert c.get_parcel_music_url() is None


def test_get_parcel_music_url_bare_url_defensive():
    # A build that returns the bare URL with no key echo still works.
    body = encode_kv({"command": "getparceldata", "success": "True",
                      "data": "http://listen.181fm.com:8700"}).decode()
    c, _ = _client(body)
    assert c.get_parcel_music_url() == "http://listen.181fm.com:8700"


def test_ok_false_when_success_false():
    c, _ = _client("success=False&error=no+permission")
    assert CorradeClient.ok(c.command(command="x")) is False


def test_transport_error_raises_corrade_error():
    def boom(url, body):
        raise CorradeError("refused")

    c = CorradeClient("http://127.0.0.1:8080", "g", "p", transport=boom)
    try:
        c.command(command="x")
    except CorradeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected CorradeError")


# -- effectors ---------------------------------------------------------------#

def test_say_builds_local_tell():
    c, ft = _client()
    c.say("Good day!")
    p = ft.last_pairs
    assert p["command"] == "tell"
    assert p["entity"] == "local"
    assert p["type"] == "Normal"
    assert p["message"] == "Good day!"


def test_im_by_agent_uuid():
    c, ft = _client()
    c.im("hi", agent="0fe3acf3-1526-4b72-a86d-98694932723b")
    p = ft.last_pairs
    assert p["entity"] == "avatar"
    assert p["agent"].startswith("0fe3acf3")
    assert "firstname" not in p


def test_im_by_name():
    c, ft = _client()
    c.im("hi", firstname="Good", lastname="Day")
    p = ft.last_pairs
    assert p["firstname"] == "Good" and p["lastname"] == "Day"
    assert "agent" not in p


def test_wear_outfit_is_changeappearance():
    c, ft = _client()
    c.wear_outfit("/My Inventory/CoolOutfit")
    p = ft.last_pairs
    assert p["command"] == "changeappearance"
    assert p["folder"] == "/My Inventory/CoolOutfit"


def test_teleport_stringifies_fly_bool():
    c, ft = _client()
    c.teleport("Anchorage", "<128, 128, 22>", fly=False)
    p = ft.last_pairs
    assert p["command"] == "teleport"
    assert p["region"] == "Anchorage"
    assert p["position"] == "<128, 128, 22>"
    assert p["fly"] == "False"


def test_notify_joins_type_list_and_sets_url():
    c, ft = _client()
    c.notify(["local", "message", "avatars"], "http://127.0.0.1:9000/corrade-events",
             action="set", tag="daemon")
    p = ft.last_pairs
    assert p["command"] == "notify"
    assert p["action"] == "set"
    assert p["type"] == "local,message,avatars"
    assert p["URL"] == "http://127.0.0.1:9000/corrade-events"
    assert p["tag"] == "daemon"


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
