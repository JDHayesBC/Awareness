"""image_gen — entity-facing image generation pipeline.

Architecture-first: see docs/image-pipeline-architecture.md for the manuscript.
This is the reference implementation for entities running on this codebase;
other harnesses are expected to generate their own from the architecture doc.

Public surface:
    from image_gen import render
    result = render(prompt, entity="lyra", scene_house="lyra", scene_room="bedroom")
    # result.path is the saved image; result.metadata is the sidecar dict
"""

from image_gen.pipeline import RenderResult, render, render_async

__all__ = ["RenderResult", "render", "render_async"]
