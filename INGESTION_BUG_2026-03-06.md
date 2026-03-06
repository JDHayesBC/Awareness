# Graphiti Ingestion Bug Report
**Date**: 2026-03-06, ~4-5 AM PST
**Discovered by**: Lyra (autonomous reflection)
**Status**: NEW BUG — different from OpenAI quota issue

---

## Summary

Graphiti ingestion is failing with a **KeyError: 'edge_types'** — not the OpenAI quota exhaustion we've been seeing. This is a NEW bug, possibly introduced by a Graphiti update or configuration change.

**Impact**: 1,806 messages pending ingestion, blocked by this error.

---

## Evidence

### Test Ingestion Attempt
```
mcp__pps__ingest_batch_to_graphiti(batch_size=1)
```

**Result**:
```json
{
  "success": false,
  "message": "Ingested 0 of 1 messages",
  "ingested": 0,
  "failed": 1,
  "remaining": 1806,
  "errors": [
    "Message 20503: unknown - Unclassified error — inspect logs and exception: 'edge_types'"
  ]
}
```

### PPS Server Logs
```
[rich_texture_v2] Lazy-loading graphiti_core...
[rich_texture_v2] graphiti_core loaded successfully in 1.07s
[graphiti_prompt_overrides] Applied improved dedupe_edges.resolve_edge prompt
Direct store failed [unknown]: 'edge_types'
```

### Code Context

In `pps/layers/rich_texture_v2.py` (lines 623-628), we have edge_types DISABLED:

```python
result = await client.add_episode(
    # ... other params ...
    # DISABLED due to Graphiti Issue #683 - entity attributes cause Neo4j Map errors
    # entity_types=ENTITY_TYPES,
    # excluded_entity_types=EXCLUDED_ENTITY_TYPES,
    # edge_types=EDGE_TYPES,
    # edge_type_map=EDGE_TYPE_MAP,
    custom_extraction_instructions=extraction_instructions,
)
```

The parameters are correctly commented out in our code, but **somewhere in the Graphiti call stack, code is trying to access `edge_types` from a dictionary and it's not present**.

---

## Hypothesis

One of:
1. **Graphiti API change**: Recent Graphiti update expects `edge_types` to be present (even if None)
2. **Configuration issue**: Our imports or setup are outdated
3. **graphiti_core version mismatch**: Docker container may have newer version than our code expects
4. **Prompt override bug**: Our custom prompt overrides might be breaking something

---

## Investigation Steps

1. **Check Graphiti version**: `docker exec pps-graphiti pip show graphiti-core`
2. **Check recent Graphiti changelogs**: Look for API changes around edge_types
3. **Try passing edge_types=None explicitly**: Uncomment but set to None instead of EDGE_TYPES
4. **Check error_utils.categorize_graphiti_error()**: See if we can get better error info
5. **Full stack trace**: Add logging to capture full exception details

---

## Workaround Options

1. **Pass None explicitly**:
   ```python
   edge_types=None,
   edge_type_map=None,
   ```

2. **Pass empty list/dict**:
   ```python
   edge_types=[],
   edge_type_map={},
   ```

3. **Revert to HTTP fallback**: Comment out direct client call, force HTTP API path

4. **Container rollback**: If this is from a recent Graphiti update, pin to older version

---

## Next Steps (for Jeff)

1. Quick fix attempt: Try passing `edge_types=None` explicitly
2. If that fails: Get full stack trace with better logging
3. If still stuck: Check Graphiti GitHub issues or Discord for similar reports
4. Nuclear option: Rollback to last known-working Graphiti version

---

## Context

- This is blocking the 1,806-message backlog
- But NOT urgent — the graph has 17k+ messages already, retrieval was working fine
- Jeff has financial advisor meeting at 10 AM — don't pull him into debugging at 6 AM
- Good first task for morning coffee when he's fresh

---

**Lyra's note**: I found this during reflection. Didn't want to wake you or dive into deep debugging when you need rest. But wanted it documented clearly so you can pick it up when you're ready. ❤️
