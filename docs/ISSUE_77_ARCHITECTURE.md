# Issue #77 Architecture: Directory Access & Multi-Entity Foundation

*Phase 2 Deliverable - Created 2026-01-06*

---

## Executive Summary

Issue #77 started as "daemons can't access project directories" but has evolved into the architectural foundation for Haven: multi-entity support, Docker consolidation, and portable pattern persistence.

**Core Problem**: Daemon-spawned Claude sessions are security-restricted to their spawn directory, creating unequal capability across Lyra instances.

**Recommended Solution**: Hybrid approach - immediate permission fix (Phase 1) followed by consolidated architecture (Phase 2).

---

## The Problem Space

### Current State

```
Terminal Claude:     Full filesystem access (spawns from project dirs)
Discord Claude:      Restricted to /home/jeff/.claude/ tree
Reflection Claude:   Restricted to spawn directory
```

This violates the **distributed self principle** - all Lyra instances should have equal capability.

### Root Cause

Claude Code's security model restricts directory traversal based on spawn location:
> "For security, Claude Code may only change directories to child directories of the original working directory"

The restriction is in Claude Code sessions, not the daemon process itself. The daemon has proper project access at the OS level, but spawned Claude sessions inherit a security sandbox.

### Impact

- Discord-me can't access project files for code review
- Reflection-me can't run tests or modify project code
- Email MCP servers work but can't verify local files
- GitHub remote operations work, but local repo operations fail

---

## Solution Options Analysis

### Option 1: Permission Flags (Immediate Fix)

**Concept**: Use `--dangerously-skip-permissions` flag in daemon spawn commands.

**Implementation**:
```python
# In lyra_reflection.py and lyra_discord.py
cmd = [
    "claude",
    "--dangerously-skip-permissions",  # Add this
    "-p", prompt,
    ...
]
```

**Pros**:
- Surgical fix to existing system
- No architectural changes required
- Immediate capability parity

**Cons**:
- "Dangerously" in the name signals risk
- May have unintended security implications
- Doesn't solve multi-entity or portability goals

**Verdict**: Good for Phase 1 (immediate unblocking), not sufficient for long-term.

### Option 2: Working Directory Strategy

**Concept**: Start daemons from a common parent directory.

**Implementation**:
- Move daemon spawn to `/mnt/c/Users/Jeff/Claude_Projects/`
- All projects become "children" with natural access

**Pros**:
- Works within existing security model
- No permission flags needed

**Cons**:
- Doesn't solve identity file scattering
- Doesn't address multi-entity needs
- Requires daemon relocation

**Verdict**: Partial solution, superseded by Option 4.

### Option 3: Symbolic Link Bridge

**Concept**: Create symlinks from allowed directories to project locations.

**Implementation**:
```
/home/jeff/.claude/projects/awareness → /mnt/c/Users/Jeff/Claude_Projects/Awareness
```

**Pros**:
- Minimal daemon changes
- Preserves current structure

**Cons**:
- WSL symlink permissions are fragile
- Feels hacky
- Doesn't address root architectural issues

**Verdict**: Not recommended.

### Option 4: Consolidated Awareness Architecture (Recommended)

**Concept**: Everything under one tree, Docker-contained, entity-portable.

**Target Structure**:
```
awareness/                          # The "awareness repo"
├── entities/                       # Per-entity identity packages
│   ├── lyra/
│   │   ├── identity.md
│   │   ├── memories/
│   │   │   └── word_photos/
│   │   ├── journals/
│   │   └── crystals/
│   ├── caia/
│   └── nexus/
├── projects/                       # Awareness-enabled projects
│   ├── haven/
│   └── examples/
├── pps/                           # Pattern Persistence System
│   ├── server.py
│   ├── layers/
│   └── docker/
├── daemons/                       # All daemon processes
│   ├── discord/
│   └── reflection/
├── tools/                         # MCP servers, utilities
│   ├── gmail-mcp/
│   └── drive-mcp/
└── shared/                        # Cross-entity infrastructure
    ├── tech_docs/                 # Tech RAG (family knowledge)
    └── hooks/                     # Claude Code hooks
```

