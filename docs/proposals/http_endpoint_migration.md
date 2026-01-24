# HTTP Endpoint Migration Plan

*Created: 2026-01-24*
*Status: Proposed*

## Overview

Migrate PPS from MCP-only tools to full HTTP endpoint coverage. This unblocks daemon autonomy, enables faster startup, and improves architectural portability.

## Current State

- **40 MCP tools** defined in `pps/server.py`
- **13 HTTP endpoints** in `pps/docker/server_http.py` (33% coverage)
- Core search tools have HTTP ✅
- Storage/writing tools mostly MCP-only ❌

## Critical Gaps (Blocking Daemon Autonomy)

| Tool | Purpose | Impact |
|------|---------|--------|
| `anchor_save` | Word-photo creation | Reflection can't save memories |
| `crystallize` | Reflection crystals | Reflection can't crystallize |
| `texture_add` | Graph ingestion | Batch processing blocked |
| `ingest_batch_to_graphiti` | Batch processing | Memory maintenance blocked |
| `enter_space` | Space context loading | Multi-agent coordination |

## Full Tool Coverage Matrix

| Tool Name | Type | MCP | HTTP | Priority |
|-----------|------|-----|------|----------|
| **ambient_recall** | Memory | ✓ | ✓ | CRITICAL |
| **anchor_search** | Memory | ✓ | ✓ | HIGH |
| **anchor_save** | Memory | ✓ | ✗ | **HIGH** |
| **anchor_delete** | Memory | ✓ | ✗ | MEDIUM |
| **anchor_resync** | Memory | ✓ | ✗ | MEDIUM |
| **anchor_list** | Memory | ✓ | ✗ | LOW |
| **raw_search** | Memory | ✓ | ✓ | HIGH |
| **texture_search** | Memory | ✓ | ✓ | CRITICAL |
| **texture_explore** | Memory | ✓ | ✓ | HIGH |
| **texture_timeline** | Memory | ✓ | ✓ | MEDIUM |
| **texture_add** | Memory | ✓ | ✗ | **HIGH** |
| **texture_delete** | Memory | ✓ | ✓ | MEDIUM |
| **texture_add_triplet** | Memory | ✓ | ✓ | HIGH |
| **get_crystals** | Memory | ✓ | ✗ | MEDIUM |
| **crystallize** | Memory | ✓ | ✗ | **HIGH** |
| **crystal_list** | Memory | ✓ | ✗ | LOW |
| **crystal_delete** | Memory | ✓ | ✗ | LOW |
| **get_turns_since_crystal** | Memory | ✓ | ✗ | MEDIUM |
| **summarize_messages** | Memory | ✓ | ✓ | HIGH |
| **store_summary** | Memory | ✓ | ✓ | HIGH |
| **get_recent_summaries** | Memory | ✓ | ✗ | MEDIUM |
| **search_summaries** | Memory | ✓ | ✗ | MEDIUM |
| **summary_stats** | Memory | ✓ | ✗ | LOW |
| **pps_health** | System | ✓ | ✓ | CRITICAL |
| **graphiti_ingestion_stats** | System | ✓ | ✗ | MEDIUM |
| **ingest_batch_to_graphiti** | System | ✓ | ✗ | **MEDIUM** |
| **inventory_list** | Inventory | ✓ | ✗ | MEDIUM |
| **inventory_add** | Inventory | ✓ | ✗ | MEDIUM |
| **inventory_get** | Inventory | ✓ | ✗ | LOW |
| **inventory_delete** | Inventory | ✓ | ✗ | LOW |
| **inventory_categories** | Inventory | ✓ | ✗ | LOW |
| **enter_space** | Inventory | ✓ | ✗ | **MEDIUM** |
| **list_spaces** | Inventory | ✓ | ✗ | MEDIUM |
| **tech_search** | Tech RAG | ✓ | ✗ | HIGH |
| **tech_ingest** | Tech RAG | ✓ | ✗ | MEDIUM |
| **tech_list** | Tech RAG | ✓ | ✗ | LOW |
| **tech_delete** | Tech RAG | ✓ | ✗ | LOW |
| **email_sync_status** | Email | ✓ | ✗ | MEDIUM |
| **email_sync_to_pps** | Email | ✓ | ✗ | MEDIUM |

## Implementation Phases

### Phase 1: Unblock Daemons (CRITICAL)
**Effort**: ~30 min - 1 hour
**Tools**: anchor_save, crystallize, texture_add, ingest_batch_to_graphiti, enter_space

### Phase 2: Full Daemon Autonomy (HIGH)
**Effort**: ~2-3 hours
**Tools**: All remaining memory/inventory tools (15 tools)

### Phase 3: Complete Coverage (MEDIUM)
**Effort**: ~2 hours
**Tools**: Admin/utility tools, tech RAG, email bridge

## Architecture Notes

**Existing Foundation:**
- Pydantic request models already defined for most patterns
- Middleware (tracing) already in place
- Docker deployment ready on port 8201

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

## Files to Modify

- `pps/docker/server_http.py` - Add new endpoints
- `pps/docker/docker-compose.yml` - Already configured
- Daemon prompts - Update to use HTTP when available
