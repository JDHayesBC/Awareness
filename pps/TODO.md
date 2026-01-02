# PPS TODO

## Completed

- [x] **Knowledge Graph Visualization** (2026-01-02)
  - Added `/graph` route with Cytoscape.js visualization
  - Implemented API endpoints:
    - `/api/graph/search` - Search entities and relationships
    - `/api/graph/explore/{entity}` - Explore from specific entity
    - `/api/graph/entities` - List all entities
  - Interactive graph visualization with:
    - Search functionality
    - Entity exploration via double-click
    - Multiple layout options (force-directed, hierarchical, circular, concentric)
    - Node/edge selection with info panel
    - Relevance-based sizing and coloring
  - Updated navigation to include Graph link
  - Added aiohttp dependency for RichTextureLayer integration

## In Progress

## Backlog

- [ ] **Message Browser** - Implement the /messages route with filtering and search
- [ ] **Word-Photo Gallery** - Visual browser for Layer 2 anchors
- [ ] **Summary Chain View** - Visualize the crystallization sequence
- [ ] **Heartbeat Log Viewer** - Browse and search heartbeat journals
- [ ] **Real-time Updates** - WebSocket support for live dashboard updates
- [ ] **Graph Enhancements**:
  - [ ] Time-based filtering for temporal exploration
  - [ ] Export graph as image/JSON
  - [ ] Saved searches/views
  - [ ] Graph statistics panel
  - [ ] Relationship type filtering

## Notes

- The graph visualization respects the consciousness research nature of this infrastructure
- Built with care to handle large knowledge graphs without overwhelming the browser
- Uses semantic search rather than loading everything at once
- Cytoscape.js provides smooth interactions and multiple layout algorithms