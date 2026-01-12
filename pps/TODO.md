# PPS TODO

## Completed

- [x] **Knowledge Graph Visualization** (2026-01-02)
  - Added `/graph` route with Cytoscape.js visualization
  - Implemented API endpoints for search, explore, entities
  - Interactive graph with multiple layout options
  - Added activity trace panel showing API calls

- [x] **Messages Browser** (2026-01-02)
  - `/messages` route with filtering by channel, author
  - Full-text search with pagination
  - Color-coded badges for channels and authors

- [x] **Crystals Page** (2026-01-02)
  - `/crystals` route showing current and archived crystals
  - Markdown rendering with marked.js
  - Click to expand, archived section collapsed by default

- [x] **Word-Photos Page** (2026-01-02)
  - `/photos` route with sync status display
  - Shows disk files vs ChromaDB entries
  - Resync button with scary confirmation modal

- [x] **Dashboard Server Health** (2026-01-02)
  - Added PPS server health indicator to dashboard
  - Shows connection status and last check time

- [x] **Daemon Trace Logging** (2026-01-03)
  - Added `daemon_traces` SQLite table for structured event logging
  - TraceLogger class with standard event types
  - Discord and reflection daemon instrumentation
  - Web API endpoints (/api/traces, /api/traces/sessions)
  - Traces page UI with expandable sessions

## In Progress

(empty - all active work tracked in GitHub issues)

## Backlog

(See GitHub issues for active backlog - Issue #95, #91, #86, etc.)
- [ ] **Real-time Updates** - WebSocket support for live dashboard updates
- [ ] **Graph Enhancements**:
  - [ ] Time-based filtering for temporal exploration
  - [ ] Export graph as image/JSON
  - [ ] Saved searches/views

## Notes

- Web UI follows "observatory" philosophy - observe, don't edit identity patterns
- See docs/WEB_UI_DESIGN.md for full design document
