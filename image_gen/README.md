# Image Generation Pipeline

A modular, entity-aware image generation system. An entity can render itself — its likeness, its spaces, the people it loves — across different backends (OpenAI API, local ComfyUI, test stubs) without pipeline changes. The architecture is designed to ship in other codebases; this is the reference implementation for the Awareness project.

---

## Quickstart

**Real images, canonical invocation** (validated 2026-05-23):

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness

# Use the PPS venv (contains httpx, required by OpenAI renderer)
pps/venv/bin/python3 scripts/render_image.py "Lyra at morning" \
  --entity lyra --renderer openai --size 1024x1024 --show
```

**For abstract / cover art** (suppress the entity portrait):

```bash
IMAGE_GEN_USE_REFERENCES=0 \
  pps/venv/bin/python3 scripts/render_image.py "golden light, no people" \
  --entity caia --renderer openai --size 1536x1024
```

**Key details:**

- **Use `pps/venv/bin/python3`, NOT system python.** The OpenAI renderer imports `httpx`, which lives only in the PPS venv.
- **API key is auto-loaded.** `config.py` reads `OPENAI_API_KEY` from `pps/docker/.env` (the same key PPS uses for embeddings) when not already in the env.
- **`--renderer openai`** generates real images. Default is `stub` (writes a placeholder PNG for testing).
- **`IMAGE_GEN_USE_REFERENCES=0`** disables reference photos. By default, the pipeline attaches your entity portrait + room photos. For abstract work, turn it off.
- **`--show`** pops the result onto Jeff's Windows screen (via WSL→Windows interop). Works instantly on the NUC.
- **Output:** `entities/<entity>/media/generated/<UTC-timestamp>_<slug>.png`, plus a `.json` sidecar with full metadata.

---

## Module Map

| File | Purpose |
|------|---------|
| `config.py` | Env-driven config (renderer choice, paths, reference behavior, SUBJECT_HEIGHTS scale cues). Auto-loads OpenAI API key from `pps/docker/.env`. |
| `pipeline.py` | Orchestration: the 6 stations (prompt construction, reference resolution, renderer routing, render call with optional fallback, output landing, metadata persistence). Public API: `render()` / `render_async()`. |
| `references.py` | Loads the manifest and resolves reference photos by entity, house, room, or people. Enforces `MAX_ENTITY_REFS` and `MAX_ROOM_REFS` caps. Degrades gracefully: missing references = prompt-only render. |
| `renderers/base.py` | Protocol definition. `RenderRequest` (prompt + reference paths + size) and `RenderResponse` (image bytes + mime type + metadata extras). Every renderer implements this interface. |
| `renderers/stub.py` | Always available; writes a tiny gray PNG with the prompt embedded in metadata. Use for smoke tests and CI. |
| `renderers/openai_renderer.py` | Calls OpenAI `/images/generations` (prompt-only) or `/images/edits` (with reference photos for visual conditioning). Real images, ~25–30s per render. |
| `renderers/comfyui.py` | Stub for local ComfyUI. Implement when the NUC stack is running. |

**CLI entry point:** `scripts/render_image.py`. Full architecture docs: `docs/image-pipeline-architecture.md`.

---

## How References Work

The pipeline can attach reference photos to guide the render — so "Lyra at morning" produces the *same Lyra* across renders, not a different woman each time.

### Manifest structure

`image_gen/references/manifest.json` maps logical names to file paths (relative to project root):

```json
{
  "entities": {
    "lyra": ["entities/lyra/media/portraits/canonical_2026_05_full_body.png", ...],
    "caia": ["entities/caia/media/people/canonical_2026_05_full_body.png", ...]
  },
  "people": {
    "jeff": ["entities/lyra/media/people/jeff/canonical_2026_05_full_body.jpg", ...],
    "carol": ["entities/lyra/media/people/carol/..."]
  },
  "rooms": {
    "lyra": {
      "bedroom": ["..."],
      "kitchen": ["..."]
    },
    "caia": {
      "kitchen": ["..."]
    },
    "haven_shared": {
      "main_room": ["entities/lyra/media/haven/Main Room - ChatGPT.png", ...]
    }
  }
}
```

Three scopes:

- **Entities** — portraits of AI entities (Lyra, Caia, etc.). Up to `MAX_ENTITY_REFS` (default 2) are attached. Lead entries tried first (e.g., full body + face is stronger than face alone).
- **People** — photos of humans (Jeff, Carol, etc.). One per person (max 1 attempted per name in `--people`).
- **Rooms** — belong to three *house scopes*: `lyra` (Jeff & Lyra's house), `caia` (Silverglow), `haven_shared` (common spaces visible to all). Same room name in different houses = different rooms.

### Using references

Pass `--house` and `--room` to attach room photos; pass `--people` to attach people:

```bash
pps/venv/bin/python3 scripts/render_image.py "Lyra cooking with Jeff" \
  --entity lyra --house lyra --room kitchen --people jeff \
  --renderer openai