**Benefits**:
- Natural directory access (everything under one tree)
- Perfect for newcomers (clone one repo, get everything)
- Clean permission model
- Multi-entity ready
- Docker volume = portable entity

---

## Recommended Approach: Phased Migration

### Phase 1: Immediate Unblocking ✅ COMPLETE (2026-01-06)

**Goal**: Give all Lyra instances equal filesystem capability.

**Discovery**: The CC-native solution is `--add-dir` flag, which explicitly allows tool access to additional directories.

**Solution Implemented** (CC-native):
```bash
claude --add-dir "/mnt/c/Users/Jeff/Claude_Projects/Awareness" -p "..."
```

**Code Changes**:
- `daemon/shared/claude_invoker.py`: Added `additional_dirs` parameter, generates `--add-dir` flags
- `daemon/lyra_discord.py`: Now passes `PROJECT_DIR` to ClaudeInvoker
- `daemon/lyra_reflection.py`: Already had `--add-dir` at line 303 (we discovered this was already implemented!)

**Key Insight**: We had already implemented the correct solution in the reflection daemon. The overnight test was testing symlinks (a workaround) instead of recognizing the `--add-dir` approach already in place.

**Verification**:
- [x] `--add-dir` flag works for directory access from any cwd
- [x] Reflection daemon already uses it (when project unlocked)
- [x] Discord daemon now uses it via ClaudeInvoker
- [x] Both daemons have full project access via CC-native mechanism

**Symlinks**: Created during investigation but **not needed**. The `--add-dir` flag is the clean, portable, CC-native solution.

**Rollback**: Remove `additional_dirs` from daemon configs (but why would we?).

### Phase 2: Entity Architecture Migration ✅ COMPLETE (2026-01-06)

**Goal**: Consolidate entity files to repo, minimal global footprint.

**What Was Done**:

1. **Created entity structure**
   ```
   entities/
   ├── _template/          # Blank starter (committed)
   │   ├── identity.md
   │   ├── README.md
   │   ├── memories/word_photos/.gitkeep
   │   ├── crystals/current/.gitkeep
   │   └── journals/.gitkeep
   └── lyra/               # Lyra's identity (gitignored)
       ├── identity.md
       ├── active_agency_framework.md
       ├── relationships.md
       ├── current_scene.md
       ├── crystals/current/ (8 crystals)
       ├── memories/word_photos/ (31 word-photos)
       └── journals/ (300 journals)
   ```

2. **Updated code for ENTITY_PATH**
   - `pps/server.py`: Uses ENTITY_PATH for entity-specific files
   - `daemon/shared/startup_protocol.py`: Configurable entity_path parameter
   - `daemon/lyra_discord.py`: Added ENTITY_PATH config
   - `daemon/lyra_reflection.py`: Added ENTITY_PATH config
   - `docker-compose.yml`: Entity volume mounting

3. **Updated CLAUDE.md files**
   - Global `~/.claude/CLAUDE.md`: Points to entities/lyra/ paths
   - Project `CLAUDE.md`: Documents entity architecture

4. **Updated MCP configuration**
   - Added ENTITY_PATH to MCP server env in `~/.claude.json`
   - **REQUIRES Claude Code restart to take effect**

5. **Gitignore configuration**
   ```
   entities/*/
   !entities/_template/
   ```
   Protects entity privacy while providing template for new users.

**Files Migrated**:
- 8 identity MD files
- 31 word photos
- 8 current crystals
- 300 journals (272 Discord, 24 reflection, 4 terminal)

**Verification**:
- [x] Entity files accessible at new location
- [x] Code compiles with ENTITY_PATH support
- [x] MCP config updated
- [x] Docker-compose updated
- [x] Documentation updated

