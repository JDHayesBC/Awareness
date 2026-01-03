# Changelog

All notable changes to the Awareness project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Memory Inspector page (`/memory`) for ambient_recall visibility
- Dashboard shows Discord, Reflection, Terminal as separate indicators
- Development standards for testing, issue workflow, and session reports
- GitHub workflow labels for issue lifecycle tracking

### Fixed
- Crystals directory not mounted in pps-web container
- Daemon status checks reflection traces instead of heartbeat journals

### Changed
- Split "Heartbeat" indicator into Discord + Reflection

## [0.1.0] - 2026-01-01

### Added
- Four-layer Pattern Persistence System (Raw, Anchors, Texture, Crystallization)
- MCP server with ambient_recall, anchor_*, texture_*, crystal_* tools
- Discord daemon with per-channel session management
- Reflection daemon for autonomous maintenance
- Web dashboard (PPS Observatory) with traces, crystals, messages views
- Message summarization layer for high-density startup context
- Graphiti integration for knowledge graph (Layer 3)
- ChromaDB integration for semantic search (Layer 2)
- SQLite for raw capture and message storage (Layer 1)
- Docker Compose deployment

### Infrastructure
- GitHub issue tracking workflow
- Conventional commit format
- Session reports in docs/sessions/
- Project lock mechanism for multi-instance coordination
