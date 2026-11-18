"""Say when something was said, the same way in every search result.

A retrieved line with no date gets read as current, and one with no speaker gets
credited to whoever seems likely. Every layer that hands text back to a reader
uses these helpers so the time is never dropped. All times are UTC.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional


_STAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?"
)


def parse_utc(stamp) -> Optional[datetime]:
    """A stored time -> aware UTC datetime, or None when it cannot be read.

    Accepts SQLite text ("2026-03-10 07:00:00"), a datetime, and Neo4j DateTime
    values (via str(): "2026-03-10T07:00:00.000000000+00:00"). Text with no
    offset is taken as UTC, which is how both stores write it.
    """
    if stamp is None:
        return None
    if isinstance(stamp, datetime):
        then = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        return then.astimezone(timezone.utc)
    m = _STAMP_RE.match(str(stamp).strip())
    if not m:
        return None
    try:
        then = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    offset = m.group(3)
    if offset and offset != "Z":
        digits = offset[1:].replace(":", "")
        delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        then = then - delta if offset[0] == "+" else then + delta
    return then.replace(tzinfo=timezone.utc)


def when_text(then: datetime) -> str:
    """"2026-03-10 11:48 UTC"."""
    return then.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def age_text(then: datetime, now: Optional[datetime] = None) -> str:
    """How long ago, in one unit: "12 min ago", "5 h ago", "3 days ago"."""
    seconds = ((now or datetime.now(timezone.utc)) - then).total_seconds()
    if seconds < 0:
        return "in the future"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"
