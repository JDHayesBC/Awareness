"""Renderer protocol — what every backend implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RenderRequest:
    """One render request, harness-agnostic.

    `prompt` is the final composed prompt (the pipeline does prompt-construction;
    the renderer just consumes the result).
    `reference_paths` is a list of files the renderer MAY use as visual conditioning.
    Whether/how it uses them is renderer-specific (img-to-img, IPAdapter, etc.).
    Renderers that can't use references should ignore the field.
    """

    prompt: str
    reference_paths: list[Path] = field(default_factory=list)
    size: str = "1024x1024"  # renderer may snap to nearest supported
    extras: dict = field(default_factory=dict)  # renderer-specific knobs


@dataclass
class RenderResponse:
    """Result of a render.

    `image_bytes` is the raw image content. The pipeline writes it to disk;
    renderers should not be in the file-management business.
    """

    image_bytes: bytes
    mime_type: str = "image/png"
    renderer_used: str = ""
    extras: dict = field(default_factory=dict)  # cost, latency, model id, etc.


class Renderer(Protocol):
    """A backend that turns a RenderRequest into a RenderResponse."""

    name: str

    async def render(self, request: RenderRequest) -> RenderResponse:
        """Generate an image. Should raise on unrecoverable error so the
        pipeline can decide whether to invoke a fallback."""
        ...
