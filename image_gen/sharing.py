"""Share rendered images into Haven as messages.

Wraps Haven's /api/share-image multipart endpoint. Used by entities to push
a specific render into a chat (room or DM) — explicitly, after deciding the
image is worth showing. NOT auto-broadcast; sharing is an act of judgment.

Auth: reads the entity token from `<entity_path>/.entity_token`. By default
`entity_path` is taken from $ENTITY_PATH, but callers can pass it explicitly
(useful for sharing on behalf of a different entity from a one-off CLI run).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_HAVEN_URL = os.getenv("HAVEN_URL", "http://localhost:8205")


@dataclass
class ShareResult:
    message_id: int
    image_url: str
    room_id: str
    haven_url: str

    @property
    def absolute_image_url(self) -> str:
        return f"{self.haven_url.rstrip('/')}{self.image_url}"


def _resolve_token(entity_path: Path | str | None) -> str:
    """Read the entity token from disk."""
    if entity_path is None:
        env_ep = os.getenv("ENTITY_PATH")
        if not env_ep:
            raise RuntimeError(
                "No entity_path given and $ENTITY_PATH is not set; "
                "cannot read .entity_token"
            )
        entity_path = env_ep
    token_file = Path(entity_path) / ".entity_token"
    if not token_file.is_file():
        raise RuntimeError(f"Entity token not found at {token_file}")
    token = token_file.read_text().strip()
    if not token:
        raise RuntimeError(f"Entity token at {token_file} is empty")
    return token


def share(
    image_path: str | Path,
    room: str,
    caption: str = "",
    *,
    entity_path: Path | str | None = None,
    haven_url: str = DEFAULT_HAVEN_URL,
    timeout: float = 30.0,
) -> ShareResult:
    """Upload an image to Haven and post it as a message in `room`.

    Args:
        image_path: Path to the image file on disk.
        room: Room name (e.g. "haven-test") or room UUID.
        caption: Optional message text to accompany the image.
        entity_path: Override the entity dir (defaults to $ENTITY_PATH).
        haven_url: Override the Haven base URL (defaults to $HAVEN_URL or
            http://localhost:8205).

    Returns:
        ShareResult with the new message_id and the public image URL.
    """
    img = Path(image_path)
    if not img.is_file():
        raise FileNotFoundError(f"Image not found: {img}")

    token = _resolve_token(entity_path)

    with img.open("rb") as fh:
        files = {"image": (img.name, fh.read(), _guess_mime(img.suffix))}
    data = {"room": room, "caption": caption}

    resp = httpx.post(
        f"{haven_url.rstrip('/')}/api/share-image",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        files=files,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    return ShareResult(
        message_id=payload["id"],
        image_url=payload["image_url"],
        room_id=payload["room_id"],
        haven_url=haven_url,
    )


def _guess_mime(ext: str) -> str:
    ext = ext.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")
