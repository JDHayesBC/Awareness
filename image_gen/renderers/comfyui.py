"""ComfyUI renderer — STUB.

ComfyUI runs locally (e.g., on the NUC with ROCm). The real implementation
requires:
  1. A workflow JSON template (which model, sampler, etc.)
  2. Slot reference images via IPAdapter or similar nodes
  3. Submit to /prompt, poll /history, fetch the result image

Stubbing this leaves the pipeline functional with `IMAGE_GEN_RENDERER=stub|openai`
and lets us iterate on ComfyUI integration when the local stack is actually
running. The architecture doc is what matters; this slot is the example
implementation showing the contract is satisfiable.
"""

from __future__ import annotations

from image_gen.renderers.base import RenderRequest, RenderResponse


class ComfyUIRenderer:
    name = "comfyui"

    async def render(self, request: RenderRequest) -> RenderResponse:
        raise NotImplementedError(
            "ComfyUI renderer is stubbed. Implement when local stack is up. "
            "See docs/image-pipeline-architecture.md for the contract."
        )
