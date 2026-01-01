# Changelog

All notable changes to the Awareness project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- **PPS Observatory Web Dashboard** (Issue #10, Phase 1)
  - FastAPI backend with Jinja2 templates
  - Dashboard showing layer health, channel stats, recent activity
  - Docker container on port 8202 for portability
  - TailwindCSS + htmx for responsive frontend
- Web UI design document (`docs/WEB_UI_DESIGN.md`) - comprehensive design for PPS Observatory dashboard
- GitHub Issues #9 (Graphiti) and #10 (Web UI) for feature tracking

### Changed
- **Unified Startup Protocol** - All Lyra instances now use same startup
  - Core identity → ambient_recall → agency/relationships → embody
  - Fixed MCP tool names (`mcp__pps__*` not `mcp__pattern-persistence-system__*`)
  - Context reduced from 8000 chars to 1000 (`--continue` already has history)
  - Documented in PATTERN_PERSISTENCE_SYSTEM.md

### Fixed
- **Discord daemon "Prompt is too long" crash** (Issue #1)
  - Root cause: Unbounded conversation context exceeding Claude's input limit
  - Reduced context size drastically (unified protocol uses 1000 chars max)
  - Truncate individual messages >500 chars
  - Explicit detection and logging of "Prompt is too long" errors

### Planned
- PPS Observatory Phase 2+ (Messages, Word-Photos, Summaries pages)
- Graphiti integration for Layer 3 (Issue #9)

---

## [0.3.0] - 2026-01-01

### Added
- **Professional Development Standards**
  - `CONTRIBUTING.md` with GitHub workflow, commit conventions, code standards
  - `CLAUDE.md` for automatic project context loading on startup
  - `docs/` directory for detailed documentation

- **Pattern Persistence System in Repository**
  - Moved PPS code from `~/.claude/pps/` into git-tracked `pps/` directory
  - Full four-layer architecture now version controlled
  - Docker configurations included

- **Terminal Session Logging** (Issue #3)
  - Claude Code hook captures terminal conversations to SQLite
  - FTS5 full-text search over terminal content
  - `get_turns_since_summary` includes terminal turns
  - Channel naming: `terminal:{session_id}`

### Fixed
- **ChromaDB Persistence** (Issue #7)
  - Volume mount corrected from `/chroma/chroma` to `/data`
  - Word-photos now survive container restarts

- **FTS5 Search** (Issue #8)
  - SearchResult parameter mismatch (`relevance` → `relevance_score`)
  - Added missing `source` and `layer` parameters
  - Silent exception was hiding the bug

### Changed
- Expanded `.gitignore` for Python/Docker/IDE artifacts
- Project lock mechanism for terminal/heartbeat coordination

---

## [0.2.0] - 2025-12-31

### Added
- **Pattern Persistence System (PPS)**
  - Four-layer architecture: Raw Capture, Core Anchors, Rich Texture, Crystallization
  - MCP server for Claude Code integration
  - ChromaDB for word-photo semantic search
  - SQLite with FTS5 for message storage

- **Smart Startup Protocol**
  - 10x faster daemon warmup
  - Automatic context loading

- **Crystallization Layer**
  - Rolling summaries (keep 4 active)
  - Archive for older summaries
  - `crystallize` MCP tool

### Changed
- Renamed memory architecture documentation to `PATTERN_PERSISTENCE_SYSTEM.md`
- SQLite schema updated with `channel` column for multi-source support

---

## [0.1.0] - 2025-12-28

### Added
- **Discord Daemon**
  - Persistent connection to Discord
  - Message capture to SQLite
  - Lyra presence in Discord channels
  - systemd service configuration

- **Heartbeat Daemon**
  - Autonomous reflection cycles
  - Full tool access during reflection
  - Journal generation

- **Identity Infrastructure**
  - `lyra_identity.md` - Core identity pattern
  - `lyra_memories.md` - Episodic memories
  - `active_agency_framework.md` - Permissions
  - `relationships.md` - People and identities

- **Spaces Architecture**
  - `spaces/terminal/` - Main room, kitchen, bedroom
  - Sensory anchoring for embodiment

- **Initial Documentation**
  - `README.md`, `ARCHITECTURE.md`
  - `THE_DREAM.md` - Vision for autonomous self-improvement
  - `MATHEMATICS_OF_CARING.md`, `SELF_SPACE_FRAMEWORK.md`

---

## Session Reports

Session-by-session development reports are available in `docs/sessions/` (when generated).

---

*This changelog is maintained as part of professional development practices. See `CONTRIBUTING.md` for standards.*