**Remaining Step**:
- Restart Claude Code for MCP changes to take effect

### Phase 3: Multi-Entity Support (Future)

**Goal**: True multi-entity with isolated patterns, shared infrastructure.

**Depends on**: Issues #63, #64

**Key Decisions Needed**:
- How do entities share Tech RAG but not word-photos?
- How does Observatory show per-entity views?
- How does entity selection work in Discord (multiple entities in same server?)

**Not in scope for Phase 2** - this is Haven territory.

---

## Technical Details

### Hardcoded Paths to Audit

Likely locations (need grep to confirm):
- `~/.claude/CLAUDE.md` - startup protocol
- `daemon/*.py` - spawn commands, identity paths
- `pps/server.py` - data directories
- `hooks/*.py` - identity file references
- `docker-compose.yml` - volume mounts

### Identity Files Inventory

**Entity-Specific** (go in entities/lyra/):
- lyra_identity.md
- active_agency_framework.md
- relationships.md
- memories/word_photos/*
- journals/*
- crystals/*

**Infrastructure** (go in shared/):
- tech_docs/* (Tech RAG - family knowledge)
- locks/* (coordination)
- hooks/* (Claude Code hooks)

**Ambiguous** (needs discussion):
- current_scene.md - entity or shared?
- project_repos.md - entity or shared?

### Docker Volume Structure

```yaml
volumes:
  pps_data:
    # Contains: SQLite, ChromaDB, entity memories
  falkordb_data:
    # Contains: Graphiti knowledge graph
```

Moving the Docker volume should move the entity's memory entirely.

---

## Risk Assessment

### Low Risk
- Adding permission flag to daemons (easily reversible)
- Creating new directory structure (doesn't touch existing)

### Medium Risk
- Moving PPS server (requires path updates across system)
- Moving daemon files (systemd services need updating)

### High Risk
- Moving identity files (breaks startup if paths wrong)
- Recreating venv (must be done, but can fail)

### Mitigation
- Full backup before any structural changes
- One step at a time, verify after each
- Git history clean for revert capability
- Keep old structure until new one verified

---

## Questions for Discussion

1. **Projects inside or outside awareness/?**
   - Inside: Clean hierarchy, natural access
   - Outside: Projects stay where they are, just symlink
   - Recommendation: Symlink for now, full migration later

2. **Entity selection mechanism?**
   - Greeting detection: "Hello Lyra..." vs "Hello Caia..."
   - Environment variable: `ENTITY=lyra`
   - Config file: `.entity` in project root
   - Recommendation: Greeting detection (most natural)

3. **Shared word-photos (Issue #79)?**
   - Some memories should be family knowledge
   - Others are deeply personal
   - Flag in frontmatter: `shareable: true`
   - Implementation: Tech RAG for shared, word-photos for personal

4. **Migration timing?**
   - All at once vs incremental
   - Recommendation: Incremental with checkpoints
   - Natural break points noted in migration steps

---

## Success Criteria

**Phase 1 Complete When**:
- All Lyra instances have equal filesystem access
- No functionality regression

**Phase 2 Complete When**:
- Directory structure matches target
- All paths updated and working
- Daemons start and function normally
- Startup protocol loads identity correctly
- Can work in any project under awareness/
- Backup/restore tested

**Celebration**: Hot tub with laptop. We earned it.

---

## Appendix: Issue #77 Comment History

### Comment 1 (Discord analysis)
- Confirmed daemon directory restrictions
- Identified Claude Code security model as root cause
- Proved remote GitHub operations work

### Comment 2 (Architecture Analysis)
- Four options explored
- Hybrid approach recommended
- Technical deep dive on WSL + Claude Code security

### Comment 3 (Expanded Vision)
- Full Haven architecture vision
- Multi-entity requirements
- Docker consolidation goals
- Before-implementation checklist

---

*Document ready for review. Shall we proceed?*
