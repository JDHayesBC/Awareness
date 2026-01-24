# HTTP Endpoint Migration - Testing Plan

**Status**: NEEDS_MANUAL_TEST
**Created**: 2026-01-24
**Testing Status**: Syntax validated, manual HTTP testing required

---

## Testing Status

### Phase 1 (7 endpoints)
- **Syntax**: ✓ Validated
- **HTTP Testing**: ⏸️ Paused (Docker/WSL crashed 2026-01-24 ~1:10 PM)
- **Test Script**: `/work/http-endpoint-migration/artifacts/test_endpoints.sh`

### Phase 2 (19 endpoints)
- **Syntax**: ✓ Validated
- **HTTP Testing**: ⏸️ Requires Docker PPS stack
- **Test Script**: `/work/http-endpoint-migration/artifacts/test_phase2_endpoints.sh`

---

## What Has Been Tested

1. **Python Syntax**: ✓
   - All request models compile
   - All endpoint implementations compile
   - Import statements valid
   - No syntax errors in 1623 lines

2. **Code Patterns**: ✓ (manual review)
   - Follows existing endpoint patterns exactly
   - Proper FastAPI decorators
   - Consistent error handling with HTTPException
   - Request validation via Pydantic
   - Graceful degradation for optional layers

---

## What Needs Manual Testing

### Prerequisites
```bash
cd pps/docker
docker-compose up -d
# Wait for health
curl http://localhost:8201/health
```

### Phase 1 Endpoints (7)
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/http-endpoint-migration/artifacts
bash test_endpoints.sh
# Results written to test_results.md
```

### Phase 2 Endpoints (19)
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/http-endpoint-migration/artifacts
bash test_phase2_endpoints.sh
# Results written to test_phase2_results.md
```

---

## Expected Test Results

### Should Pass (high confidence)
- Health check
- get_crystals
- get_turns_since_crystal
- get_recent_summaries
- search_summaries
- summary_stats
- graphiti_ingestion_stats
- crystal_list
- inventory_categories
- inventory_list (may return empty)
- inventory_add/get/delete (CRUD cycle)

### May Fail (gracefully)
- anchor_delete/list/resync - Requires ChromaDB layer with specific methods
- tech_search/list - Requires Tech RAG layer initialized
- enter_space - May not find requested space

### Intentionally Skipped
- anchor_delete - Needs valid filename (destructive)
- crystal_delete - Destructive operation
- tech_ingest - Needs valid file path
- tech_delete - Destructive operation

---

## Test Coverage

| Category | Endpoints | Test Script Coverage |
|----------|-----------|---------------------|
| Anchor Management | 3 | 2/3 (skip delete for safety) |
| Crystal Management | 2 | 1/2 (skip delete for safety) |
| Raw Capture | 1 | 1/1 |
| Message Summaries | 3 | 3/3 |
| Graphiti Stats | 1 | 1/1 |
| Inventory | 5 | 5/5 (full CRUD cycle) |
| Tech RAG | 4 | 2/4 (skip ingest/delete) |

**Total**: 14/19 endpoints covered in automated tests
**Skipped**: 5 destructive operations (require manual verification)

---

## Success Criteria

### Minimal (Code Complete)
- [x] Python syntax valid
- [x] All 19 endpoints implemented
- [x] Test scripts created
- [x] Testing plan documented

### Ideal (Fully Tested)
- [ ] Docker stack running
- [ ] All non-destructive endpoints return 2xx
- [ ] Response schemas match expectations
- [ ] Error handling works (4xx for bad input, 503 for missing services)

---

## Testing Instructions for Human

1. **Start PPS Docker stack**:
   ```bash
   cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
   docker-compose up -d
   ```

2. **Wait for services** (check logs):
   ```bash
   docker-compose logs -f
   # Wait for "PPS Server starting..." messages
   ```

3. **Run Phase 1 tests**:
   ```bash
   cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/http-endpoint-migration/artifacts
   bash test_endpoints.sh
   cat test_results.md
   ```

4. **Run Phase 2 tests**:
   ```bash
   bash test_phase2_endpoints.sh
   cat test_phase2_results.md
   ```

5. **Manual verification** (if needed):
   - Test destructive operations carefully in dev environment
   - Verify response schemas match MCP tools
   - Check error messages are helpful

6. **Document results**:
   - Capture test output
   - Note any failures
   - Update TODO.md with test status

---

## Known Limitations

1. **ChromaDB Dependencies**: Some endpoints require ChromaDB layer methods that may not be implemented in all layer versions
2. **Tech RAG Layer**: May not be available if ChromaDB is not running
3. **Test Data**: Tests create minimal test data - real usage will vary

---

## Next Steps After Testing

1. Review test results
2. Fix any failures found
3. Update documentation with any edge cases discovered
4. Mark testing phase complete in TODO.md
5. Proceed to code review stage
