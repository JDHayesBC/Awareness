"""Outgoing credential redactor (GH #372).

On 2026-10-15 a live API key was posted by the Haven bot into a shared room and
nothing on the outgoing path could have stopped it. This module is the filter:
known secret values (from the project .env and process env) are replaced
exactly, then well-known token prefixes, then a generic "long random-looking
token" pattern. Values are never logged or returned in hits -- only kind,
length and span.

Spans in ``Hit`` refer to the ORIGINAL text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, Sequence

REDACTED = "[redacted]"
MIN_SECRET_LEN = 12

_SECRET_KEY_RE = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD|_PASS|KEY)$", re.IGNORECASE)

# 32+ token chars containing at least one letter AND one digit, not embedded in
# a longer token run. Pure-hex 40-char strings (git SHAs) are exempted in code.
GENERIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*[0-9])"
    r"[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])"
)
_HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
# Canonical UUIDs (room ids, session ids, graph edge ids) are everyday chatter, not
# secrets. Entity tokens ARE UUIDs, but they arrive via the known-values net
# (ENTITY_TOKEN in the process env), so exempting the shape here is safe.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ALPHA_WORD_RE = re.compile(r"^[A-Za-z]{4,}$")


def _looks_like_slug(token: str) -> bool:
    """A hyphen/underscore-joined slug (file names, arc names, dates) rather than a
    random token: 3+ segments, at least one of which is a plain word of 4+ letters.
    Random tokens with separators (UUIDs, base62 keys) essentially never contain a
    pure-alphabetic 4+ letter segment; slugs almost always do."""
    parts = [p for p in re.split(r"[-_]", token) if p]
    return len(parts) >= 3 and any(_ALPHA_WORD_RE.match(p) for p in parts)

PREFIXED_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[abp]-[A-Za-z0-9\-]{20,}"),
)
# Only the token part is replaced. Requires a digit and 16+ chars so prose like
# "Bearer authentication" is left alone.
_BEARER_RE = re.compile(r"(?i:Bearer)\s+((?=[A-Za-z0-9._~+/=\-]*[0-9])[A-Za-z0-9._~+/=\-]{16,})")


@dataclass
class Hit:
    kind: Literal["known", "generic", "prefixed"]
    length: int
    span: tuple[int, int]


@dataclass
class RedactResult:
    text: str
    hits: list[Hit] = field(default_factory=list)


# ---------------------------------------------------------------- secret loading

def _default_env_path() -> Path:
    project_dir = Path(os.getenv("PROJECT_DIR", str(Path(__file__).parent.parent)))
    return project_dir / "pps" / "docker" / ".env"


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:  # inline comment on an unquoted value
            val = val.split(" #", 1)[0].rstrip()
        out[key] = val
    return out


def load_secret_values(
    env_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> set[str]:
    """Collect secret-looking values from a dotenv file and the process env."""
    path = env_path if env_path is not None else _default_env_path()
    environ = os.environ if environ is None else environ
    secrets: set[str] = set()
    for source in (_parse_dotenv(Path(path)), dict(environ)):
        for key, val in source.items():
            if _SECRET_KEY_RE.search(key) and len(val) >= MIN_SECRET_LEN:
                secrets.add(val)
    return secrets


_known_cache: set[str] | None = None


def get_known_secrets() -> set[str]:
    """Lazily load (once) and return the known secret values."""
    global _known_cache
    if _known_cache is None:
        _known_cache = load_secret_values()
    return _known_cache


def reload_known_secrets() -> set[str]:
    """Drop the cache and reload."""
    global _known_cache
    _known_cache = None
    return get_known_secrets()


# ---------------------------------------------------------------- redaction

def _find_spans(text: str, known: set[str]) -> list[Hit]:
    claimed: list[Hit] = []

    def free(s: int, e: int) -> bool:
        return all(e <= h.span[0] or s >= h.span[1] for h in claimed)

    def claim(kind: str, s: int, e: int) -> None:
        if free(s, e):
            claimed.append(Hit(kind, e - s, (s, e)))  # type: ignore[arg-type]

    for val in sorted((v for v in known if v), key=len, reverse=True):
        start = 0
        while (i := text.find(val, start)) != -1:
            claim("known", i, i + len(val))
            start = i + len(val)
    for rx in PREFIXED_RES:
        for m in rx.finditer(text):
            claim("prefixed", m.start(), m.end())
    for m in _BEARER_RE.finditer(text):
        claim("prefixed", m.start(1), m.end(1))
    for m in GENERIC_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if _HEX40_RE.match(tok) or _UUID_RE.match(tok) or _looks_like_slug(tok):
            continue
        claim("generic", m.start(), m.end())
    return sorted(claimed, key=lambda h: h.span)


def redact(text: str, *, known: set[str], allow: bool) -> RedactResult:
    """Redact credentials. With allow=True the text is unchanged but hits are reported."""
    if not text:
        return RedactResult(text=text, hits=[])
    hits = _find_spans(text, known)
    if allow or not hits:
        return RedactResult(text=text, hits=hits)
    parts: list[str] = []
    pos = 0
    for h in hits:
        parts.append(text[pos:h.span[0]])
        parts.append(REDACTED)
        pos = h.span[1]
    parts.append(text[pos:])
    return RedactResult(text="".join(parts), hits=hits)


def redact_for_room(text: str, *, is_private_human_dm: bool, known: set[str]) -> RedactResult:
    """Redact unless the room is a private DM with a human."""
    return redact(text, known=known, allow=is_private_human_dm)


# ---------------------------------------------------------------- room privacy

DEFAULT_ALLOWED_HUMANS: frozenset[str] = frozenset({"jeff"})


def allowed_humans(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """HAVEN_REDACT_ALLOW_USERS: comma-separated usernames whose private DM may carry
    credentials (allow-but-log). Default: jeff only. Credentials are never allowed in
    a DM with any other human (Crusher, Jaden, Night, ...) -- "credentials in chat is
    a no" is Jeff's rule, and the exception is his DM, not DMs in general."""
    environ = os.environ if environ is None else environ
    raw = environ.get("HAVEN_REDACT_ALLOW_USERS")
    if raw is None:
        return DEFAULT_ALLOWED_HUMANS
    return frozenset(u.strip().lower() for u in raw.split(",") if u.strip())


