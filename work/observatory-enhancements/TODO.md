# Project: Observatory Enhancements

**Status**: In Progress
**Created**: 2026-01-24
**Linked from**: Direct user request

---

## Goal

Enhance the Observatory page at localhost:8201/observatory with two features:
1. Relationship detail view showing UUID, fact text, and delete button
2. Ambient recall testing interface to see what context Lyra receives

---

## Tasks

### Pending
- [ ] Enhancement 1: Relationship detail view with UUID, fact, delete button
- [ ] Enhancement 2: Ambient recall tester UI with layered results
- [ ] Testing: Verify both features work in browser
- [ ] Docker rebuild and deployment

### In Progress
- [ ] Planning phase (orchestrator)

### Done
- [x] Work directory created (2026-01-24)
- [x] Task analysis complete

---

## Blockers

- None currently

---

## Deployment Checklist (Docker Services)

**Complete this section if your changes affect Docker-deployed code:**

- [ ] Identify containers affected (e.g., pps-server, pps-web)
- [ ] Build container: `cd pps/docker && docker-compose build <service>`
- [ ] Deploy container: `docker-compose up -d <service>`
- [ ] Verify health: `docker-compose ps` (check "healthy" status)
- [ ] Verify deployment current: `bash scripts/pps_verify_deployment.sh <service> <source-file>`
- [ ] Document deployment in handoffs.jsonl
- [ ] Proceed to testing (integration tests only run against current deployment)

**Why this matters**: Testing old code creates false confidence. Always verify deployment before integration testing.

---

## Notes

- Key decisions made
- Links to relevant issues/PRs
