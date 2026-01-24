# Project: [NAME]

**Status**: In Progress | Complete | Blocked
**Created**: YYYY-MM-DD
**Linked from**: TODO.md WIP section

---

## Goal

[One paragraph describing what this project accomplishes]

---

## Tasks

### Pending
- [ ] Task 1
- [ ] Task 2

### In Progress
- [ ] Current task (who is working on it)

### Done
- [x] Completed task (YYYY-MM-DD)

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
