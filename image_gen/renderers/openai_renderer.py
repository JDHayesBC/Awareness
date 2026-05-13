"""OpenAI image renderer.

Calls the OpenAI Images API. Two paths:

- No reference photos -> /v1/images/generations (JSON, prompt-only).
- One or more reference photos -> /v1/images/edits (multipart). gpt-image-1
  accepts multiple image[] inputs and uses them as visual conditioning, so a
  request with the entity's portrait + a room photo will produce a render
  that looks like *that entity* in *that room*.

Auth: reads `OPENAI_API_KEY` from env (not from a file — this matches the
project's existing convention for OpenAI access).
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

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
        size = request.size or self.size
        if request.reference_paths:
            data = await self._render_edits(request, size)
            endpoint_used = "edits"
        else:
            data = await self._render_generations(request, size)
            endpoint_used = "generations"

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
                "size": size,
                "quality": self.quality,
                "endpoint": endpoint_used,
                "reference_count": len(request.reference_paths),
                "usage": data.get("usage", {}),
            },
        )

    async def _render_generations(self, request: RenderRequest, size: str) -> dict:
        body = {
            "model": self.model,
            "prompt": request.prompt,
            "size": size,
            "quality": self.quality,
            "n": 1,
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"OpenAI /v1/images/generations {resp.status_code}: {resp.text}"
                )
            return resp.json()

    async def _render_edits(self, request: RenderRequest, size: str) -> dict:
        # gpt-image-1 /edits accepts multiple inputs as `image[]`. We send each
        # reference path as a separate file in the multipart body. Quality and
        # size still apply.
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for ref in request.reference_paths:
            ref_path = Path(ref)
            mime, _ = mimetypes.guess_type(ref_path.name)
            mime = mime or "image/png"
            files.append(
                ("image[]", (ref_path.name, ref_path.read_bytes(), mime))
            )
        data = {
            "model": self.model,
            "prompt": request.prompt,
            "size": size,
            "quality": self.quality,
            "n": "1",
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"OpenAI /v1/images/edits {resp.status_code}: {resp.text}"
                )
            return resp.json()
