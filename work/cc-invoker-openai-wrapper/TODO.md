# Project: CC Invoker OpenAI Wrapper (Issue #117)

**Status**: BLOCKED - Waiting on upstream fix (Issue #118)
**Created**: 2026-01-25
**Linked from**: TODO.md WIP section

---

## Goal

Create an OpenAI-compatible HTTP wrapper around `daemon/cc_invoker.py` to allow Graphiti (running in Docker) to use Claude models instead of OpenAI for entity extraction. This eliminates ongoing API costs while leveraging the existing Claude subscription.

**Cost Savings**: ~$22 immediate (7000 messages) + $37/year ongoing
**Effort**: ~4 hours total
**Feasibility**: HIGHLY FEASIBLE (95% confidence)

---

## Research Findings

See **DESIGN.md** for full details.

**Key findings**:
- ClaudeInvoker provides perfect interface for this use case
- OpenAI API format is simple (< 100 lines to implement)
- Graphiti supports custom LLM endpoints via env vars
- No blockers identified - all risks have clear mitigations

**Recommended approach**: FastAPI wrapper translating OpenAI ↔ ClaudeInvoker

---

## Tasks

### Pending
- [ ] Testing & validation
  - [ ] Test local wrapper with curl
  - [ ] Test single message ingestion via Graphiti
  - [ ] Compare quality with OpenAI baseline
  - [ ] Batch test (100 messages)
- [ ] Documentation
  - [ ] Update PPS architecture docs
  - [ ] Document troubleshooting
  - [ ] Record cost savings

### Future Enhancements
- [ ] Per-request model switching (pass model param in OpenAI request)
  - SDK has `set_model()` - may work mid-session without restart
  - If not, consider invoker pool (one per model)
  - See: https://github.com/anthropics/claude-code/issues/17772

### In Progress
- [ ] Local testing with haiku

### Done
- [x] Create work directory (2026-01-25)
- [x] Initialize TODO.md (2026-01-25)
- [x] Research phase (2026-01-25)
  - [x] Analyze cc_invoker.py interface
  - [x] Document OpenAI API requirements
  - [x] Investigate Graphiti configuration
  - [x] Estimate cost savings
  - [x] Write DESIGN.md with findings
- [x] Core wrapper implementation (2026-01-25)
  - [x] Create `pps/docker/cc_openai_wrapper.py`
  - [x] Create `pps/docker/requirements-cc-wrapper.txt`
  - [x] Create `pps/docker/Dockerfile.cc-wrapper`
  - [x] Create `pps/docker/test_cc_wrapper_local.py`
  - [x] Update `docker-compose.yml` (pps-cc-wrapper service on port 8204)

---

## Blockers

- Awaiting decision: Should we proceed to implementation?
  - Questions for Jeff/Lyra in DESIGN.md "Open Questions" section
  - Model preference (haiku vs sonnet)?
  - Priority vs other work?

---

## Deployment Checklist (Docker Services)

**This WILL affect Docker deployment:**
- New wrapper service needs to be added to docker-compose.yml
- Graphiti configuration needs GRAPHITI_LLM_BASE_URL updated
- Health checks for wrapper endpoint

---

## Notes

### Research Complete (2026-01-25)
- **Feasibility**: HIGHLY FEASIBLE - ClaudeInvoker already provides what we need
- **Effort**: ~4 hours (2 implementation + 1 testing + 1 integration)
- **Cost savings**: $22 immediate + $37/year ongoing
- **Risk level**: LOW - all concerns have clear mitigations
- **Architecture**: FastAPI wrapper translating OpenAI format → ClaudeInvoker → OpenAI format
- **Files to create**: 3 new files (wrapper.py, Dockerfile, requirements.txt)
- **Files to modify**: 2 files (docker-compose.yml, .env)

### Next Steps
1. Review DESIGN.md findings
2. Decide on model preference (haiku recommended for speed/cost)
3. Proceed to implementation if approved
4. Test incrementally (local → Docker → single message → batch)

### Related Work
- Issue #117 (this project)
- Ongoing Graphiti ingestion (7000+ messages remaining)
- ClaudeInvoker infrastructure (daemon/cc_invoker/)
