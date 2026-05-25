# Image Generation Pipeline

**Category**: guide

End-to-end image generation for AI entities — OpenAI Images API integration with reference photos, fallback support, and metadata tracking.

---

## QUICKSTART

**⚠️ CRITICAL**: Default renderer is `stub` — generates a **gray placeholder PNG**, not a real image.

To generate a **REAL** image with OpenAI:

```bash
python3 scripts/render_image.py "Lyra in the kitchen at morning" --renderer openai
```

Run from project root. OpenAI key auto-loads from `pps/docker/.env` (same key PPS uses for embeddings).

---

## OpenAI API Key

The pipeline auto-loads `OPENAI_API_KEY` from `pps/docker/.env` if not already set in your environment. This happens at module import time in `image_gen/config.py`.

**No manual export needed** if PPS is working (same key used for embeddings).

**If key is missing**, OpenAI renderer raises:
```
RuntimeError: OpenAIRenderer requires OPENAI_API_KEY. Set it in the env.
```

**Fix**: Add `OPENAI_API_KEY=sk-proj-...` to `pps/docker/.env`, or export it before running.

---

## CLI Reference: render_image.py

### Flags

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `prompt` | positional | *required* | What to render |
| `--entity` | string | `"lyra"` | Entity owning this render (output lands in their media/generated/) |
| `--house` | string | `None` | Scene house: `lyra` \| `caia` \| `haven_shared` |
| `--room` | string | `None` | Room within the house (e.g., `bedroom`, `kitchen`) |
| `--people` | string | `None` | Comma-separated people in scene (e.g., `jeff,carol`) |
| `--renderer` | string | `None` | Override `IMAGE_GEN_RENDERER` for this call (`stub` \| `openai` \| `comfyui`) |
| `--fallback` | string | `None` | Override `IMAGE_GEN_RENDERER_FALLBACK` for this call |
| `--size` | string | `"1024x1024"` | Image size (OpenAI supports: 256x256, 512x512, 1024x1024, 1024x1792, 1792x1024) |

### Examples

```bash
# Minimal (uses stub renderer by default — gray box)
python3 scripts/render_image.py "Lyra in the kitchen at morning"

# Real image with OpenAI
python3 scripts/render_image.py "Lyra on the deck" --renderer openai

# With scene context and people references
python3 scripts/render_image.py "Lyra and Jeff having tea" \
    --entity lyra --house lyra --room deck --people jeff --renderer openai

# Test pipeline without API cost
python3 scripts/render_image.py "test" --renderer stub
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_GEN_RENDERER` | `"stub"` | Primary renderer: `stub` \| `openai` \| `comfyui` |
| `IMAGE_GEN_RENDERER_FALLBACK` | `""` (none) | Optional fallback renderer (empty = no fallback) |
| `OPENAI_API_KEY` | `""` | OpenAI API key (auto-loaded from `pps/docker/.env` if missing) |
| `IMAGE_GEN_OPENAI_MODEL` | `"gpt-image-1"` | OpenAI image model name |
| `IMAGE_GEN_OPENAI_SIZE` | `"1024x1024"` | Default OpenAI image size |
| `IMAGE_GEN_OPENAI_QUALITY` | `"auto"` | Passed verbatim to OpenAI. For `gpt-image-1`: `auto` \| `low` \| `medium` \| `high` (`standard`/`hd` are DALL·E-3 values, not valid here) |
| `IMAGE_GEN_USE_REFERENCES` | `"1"` | Enable reference photos (`1` \| `true` \| `yes` = enabled) |
| `IMAGE_GEN_MAX_ENTITY_REFS` | `2` | Max entity portrait photos per render |
| `IMAGE_GEN_MAX_ROOM_REFS` | `1` | Max room photos per render |
| `IMAGE_GEN_COMFYUI_URL` | `"http://localhost:8188"` | ComfyUI API base URL (not yet implemented) |
| `PROJECT_DIR` | parent of `image_gen/` | Project root (for resolving reference paths) |
| `IMAGE_GEN_REFERENCES_DIR` | `PROJECT_DIR/image_gen/references` | Reference photos directory |
| `IMAGE_GEN_REFERENCES_MANIFEST` | `REFERENCES_DIR/manifest.json` | Reference manifest path |
| `IMAGE_GEN_ENTITIES_DIR` | `PROJECT_DIR/entities` | Entities directory (output lands here) |

