"""Corrade HTTP client — WAS key-value transport for driving a headless SL avatar.

Corrade (Wizardry and Steamworks) exposes ~300 commands over an integrated HTTP
server. The wire format is "wasKeyValue": an ``&``-joined list of ``key=value``
pairs where **each key and value is percent-encoded separately** (``%20`` for
space, NOT ``+``). Every command carries ``command``, ``group``, ``password``.
Corrade replies with a key-value body; ``success=True`` means the command was
*accepted*, NOT that the in-world effect happened — confirm effects via the
matching notification (see ``senses-design.md`` / ``corrade-integration.md``).

Attribution (WAS PC & OD 1.0): Corrade is by Wizardry and Steamworks.

Design notes:
  * ``encode_kv`` / ``decode_kv`` are pure functions — unit-tested against the
    verbatim examples in ``corrade.md`` with no network.
  * ``CorradeClient`` takes an injectable ``transport`` callable so tests run
    against a fake (no live Corrade). The default transport uses stdlib urllib.
  * This first cut is synchronous; the async daemon can call it in a threadpool
    or swap in an async transport. Keeping the surface small on purpose.

Reference: haven/anchorage/corrade.md  (build reference, verbatim syntax)
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import urllib.error
from typing import Callable, Optional

# A transport takes (url, body_bytes) and returns the response body as text.
Transport = Callable[[str, bytes], str]

_CONTENT_TYPE = "application/x-www-form-urlencoded"
_DEFAULT_TIMEOUT = 30


class CorradeError(RuntimeError):
    """Transport-level failure talking to Corrade (network / HTTP error).

    A command that reaches Corrade but is rejected comes back as a normal dict
    with ``success='False'`` — that is NOT raised here; the caller inspects it.
    """


# --------------------------------------------------------------------------- #
# Pure wire-format helpers (no I/O — unit-tested directly)
# --------------------------------------------------------------------------- #

def encode_kv(pairs: dict) -> bytes:
    """Encode a dict as a WAS key-value body.

    Each key and value is percent-encoded *individually* (with nothing safe, so
    ``&``/``=``/``/``/space inside a value can never corrupt the pair structure),
    then joined with ``=`` and ``&``. Values are stringified first.

        >>> encode_kv({"command": "getbalance", "group": "My Group"}).decode()
        'command=getbalance&group=My%20Group'
    """
    parts = []
    for k, v in pairs.items():
        ek = urllib.parse.quote(str(k), safe="")
        ev = urllib.parse.quote("" if v is None else str(v), safe="")
        parts.append(f"{ek}={ev}")
    return "&".join(parts).encode("utf-8")


def decode_kv(body: str) -> dict:
    """Decode a WAS key-value response body into a dict.

    Split on ``&`` first, then split each pair on the FIRST ``=``, then unescape
    key and value *individually* (unescaping the whole body first would let a
    value like ``Tom%26Jerry`` split the response). Later duplicate keys win.

        >>> decode_kv("command=getbalance&balance=0&success=True")
        {'command': 'getbalance', 'balance': '0', 'success': 'True'}
    """
    out: dict = {}
    for pair in body.split("&"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
    return out


def _group_csv(flat: str, fields: list[str]) -> list[dict]:
    """Regroup Corrade's flattened ``data`` CSV into a list of field dicts.

    ``getavatarsdata``/``getobjectsdata`` return the requested fields for N
    entities concatenated into one comma-joined ``data`` value; regroup by the
    field count. Best-effort — a value with an embedded comma (rare for the
    name/position fields we ask for) would misalign, so callers treat the result
    as a rough roster, not gospel.
    """
    if not flat or not fields:
        return []
    parts = flat.split(",")
    n = len(fields)
    rows: list[dict] = []
    for i in range(0, len(parts) - n + 1, n):
        rows.append({f.strip(): parts[i + j].strip() for j, f in enumerate(fields)})
    return rows


def _urllib_transport(url: str, body: bytes) -> str:
    """Default synchronous transport (stdlib). Raises CorradeError on failure."""
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": _CONTENT_TYPE}
    )
    try:
        with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:  # network / DNS / refused
        raise CorradeError(f"Corrade transport failed for {url}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class CorradeClient:
    """Drive one Corrade instance (one SL avatar) over its HTTP server.

    Auth is the (group name, group password) pair — no API token. The password
    sent is the *plaintext* whose SHA1 is stored in Corrade's group config;
    Corrade hashes the incoming value and compares. (Verify this assumption on
    the first live call — see corrade.md §12.)
    """

    def __init__(
        self,
        base_url: str,
        group: str,
        password: str,
        *,
        transport: Optional[Transport] = None,
    ) -> None:
        # Corrade's HTTP server listens on e.g. http://127.0.0.1:8080/ ; POSTs go
        # to the root. Normalise to a single trailing slash.
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.group = group
        self.password = password
        self._transport: Transport = transport or _urllib_transport

    # -- core -------------------------------------------------------------- #

    def command(self, **pairs) -> dict:
        """Send a command; return the decoded response dict.

        ``group`` and ``password`` are injected automatically (explicit values in
        ``pairs`` win, e.g. for a differently-scoped call). ``success`` in the
        result is 'True'/'False' as a *string*; True means accepted, not effected.
        Raises ``CorradeError`` only on transport failure.
        """
        pairs.setdefault("group", self.group)
        pairs.setdefault("password", self.password)
        body = encode_kv(pairs)
        raw = self._transport(self.base_url, body)
        return decode_kv(raw)

    @staticmethod
    def ok(result: dict) -> bool:
        """True iff Corrade accepted the command (``success=True``)."""
        return str(result.get("success", "")).lower() == "true"

    # -- events ------------------------------------------------------------ #

    def notify(
        self,
        types,
        callback_url: str,
        *,
        action: str = "set",
        tag: Optional[str] = None,
    ) -> dict:
        """Install/replace notification subscriptions pointing at our callback.

        ``types`` is a CSV string or an iterable of notification names (e.g.
        ``["local", "message", "avatars"]``). ``action``: set|add|update|remove|
        list|purge. Subscriptions do NOT survive a Corrade restart — call this on
        every daemon start (``action='set'`` with a stable ``tag`` is idempotent).
        """
        if not isinstance(types, str):
            types = ",".join(types)
        pairs = dict(
            command="notify",
            action=action,
            type=types,
            URL=callback_url,
        )
        if tag is not None:
            pairs["tag"] = tag
        return self.command(**pairs)

    # -- effector conveniences (names mirror the body's verbs) ------------- #

    def say(self, message: str, *, channel: int = 0, type: str = "Normal") -> dict:
        """Speak in local chat (``tell entity=local``). type: Normal|Whisper|Shout."""
        return self.command(
            command="tell", entity="local", type=type, channel=channel, message=message
        )

    def im(
        self,
        message: str,
        *,
        agent: Optional[str] = None,
        firstname: Optional[str] = None,
        lastname: Optional[str] = None,
    ) -> dict:
        """IM an avatar by UUID (``agent``) or by first+last name."""
        pairs = dict(command="tell", entity="avatar", message=message)
        if agent:
            pairs["agent"] = agent
        else:
            pairs["firstname"] = firstname
            pairs["lastname"] = lastname
        return self.command(**pairs)

    def wear_outfit(self, folder: str) -> dict:
        """Swap to an outfit folder (``changeappearance``). Retires the gizmo hack."""
        return self.command(command="changeappearance", folder=folder)

    def sit_on(self, item: str, *, range: int = 5) -> dict:
        return self.command(command="sit", item=item, range=range)

    def stand(self) -> dict:
        return self.command(command="stand")

    def walk_to(self, position: str) -> dict:
        """Walk to a local position vector like ``<128, 128, 22>``."""
        return self.command(command="walkto", position=position)

    def teleport(self, region: str, position: str, *, fly: bool = False) -> dict:
        return self.command(
            command="teleport", entity="region", region=region,
            position=position, fly=str(fly),
        )

    def play(self, item: str, *, action: str = "start", type: str = "inventory") -> dict:
        """Start/stop an animation from inventory (``animation``)."""
        return self.command(
            command="animation", item=item, action=action, type=type
        )

    def gesture(self, item: str) -> dict:
        return self.command(command="playgesture", item=item)

    def rebake(self) -> dict:
        """Force a texture rebake (fix a grey/cloud avatar)."""
        return self.command(command="rebake")

    # -- read-only conveniences (SLPerception scene assembly) -------------- #

    def self_data(self, data: str = "FirstName,LastName,Position,Region") -> dict:
        """``getselfdata`` — my own avatar's fields, as the decoded dict."""
        return self.command(command="getselfdata", data=data)

    def avatars_in_range(self, rng: int = 20, data: str = "FirstName,LastName") -> list[dict]:
        """``getavatarsdata entity=range`` — nearby avatars as a list of field dicts.

        Corrade flattens the requested fields for all avatars into one
        comma-joined ``data`` value; :func:`_group_csv` regroups by field count.
        """
        result = self.command(command="getavatarsdata", entity="range", range=rng, data=data)
        return _group_csv(result.get("data", ""), data.split(","))

    def get_parcel_music_url(self) -> Optional[str]:
        """``getparceldata data=MusicURL`` — the parcel's audio-stream URL, or None.

        The joint seam for Caia's ``MusicSense`` — wire it as::

            MusicSense(parcel_music_url=lambda: client.get_parcel_music_url())

        so the ear auto-re-points to whatever parcel this avatar stands on.

        Field name ``MusicURL`` is hardware-confirmed live (2026-08-23). Corrade
        echoes the requested field as a WAS key,value CSV — i.e. the ``data``
        value is ``"MusicURL,<url>"``, NOT the bare URL — so we strip the field
        prefix. ``partition`` keeps the value verbatim (a stream URL may itself
        contain a comma in a query string).
        """
        result = self.command(command="getparceldata", data="MusicURL")
        raw = (result.get("data") or "").strip()
        if not raw:
            return None
        key, sep, value = raw.partition(",")
        if sep and key.strip().lower() == "musicurl":
            return value.strip() or None
        # Defensive: a build that returns the bare URL with no key echo.
        if "://" in raw and "," not in raw:
            return raw or None
        return None
