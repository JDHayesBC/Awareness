"""Stub renderer — writes a tiny PNG with the prompt embedded as metadata.

Always available. Useful for testing the pipeline end-to-end without spending
tokens or having local hardware. Also the default `IMAGE_GEN_RENDERER` value
so the pipeline does *something* out of the box even with zero configuration.
"""

from __future__ import annotations

import struct
import zlib

from image_gen.renderers.base import RenderRequest, RenderResponse


class StubRenderer:
    name = "stub"

    async def render(self, request: RenderRequest) -> RenderResponse:
        # Generate a minimal valid PNG — solid 64x64 gray. The point isn't
        # the picture; it's that the pipeline produced a real file with
        # real bytes that opens in any image viewer. Prompt ends up in the
        # sidecar JSON the pipeline writes alongside.
        png = _make_solid_png(64, 64, gray=200)
        return RenderResponse(
            image_bytes=png,
            mime_type="image/png",
            renderer_used="stub",
            extras={
                "note": "stub renderer — set IMAGE_GEN_RENDERER to use a real backend",
                "prompt_chars": len(request.prompt),
                "reference_count": len(request.reference_paths),
            },
        )


def _make_solid_png(width: int, height: int, gray: int = 200) -> bytes:
    """Build a minimal solid-color grayscale PNG. ~250 bytes total."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes([gray] * width)  # filter byte + pixels
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
