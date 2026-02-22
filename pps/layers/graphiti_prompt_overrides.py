"""
Graphiti prompt library overrides.

Replaces the default dedupe_edges.resolve_edge prompt with an improved
version that makes index constraints explicit, reducing out-of-range
index errors from smaller models (Claude Haiku).

Root cause: Graphiti's default resolve_edge prompt presents two separately
indexed lists (EXISTING FACTS and INVALIDATION CANDIDATES, both starting at
idx 0) without telling the model how many items are in each list. Haiku
frequently returns indices beyond the valid range, causing ingestion failures.

Fix: Inject explicit count + max-index into the prompt header, and add a
one-shot example that shows correct empty-list behavior.

Usage:
    from pps.layers.graphiti_prompt_overrides import apply_prompt_overrides
    apply_prompt_overrides()  # Call once after graphiti_core is imported
"""

from typing import Any


def _resolve_edge_improved(context: dict[str, Any]) -> list:
    """
    Improved resolve_edge prompt with explicit index range constraints.

    Identical in structure to the original but adds:
    - Explicit count and max index for each list in the task header
    - Hard constraint: "Do NOT return any index >= N"
    - One-shot example showing correct empty-list response
    - Clearer separation between the two list scopes
    """
    # Import Message lazily to avoid circular imports at module load time
    from graphiti_core.prompts.models import Message

    existing = context.get('existing_edges', [])
    candidates = context.get('edge_invalidation_candidates', [])
    n_existing = len(existing)
    n_candidates = len(candidates)

    # Build range constraint strings
    if n_existing == 0:
        existing_range = "EXISTING FACTS list is EMPTY — duplicate_facts MUST be []"
    else:
        existing_range = (
            f"EXISTING FACTS has {n_existing} item(s), idx 0 through {n_existing - 1}. "
            f"Do NOT return any index >= {n_existing}."
        )

    if n_candidates == 0:
        candidates_range = "INVALIDATION CANDIDATES list is EMPTY — contradicted_facts MUST be []"
    else:
        candidates_range = (
            f"INVALIDATION CANDIDATES has {n_candidates} item(s), idx 0 through {n_candidates - 1}. "
            f"Do NOT return any index >= {n_candidates}."
        )

    import json
    existing_json = json.dumps(existing, ensure_ascii=False)
    candidates_json = json.dumps(candidates, ensure_ascii=False)

    return [
        Message(
            role='system',
            content=(
                'You are a helpful assistant that de-duplicates facts from fact lists '
                'and determines which existing facts are contradicted by a new fact.'
            ),
        ),
        Message(
            role='user',
            content=f"""Task:
You will receive TWO separate lists of facts. Each list uses 'idx' as its index field, starting from 0.
The lists have INDEPENDENT index ranges — they do not share indices.

INDEX CONSTRAINTS (read carefully before responding):
- {existing_range}
- {candidates_range}

1. DUPLICATE DETECTION:
   - If NEW FACT represents identical factual information as any fact in EXISTING FACTS, return those idx values in duplicate_facts.
   - Facts with similar information that contain key differences should NOT be marked as duplicates.
   - Return idx values ONLY from EXISTING FACTS (idx 0 through {n_existing - 1 if n_existing > 0 else 'N/A'}).
   - If no duplicates, return an empty list [].

2. FACT TYPE CLASSIFICATION:
   - Given the predefined FACT TYPES, determine if NEW FACT should be classified as one of these types.
   - Return the fact type as fact_type, or DEFAULT if not one of the FACT TYPES.

3. CONTRADICTION DETECTION:
   - Determine which INVALIDATION CANDIDATES the new fact contradicts.
   - Return idx values ONLY from INVALIDATION CANDIDATES (idx 0 through {n_candidates - 1 if n_candidates > 0 else 'N/A'}).
   - If no contradictions, return an empty list [].

EXAMPLE (for illustration — do not use these indices for the actual task):
  If EXISTING FACTS has 2 items [idx 0, idx 1] and the new fact duplicates item at idx 0:
    duplicate_facts: [0]   (valid — 0 is within 0..1)
  If EXISTING FACTS has 2 items and there are no duplicates:
    duplicate_facts: []    (correct — never return [2] or higher)

IMPORTANT:
- duplicate_facts: Use ONLY idx values from EXISTING FACTS
- contradicted_facts: Use ONLY idx values from INVALIDATION CANDIDATES
- If a list is empty, you MUST return [] for that field — never return a non-empty list

<FACT TYPES>
{context['edge_types']}
</FACT TYPES>

<EXISTING FACTS>
{existing_json}
</EXISTING FACTS>

<FACT INVALIDATION CANDIDATES>
{candidates_json}
</FACT INVALIDATION CANDIDATES>

<NEW FACT>
{context['new_edge']}
</NEW FACT>
""",
        ),
    ]


_overrides_applied = False


def apply_prompt_overrides() -> None:
    """
    Monkey-patch graphiti_core's prompt_library with improved prompts.

    Safe to call multiple times — subsequent calls are no-ops.
    Must be called AFTER graphiti_core has been imported.
    """
    global _overrides_applied
    if _overrides_applied:
        return

    try:
        # Import the module-level prompt_library object that edge_operations.py uses.
        # Both this module and edge_operations.py reference the same object via
        # graphiti_core.prompts, so mutating it here affects edge_operations.py.
        import graphiti_core.prompts as _prompts_module
        from graphiti_core.prompts.lib import VersionWrapper

        # Replace resolve_edge on the dedupe_edges PromptTypeWrapper
        prompt_library = _prompts_module.prompt_library
        prompt_library.dedupe_edges.resolve_edge = VersionWrapper(_resolve_edge_improved)

        _overrides_applied = True
        print(
            "[graphiti_prompt_overrides] Applied improved dedupe_edges.resolve_edge prompt",
            flush=True,
        )
    except Exception as e:
        # Non-fatal — log and continue with original prompts
        print(
            f"[graphiti_prompt_overrides] WARNING: Failed to apply prompt overrides: {e}",
            flush=True,
        )
