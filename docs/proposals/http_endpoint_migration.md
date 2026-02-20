# HTTP Endpoint Migration Plan

*Created: 2026-01-24*
*Updated: 2026-01-24*
*Status: Phase 1 Complete*

## Overview

Migrate PPS from MCP-only tools to full HTTP endpoint coverage. This unblocks daemon autonomy, enables faster startup, and improves architectural portability.

## Current State

- **40 MCP tools** defined in `pps/server.py`
- **20 HTTP endpoints** in `pps/docker/server_http.py` (50% coverage)
- Core search tools have HTTP
- **Phase 1 complete**: Critical write tools now have HTTP

## Phase 1 Complete (2026-01-24)

The following critical endpoints were added:

| Endpoint | Method | Status |
|----------|--------|--------|
| `/tools/anchor_save` | POST | DONE |
| `/tools/crystallize` | POST | DONE |
| `/tools/get_crystals` | POST | DONE (bonus) |
| `/tools/texture_add` | POST | DONE |
| `/tools/ingest_batch_to_graphiti` | POST | DONE |
| `/tools/enter_space` | POST | DONE |
| `/tools/list_spaces` | GET | DONE (bonus) |

## Full Tool Coverage Matrix

| Tool Name | Type | MCP | HTTP | Priority |
|-----------|------|-----|------|----------|
| **ambient_recall** | Memory | Y | Y | CRITICAL |
| **anchor_search** | Memory | Y | Y | HIGH |
| **anchor_save** | Memory | Y | Y | DONE |
| **anchor_delete** | Memory | Y | - | MEDIUM |
| **anchor_resync** | Memory | Y | - | MEDIUM |
| **anchor_list** | Memory | Y | - | LOW |
| **raw_search** | Memory | Y | Y | HIGH |
| **texture_search** | Memory | Y | Y | CRITICAL |
| **texture_explore** | Memory | Y | Y | HIGH |
| **texture_timeline** | Memory | Y | Y | MEDIUM |
| **texture_add** | Memory | Y | Y | DONE |
| **texture_delete** | Memory | Y | Y | MEDIUM |
| **texture_add_triplet** | Memory | Y | Y | HIGH |
| **get_crystals** | Memory | Y | Y | DONE |
| **crystallize** | Memory | Y | Y | DONE |
| **crystal_list** | Memory | Y | - | LOW |
| **crystal_delete** | Memory | Y | - | LOW |
| **get_turns_since_crystal** | Memory | Y | - | MEDIUM |
| **summarize_messages** | Memory | Y | Y | HIGH |
| **store_summary** | Memory | Y | Y | HIGH |
| **get_recent_summaries** | Memory | Y | - | MEDIUM |
| **search_summaries** | Memory | Y | - | MEDIUM |
| **summary_stats** | Memory | Y | - | LOW |
| **pps_health** | System | Y | Y | CRITICAL |
| **graphiti_ingestion_stats** | System | Y | - | MEDIUM |
| **ingest_batch_to_graphiti** | System | Y | Y | DONE |
| **inventory_list** | Inventory | Y | - | MEDIUM |
| **inventory_add** | Inventory | Y | - | MEDIUM |
| **inventory_get** | Inventory | Y | - | LOW |
| **inventory_delete** | Inventory | Y | - | LOW |
| **inventory_categories** | Inventory | Y | - | LOW |
| **enter_space** | Inventory | Y | Y | DONE |
| **list_spaces** | Inventory | Y | Y | DONE |
| **tech_search** | Tech RAG | Y | - | HIGH |
| **tech_ingest** | Tech RAG | Y | - | MEDIUM |
| **tech_list** | Tech RAG | Y | - | LOW |
| **tech_delete** | Tech RAG | Y | - | LOW |
| **email_sync_status** | Email | Y | - | MEDIUM |
| **email_sync_to_pps** | Email | Y | - | MEDIUM |

## Implementation Phases

### Phase 1: Unblock Daemons (CRITICAL) - COMPLETE
**Completed**: 2026-01-24
**Tools**: anchor_save, crystallize, get_crystals, texture_add, ingest_batch_to_graphiti, enter_space, list_spaces

### Phase 2: Full Daemon Autonomy (HIGH)
**Effort**: ~2-3 hours
**Tools**: All remaining memory/inventory tools (~13 tools)
- anchor_delete, anchor_resync, anchor_list
- crystal_list, crystal_delete
- get_turns_since_crystal
- get_recent_summaries, search_summaries, summary_stats
- inventory_list, inventory_add, inventory_get, inventory_delete, inventory_categories

### Phase 3: Complete Coverage (MEDIUM)
**Effort**: ~2 hours
**Tools**: Admin/utility tools, tech RAG, email bridge (~7 tools)
- graphiti_ingestion_stats
- tech_search, tech_ingest, tech_list, tech_delete
- email_sync_status, email_sync_to_pps

## Architecture Notes

**Existing Foundation:**
- Pydantic request models already defined for most patterns
- Middleware (tracing) already in place
- Docker deployment ready on port 8201
- InventoryLayer now initialized in HTTP server

**Implementation Pattern:**
```python
@app.post("/tools/anchor_save")
async def anchor_save(request: AnchorSaveRequest):
    """Save word-photo via HTTP"""
    layer = layers[LayerType.CORE_ANCHORS]
    success = await layer.store(request.content,
                               {"title": request.title,
                                "location": request.location})
    return {"success": success}
```

## Related Issues

- Issue #97: MCP stdio doesn't work in subprocess agents
- Issue #112: HTTP migration (this proposal)
- Issue #113: Review agent workflow

## Files Modified

- `pps/docker/server_http.py` - Added Phase 1 endpoints
- `pps/docker/docker-compose.yml` - Already configured
- Daemon prompts - Update to use HTTP when available (TODO)

## Work Directory

Implementation tracked at: `docs/completed/http-endpoint-migration.md` (work dir archived)