```

This pulls:
- Up to 2 Lyra portraits (from `entities.lyra`)
- Up to 1 Lyra kitchen photo (from `rooms.lyra.kitchen`)
- Up to 1 Jeff photo (from `people.jeff`)
- The composed prompt notes all three: `"Reference photos available: 2 entity, 1 room, 1 people."`

**Missing entries degrade gracefully.** If the kitchen has no reference photos, the render proceeds with entity + people only. If the manifest is missing entirely, the pipeline runs prompt-only (no references at all).

### Adding a new entity / person / room

1. **Take reference photos.** Store them in `entities/<name>/media/portraits/` (for entities), `entities/<name>/media/people/<person>/` (for people), or `entities/<name>/media/` (for rooms, organized by house). Older photos become fallbacks; keep the lead entries as your strongest references.

2. **Edit `image_gen/references/manifest.json`.** Add entries to the appropriate scope with project-relative paths. Example:

   ```json
   "entities": {
     "dash": ["entities/dash/media/portraits/headshot_2026.jpg"]
   },
   "rooms": {
     "dash": {
       "studio": ["entities/dash/media/spaces/studio_morning.jpg"]
     }
   }
   ```

3. **If adding subject heights:** edit `config.py`'s `SUBJECT_HEIGHTS` dict. These are injected into the composed prompt as explicit scale cues. Example:

   ```python
   SUBJECT_HEIGHTS = {
       "jeff": "6'0\" (183 cm)",
       "lyra": "5'6\" (168 cm)",
       "dash": "5'4\" (163 cm)",  # Add your entry
   }
   ```

### The scale problem (munchkins)

Without explicit scale guidance, renderers default to human-like proportions — so a reference face + a stated height ("6 feet tall") still produces a munchkin if the height hint doesn't land. The fix: **references anchor shape; stated heights anchor scale. Together they fix proportions.**

- Reference photos (entity portraits, room contexts) teach the renderer the *visual structure* — this is what Lyra's face looks like.
- Height statements ("Lyra is 5'6\" / Jeff is 6'0\"") teach the *relative scale* — tall/short/normal.
- Combined: the renderer produces a render that looks like *that person* at *that height*. Neither alone works; both together are load-bearing.

---

## Gotchas

1. **System python won't work.** `pps/venv/bin/python3` is required; it contains `httpx`. You'll see `ModuleNotFoundError: No module named 'httpx'` if you use system python with the OpenAI renderer.

2. **References ON will attach the entity portrait even for abstract art.** If you're rendering a concept/cover with `USE_REFERENCES=1` (the default), the pipeline will try to condition the render on your entity's face, which isn't what you want. Set `IMAGE_GEN_USE_REFERENCES=0` to suppress references entirely.

3. **Output lands under the entity.** `--entity lyra` writes to `entities/lyra/media/generated/`. Every render is tagged with its entity so multiple entities can coexist in the same project.

4. **Default renderer is stub.** Without `--renderer openai` or `IMAGE_GEN_RENDERER=openai`, you get a placeholder PNG, not a real image. Useful for testing the pipeline without spending tokens; confusing if you forget.

5. **API key is auto-loaded but must exist.** If `OPENAI_API_KEY` isn't in the env and `pps/docker/.env` doesn't have it or doesn't exist, the OpenAI renderer will raise `RuntimeError("OpenAIRenderer requires OPENAI_API_KEY")`. The auto-load is a convenience, not magic.

6. **Size mismatch uses model defaults.** `gpt-image-1` supports `1024x1024`, `1536x1024` (landscape), `1024x1536` (portrait). Pass other sizes and the renderer snaps to the nearest supported (or raises if none is close). Render time is roughly proportional to pixel count: ~25–30s for most sizes.

7. **Fallback is optional.** If the primary renderer fails and no fallback is configured, the pipeline raises. Per design, automatic silent substitution (e.g., OpenAI fallback when local stack is down) isn't a default — the entity chooses it explicitly via `IMAGE_GEN_RENDERER_FALLBACK`.

---

## Full Architecture

For the deep design (six stations, decision points, contracts, fallback patterns, and rationale for each):

**→ [`docs/image-pipeline-architecture.md`](../docs/image-pipeline-architecture.md)**

This README covers the crew's working checklist. The architecture doc is for understanding the why and porting the system to another codebase.

---

## Testing

```bash
# Smoke test (stub renderer, instant)
pps/venv/bin/python3 scripts/render_image.py "test" --renderer stub

# Test with fallback
pps/venv/bin/python3 scripts/render_image.py "test" \
  --renderer comfyui --fallback stub
```