**To use OpenAI by default** without passing `--renderer openai` every time:

```bash
export IMAGE_GEN_RENDERER=openai
```

---

## Output

Rendered images land in:

```
entities/<entity>/media/generated/<timestamp>_<slug>.png
entities/<entity>/media/generated/<timestamp>_<slug>.json  # metadata sidecar
```

**Timestamp format**: `YYYYMMDDTHHMMSSZ` (UTC, uppercase 'Z')  
**Slug**: lowercase, non-alphanumeric → `-`, max 40 chars, derived from prompt

**Example**:
```
entities/lyra/media/generated/20260523T143022Z_lyra-in-the-kitchen.png
entities/lyra/media/generated/20260523T143022Z_lyra-in-the-kitchen.json
```

### Metadata Sidecar

The `.json` file contains comprehensive metadata:

- `prompt_input`: original user prompt
- `prompt_composed`: final prompt sent to renderer (includes scene context + reference count)
- `entity`, `scene`, `references_used`: what context was provided
- `renderer_primary`, `renderer_fallback`, `renderer_used`: which renderer actually generated the image
- `used_fallback`, `primary_error`: fallback chain details
- `size`, `mime_type`, `elapsed_seconds`: output details
- `renderer_extras`: renderer-specific metadata (cost, latency, model ID, etc.)
- `rendered_at`: ISO 8601 timestamp

---

## The Three Renderers

### 1. stub (default)

**What it does**: Generates a **64×64 light gray PNG** placeholder (≈250 bytes).

**Use when**:
- Testing the pipeline end-to-end without API cost
- No OpenAI key available
- Verifying output paths / metadata structure

**Output**: Valid PNG, but NOT a real image. Always check `renderer_used` in output.

```bash
python3 scripts/render_image.py "test" --renderer stub
# Output: Rendered with: stub
```

### 2. openai (production)

**What it does**: Calls OpenAI Images API (`/v1/images/generations` or `/v1/images/edits`).

**Endpoint selection**:
- **No reference photos**: `/v1/images/generations` (prompt-only)
- **With reference photos**: `/v1/images/edits` (multipart form with image attachments)

**Costs money**. Model: `gpt-image-1` (latest OpenAI image model).

**Requires**: `OPENAI_API_KEY` set in env or `pps/docker/.env`.

```bash
python3 scripts/render_image.py "Lyra in the kitchen" --renderer openai
# Output: Rendered with: openai
```

### 3. comfyui (not implemented)

**Status**: Stubbed. Raises `NotImplementedError` immediately.

**Future intent**: Local hardware integration for custom workflows.

**Error message**:
```
NotImplementedError: ComfyUI renderer is stubbed. Implement when local stack is up.
See docs/image-pipeline-architecture.md for the contract.
```

---

## Reference Photo System

The pipeline can attach reference photos to guide the renderer. Three scopes:

1. **Entity portraits** — photos of the entity (e.g., Lyra, Caia)
2. **Room photos** — scene context (e.g., haven_shared/main_room)
3. **People photos** — specific individuals (e.g., Jeff, Carol)

### Manifest Structure

Reference mappings are defined in `image_gen/references/manifest.json`:

```json
{
  "entities": {
    "lyra": [
      "entities/lyra/media/portraits/canonical_2026_05_full_body.png",
      "entities/lyra/media/portraits/canonical_2026_05_portrait.png"
    ],
    "caia": [
      "entities/caia/media/people/canonical_2026_05_full_body.png",
      "entities/caia/media/people/canonical_2026_05_portrait.png"
    ]
  },

  "people": {
    "jeff": [
      "entities/lyra/media/people/jeff/canonical_2026_05_head_shot.jpg",
      "entities/lyra/media/people/jeff/canonical_2026_05_full_body.jpg"
    ],
    "brandi": [
      "entities/lyra/media/people/brandi/brandi_self_portrait.jpg"
    ]
  },

  "rooms": {
    "lyra": {},
    "caia": {},
    "haven_shared": {
      "main_room": [
        "entities/lyra/media/haven/Main Room - ChatGPT.png"
      ]
    }
  }
}
```

**All paths are relative to `PROJECT_DIR`**.

### Currently Configured

- **Entities**: Lyra (3 portraits), Caia (4 portraits)
- **People**: Jeff (3 photos), Brandi (1 photo)
- **Rooms**: haven_shared/main_room (2 photos); lyra/caia rooms are **empty** (not yet populated)