def is_private_human_dm(
    room: Mapping | None,
    members: Sequence[Mapping] | None,
    my_username: str,
    known_bots: set[str] | frozenset[str] = frozenset(),
    allowed: frozenset[str] | set[str] | None = None,
) -> bool:
    """True only when we can positively show: DM room, exactly two members
    (us + one other), the other is a human, AND that human is on the allow-list
    (default: jeff). Anything unknown -> False (treated as shared, so redaction
    applies).

    ``room``: the ``connected``-payload room record (needs ``is_dm``).
    ``members``: the ``/api/rooms/{id}/members`` list (``username``, ``is_bot``).
    """
    if not room or not room.get("is_dm") or not members:
        return False
    others = [m for m in members if m.get("username") != my_username]
    if len(members) != 2 or len(others) != 1:
        return False
    other = others[0]
    if other.get("is_bot") or other.get("username") in known_bots:
        return False
    name = (other.get("username") or "").lower()
    allow = DEFAULT_ALLOWED_HUMANS if allowed is None else allowed
    return bool(name) and name in allow


def resolve_redact_mode(environ: Mapping[str, str] | None = None) -> str:
    """HAVEN_REDACT_MODE: strict (default) | log | off. Unknown values -> strict."""
    environ = os.environ if environ is None else environ
    mode = (environ.get("HAVEN_REDACT_MODE") or "strict").strip().lower()
    return mode if mode in ("strict", "log", "off") else "strict"
