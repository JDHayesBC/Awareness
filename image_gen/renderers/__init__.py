"""Pluggable renderer backends.

Each renderer implements the `Renderer` protocol from `base.py`. The pipeline
selects one at runtime based on `IMAGE_GEN_RENDERER`. Adding a new backend
means dropping a new module here and registering it in `pipeline._get_renderer`.
"""

from image_gen.renderers.base import Renderer, RenderRequest, RenderResponse

__all__ = ["Renderer", "RenderRequest", "RenderResponse"]
