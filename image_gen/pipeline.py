"""Pipeline orchestration — composes prompt, resolves references, dispatches
to a renderer, lands the output, persists metadata.

Stations (see docs/image-pipeline-architecture.md):
  1. prompt-construction
  2. reference-photo resolution
  3. router (renderer selection)
  4. renderer call (with optional fallback)
  5. output landing
  6. metadata persistence

Public surface is `render()` (sync convenience) and `render_async()`.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from image_gen import config, references
from image_gen.renderers.base import Renderer, RenderRequest


@dataclass
class RenderResult:
    """The product of a render: where the file landed, and what we know about it."""

    path: Path
    metadata_path: Path
    renderer_used: str
    elapsed_seconds: float
    metadata: dict


# ==================== Renderer registry ====================


def _get_renderer(name: str) -> Renderer:
    """Return a Renderer by config name. Raises if name is unknown."""
    name = (name or "").lower()
    if name == "stub":
        from image_gen.renderers.stub import StubRenderer
        return StubRenderer()
    if name == "openai":
        from image_gen.renderers.openai_renderer import OpenAIRenderer
        return OpenAIRenderer(
            model=config.OPENAI_IMAGE_MODEL,
            size=config.OPENAI_IMAGE_SIZE,
            quality=config.OPENAI_IMAGE_QUALITY,
        )
    if name == "comfyui":
        from image_gen.renderers.comfyui import ComfyUIRenderer
        return ComfyUIRenderer()
    raise ValueError(
        f"Unknown renderer: {name!r}. "
        f"Set IMAGE_GEN_RENDERER to one of: stub, openai, comfyui."
    )


# ==================== Prompt construction ====================


def _compose_prompt(
    user_prompt: str,
    *,
    entity: str | None,
    house: str | None,
    room: str | None,
    refs: references.ReferenceSet,
) -> str:
    """Compose the final prompt text from the user prompt + scene context.

    The pipeline does NOT inject visual references as text descriptions — that's
    the renderer's job (image-to-image, IPAdapter, etc.). What this function
    does is contextualize: if we know we're in Lyra's bedroom, mention that.
    """
    parts: list[str] = [user_prompt.strip()]
    scene_bits: list[str] = []
    if room and house:
        scene_bits.append(f"Scene: {room} of the {house} house.")
    elif room:
        scene_bits.append(f"Scene: {room}.")
    if entity:
        scene_bits.append(f"Subject: {entity}.")
    if scene_bits:
        parts.append(" ".join(scene_bits))
    if refs.entity_paths or refs.room_paths or refs.people_paths:
        parts.append(
            f"Reference photos available: "
            f"{len(refs.entity_paths)} entity, "
            f"{len(refs.room_paths)} room, "
            f"{len(refs.people_paths)} people."
        )
    return "\n\n".join(parts)


# ==================== Output landing ====================


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "render"


def _output_paths(entity: str, prompt: str) -> tuple[Path, Path]:
    """Compute (image_path, metadata_path) for a render. Creates parent dir."""
    out_dir = config.get_output_dir(entity)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = _slugify(prompt)
    base = f"{ts}_{slug}"
    return out_dir / f"{base}.png", out_dir / f"{base}.json"


# ==================== Main pipeline ====================


async def render_async(
    prompt: str,
    *,
    entity: str = "lyra",
    scene_house: str | None = None,
    scene_room: str | None = None,
    people: list[str] | None = None,
    size: str = "1024x1024",
    renderer: str | None = None,
    fallback_renderer: str | None = None,
) -> RenderResult:
    """Run the pipeline. Returns a RenderResult once the image is on disk.

    `entity` — which entity is rendering this; output lands under their media/.
    `scene_house` — "lyra" | "caia" | "haven_shared" — which house's room refs.
    `scene_room` — room name within the house; pulls room reference photos.
    `people` — additional people to pull reference photos for.
    `renderer` — override the configured renderer for this call.
    `fallback_renderer` — override the configured fallback for this call.
    """
    t0 = time.time()

    # Station 2: reference resolution
    refs = (
        references.resolve(
            entity=entity, house=scene_house, room=scene_room, people=people
        )
        if config.USE_REFERENCES
        else references.ReferenceSet([], [], [])
    )

    # Station 1: prompt construction
    composed_prompt = _compose_prompt(
        prompt,
        entity=entity,
        house=scene_house,
        room=scene_room,
        refs=refs,
    )

    request = RenderRequest(
        prompt=composed_prompt,
        reference_paths=refs.all_paths,
        size=size,
    )

    # Station 3+4: router + renderer (with optional fallback)
    primary_name = renderer or config.RENDERER
    fallback_name = (
        fallback_renderer
        if fallback_renderer is not None
        else config.RENDERER_FALLBACK
    )

    primary_error: Exception | None = None
    response = None
    used_fallback = False

    try:
        primary = _get_renderer(primary_name)
        response = await primary.render(request)
    except Exception as e:  # noqa: BLE001 - we want to log everything and try fallback
        primary_error = e

    if response is None:
        if not fallback_name:
            # Per Jeff: fallback is OPTIONAL, not mandatory. Surface the error.
            raise RuntimeError(
                f"Primary renderer {primary_name!r} failed and no fallback configured: "
                f"{primary_error}"
            )
        try:
            fb = _get_renderer(fallback_name)
            response = await fb.render(request)
            used_fallback = True
        except Exception as fb_error:  # noqa: BLE001
            raise RuntimeError(
                f"Both renderers failed. Primary {primary_name!r}: {primary_error}. "
                f"Fallback {fallback_name!r}: {fb_error}"
            ) from fb_error

    # Station 5: output landing
    image_path, metadata_path = _output_paths(entity, prompt)
    image_path.write_bytes(response.image_bytes)

    elapsed = time.time() - t0

    # Station 6: metadata persistence
    metadata = {
        "prompt_input": prompt,
        "prompt_composed": composed_prompt,
        "entity": entity,
        "scene": {"house": scene_house, "room": scene_room, "people": people or []},
        "references_used": {
            "entity": [str(p) for p in refs.entity_paths],
            "room": [str(p) for p in refs.room_paths],
            "people": [str(p) for p in refs.people_paths],
        },
        "renderer_primary": primary_name,
        "renderer_fallback": fallback_name or None,
        "renderer_used": response.renderer_used or primary_name,
        "used_fallback": used_fallback,
        "primary_error": str(primary_error) if primary_error else None,
        "size": size,
        "mime_type": response.mime_type,
        "elapsed_seconds": elapsed,
        "renderer_extras": response.extras,
        "rendered_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))

    return RenderResult(
        path=image_path,
        metadata_path=metadata_path,
        renderer_used=metadata["renderer_used"],
        elapsed_seconds=elapsed,
        metadata=metadata,
    )


def render(prompt: str, **kwargs) -> RenderResult:
    """Sync convenience wrapper. Don't call from inside a running loop."""
    return asyncio.run(render_async(prompt, **kwargs))


__all__ = ["RenderResult", "render", "render_async"]
