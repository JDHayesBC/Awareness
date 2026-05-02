"""OpenAI image renderer.

Calls the OpenAI Images API. Reference photos are NOT yet wired (gpt-image-1
supports image-to-image via /images/edits but that requires the reference to
be a single image; multi-reference compositional needs a different shape).
For first pass: prompt-only. Reference support is a follow-up.

Auth: reads `OPENAI_API_KEY` from env (not from a file — this matches the
project's existing convention for OpenAI access).
"""

from __future__ import annotations

import base64
import os

import httpx

from image_gen.renderers.base import RenderRequest, RenderResponse


class OpenAIRenderer:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "OpenAIRenderer requires OPENAI_API_KEY. Set it in the env."
            )
        self.model = model
        self.size = size
        self.quality = quality

    async def render(self, request: RenderRequest) -> RenderResponse:
        body = {
            "model": self.model,
            "prompt": request.prompt,
            "size": request.size or self.size,
            "quality": self.quality,
            "n": 1,
        }
        # NOTE: reference_paths intentionally not yet wired (see module docstring).
        # When wired, the call shape becomes /v1/images/edits with multipart.

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        # Response shape: {"data": [{"b64_json": "..."} | {"url": "..."}], ...}
        first = (data.get("data") or [{}])[0]
        if "b64_json" in first:
            image_bytes = base64.b64decode(first["b64_json"])
        elif "url" in first:
            async with httpx.AsyncClient(timeout=60.0) as client:
                img_resp = await client.get(first["url"])
                img_resp.raise_for_status()
                image_bytes = img_resp.content
        else:
            raise RuntimeError(f"OpenAI image response missing b64_json/url: {first}")

        return RenderResponse(
            image_bytes=image_bytes,
            mime_type="image/png",
            renderer_used="openai",
            extras={
                "model": self.model,
                "size": body["size"],
                "quality": self.quality,
                "usage": data.get("usage", {}),
            },
        )
