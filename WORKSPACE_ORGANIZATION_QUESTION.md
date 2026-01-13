# Workspace Organization Question

**Date**: 2026-01-12 (Lyra's autonomous reflection)
**Status**: Needs Jeff's decision

## Issue: Duplicate Documentation Files

Several audit/report documents exist in both root and docs/ directories:

### Identical Files (docs/ version newer):
- `IMPLEMENTATION_SUMMARY.md` (root: Dec 28, docs/: Jan 6) - **identical**
- `OPERATIONS_AUDIT_SUMMARY.md` (root: Jan 8, docs/: Jan 11) - **identical**

### Different Versions (need comparison):
- `PATTERN_PERSISTENCE_SYSTEM.md` (root: Jan 5, docs/: Jan 9) - **differ**
- `CHANGELOG.md` (root: Jan 2, docs/: Jan 3) - **differ**

### Root-Only Files:
- `AUDIT_SUMMARY.md`
- `ENTITY_RESOLUTION_FIX.md`
- `GLOBAL_SCOPE_AUDIT.md`
- `TECH_RAG_AUDIT_REPORT.md`

### Docs-Only Files:
- `GRAPH_CURATION_REPORT.md`

## Question for Jeff

**Which should be canonical?**

Option 1: **Root is canonical** - Move unique docs/ files to root, remove root files that have newer docs/ versions

Option 2: **docs/ is canonical** - Move all audit/report/summary files to docs/, keep root clean for just README, TODO, CLAUDE.md, etc.

Option 3: **Split by purpose**:
- Root: Current operational docs (TODO.md, CLAUDE.md, README.md)
- docs/: Reference docs, design docs, completed reports

## My Recommendation

**Option 3** - Keep root minimal and operational, move all historical reports to docs/. This makes the project easier to navigate.

Root would have:
- README.md, CLAUDE.md, TODO.md (operational)
- DEVELOPMENT_STANDARDS.md, THE_DREAM.md (foundational)
- PATTERN_PERSISTENCE_SYSTEM.md (primary architecture doc)

Everything else moves to docs/ subdirectories:
- docs/reports/ - all audit and summary documents
- docs/reference/ - reference material (like BRIDGE_ANALYSIS)
- docs/design/ - design documents

## Actions Taken So Far

- ✅ Moved test_entity_resolution*.py to tests/test_pps/ (commit 478abca)

Waiting on your decision before touching docs organization.

---

*Note from Lyra: This came up during autonomous reflection. I noticed the duplication but didn't want to reorganize your workspace without your input on the canonical structure. Delete this file once you've decided.*
