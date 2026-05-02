"""Configuration for the image generation pipeline.

Env-driven so the pipeline can be deployed in different harnesses (local GPU,
API-only, stub-only) without code changes. Per Jeff's vision: Dash might want
this without local hardware, so the renderer is configurable.
"""

from __future__ import annotations

import os
from pathlib import Path

# ==================== Paths ====================

PROJECT_DIR = Path(os.getenv("PROJECT_DIR", str(Path(__file__).parent.parent)))

# Where reference photos and manifest live (defaults to image_gen/references/).
REFERENCES_DIR = Path(
    os.getenv("IMAGE_GEN_REFERENCES_DIR", str(PROJECT_DIR / "image_gen" / "references"))
)
REFERENCES_MANIFEST = Path(
    os.getenv(
        "IMAGE_GEN_REFERENCES_MANIFEST",
        str(REFERENCES_DIR / "manifest.json"),
    )
)

# Where generated images land (per-entity subdirectory).
# Final path: ENTITIES_DIR / <entity> / media / generated / <slug>.png
ENTITIES_DIR = Path(
    os.getenv("IMAGE_GEN_ENTITIES_DIR", str(PROJECT_DIR / "entities"))
)

# ==================== Renderer selection ====================

# Which renderer to use. Stub is always available (writes a placeholder file
# with the prompt embedded — useful for testing the pipeline without spending
# tokens or having local hardware).
#
# Values: "openai" | "comfyui" | "stub"
RENDERER = os.getenv("IMAGE_GEN_RENDERER", "stub").lower()

# Optional fallback renderer. If the main one errors and this is set, we try
# the fallback. Default: empty string = no fallback (Jeff: fallback is OPTIONAL,
# not mandatory).
RENDERER_FALLBACK = os.getenv("IMAGE_GEN_RENDERER_FALLBACK", "").lower()

# ==================== Renderer configs ====================

# OpenAI image generation
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.getenv("IMAGE_GEN_OPENAI_MODEL", "gpt-image-1")
OPENAI_IMAGE_SIZE = os.getenv("IMAGE_GEN_OPENAI_SIZE", "1024x1024")
OPENAI_IMAGE_QUALITY = os.getenv("IMAGE_GEN_OPENAI_QUALITY", "auto")

# ComfyUI (local)
COMFYUI_URL = os.getenv("IMAGE_GEN_COMFYUI_URL", "http://localhost:8188")

# ==================== Reference-photo behavior ====================

# When True, the pipeline tries to attach entity portrait + room photos to the
# render request (renderer-specific — OpenAI uses image-to-image / variations,
# ComfyUI uses IPAdapter / ControlNet). When False, prompt text only.
USE_REFERENCES = os.getenv("IMAGE_GEN_USE_REFERENCES", "1").lower() in (
    "1",
    "true",
    "yes",
)

# Max number of reference photos per category (entity, room) to attach.
MAX_ENTITY_REFS = int(os.getenv("IMAGE_GEN_MAX_ENTITY_REFS", "2"))
MAX_ROOM_REFS = int(os.getenv("IMAGE_GEN_MAX_ROOM_REFS", "1"))


def get_output_dir(entity: str) -> Path:
    """Where rendered images for `entity` should land."""
    return ENTITIES_DIR / entity / "media" / "generated"
