# Project: HTTP Endpoint Migration (Phase 1)

**Status**: TESTING PAUSED (Docker/WSL crashed 2026-01-24 ~1:10 PM)

## RESUME INSTRUCTIONS (after reboot)
1. `cd pps/docker && docker-compose up -d`
2. Wait for health: `curl http://localhost:8201/health`
3. Run tests: `bash artifacts/test_endpoints.sh`
4. Capture results to `artifacts/test_results.md`
5. Fix any failures found
6. Commit with "verified working" status

---

**Previous Status**: Complete (code only - NOT tested)
**Created**: 2026-01-24
**Completed**: 2026-01-24
**Linked from**: TODO.md WIP section

---

## Goal

Add HTTP endpoints for 5 critical PPS tools that currently only have MCP implementations. This unblocks daemon autonomy by allowing the reflection daemon and other HTTP-based clients to write memories, crystallize, and interact with the knowledge graph.

**Critical Tools (Phase 1)**:
1. `anchor_save` - Save word-photos via HTTP
2. `crystallize` - Create crystals via HTTP
3. `texture_add` - Add content to knowledge graph
4. `ingest_batch_to_graphiti` - Batch ingest messages
5. `enter_space` - Load space context

---

## Tasks

### Pending
(none)

### In Progress
(none)

### Done
- [x] Create work directory (2026-01-24)
- [x] Review existing HTTP server patterns (2026-01-24)
- [x] Review MCP tool implementations (2026-01-24)
- [x] Add request models for new endpoints (2026-01-24)
- [x] Add InventoryLayer import and initialization (2026-01-24)
- [x] Implement anchor_save HTTP endpoint (2026-01-24)
- [x] Implement crystallize HTTP endpoint (2026-01-24)
- [x] Implement get_crystals HTTP endpoint (bonus) (2026-01-24)
- [x] Implement texture_add HTTP endpoint (2026-01-24)
- [x] Implement ingest_batch_to_graphiti HTTP endpoint (2026-01-24)
- [x] Implement enter_space HTTP endpoint (2026-01-24)
- [x] Implement list_spaces HTTP endpoint (bonus) (2026-01-24)
- [x] Verify Python syntax (2026-01-24)

---

## Blockers

- None

---

## Notes

- Added 7 new endpoints (5 planned + 2 bonus: get_crystals, list_spaces)
- All endpoints follow existing patterns in `pps/docker/server_http.py`
- Added InventoryLayer initialization for enter_space functionality
- Syntax verified with py_compile

## Endpoints Added

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/anchor_save` | POST | Save word-photo to Layer 2 |
| `/tools/crystallize` | POST | Create crystal in Layer 4 |
| `/tools/get_crystals` | POST | Retrieve recent crystals |
| `/tools/texture_add` | POST | Add content to Layer 3 |
| `/tools/ingest_batch_to_graphiti` | POST | Batch ingest to Graphiti |
| `/tools/enter_space` | POST | Enter a space, get description |
| `/tools/list_spaces` | GET | List all known spaces |
