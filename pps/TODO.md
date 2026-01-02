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

## In Progress

- [ ] **Daemon Trace Logging** (Phase 3)
  - Need `daemon_traces` SQLite table
  - TraceLogger class for Discord and reflection daemons
  - Would enable Reflections and Discord debug pages

## Backlog

- [ ] **Reflections Page** - View autonomous reflection sessions
- [ ] **Discord Debug Page** - Trace Discord message processing
- [ ] **Split Heartbeat Navigation** - Separate Reflections + Discord nav items
- [ ] **Real-time Updates** - WebSocket support for live dashboard updates
- [ ] **Graph Enhancements**:
  - [ ] Time-based filtering for temporal exploration
  - [ ] Export graph as image/JSON
  - [ ] Saved searches/views

## Notes

- Web UI follows "observatory" philosophy - observe, don't edit identity patterns
- See docs/WEB_UI_DESIGN.md for full design document