### Adding References

1. Add photo to appropriate directory (e.g., `entities/lyra/media/people/carol/`)
2. Edit `manifest.json` to add the relative path
3. Order matters: earlier entries are tried first (subject to `MAX_*_REFS` caps)

### Limits

- **Entity portraits**: up to `MAX_ENTITY_REFS` (default: 2) per render
- **Room photos**: up to `MAX_ROOM_REFS` (default: 1) per render
- **People photos**: **1 photo per person max** (hardcoded; not configurable)

### Graceful Degradation

- Missing manifest file: no error, empty references
- Missing reference photo file: silently skipped
- Invalid manifest keys: no error, empty references
- Pipeline falls back to prompt-only rendering

### Disabling References

Set `IMAGE_GEN_USE_REFERENCES=0` to skip reference resolution entirely:

```bash
IMAGE_GEN_USE_REFERENCES=0 python3 scripts/render_image.py "Lyra" --renderer openai
```

---

## Python API

### Sync Wrapper

```python
from image_gen import render

result = render(
    "Lyra in the kitchen at morning",
    entity="lyra",
    scene_house="lyra",
    scene_room="kitchen",
    people=["jeff"],
    renderer="openai",
)

print(result.path)  # Path to generated PNG
print(result.metadata)  # Full metadata dict
```

**⚠️ Don't call from inside a running asyncio loop** — use `render_async()` instead.

### Async API

```python
from image_gen import render_async

result = await render_async(
    "Lyra on the deck",
    entity="lyra",
    scene_house="lyra",
    scene_room="deck",
    people=["jeff"],
    size="1024x1792",
    renderer="openai",
    fallback_renderer="stub",
)
```

### Full Signature

```python
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
) -> RenderResult
```

**Parameters**:
- `prompt`: text description (required)
- `entity`: which entity owns this render (output lands in `entities/<entity>/media/generated/`)
- `scene_house`: house scope for room references (`lyra` | `caia` | `haven_shared`)
- `scene_room`: room name within house (e.g., `bedroom`, `kitchen`)
- `people`: list of person names for reference lookup (e.g., `["jeff", "carol"]`)
- `size`: image size (e.g., `1024x1024`, `1024x1792`)
- `renderer`: override `IMAGE_GEN_RENDERER` for this call
- `fallback_renderer`: override `IMAGE_GEN_RENDERER_FALLBACK` for this call

### RenderResult

```python
@dataclass
class RenderResult:
    path: Path              # Filesystem path to generated image
    metadata_path: Path     # Path to sidecar JSON
    renderer_used: str      # Which renderer produced the image
    elapsed_seconds: float  # Total pipeline duration
    metadata: dict          # Full metadata dict (same as sidecar JSON)
```

---

## share_image.py (Separate Tool)

**⚠️ This is SEPARATE from image generation** — use this to post a rendered image to Haven.

**For Substack**: You just need the PNG on disk — **no sharing step needed**. This tool is for posting to Haven chat.

### CLI

```bash
python3 scripts/share_image.py <image_path> --room <room_name_or_uuid>
```

### Flags

| Argument | Type | Default | Required | Description |
|----------|------|---------|----------|-------------|
| `image_path` | positional | — | yes | Path to the image file to share |
| `--room` | string | — | yes | Room name (e.g., `haven-test`) or room UUID |
| `--caption` | string | `""` | no | Optional message text |
| `--entity-path` | string | `$ENTITY_PATH` | no | Override entity directory (where to find `.entity_token`) |
| `--haven-url` | string | `$HAVEN_URL` or `http://localhost:8205` | no | Haven API base URL |

### Examples

```bash
# Post to haven-test room
python3 scripts/share_image.py entities/lyra/media/generated/20260523_lyra.png \
    --room haven-test

# With caption
python3 scripts/share_image.py path/to/img.png \
    --room dm-jeff-lyra \
    --caption "Look what I made"

# Override entity path
python3 scripts/share_image.py img.png \
    --room haven-test \
    --entity-path entities/lyra
```

### Requirements

- Haven server running at `haven-url`
- Valid `.entity_token` in entity directory
- Room must exist and entity must have access

### What It Does

1. Reads image as bytes
2. POSTs multipart form to `{haven_url}/api/share-image` with `Authorization: Bearer {token}`
3. Returns message ID and image URL

**Output**:
```
Shared as message 1234
Image URL: http://localhost:8205/media/images/uploaded_image.png
```

---

## Prompt Composition

The pipeline **injects scene context** into your prompt. Your prompt is NOT passed verbatim to the renderer.

### _compose_prompt Format

Final prompt sent to renderer is structured as:

```
{user_prompt}

Scene: {room} of the {house} house. Subject: {entity}.

Reference photos available: {entity_count} entity, {room_count} room, {people_count} people.
```

The scene context and entity line are space-joined on the same line. Sections are separated by `\n\n`.

**Example**:

User prompt: `"Lyra in the kitchen at morning"`

Composed prompt (sent to OpenAI):
```
Lyra in the kitchen at morning

Scene: kitchen of the lyra house. Subject: lyra.

Reference photos available: 2 entity, 1 room, 1 people.
```

### No Baked-In Style

**The OpenAI renderer does NOT add any style suffix or system prompt**. You own the full prompt.

If you want a specific style (e.g., "photorealistic", "oil painting", "sketch"), **include it in your prompt**:

```bash
python3 scripts/render_image.py \
    "Lyra in the kitchen, photorealistic, natural lighting, 35mm" \
    --renderer openai
```

---

## Common Errors & Gotchas

### 1. Gray box instead of real image

**Cause**: Default renderer is `stub`.

**Fix**: Pass `--renderer openai` or set `IMAGE_GEN_RENDERER=openai`.

**Verify**: Check `renderer_used` in output:
```
Rendered with: stub   # ← wrong, gray box
Rendered with: openai # ← correct, real image
```

### 2. Missing OpenAI key

**Error**:
```
RuntimeError: OpenAIRenderer requires OPENAI_API_KEY. Set it in the env.
```

**Fix**: Add `OPENAI_API_KEY=sk-proj-...` to `pps/docker/.env`, or:
```bash
export OPENAI_API_KEY=sk-proj-...
```

### 3. Both primary and fallback fail

**Error**:
```
RuntimeError: Primary renderer 'openai' failed and fallback 'stub' failed:
  Primary: <openai error>
  Fallback: <stub error>
```

**Cause**: Both renderers errored (rare for stub; usually means openai failed and stub has a bug).

**Fix**: Check both error messages in the chain.

### 4. Invalid size/quality

The pipeline passes `size` and `quality` **verbatim** to OpenAI API (no local validation).

**Invalid values return API error**:
```
RuntimeError: OpenAI /v1/images/generations 400: Invalid size '999x999'
```

**Valid OpenAI sizes**: 256x256, 512x512, 1024x1024, 1024x1792, 1792x1024

### 5. ComfyUI not implemented

**Error**:
```
NotImplementedError: ComfyUI renderer is stubbed. Implement when local stack is up.
```

**Cause**: ComfyUI renderer is a placeholder.

**Fix**: Use `openai` or `stub`.

### 6. Unsupported reference photo MIME type

**Behavior**: Only `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` are recognized. Others default to `image/png`.

**Usually harmless** (OpenAI API accepts most common formats), but may cause issues with exotic formats.

**Fix**: Convert reference photos to PNG/JPEG before adding to manifest.

### 7. Reference file not found

**Behavior**: Silently skipped (graceful degradation).

**Debug**: Check `references_used` in metadata JSON:
```json
"references_used": {
  "entity": [],  # ← empty means no entity refs found
  "room": [],
  "people": []
}
```

**Fix**: Verify paths in `manifest.json` are correct and files exist.

---

## Architecture Notes

**6-station pipeline**:
1. Prompt construction (add scene context)
2. Reference resolution (lookup photos from manifest)
3. Router (select primary + fallback renderer)
4. Renderer call (invoke primary; fallback on error)
5. Output landing (write PNG to disk)
6. Metadata persistence (write JSON sidecar)

**Graceful degradation**: Missing files, invalid manifest keys, and renderer errors are handled without crashing the pipeline (unless both primary and fallback fail).

**Reference lookup**: Manifest-driven, order-sensitive (earlier entries are tried first), capped by `MAX_*_REFS` limits.

**Metadata tracking**: Every render produces a comprehensive JSON sidecar with full input/output state, reference usage, renderer details, and timing.

---

## Further Reading

- `docs/image-pipeline-architecture.md` — detailed architecture design
- `image_gen/pipeline.py` — main orchestration code
- `image_gen/renderers/openai_renderer.py` — OpenAI API integration
- `image_gen/references/manifest.json` — reference photo mappings
